# Remediation Summary — 017-loan-origination-workflow

**Author:** Danny (Lead/Architect)
**Date:** 2026-05-15
**Trigger:** `/speckit.analyze` flagged 16 findings (1C, 2H, 5M, 6L, 2I)

---

## C1 — CRITICAL: Constitution conflict in state-machine (`decided → funded`)

**Problem:** data-model.md state-machine diagram and transition table said `decided → funded` requires "Successful `account-service` + `transaction-service` calls in the decision handler." This directly contradicts spec FR-12, NFR-7, plan §Constitution Check, research R8, and the NON-NEGOTIABLE Separation-of-Concerns gate.

**Fix applied:**
- **data-model.md ~lines 229–230:** Replaced the ASCII diagram annotation from "AND account-service + transaction-service succeed" to "LoanAccount + LoanDisbursement written (in-domain), then loan.funded event published".
- **data-model.md ~line 245 (transition table):** Replaced trigger text with: `LoanFundingService` writes a `LoanAccount` to `loan-accounts` and a `LoanDisbursement` to `loan-disbursements` (both in-domain Cosmos containers), then publishes `loan.approved` + `loan.funded` events to `banking-events` Redis Stream. **No cross-domain service calls.**

**Rationale:** Implementation tasks (T071/T075) were already correct. The doc was the only source of the contradiction. Events are the ONLY cross-domain mechanism per FR-14.

---

## H1 — HIGH: .NET 9 vs .NET 10 drift

**Problem:** Persistent `.NET 9` references despite authoritative choice being `.NET 10` (spec.md:22, plan.md:8/16/67/216, tasks T002/T003).

**Verification:** `prompt-eval-service.csproj` targets `net10.0` — so prompt-eval-service is already .NET 10, not .NET 9. All .NET 10 references are correct.

**Fixes applied:**
- **plan.md:103** — Changed `# NEW — .NET 9 ASP.NET Core` → `.NET 10 ASP.NET Core`
- **quickstart.md:10** — Changed `.NET 9 SDK` → `.NET 10 SDK`
- **research.md:16** — Changed `(also .NET 9)` → `(also .NET 10)` (confirmed prompt-eval-service is net10.0)
- **spec.md:131** — Changed `.NET 9 + Azure.AI.Projects` → `.NET 10 + Azure.AI.Projects`

---

## H2 — HIGH: Missing contract test for `GET /decisions`

**Problem:** `GET /api/loans/applications/{applicationNo}/decisions` is in plan + implemented (T074) but has no corresponding contract test.

**Action:** No doc edit — this is a tasks.md gap. See **NEW TASKS NEEDED** section below.

---

## M1 — DECISION: Event scope expanded from 2 to 5

**Decision:** **Expand to 5 events.** The existing services in this repo (`transaction-service`, `transfer-service`, `ai-service`) publish a domain event per meaningful state change for audit purposes via `event-processor`. The loan domain should follow the same pattern for consistency and audit completeness.

**Events (aligned with data-model.md Lifecycle Events table):**
1. `loan.application.submitted` — after POST /applications
2. `loan.run.completed` — after POST /run or /recompute
3. `loan.approved` — after approve decision, before funding
4. `loan.declined` — after decline decision
5. `loan.funded` — after LoanAccount + LoanDisbursement written

**Fixes applied:**
- **spec.md FR-14** — Expanded from 2 events to full 5-event list with payload descriptions
- **spec.md Goals §5** — Updated event list from `(loan.approved, loan.funded)` to all 5
- **plan.md summary paragraph** — Updated event list to all 5
- **plan.md Constitution Check table** — Updated cross-domain communication row to reference 5 events
- **data-model.md Lifecycle Events table** — Already had all 5 (no change needed)

**New tasks needed:** See **NEW TASKS NEEDED** section below.

---

## M2 — DECISION: Keep `Foundry__Mode=offline` promise

**Decision:** **Keep.** The quickstart already documents it, and local-dev affordance is critical for this team. Frontend engineers iterating on `/loans` UI components need to run the service without a Foundry connection. The offline mode returns deterministic stub recommendations keyed on `applicationNo`, which is exactly what the synthetic data strategy (R6) supports.

**Doc changes:** None needed — quickstart.md already documents this correctly.

**New task needed:** See **NEW TASKS NEEDED** section below.

---

## M3 — DECISION: Keep docker-compose entry promise

**Decision:** **Keep.** The project constitution (§Local Development, per `docs/deployment-local.md`) requires all services to be runnable via `docker-compose up`. The existing `docker-compose.yml` at repo root includes all current services. A new entry for `loan-origination-service` is required.

**Verified:** `docker-compose.yml` exists at repo root with entries for user-service, account-service, transaction-service, transfer-service, and others — all following the same pattern (build from repo root, port mapping, env vars, depends_on redis).

**Doc changes:** None needed — quickstart.md already references `docker-compose up`.

**New task needed:** See **NEW TASKS NEEDED** section below.

---

## L1 — plan.md "four Cosmos entities" → six

**Fix applied:**
- **plan.md:239** — Changed "Defines four Cosmos entities (`LoanApplication`, `LoanRun`, `Decision`, `PolicyRule`)" to "Defines six Cosmos entities (`LoanApplication`, `LoanRun`, `Decision`, `PolicyRule`, `LoanAccount`, `LoanDisbursement`)"
- **plan.md:58** — Changed "across the new four" to "across the new six"

---

## L2 — research.md / data-model.md "four containers" → six

**Fix applied:**
- **research.md R7:116** — Changed "four new containers" to "six new containers"
- **data-model.md:323** — Changed "All four containers" to "All six containers"

---

## L3 — /healthz, /readyz not in OpenAPI

**Fix applied:**
- **plan.md ~line 250** — Added note: "`/healthz` and `/readyz` are intentionally omitted from the OpenAPI contract. They are infrastructure-only endpoints consumed by Kubernetes probes, not part of the public API surface."

---

## L4/L5 — Agent count inconsistency (five specialists vs six agents)

**Problem:** FR-5 said "Six versioned agents" listing 5 specialists + 1 underwriting. FR-6 said "five specialist agents." The acceptance criterion said "6 specialist + 1 health-check." The actual breakdown is 5 specialists + 1 underwriting + 1 health-check = 7.

**Fix applied:**
- **spec.md FR-5** — Reworded to clearly enumerate: "Five specialist agents (credit, income, fraud, policy, pricing) + one underwriting-recommendation agent. A seventh agent, health-check-agent, is registered for readiness probes (FR-17). **Total: 7 registered agents.**"
- **spec.md FR-6** — Clarified "five specialist agents" and "underwriting-recommendation agent" (not just "underwriting agent").
- **spec.md Acceptance Criteria** — Changed to "All 7 agents (5 specialists + 1 underwriting-recommendation + 1 health-check) registered."

---

## L6 — DecisionRecord ↔ Decision cross-reference

**Fix applied:**
- **data-model.md**, above the Decision entity JSON: Added naming note explaining that the C# model class is `DecisionRecord` while the data-model/spec docs use "Decision" — both refer to the same `underwriting-decisions` Cosmos entity.

---

## NEW TASKS NEEDED

These tasks should be added when `/speckit.tasks` is re-run. **Do not edit tasks.md manually.**

### NT-1: Contract test for `GET /api/loans/applications/{applicationNo}/decisions` (H2)

- **Proposed ID:** T065
- **Phase:** Phase 4 (US2 Tests)
- **File:** `src/loan-origination-service.Tests/Contracts/DecisionsGetContractTests.cs`
- **Description:** Contract test for `GET /api/loans/applications/{applicationNo}/decisions` against `contracts/loan-origination-api.json`. Validates response shape (array of Decision objects with `id`, `applicationNo`, `decision`, `fundingResult`, `createdAt`). Parallel with T060–T064.
- **Depends on:** T017 (models)

### NT-2: Expand `LoanEventPublisher` to publish 5 events (M1)

- **Proposed ID:** T073b (extend T073)
- **Phase:** Phase 4 (US2 Implementation)
- **File:** `src/loan-origination-service/Services/LoanEventPublisher.cs`
- **Description:** Extend `LoanEventPublisher` to publish `loan.application.submitted` (on create), `loan.run.completed` (on run/recompute), and `loan.declined` (on decline decision), in addition to the existing `loan.approved` + `loan.funded`. Wire the three new publish calls into `LoansController.Post` (submitted), `LoanAgentOrchestrator` (run.completed), and `DecisionsController.Post` (declined).
- **Depends on:** T073

### NT-3: Unit tests for 3 new events (M1)

- **Proposed ID:** T062b (extend T062)
- **Phase:** Phase 4 (US2 Tests)
- **File:** `src/loan-origination-service.Tests/LoanEventPublisherTests.cs`
- **Description:** Extend `LoanEventPublisherTests` to assert `loan.application.submitted`, `loan.run.completed`, and `loan.declined` payload shapes.
- **Depends on:** T062

### NT-4: `Foundry__Mode=offline` orchestrator stub (M2)

- **Proposed ID:** T045b
- **Phase:** Phase 3 (US1 Implementation, after T045)
- **File:** `src/loan-origination-service/Agents/OfflineLoanAgentOrchestrator.cs`
- **Description:** Implement an `ILoanAgentOrchestrator` that skips all Foundry agent calls and returns deterministic canned recommendations based on `applicationNo` hash (same synthetic data strategy as R6). Registered in DI when `Foundry__Mode=offline`. Enables local UI iteration without a Foundry connection.
- **Depends on:** T045 (interface), T042 (enrichment service)

### NT-5: docker-compose entry for loan-origination-service (M3)

- **Proposed ID:** T003b
- **Phase:** Phase 1 (Setup)
- **File:** `docker-compose.yml` (repo root)
- **Description:** Add `loan-origination-service` entry to `docker-compose.yml` mirroring the existing .NET service pattern: build from repo root, Dockerfile at `src/loan-origination-service/Dockerfile`, port `5290:8080`, env vars for `ASPNETCORE_ENVIRONMENT`, `UseInMemoryDatabase`, `Jwt__Key`, `Jwt__Issuer`, `OTEL_*`, `Foundry__Mode=offline` (default for local dev), `depends_on: redis`.
- **Depends on:** T003 (Dockerfile)

---

## FINAL VERDICT

**GREEN-ready for `/speckit.implement`?** — **YES, with caveats.**

All critical and high findings are resolved. The 5 new tasks above (NT-1 through NT-5) should be picked up by the next `/speckit.tasks` run before implementation begins. The spec artifacts are now internally consistent:

- State machine correctly reflects in-domain funding (C1 ✅)
- .NET 10 is consistent across all docs (H1 ✅)
- Event scope is 5 events everywhere (M1 ✅)
- Agent count is unambiguous: 5 + 1 + 1 = 7 (L4/L5 ✅)
- Container counts are six everywhere (L1/L2 ✅)
- Health endpoints excluded from OpenAPI by design (L3 ✅)
- DecisionRecord naming clarified (L6 ✅)

**Recommended workflow:** Re-run `/speckit.tasks` to pick up NT-1 through NT-5, then proceed to `/speckit.implement`.
