# Feature Spec: Loan Origination — Multi-Agent Workflow Underwriting

**Issue**: #140
**Branch**: `017-loan-origination-workflow`
**Date**: 2026-05-15

## Problem Statement

The online-banking-demo currently covers account opening, transactions, transfers, and budgeting — but has no lending lifecycle. We have a separate reference architecture (`briandenicola/loan-originations-demo`) that demonstrates Microsoft Agent Framework + Azure AI Foundry for multi-agent loan underwriting using two orchestration patterns. We want to bring **only the workflow (code-based coordinator) implementation** into this repo as a new domain alongside the existing services, demonstrating multi-agent underwriting on top of the platform.

The workflow pattern (deterministic code-based coordinator over `Azure.AI.Projects` + versioned `PromptAgentDefinition` agents) maps cleanly to the existing Foundry agent patterns already used by `account-opening-service` and `ai-service`, and is well-suited to demos where reproducible step-by-step behavior matters.

## Preconditions and Boundaries

- **The applicant is an existing authenticated user.** Account opening, KYC, and identity verification are handled entirely by `account-opening-service` upstream and are **out of scope for this feature**. A user must already have a record in the `users` container before they can submit a loan application.
- **No deposit account is required, queried, created, or modified.** A `LoanAccount` is a *loan record* (principal owed) — it is not a deposit / checking / savings account. We do not credit any deposit-side balance and we never call `account-service`.
- **Existing services are not modified.** `account-opening-service`, `account-service`, `transaction-service`, `transfer-service`, `user-service`, `ai-service`, `chatbot-service`, `budget-service`, `event-processor`, and `prompt-eval-service` receive **zero code changes** as part of this feature. The only cross-domain touchpoint is a read-only FK reference to `users.id` (validated lazily via `user-service` `GET /api/users/{id}` — same pattern `account-service` already uses).
- **No document upload, no Content Understanding, no fraud-document re-verification.** The `fraud-screening-agent` consumes synthetic risk signals (device risk, watchlist, address-mismatch flags) generated deterministically inside loan-origination-service; it does not re-do account-opening's identity work.

## Goals

1. Add a `loan-origination-service` (.NET 10 / ASP.NET Core) under `src/` that exposes a REST API for submitting and underwriting loan applications for **existing authenticated users**.
2. Use the **workflow / code-based coordinator** orchestration pattern from the source repo — six versioned specialist agents called sequentially, results compiled into a brief, final recommendation produced by an underwriting agent.
3. Reuse the existing Foundry account, capability host, and BYO connections (Cosmos / Storage / Search) provisioned by spec **001-azure-private-endpoints** — no new Foundry resources.
4. Persist applications, runs, decisions, **loan accounts, and disbursements** in Cosmos DB containers owned exclusively by loan-origination-service. (Replaces the source repo's CSV layer.)
5. Publish lifecycle events (`loan.approved`, `loan.funded`) to the existing `banking-events` Redis Stream for any downstream observer. **No synchronous calls into other services for state changes.**
6. Add a React UI route `/loans` (intake form, workflow visualization, "my loans" page, admin review dashboard, decision panel) using MUI v9 components. Existing `/accounts` page is untouched.
7. Emit OpenTelemetry traces for the full agent chain to Application Insights via the existing OTEL Collector.

## Non-Goals

- Porting the **classic** (`ConnectedAgentTools` / agentic) implementation. (Stretch only.)
- Servicing the loan after funding — payments, interest accrual, statements, payoff, collections.
- Real credit bureau, identity, or fraud integrations — synthetic data only.
- TILA / RESPA / regulatory disclosures — demo only.
- Secondary-market loan packaging or sale workflows.
- **Anything that touches `account-opening-service`, `account-service`, or `transaction-service`** — those services are not modified, called, or extended.
- Crediting a deposit account on funding. The borrower's "money" is represented by the `LoanAccount.principalBalance` field; we do not model where it lands.

## Requirements

### Functional Requirements

1. **FR-1 — Application submission.** `POST /api/loans/applications` accepts a loan application from an authenticated user (loan amount, term, type, purpose, declared income/debt, housing status). The `userId` is taken from the JWT — never accepted from the request body. Identity fields (name, DOB, SSN-last-4, address) are optional in the body and default to the user's profile values from `user-service`; if supplied they are stored on the application snapshot but never written back to `user-service`. Returns `applicationNo` (e.g., `APP-2026-000123`) and persists to Cosmos `loan-applications` with status `submitted`.
2. **FR-2 — Application retrieval.** `GET /api/loans/applications/{applicationNo}` returns the application + last run (if any) + last decision (if any).
3. **FR-3 — Workflow execution.** `POST /api/loans/applications/{applicationNo}/run` triggers the S01–S10 workflow. Synchronous response returns the full `AgentRunResponse` (run_id, prepared payload, workflow log, recommendation).
4. **FR-4 — Workflow streaming.** `GET /api/loans/applications/{applicationNo}/run-stream` streams Server-Sent Events as steps complete, ending with a final `complete` event carrying the recommendation. Used by the UI workflow visualization.
5. **FR-5 — Specialist agents.** Six versioned `PromptAgentDefinition` agents are registered in Foundry at service startup (or via init container) using prompts ported from the source repo: `credit-profile-agent`, `income-verification-agent`, `fraud-screening-agent`, `policy-evaluation-agent`, `pricing-agent`, `underwriting-recommendation-agent`. All run on the existing `gpt-5.4-mini` deployment.
6. **FR-6 — Code-based coordinator.** A `LoanAgentOrchestrator` calls the five specialist agents sequentially with full enriched application context, compiles their responses into a brief, then sends the brief to the underwriting agent for the final `APPROVE` / `CONDITIONAL` / `DECLINE` recommendation with a confidence score in `[0,1]`.
7. **FR-7 — Workflow steps S01–S10.** Steps execute in this order: S01 Application Intake → S02 Data Enrichment → S03 Credit Profile Agent → S04 Income Verification Agent → S05 Fraud Screening Agent → S06 Policy Evaluation Agent → S07 DTI & Affordability → S08 Pricing Agent → S09 Underwriting Recommendation → S10 Human Review Ready. Each step's status (`running` | `completed` | `failed`) and timestamp are recorded in the run log.
8. **FR-8 — Underwriting policy rules POL-001..POL-010.** Rules are seeded into Cosmos `loan-policy` container at deploy time and read by the policy-evaluation step. Source rules from the original repo are preserved verbatim.
9. **FR-9 — Decision recording.** `POST /api/loans/applications/{applicationNo}/decisions` records a human reviewer decision (`approve` | `conditional` | `decline`) with optional adjusted amount/term/rate and notes. Persisted to `underwriting-decisions` container.
10. **FR-10 — Recompute with adjusted terms.** `POST /api/loans/applications/{applicationNo}/recompute` re-runs steps S07–S09 with adjusted requested amount, term, and loan type. Returns a new recommendation without losing the original run.
11. **FR-11 — JWT authentication.** All endpoints require a valid JWT issued by `user-service` with claims:
    - User endpoints (submit, view own, run own): `User` role.
    - Decision endpoints, list-all-applications: `Admin` role.
    Roles enforced via the same shared `Jwt__Key` / `Jwt__Issuer` pattern used by other .NET services.
12. **FR-12 — Loan account provisioning on approval (owned in-domain).**
    - On `approve` decision (whether AI-recommended `APPROVE` auto-approved or human-confirmed), loan-origination-service creates a `LoanAccount` record in its **own** `loan-accounts` Cosmos container with the approved `principalBalance`, `aprPct`, `termMonths`, `monthlyPayment`, and `payoffDate`. Status is set to `funded`.
    - Records the initial funding as a single `LoanDisbursement` row in the **own** `loan-disbursements` container (`kind: "funding"`, `amount` = approved principal, references the `loanAccountId`). This is an internal accounting entry — it is **not** a deposit-account credit and is **not** written to the `transactions` container.
    - Stores the new `loanAccountId` back on the application as `fundedLoanAccountId`.
    - **Does NOT call `account-service`** — deposit accounts and loan accounts are separate domains. The existing `accounts` container is for deposit accounts only and is not extended.
    - **Does NOT call `transaction-service`** — the deposit-account ledger does not record loan-side activity.
    - **Does NOT call `account-opening-service`** — the user already exists; no opening flow is triggered.
    - **No deposit account is required** — a user with zero deposit accounts can still apply for and receive a loan.

13. **FR-13 — Loan account read API.**
    - `GET /api/loans/accounts` returns the caller's loan accounts (Admin sees all when `?userId=` is supplied).
    - `GET /api/loans/accounts/{loanAccountId}` returns full loan account detail.
    - `GET /api/loans/accounts/{loanAccountId}/disbursements` returns the disbursement history.

14. **FR-14 — Event publishing on state changes.**
    - On approval & funding, publish a `loan.approved` event then a `loan.funded` event to the existing `banking-events` Redis Stream (the same stream `transaction-service`, `transfer-service`, and `ai-service` use). Event payload: `{event_type, application_no, loan_account_id, user_id, amount, apr_pct, term_months, timestamp}`.
    - This is the **only** mechanism by which other services may react to loan lifecycle changes. No service makes synchronous calls into loan-origination-service except via the public REST API above.
    - `event-processor` (Go) automatically picks up the new events for audit logging — no code change required there because it's a generic stream consumer.
15. **FR-15 — Frontend route `/loans` (separate from `/accounts`).**
    - **Intake page** (`/loans/apply`): form for applicant identity (auto-filled from JWT user profile), loan amount, term, type, purpose, income, debts, housing.
    - **My loans** (`/loans/accounts`): user's loan accounts and applications. Distinct from `/accounts` — deposit accounts stay where they are; the existing `/accounts` page is **not modified**.
    - **Workflow visualization** (`/loans/applications/:appNo`): Live SSE-driven step-by-step display (10 steps with status dots), per-step timing, agent name shown for AI steps.
    - **Review dashboard** (`/loans/admin/review`, `Admin` only): table of all applications + status + recommendation + confidence; filter by status.
    - **Decision panel** (`Admin` only): full recommendation rationale + key factors + policy hits; accept / conditional / decline + optional term adjustments.
16. **FR-16 — OpenTelemetry tracing.** A single trace per workflow run with one child span per step (S01–S10). Agent calls add `agent.name` and `agent.duration_ms` attributes. Traces export via the existing OTEL Collector to Application Insights.
17. **FR-17 — Health checks.** Standard `/healthz` (liveness) and `/readyz` (readiness — verifies Cosmos and Foundry connectivity via a startup health-check agent call).

### Non-Functional Requirements

1. **NFR-1 — Performance.** A full S01–S10 run completes in < 60 seconds p95 against `gpt-5.4-mini` (six sequential agent calls).
2. **NFR-2 — Auth.** Cosmos, Redis, and Foundry use Workload Identity + Entra RBAC. No connection-string secrets in the service.
3. **NFR-3 — Private networking.** All Foundry / Cosmos / Redis calls go via private endpoints provisioned by spec 001. No new public IPs, no new private DNS zones.
4. **NFR-4 — Observability.** Service emits structured JSON logs and OTEL traces using the existing OTEL Collector endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`). No direct calls to App Insights from the service.
5. **NFR-5 — Idempotency.** Re-running a workflow for the same `applicationNo` produces a new `runId`; previous runs are preserved. Decisions are append-only — overwriting requires a new decision record. Approval is idempotent on `applicationNo`: re-approving an already-funded application returns the existing `loanAccountId` rather than creating a duplicate.
6. **NFR-6 — Cosmos partitioning** (all six containers owned by loan-origination-service alone):
    - `loan-applications` PK: `/id` (where `id` == `applicationNo`)
    - `loan-runs` PK: `/applicationNo`
    - `underwriting-decisions` PK: `/applicationNo`
    - `loan-policy` PK: `/id` (where `id` == `ruleId`)
    - `loan-accounts` PK: `/userId`
    - `loan-disbursements` PK: `/loanAccountId`
7. **NFR-7 — Separation of concerns (NON-NEGOTIABLE).** loan-origination-service is the **only** service that reads or writes its six containers. It does **not** write to any container owned by another service. It does **not** add new fields, types, or behaviors to `account-opening-service`, `account-service`, `transaction-service`, `user-service`, `transfer-service`, `ai-service`, `chatbot-service`, `budget-service`, `event-processor`, or `prompt-eval-service`. The only cross-domain interactions are: (a) read-only FK reference to `users.id` (validated lazily via `user-service` `GET /api/users/{id}`), and (b) publish-only events on the shared `banking-events` Redis Stream (no service is required to consume).
8. **NFR-8 — Test coverage.** Unit tests for the orchestrator, controllers, Cosmos repositories, and Redis Stream publisher. Playwright E2E test that submits an application, runs the workflow, approves, and verifies the loan account appears under `/loans/accounts` and a `loan.funded` event was published.
9. **NFR-9 — Deployment.** Service deployed to AKS via `task cloud:deploy`. Uses the same kustomize base + workload-identity pattern as other .NET services. Image built via `task cloud:build` → ACR.

## Test Personas

Reuse demo seed data from `./scripts/seed-data.sh` — these users are created by the existing seed flow (which covers user creation and is unrelated to this feature). Add three loan applications for these users:

| Persona | User exists from seed? | Profile | Expected outcome |
|---|---|---|---|
| **Alice Goodman** | yes (existing demo user) | 760 credit score, $120k income, $400/mo debt, $25k loan / 36mo / personal | `APPROVE`, ~7.5% APR |
| **Bob Marginal** | yes (existing demo user) | 660 credit score, $58k income, $1,200/mo debt, $15k loan / 60mo / auto | `CONDITIONAL` (DTI borderline) |
| **Charlie Risky** | yes (existing demo user) | 540 credit score, $42k income, $1,800/mo debt, $30k loan / 84mo / personal | `DECLINE` (POL-001 score floor + POL-004 DTI ceiling) |

> No persona requires account-opening to run as part of this feature. If Alice / Bob / Charlie don't already exist in your seed, add them via the **existing** `seed-data.sh` user-creation path — not by triggering account-opening-service.

## Acceptance Criteria

- [ ] `loan-origination-service` deployed to AKS at `/api/loans/*` via the Istio gateway.
- [ ] All 6 specialist agents + 1 health-check agent registered in the existing Foundry project under versioned names.
- [ ] Submitting Alice's application and running the workflow returns `APPROVE` with confidence ≥ 0.7.
- [ ] Approving Alice's recommendation creates a `LoanAccount` for her `userId` in the **new `loan-accounts` container** (not in the existing `accounts` container) and records the initial funding as a `LoanDisbursement` in `loan-disbursements`. A `loan.approved` then `loan.funded` event is published to the `banking-events` Redis Stream.
- [ ] `account-opening-service`, `account-service`, and `transaction-service` are **bit-for-bit unchanged** — `git diff` against `main` shows zero modifications to their `src/` trees.
- [ ] A user with **zero** deposit accounts can still successfully submit, run, and have a loan approved end-to-end (verified by an explicit Playwright test).
- [ ] React UI at `/loans` renders intake form, live SSE workflow viz, the admin review panel, and a "My Loans" page distinct from the existing `/accounts` page (which remains unchanged).
- [ ] Application Insights shows a single trace per run with 10 child spans, one per workflow step.
- [ ] Smoke test against `${CUSTOM_DOMAIN}` (`onlinebankingdemo.bjdazure.tech`) submits an application, runs it, and renders the decision in the UI.
- [ ] Playwright E2E suite gains at least one new `loan-origination.spec.ts` covering the happy path.

## Dependencies

- **Hard dependency:** Spec **001-azure-private-endpoints** — must be applied so the Foundry project, capability host, and connections exist privately. No new infra is provisioned by this feature.
- **Soft dependency:** Spec **002-ai-anomaly-detection** — established the pattern for .NET 9 + `Azure.AI.Projects` (prerelease) + Foundry agent registration. We mirror it here.
- **Reuses:** existing `gpt-5.4-mini` model deployment; existing `accounts` and `transactions` Cosmos containers; existing Istio gateway routing; existing OTEL Collector.

## Out of Scope (explicit)

- Classic / agentic (`ConnectedAgentTools`) orchestration pattern — Phase 4 stretch only, not in this spec.
- Account opening, KYC, and identity verification — all handled upstream by `account-opening-service`. The applicant must already exist as a `users` record before they can apply.
- Modifying `account-opening-service`, `account-service`, `transaction-service`, or any other existing service. This feature is purely additive — only loan-origination-service and the React UI gain new code.
- Loan servicing — payments, interest accrual, statements, payoff, collections.
- Crediting a deposit account on funding. The loan principal is recorded on the `LoanAccount` only.
- Variable-rate or amortizing payment schedules beyond a single APR + monthly-payment quote.
- Real credit bureau, identity-verification, or fraud-screening providers.
- Multi-currency / multi-region.
- Mobile app surfaces.
