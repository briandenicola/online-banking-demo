# Phase 0 Research — Loan Origination Workflow

**Branch:** `017-loan-origination-workflow`
**Date:** 2026-05-15

This document resolves all technical unknowns and `NEEDS CLARIFICATION` items from the spec before Phase 1 design begins.

---

## R1 — SDK choice: `Azure.AI.Projects` vs. `Microsoft.Agents.AI.AzureAI.Persistent`

**Decision:** Use **`Azure.AI.Projects` 2.0.0-beta.x** (`AIProjectClient`, `PromptAgentDefinition`, `CreateAgentVersionAsync`).

**Rationale:**
- The source repo's workflow implementation uses this SDK — porting over is mechanical.
- We already use it in `prompt-eval-service` (also .NET 9), so it's a known quantity in this codebase: same auth (`DefaultAzureCredential`), same retry behavior, same telemetry hook surface.
- It produces **versioned agents** in the Foundry portal — exactly what we want for this demo, since the underwriting policies and prompts are auditable artifacts.
- The classic SDK (`Microsoft.Agents.AI.AzureAI.Persistent` + `PersistentAgentsClient`) is what the source repo's *classic* implementation uses, which is explicitly out of scope for this feature.

**Alternatives considered:**
- **`Microsoft.SemanticKernel.Agents`** — heavier abstraction; adds a third Foundry SDK to maintain in this repo; rejected.
- **Direct OpenAI Chat Completions REST** — would lose the versioned-agent metadata and require us to re-implement orchestration plumbing already provided by `Azure.AI.Projects`; rejected.

---

## R2 — Where to register agents: init container vs. service startup

**Decision:** **Service startup** (`Program.cs` `IHostedService` registered after `AddAuthentication` and before `app.Run()`).

**Rationale:**
- The agent set is small (7 agents) and registration is fast (<5 s end-to-end against the existing private-endpoint Foundry).
- `CreateAgentVersionAsync` is **idempotent on the version body** — re-creating the same prompt produces no diff, and only a real prompt change creates a new version. This is safer for auditability than wiping/recreating.
- An init container would require duplicating the prompts directory into a separate image and would slow rollouts. `account-opening-service` uses an init container only because it has a separate worker pod — we have one pod here, so the lifestyle parity is unnecessary.
- Using `IHostedService` keeps registration in a single language/codebase (.NET) and gives us natural OTEL spans for the registration pass.

**Alternatives considered:**
- **Init container modeled on `account-opening-service`'s `provision-agents`** — rejected for the reasons above; revisit only if registration time exceeds startup probe budgets.
- **One-shot Terraform module** — Foundry agent versioning is service-side state; baking it into Terraform creates ordering hazards (Terraform vs. service deploy). Rejected.

---

## R3 — Live workflow updates: SSE vs. SignalR vs. WebSockets

**Decision:** **Server-Sent Events (`text/event-stream`)**, mirroring the source repo.

**Rationale:**
- One-way server → client streaming is exactly what we need — there's no client-to-server channel mid-workflow.
- ASP.NET Core supports SSE natively via `Response.BodyWriter`; no extra dependency.
- The browser EventSource API "just works" without a dedicated SDK; trivial to consume from React.
- Istio / Envoy passes SSE through cleanly with the existing VirtualService timeout settings (already configured for long-poll-style endpoints by `chatbot-service`).
- SignalR would add a hub negotiation handshake and a server-side dependency on Redis backplane (which we have, but the negotiation roundtrip is wasted complexity for a single-stream-per-request pattern).

**Alternatives considered:**
- **SignalR** — too heavy for a single one-way stream; rejected.
- **WebSockets directly** — same overhead as SignalR without the framework benefits; rejected.
- **Polling** — wastes Cosmos RUs and hides the "live agent thinking" demo punch. Rejected.

---

## R4 — Storage shape: embed runs/decisions vs. separate containers

**Decision:** **Six separate containers** — `loan-applications`, `loan-runs`, `underwriting-decisions`, `loan-policy`, `loan-accounts`, `loan-disbursements`.

**Rationale:**
- Runs can be re-executed (`POST /run` and `POST /recompute`); we want a tamper-evident history. Embedding only the latest run on the application loses this.
- Decisions are append-only by design (audit trail) — they need their own container with PK `/applicationNo` to support the `GET /decisions` listing endpoint.
- Policy rules are independently versionable seed data and need their own lookup container so the policy-evaluation step can `ReadAllItemsAsync<PolicyRule>()` without touching application data.
- `LoanAccount` is the funded-loan record, separate from the application/run/decision lifecycle. PK by `/userId` enables the common "list my loans" query as a single-partition read.
- `LoanDisbursement` is the per-funding accounting entry; PK by `/loanAccountId` enables the per-loan history query as a single-partition read.
- Cross-container fan-out cost is a non-issue at demo scale (single-region, ~10s/day).

**Trade-offs accepted:**
- Reading "the full picture of an application" requires three reads (app + last run + last decision). Mitigated by `GET /api/loans/applications/{appNo}` aggregating them server-side in a single response.
- More containers = slightly more RU floor. We share 400 RU/s across all six new containers (matches existing demo pattern).

---

## R5 — Foundry resources: reuse existing project vs. provision a second one

**Decision:** **Reuse the existing Foundry project** provisioned by spec 001.

**Rationale:**
- Spec 001 already provisioned a Foundry account, project, capability host, and BYO connections (Cosmos / Storage / Search) in a Managed VNet. Adding more agents to it costs nothing.
- The source repo provisions two projects (one per orchestration pattern) only because it ships *both* implementations. We only ship workflow.
- Using one project means one set of RBAC role assignments, one capability host to maintain, one set of private DNS zones — all already done.
- All existing services (`ai-service`, `account-opening-service`, `chatbot-service`, `prompt-eval-service`) share this project; the loan agents are additive and namespaced by their hyphenated names (`credit-profile-agent`, etc.), so collision risk is zero.

**Alternatives considered:**
- **Second Foundry project for loan domain** — would require a new private endpoint, new managed network, new RBAC, new capability host. ~150 lines of Terraform for zero functional gain in a demo. Rejected.

---

## R6 — Synthetic data strategy

**Decision:** **Deterministic-by-`applicationNo`** generators in `EnrichmentService` — same input always produces the same credit profile, income verification, and fraud signals.

**Rationale:**
- The source repo loaded synthetic data from CSVs keyed by `application_no`. We replicate the determinism without checking in CSVs.
- Determinism enables E2E tests and demos to assert specific outcomes (Alice → APPROVE, Bob → CONDITIONAL, Charlie → DECLINE) without snapshot fragility.
- Implementation: hash `applicationNo` → seed `System.Random` → produce credit score in `[300,850]`, delinquencies, utilization, etc. within plausible bands.
- For the three named personas (Alice/Bob/Charlie), the seed-data script writes their applications with `applicationNo` values that hash into the desired bands; everyone else gets a uniformly random profile.

**Alternatives considered:**
- **Check in the source CSVs** — adds ~50 KB of demo data files; no upside over a deterministic generator. Rejected.
- **Random per-call** — would make E2E tests flaky and break demos. Rejected.
- **Single hard-coded fixture** — too narrow; can't demonstrate variation. Rejected.

---

## R7 — RBAC additions

**Decision:** **Extend the existing `banking-workload-identity` service account** — no new federated credentials.

**Required additions** (Terraform, additive only):
1. `Cognitive Services User` and `Azure AI User` roles on the existing Foundry project for the existing workload identity. (May already be granted from spec 002 — verify in `infra/cloud/identity.tf`.)
2. `Cosmos DB Built-in Data Contributor` extended to cover the four new containers (or scope at the database, which is the existing pattern).

**Rationale:**
- Adding a service-specific service account would multiply federated credentials for no benefit — every other .NET service in this repo shares `banking-workload-identity` and that's worked well.
- Foundry RBAC is at the project scope; granting it once covers all our agent-using services.
- Cosmos RBAC is already at the database scope (`/dbs/BankingDemo`), so new containers inherit access automatically. Verify this in Phase 2 task 1.

---

## R8 — Domain ownership boundaries (in-domain vs. cross-service writes)

**Decision:** **loan-origination-service owns the loan domain end-to-end** in its own Cosmos containers. It performs **no synchronous writes** into any other service's domain. Lifecycle changes are announced via events on the existing `banking-events` Redis Stream.

**Rationale:**
- The applicant is an existing authenticated user. Account opening, KYC, and identity verification are owned by `account-opening-service` upstream — this feature does not invoke it, modify it, or duplicate its work.
- A `LoanAccount` is a *loan record* (principal owed, APR, term, monthly payment) — semantically distinct from a deposit/checking/savings account. Forcing the loan into the existing `accounts` container would teach `account-service` loan semantics it doesn't need (interest, term, payoff, collections), polluting its data model and turning a single-purpose service into a polymorphic one. Hard no.
- A loan disbursement is internal to the loan domain — it's the accounting entry for "principal moved from bank to borrower". It is not a deposit-side debit/credit and does not belong in `transaction-service`'s ledger (which records transfers and payments between deposit accounts).
- Communication to other services that may want to react to loan lifecycle changes (`event-processor`'s audit log, `ai-service`'s anomaly detection if extended later, `chatbot-service` if extended later) goes through the existing `banking-events` Redis Stream — same pattern `transaction-service` and `transfer-service` already use. Subscribers are optional and add zero coupling.
- Net: the **only** cross-domain interaction this service has is (a) a read-only `GET /api/users/{id}` against `user-service` for FK validation (same pattern `account-service` uses), and (b) publish-only events to `banking-events`. No service is required to consume those events for the feature to work end-to-end.

**Concrete consequences:**
- Six Cosmos containers, all owned by loan-origination-service: `loan-applications`, `loan-runs`, `underwriting-decisions`, `loan-policy`, `loan-accounts`, `loan-disbursements`.
- Zero modifications to `account-opening-service`, `account-service`, `transaction-service`, `transfer-service`, `user-service`, `ai-service`, `chatbot-service`, `budget-service`, `event-processor`, `prompt-eval-service`. Verified by acceptance criterion (`git diff main -- src/{above}/` returns empty).
- A user with **zero deposit accounts** can still apply for, be approved for, and be funded for a loan. The loan exists independently of any deposit relationship.

**Alternatives considered:**
- **Create a deposit account in `account-service` on approval** with `accountType=loan`. Requires teaching `account-service` loan-specific fields (APR, term, monthly payment, payoff date) or storing them elsewhere with a fragile FK. Conflates loan and deposit semantics. **Rejected.**
- **Write a `loan_funding` transaction to `transaction-service`** so the disbursement shows up in the user's transaction history. Loan disbursement is not a deposit-side ledger event; it doesn't credit any deposit account. Forcing it into the deposit ledger creates phantom transactions with no offsetting account. **Rejected.**
- **Trigger account-opening-service on first loan application** in case the applicant has never opened an account. Creates a confusing onboarding loop ("I want a loan but I have to open a checking account first?") and couples two unrelated lifecycles. The applicant is already a `users` record — that's our precondition. **Rejected.**
- **Synchronous HTTP call to a hypothetical `loan-servicing-service`** (which doesn't exist yet). YAGNI for this feature. The eventual servicing service can subscribe to `banking-events` like everyone else. **Rejected.**

**Implementation:**
- `UserLookupService` is a thin `IHttpClient` wrapper that calls `user-service` `GET /api/users/{id}` to validate the FK on first run. Result is cached in-process for 5 minutes (matches existing patterns).
- `LoanEventPublisher` writes to the `banking-events` Redis Stream using `XADD` with the same payload schema other services use (`{event_type, ...}`). Entra-token auth via the existing workload identity. No new connection, no new credentials.
- Both services are scoped DI; both forward the caller's bearer token from `IHttpContextAccessor` for auditability of the user-lookup call (matches `transfer-service`'s JWT-forwarding pattern). The event publisher attaches the calling user's ID into the event payload as `user_id`.

---

## Open questions

**None.** All NEEDS CLARIFICATION items in the spec have been resolved above. Proceed to Phase 1.
