---
description: "Task list for feature 017-loan-origination-workflow"
---

# Tasks: Loan Origination — Multi-Agent Workflow Underwriting

**Input**: Design documents from `/specs/017-loan-origination-workflow/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/loan-origination-api.json, quickstart.md, REMEDIATION.md

**Tests**: Included. spec.md NFR-8 explicitly requires xUnit unit tests for orchestrator, controllers, repositories, and event publisher, plus a Playwright E2E happy-path test.

**Organization**: Tasks are grouped by user story so each story can be implemented, tested, and demoed independently.

**Remediation note (REMEDIATION.md, 2026-05-15)**: This regeneration adds 5 tasks (T003b, T045b, T062b, T065, T073b) corresponding to NT-1..NT-5 from the audit. All other tasks preserve the original numbering.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps the task to a user story (US1 / US2 / US3); Setup / Foundational / Polish phases carry no story label

## User Stories (derived from spec.md)

- **US1 — Apply & Underwrite (P1, MVP)**: An authenticated user submits a loan application and runs the multi-agent workflow synchronously, receiving an `APPROVE` / `CONDITIONAL` / `DECLINE` recommendation with confidence. Covers FR-1, FR-2, FR-3, FR-5, FR-6, FR-7, FR-8, FR-11, FR-17 and persona Alice (`APPROVE` ≥ 0.7).
- **US2 — Decide, Fund & Announce (P2)**: An admin records a decision on a workflow run; on approval the service provisions a `LoanAccount`, records a `LoanDisbursement` (both **in-domain** — no cross-domain calls to `account-service` / `transaction-service`), exposes loan-account read APIs, and publishes the **5 lifecycle events** (`loan.application.submitted`, `loan.run.completed`, `loan.approved`, `loan.declined`, `loan.funded`) to the `banking-events` Redis Stream. Covers FR-9, FR-12, FR-13, FR-14 and personas Bob (`CONDITIONAL`) / Charlie (`DECLINE`).
- **US3 — Live Workflow & Review UI (P3)**: SSE streaming of the workflow, recompute with adjusted terms, and the React `/loans` surfaces — Intake form, My Loans, Live Workflow viz, Admin Review dashboard + Decision panel — plus full OTEL trace shape (FR-4, FR-10, FR-15, FR-16) and the E2E smoke / Playwright happy-path.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffold the new .NET 10 service, project layout, and infra hooks.

- [x] T001 Create `src/loan-origination-service/` skeleton directory tree matching `plan.md` (Controllers/, Models/, Repositories/, Services/, Agents/, prompts/, Telemetry/, seed/)
- [x] T002 Create `src/loan-origination-service/LoanOrigination.csproj` targeting `net10.0` with package references to `Azure.AI.Projects` 2.0.0-beta.x, `Microsoft.Azure.Cosmos` 3.x, `Azure.Identity`, `Microsoft.AspNetCore.Authentication.JwtBearer`, `OpenTelemetry.Extensions.Hosting`, `StackExchange.Redis`, and `Newtonsoft.Json` (centralized via `Directory.Packages.props`)
- [x] T003 [P] Create `src/loan-origination-service/Dockerfile` using the `mcr.microsoft.com/dotnet/aspnet:10.0-alpine` runtime base — mirror `src/prompt-eval-service/Dockerfile`
- [x] T003b [P] **(NT-5, M3)** Add `loan-origination-service` entry to repo-root `docker-compose.yml` mirroring the existing .NET service pattern: build context from repo root, dockerfile at `src/loan-origination-service/Dockerfile`, port mapping `5290:8080`, env vars (`ASPNETCORE_ENVIRONMENT=Development`, `UseInMemoryDatabase=true`, `Jwt__Key`, `Jwt__Issuer`, `OTEL_*`, `Foundry__Mode=offline` as the local-dev default), `depends_on: [redis]`. Depends on T003 (Dockerfile must exist).
- [x] T004 [P] Create `src/loan-origination-service/appsettings.json` and `appsettings.Development.json` with Cosmos endpoint, Foundry endpoint, Redis endpoint, JWT key/issuer, and `Foundry__Mode` flag placeholders
- [x] T005 [P] Create `src/loan-origination-service.Tests/LoanOrigination.Tests.csproj` xUnit project referencing the service project; mirror `src/account-service.Tests` layout
- [x] T006 [P] Update root `Directory.Packages.props` with any new central package versions introduced by T002

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Wiring that every user story depends on — Cosmos containers, JWT auth, base models/repositories, telemetry, agent registration, prompt files, and seed data. **No user story work begins until this phase is complete.**

**⚠️ CRITICAL**: All US1/US2/US3 work depends on this phase.

- [x] T010 Add six new Cosmos containers (`loan-applications` PK `/id`, `loan-runs` PK `/applicationNo`, `underwriting-decisions` PK `/applicationNo`, `loan-policy` PK `/id`, `loan-accounts` PK `/userId`, `loan-disbursements` PK `/loanAccountId`) to `infra/cloud/cosmos.tf`
- [x] T011 [P] Verify and (if needed) extend database-scope Cosmos RBAC and Foundry RBAC for `banking-workload-identity` in `infra/cloud/identity.tf` (per research R7)
- [x] T012 Implement `src/loan-origination-service/Program.cs`: JWT bearer auth (HS256, shared `Jwt__Key`/`Jwt__Issuer`), Cosmos client (Newtonsoft serializer, `DefaultAzureCredential`), Redis multiplexer with Entra token auth, OTEL ASP.NET + HttpClient + Cosmos auto-instrumentation, structured JSON logging, controller routing, health checks
- [x] T013 [P] Implement `src/loan-origination-service/Telemetry/WorkflowTelemetry.cs` with an `ActivitySource("LoanOrigination.Workflow")` and `StartStepSpan(stepId, applicationNo, runId)` helper used by all S01–S10 spans
- [x] T014 [P] Port the six specialist prompt files from the source repo verbatim into `src/loan-origination-service/prompts/` (`CreditProfileAgentPrompt.txt`, `IncomeVerificationAgentPrompt.txt`, `FraudScreeningAgentPrompt.txt`, `PolicyEvaluationAgentPrompt.txt`, `PricingAgentPrompt.txt`, `UnderwritingAgentPrompt.txt`) plus `HealthCheckAgentPrompt.txt`
- [x] T015 [P] Implement `src/loan-origination-service/Agents/PromptLoader.cs` to load `./prompts/*.txt` from the content root
- [x] T016 Implement `src/loan-origination-service/Agents/AgentRegistration.cs` as an `IHostedService` that calls `AIProjectClient.CreateAgentVersionAsync` idempotently for all 7 agents (5 specialists: credit, income, fraud, policy, pricing + 1 underwriting-recommendation + 1 health-check) against `gpt-5.4-mini` at startup
- [x] T017 [P] Create all DTO/model classes in `src/loan-origination-service/Models/` per data-model.md: `LoanApplication.cs`, `LoanRun.cs`, `WorkflowStep.cs`, `DecisionRecord.cs`, `PolicyRule.cs`, `LoanAccount.cs`, `LoanDisbursement.cs`, `LoanLifecycleEvent.cs`, `CreditProfile.cs`, `IncomeVerification.cs`, `FraudSignals.cs`, `PolicyThreshold.cs`, `ProductPricing.cs`, `UnderwritingRecommendation.cs`, `AgentRunResponse.cs`
- [x] T018 [P] Implement `src/loan-origination-service/Repositories/ICosmosRepository.cs` generic interface + base implementation
- [x] T019 [P] Implement `src/loan-origination-service/Repositories/CosmosPolicyRepository.cs` (PK `/id`) with `GetAllAsync()` for policy evaluation
- [x] T020 [P] Create `src/loan-origination-service/seed/policy-rules.json` (POL-001..POL-010 verbatim from source repo) and `src/loan-origination-service/seed/product-pricing.json` (risk-tier APR matrix)
- [x] T021 Implement policy + pricing seed loader in `Program.cs` that upserts `policy-rules.json` rows into the `loan-policy` container on startup (idempotent by `id`)
- [x] T022 [P] Implement `src/loan-origination-service/Services/UserLookupService.cs` — typed `HttpClient` against `user-service` `GET /api/users/{id}` for read-only FK validation (mirror `account-service` pattern)
- [x] T023 Implement `Controllers/HealthController.cs` with `GET /healthz` (liveness) and `GET /readyz` (probes Cosmos + Foundry health-check agent)

**Checkpoint**: Service starts, agents registered in Foundry, Cosmos containers exist with seed policy rules, health checks pass. User-story phases can now begin in parallel.

---

## Phase 3: User Story 1 — Apply & Underwrite (Priority: P1) 🎯 MVP

**Goal**: An authenticated user submits a loan application and triggers a synchronous S01–S10 workflow run that returns an `APPROVE` / `CONDITIONAL` / `DECLINE` recommendation with confidence.

**Independent Test**: `POST /api/loans/applications` for Alice Goodman, then `POST /api/loans/applications/{appNo}/run`, then `GET /api/loans/applications/{appNo}` — response contains `recommendation = APPROVE` with `confidence ≥ 0.7` and a complete 10-step run log. Verifiable via curl alone, no UI required.

### Tests for User Story 1 ⚠️

> Write tests FIRST, ensure they FAIL before implementation.

- [ ] T030 [P] [US1] Contract test for `POST /api/loans/applications` against `contracts/loan-origination-api.json` in `src/loan-origination-service.Tests/Contracts/ApplicationsContractTests.cs`
- [ ] T031 [P] [US1] Contract test for `GET /api/loans/applications/{applicationNo}` and `POST /api/loans/applications/{applicationNo}/run` in `src/loan-origination-service.Tests/Contracts/RunContractTests.cs`
- [ ] T032 [P] [US1] Unit tests for `PolicyEvaluationService` covering POL-001..POL-010 in `src/loan-origination-service.Tests/PolicyEvaluationTests.cs`
- [ ] T033 [P] [US1] Unit tests for `PricingService` (risk-tier → APR mapping, monthly-payment formula) in `src/loan-origination-service.Tests/PricingTests.cs`
- [ ] T034 [P] [US1] Unit tests for `EnrichmentService` deterministic synthetic generation (same `applicationNo` → same signals) in `src/loan-origination-service.Tests/EnrichmentTests.cs`
- [ ] T035 [P] [US1] Unit tests for `LoanAgentOrchestrator` happy path with mocked `IAIProjectClient` returning Alice's `APPROVE` recommendation in `src/loan-origination-service.Tests/OrchestratorTests.cs`

### Implementation for User Story 1

- [ ] T040 [P] [US1] Implement `src/loan-origination-service/Repositories/CosmosLoanApplicationRepository.cs` (PK `/id` == `applicationNo`) with create/get/list-by-user
- [ ] T041 [P] [US1] Implement `src/loan-origination-service/Repositories/CosmosLoanRunRepository.cs` (PK `/applicationNo`) with append/get-latest/list-by-application
- [ ] T042 [P] [US1] Implement `src/loan-origination-service/Services/EnrichmentService.cs` — deterministic synthetic credit/income/fraud generators keyed on `applicationNo` (per research R6)
- [ ] T043 [P] [US1] Implement `src/loan-origination-service/Services/PricingService.cs` — risk-tier APR table + monthly-payment / payoff-date computation
- [ ] T044 [P] [US1] Implement `src/loan-origination-service/Services/PolicyEvaluationService.cs` — evaluates POL-001..POL-010 against enriched application data
- [ ] T045 [US1] Implement `src/loan-origination-service/Agents/ILoanAgentOrchestrator.cs` + `src/loan-origination-service/Agents/LoanAgentOrchestrator.cs` — the code-based coordinator running S01–S10 sequentially, compiling the underwriting brief, calling the underwriting agent, persisting `LoanRun` after each step, and emitting per-step OTEL spans via `WorkflowTelemetry` (depends on T013, T015, T016, T040–T044)
- [ ] T045b [US1] **(NT-4, M2)** Implement `src/loan-origination-service/Agents/OfflineLoanAgentOrchestrator.cs` — an alternate `ILoanAgentOrchestrator` registered in DI when `Foundry__Mode=offline`. Skips all Foundry agent calls and returns deterministic canned recommendations keyed on `applicationNo` hash (same synthetic strategy as research R6). Reuses `EnrichmentService` (T042) for signal generation. Enables local UI/dev iteration without a Foundry connection. Depends on T045 (interface) and T042.
- [ ] T046 [US1] Implement application-number generator (`APP-YYYY-NNNNNN`) in `src/loan-origination-service/Services/ApplicationNumberGenerator.cs`
- [ ] T047 [US1] Implement `src/loan-origination-service/Controllers/LoansController.cs` with:
  - `POST /api/loans/applications` — JWT `User` role, `userId` from claim (never body), defaults identity from `UserLookupService`, persists status `submitted`
  - `GET /api/loans/applications/{applicationNo}` — returns application + last run + last decision (decision optional in US1)
  - `GET /api/loans/applications` — admin-only list-all
  - `POST /api/loans/applications/{applicationNo}/run` — synchronous orchestrator invocation returning `AgentRunResponse`
- [ ] T048 [US1] Add DataAnnotations + manual validation (loan amount range, term range, type whitelist) and structured error responses to `LoansController`
- [ ] T049 [US1] Add `seed-data.sh` snippet under `scripts/` that creates Alice Goodman's application via the new API (extending the existing seed flow — does NOT call `account-opening-service`)

**Checkpoint**: User Story 1 is fully functional. Curl-only happy path for Alice produces `APPROVE` with confidence ≥ 0.7 and a 10-step run log.

---

## Phase 4: User Story 2 — Decide, Fund & Announce (Priority: P2)

**Goal**: An admin records a decision (`approve` / `conditional` / `decline`). On approval, the service creates a `LoanAccount` + initial `LoanDisbursement` **entirely in-domain** (writes to its own `loan-accounts` and `loan-disbursements` Cosmos containers — **no calls to `account-service` or `transaction-service`**) and publishes the 5 lifecycle events. Loan-account read APIs expose the result. Personas Bob (`CONDITIONAL`) and Charlie (`DECLINE`) become testable.

**Independent Test**: After US1, `POST /api/loans/applications/{appNo}/decisions` with `decision=approve` for Alice → `GET /api/loans/accounts/{loanAccountId}` returns the loan record; `XINFO STREAM banking-events` shows `loan.approved` then `loan.funded` entries; re-approving the same application returns the existing `loanAccountId` (NFR-5 idempotency). Bob's run returns `CONDITIONAL` and emits `loan.declined`-equivalent flow per spec; Charlie's returns `DECLINE` and emits `loan.declined`. All 5 events (`loan.application.submitted`, `loan.run.completed`, `loan.approved`, `loan.declined`, `loan.funded`) are observable on `banking-events`.

### Tests for User Story 2 ⚠️

- [ ] T060 [P] [US2] Contract test for `POST /api/loans/applications/{applicationNo}/decisions` in `src/loan-origination-service.Tests/Contracts/DecisionsContractTests.cs`
- [ ] T061 [P] [US2] Contract tests for `GET /api/loans/accounts`, `GET /api/loans/accounts/{loanAccountId}`, and `GET /api/loans/accounts/{loanAccountId}/disbursements` in `src/loan-origination-service.Tests/Contracts/LoanAccountsContractTests.cs`
- [ ] T062 [P] [US2] Unit tests for `LoanEventPublisher` asserting `loan.approved` and `loan.funded` payload shapes against `banking-events` (fake `IConnectionMultiplexer`) in `src/loan-origination-service.Tests/LoanEventPublisherTests.cs`
- [ ] T062b [P] [US2] **(NT-3, M1)** Extend `src/loan-origination-service.Tests/LoanEventPublisherTests.cs` with assertions for the 3 additional event payload shapes: `loan.application.submitted` (carries `applicationNo`, `userId`, `requestedAmount`, `loanType`), `loan.run.completed` (carries `applicationNo`, `runId`, `recommendation`, `confidence`), and `loan.declined` (carries `applicationNo`, `decisionId`, `rationale`). Depends on T062.
- [ ] T063 [P] [US2] Unit tests for `DecisionsController` covering idempotent approve (NFR-5) and admin-only authorization in `src/loan-origination-service.Tests/ControllerTests.cs`
- [ ] T064 [P] [US2] Orchestrator unit tests for Bob (`CONDITIONAL`) and Charlie (`DECLINE`) personas in `src/loan-origination-service.Tests/OrchestratorPersonaTests.cs`
- [ ] T065 [P] [US2] **(NT-1, H2)** Contract test for `GET /api/loans/applications/{applicationNo}/decisions` against `contracts/loan-origination-api.json` in `src/loan-origination-service.Tests/Contracts/DecisionsGetContractTests.cs`. Validates response shape: array of `Decision` objects with `id`, `applicationNo`, `decision`, `fundingResult`, `createdAt`. Depends on T017 (models). Parallel with T060–T064.

### Implementation for User Story 2

- [ ] T070 [P] [US2] Implement `src/loan-origination-service/Repositories/CosmosDecisionRepository.cs` (PK `/applicationNo`, append-only)
- [ ] T071 [P] [US2] Implement `src/loan-origination-service/Repositories/CosmosLoanAccountRepository.cs` (PK `/userId`) with `Create`, `GetById`, `ListByUser`, `ListAll` — writes only to the in-domain `loan-accounts` Cosmos container; no calls to `account-service`
- [ ] T072 [P] [US2] Implement `src/loan-origination-service/Repositories/CosmosLoanDisbursementRepository.cs` (PK `/loanAccountId`) with `Append`, `ListByLoanAccount` — writes only to the in-domain `loan-disbursements` Cosmos container; no calls to `transaction-service`
- [ ] T073 [P] [US2] Implement `src/loan-origination-service/Services/LoanEventPublisher.cs` — initial implementation publishes `loan.approved` and `loan.funded` to the `banking-events` Redis Stream with payload per FR-14 (XADD MAXLEN ~ trimming, payload includes `applicationNo`, `userId`, `loanAccountId` where applicable)
- [ ] T073b [US2] **(NT-2, M1)** Extend `src/loan-origination-service/Services/LoanEventPublisher.cs` to publish the 3 additional events: `loan.application.submitted` (on application create), `loan.run.completed` (on run/recompute completion), and `loan.declined` (on decline decision). Wire the publish calls into:
  - `LoansController.Post` (T047) → emits `loan.application.submitted` after persistence
  - `LoanAgentOrchestrator` (T045) and `OfflineLoanAgentOrchestrator` (T045b) → emit `loan.run.completed` after the final step
  - `DecisionsController.Post` (T074) → emits `loan.declined` on decline path
  Depends on T073, T045, T045b, T047, T074.
- [ ] T074 [US2] Implement `src/loan-origination-service/Controllers/DecisionsController.cs`:
  - `POST /api/loans/applications/{applicationNo}/decisions` — admin-only; on `approve` calls `LoanFundingService` (T075) to provision `LoanAccount` + `LoanDisbursement` in-domain and publish `loan.approved` + `loan.funded`; on `decline` publishes `loan.declined`; idempotent on re-approval (FR-12, NFR-5)
  - `GET /api/loans/applications/{applicationNo}/decisions` — admin or owning user
- [ ] T075 [US2] Implement `src/loan-origination-service/Services/LoanFundingService.cs` orchestrating **in-domain only**: read application + last run → create `LoanAccount` (status `funded`) in `loan-accounts` Cosmos container → append funding `LoanDisbursement` to `loan-disbursements` Cosmos container → update application with `fundedLoanAccountId` and `status = funded` → publish `loan.approved` then `loan.funded`. **No HTTP calls to `account-service` or `transaction-service`.** (Depends on T070–T073.)
- [ ] T076 [US2] Implement `src/loan-origination-service/Controllers/LoanAccountsController.cs`:
  - `GET /api/loans/accounts` — caller's loan accounts; admin may pass `?userId=`
  - `GET /api/loans/accounts/{loanAccountId}` — full detail (owner or admin)
  - `GET /api/loans/accounts/{loanAccountId}/disbursements` — disbursement history
- [ ] T077 [US2] Extend `scripts/seed-data.sh` to also create Bob Marginal and Charlie Risky applications via the API so personas are demoable end-to-end

**Checkpoint**: All three personas reach their expected outcomes. Approval round-trips through **in-domain** loan-account creation, in-domain disbursement record, and Redis Stream events. All 5 lifecycle events observable on `banking-events`. `account-opening-service`, `account-service`, and `transaction-service` remain bit-for-bit unchanged.

---

## Phase 5: User Story 3 — Live Workflow & Review UI (Priority: P3)

**Goal**: SSE-driven live workflow visualization, recompute with adjusted terms, and the full React `/loans` surface (Intake, My Loans, Workflow viz, Admin Review + Decision panel). OTEL trace per run shows 10 child spans. Playwright E2E covers the happy path including a zero-deposit-accounts user.

**Independent Test**: Open `/loans/apply` in the UI, submit an application, watch the live SSE workflow render 10 step dots transitioning to `completed`, then as Admin open `/loans/admin/review`, decide `approve`, and see the funded loan appear on `/loans/accounts` for the user. Application Insights shows a single trace with 10 child spans.

### Tests for User Story 3 ⚠️

- [ ] T090 [P] [US3] Contract test for SSE `GET /api/loans/applications/{applicationNo}/run-stream` (events: `step`, `complete`, content-type `text/event-stream`) in `src/loan-origination-service.Tests/Contracts/RunStreamContractTests.cs`
- [ ] T091 [P] [US3] Contract test for `POST /api/loans/applications/{applicationNo}/recompute` (re-runs S07–S09, preserves original run) in `src/loan-origination-service.Tests/Contracts/RecomputeContractTests.cs`
- [ ] T092 [P] [US3] Playwright E2E happy-path test `tests/e2e/loan-origination.spec.ts` covering: submit (UI) → live SSE workflow viz → admin approve → `/loans/accounts` shows funded loan → `loan.funded` event verified via test hook
- [ ] T093 [P] [US3] Playwright variant in the same spec asserting a user with **zero deposit accounts** can complete the full flow (acceptance criterion)

### Implementation for User Story 3

- [ ] T100 [US3] Add SSE endpoint `GET /api/loans/applications/{applicationNo}/run-stream` to `src/loan-origination-service/Controllers/LoansController.cs` — streams per-step events as the orchestrator progresses; terminates with `event: complete` carrying the `AgentRunResponse`
- [ ] T101 [US3] Add `POST /api/loans/applications/{applicationNo}/recompute` to `LoansController` — re-runs S07–S09 with adjusted `requestedAmount` / `termMonths` / `loanType` and persists as a new `LoanRun` (FR-10). Must also emit `loan.run.completed` (via T073b).
- [ ] T102 [US3] Refine `WorkflowTelemetry` so each S01–S10 step is a child span of a single per-run parent span carrying `application_no` and `run_id` baggage (FR-16)
- [ ] T110 [P] [US3] Create `src/ui-app/src/api/loans.ts` — typed REST client + `EventSource` wrapper for the SSE endpoint
- [ ] T111 [P] [US3] Implement `src/ui-app/src/components/loans/LoanIntakeForm.tsx` (MUI v9) with amount/term/type/purpose/income/debts/housing fields; auto-fills identity from JWT user profile
- [ ] T112 [P] [US3] Implement `src/ui-app/src/components/loans/WorkflowStepList.tsx` rendering the 10 steps with status dots and per-step timing
- [ ] T113 [P] [US3] Implement `src/ui-app/src/components/loans/RecommendationCard.tsx` showing `recommendation`, `confidence`, rationale, key factors, policy hits
- [ ] T114 [P] [US3] Implement `src/ui-app/src/components/loans/DecisionPanel.tsx` (admin) with accept / conditional / decline + optional adjusted amount/term/rate + notes → calls `recompute` then `decisions`
- [ ] T115 [P] [US3] Implement `src/ui-app/src/components/loans/LoanAccountCard.tsx` and `src/ui-app/src/components/loans/DisbursementHistory.tsx`
- [ ] T120 [P] [US3] Implement `src/ui-app/src/pages/LoansIntakePage.tsx` at route `/loans/apply` (composes `LoanIntakeForm`)
- [ ] T121 [P] [US3] Implement `src/ui-app/src/pages/MyLoansPage.tsx` at route `/loans/accounts` (composes `LoanAccountCard` + applications list) — distinct from `/accounts`
- [ ] T122 [P] [US3] Implement `src/ui-app/src/pages/LoanWorkflowPage.tsx` at route `/loans/applications/:appNo` (live SSE viz via `WorkflowStepList` + `RecommendationCard`)
- [ ] T123 [P] [US3] Implement `src/ui-app/src/pages/LoanReviewPage.tsx` at route `/loans/admin/review` (admin-only DataGrid + `DecisionPanel`)
- [ ] T124 [US3] Modify `src/ui-app/src/App.tsx` to register the four new `/loans/*` routes — **do not touch the existing `/accounts` route**

**Checkpoint**: Full UX flow demoable end-to-end. Application Insights shows 10-child-span trace per run. Playwright E2E green.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Deployment manifests, docs, ADR, and the smoke-test gate.

- [ ] T130 [P] Create `deploy/kustomize/base/loan-origination-service.yaml` (Deployment, Service, ServiceAccount binding to `banking-workload-identity`)
- [ ] T131 [P] Create `deploy/kustomize/base/istio/loan-origination-vs.yaml` routing `/api/loans/*` → `loan-origination-service`
- [ ] T132 Modify `deploy/kustomize/base/kustomization.yaml` to include the new resources and image entry
- [ ] T133 Modify `deploy/kustomize/base/configmap.yaml` to add `LOAN_ORIGINATION_SERVICE_URL` for `ui-app` and `USER_SERVICE_URL` for `loan-origination-service` (if not already present)
- [ ] T134 [P] Add `task cloud:build` image entry for `loan-origination-service` in `Taskfile.build.yml` (or equivalent build manifest used by the repo)
- [ ] T135 [P] Modify `docs/architecture.md` to add the Loan Origination section + service to the architecture map
- [ ] T136 [P] Create `docs/adr/007-loan-workflow-coordinator.md` documenting workflow-only port (no classic) and the in-domain ownership model
- [ ] T137 Run quickstart.md end-to-end against AKS at `${CUSTOM_DOMAIN}` (`onlinebankingdemo.bjdazure.tech`): submit, run, decide, verify in UI; confirms acceptance criteria

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)** → no dependencies
- **Phase 2 (Foundational)** → depends on Phase 1; blocks all user stories
- **Phase 3 (US1)** → depends on Phase 2
- **Phase 4 (US2)** → depends on Phase 2; US2 happy path also depends on US1's orchestrator and application repository for end-to-end demo (but US2 is unit-testable in isolation)
- **Phase 5 (US3)** → depends on Phase 2; UI surfaces for decisions/recompute exercise US2 endpoints; SSE depends on the US1 orchestrator
- **Phase 6 (Polish)** → depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Independent — needs only Phase 2.
- **US2 (P2)**: Logically follows US1 (decision requires an existing application + run) but its repositories, event publisher, and loan-account read APIs are independently testable with mocks.
- **US3 (P3)**: UI consumes US1 + US2 APIs; SSE/recompute extend US1's orchestrator. Frontend tasks themselves are independent of one another.

### New-Task Dependencies (NT-1..NT-5)

- **T003b (NT-5, docker-compose entry)**: Depends on T003 (Dockerfile). Setup phase, no story label.
- **T045b (NT-4, offline orchestrator stub)**: Depends on T045 (interface) and T042 (enrichment). US1, post-T045 — does NOT change MVP gate.
- **T062b (NT-3, 3 new event unit tests)**: Depends on T062. US2 tests, parallel with T060/T061/T063/T064/T065.
- **T065 (NT-1, GET /decisions contract test)**: Depends on T017 (models). US2 tests, parallel with T060–T064.
- **T073b (NT-2, expand publisher to 5 events)**: Depends on T073, T045, T045b, T047, T074 — must run after the controllers/orchestrators it wires into exist.

### Within Each User Story

- Tests are written first and must fail before implementation (NFR-8).
- Models → Repositories → Services → Orchestrator/Controllers → Validation.
- Cross-story integration (events, UI) only after both producing and consuming stories are complete.

### Parallel Opportunities

- Setup tasks T003, T003b, T004, T005, T006 run in parallel (T003b depends only on T003 having been authored — file-level independence).
- Foundational tasks T013–T020 run in parallel (T021 depends on T020; T012/T016/T023 are sequential within Program.cs/agent wiring).
- All US1 test tasks T030–T035 run in parallel.
- US1 repositories and services T040–T044 run in parallel; orchestrator T045 then aggregates; T045b runs after T045.
- All US2 test tasks T060, T061, T062, T062b, T063, T064, T065 run in parallel.
- US2 repositories T070–T073 run in parallel; T073b is sequential (wires existing controllers); funding service T075 aggregates.
- US3 UI components T110–T115 and pages T120–T123 are mutually independent — full parallelism.
- Polish tasks T130/T131/T134/T135/T136 run in parallel.

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together (write-first):
Task: "Contract test POST /api/loans/applications in src/loan-origination-service.Tests/Contracts/ApplicationsContractTests.cs"
Task: "Contract test run + get in src/loan-origination-service.Tests/Contracts/RunContractTests.cs"
Task: "PolicyEvaluation unit tests in src/loan-origination-service.Tests/PolicyEvaluationTests.cs"
Task: "Pricing unit tests in src/loan-origination-service.Tests/PricingTests.cs"
Task: "Enrichment unit tests in src/loan-origination-service.Tests/EnrichmentTests.cs"
Task: "Orchestrator happy-path tests in src/loan-origination-service.Tests/OrchestratorTests.cs"

# Then launch repositories + services in parallel:
Task: "CosmosLoanApplicationRepository in src/loan-origination-service/Repositories/CosmosLoanApplicationRepository.cs"
Task: "CosmosLoanRunRepository in src/loan-origination-service/Repositories/CosmosLoanRunRepository.cs"
Task: "EnrichmentService in src/loan-origination-service/Services/EnrichmentService.cs"
Task: "PricingService in src/loan-origination-service/Services/PricingService.cs"
Task: "PolicyEvaluationService in src/loan-origination-service/Services/PolicyEvaluationService.cs"

# After T045 completes, T045b can start in parallel with T046–T049:
Task: "OfflineLoanAgentOrchestrator (NT-4) in src/loan-origination-service/Agents/OfflineLoanAgentOrchestrator.cs"
```

## Parallel Example: User Story 2

```bash
# All US2 tests in parallel (NT-1 + NT-3 included):
Task: "DecisionsContractTests (POST) in src/loan-origination-service.Tests/Contracts/DecisionsContractTests.cs"
Task: "LoanAccountsContractTests in src/loan-origination-service.Tests/Contracts/LoanAccountsContractTests.cs"
Task: "LoanEventPublisherTests (loan.approved + loan.funded)"
Task: "LoanEventPublisherTests extension (NT-3) — submitted/run.completed/declined payloads"
Task: "DecisionsController unit tests"
Task: "Orchestrator persona tests (Bob, Charlie)"
Task: "DecisionsGetContractTests (NT-1) in src/loan-origination-service.Tests/Contracts/DecisionsGetContractTests.cs"

# US2 repositories + initial publisher in parallel:
Task: "CosmosDecisionRepository in src/loan-origination-service/Repositories/CosmosDecisionRepository.cs"
Task: "CosmosLoanAccountRepository (in-domain only) in src/loan-origination-service/Repositories/CosmosLoanAccountRepository.cs"
Task: "CosmosLoanDisbursementRepository (in-domain only) in src/loan-origination-service/Repositories/CosmosLoanDisbursementRepository.cs"
Task: "LoanEventPublisher (loan.approved + loan.funded) in src/loan-origination-service/Services/LoanEventPublisher.cs"

# After T073, T045, T045b, T047, T074 land:
Task: "LoanEventPublisher 5-event extension (NT-2, T073b)"
```

## Parallel Example: User Story 3

```bash
# UI components in parallel:
Task: "LoanIntakeForm.tsx"
Task: "WorkflowStepList.tsx"
Task: "RecommendationCard.tsx"
Task: "DecisionPanel.tsx"
Task: "LoanAccountCard.tsx + DisbursementHistory.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational → Phase 3 US1.
2. **STOP and VALIDATE**: Alice persona returns `APPROVE` ≥ 0.7 via curl with a complete 10-step run log.
3. Demo MVP — submit + underwrite end-to-end (no UI, no decisions, no loan accounts yet).

**MVP gate impact of new tasks**: None.
- T003b (NT-5, docker-compose) is a Setup task — runs alongside T003–T006 and does not delay the MVP.
- T045b (NT-4, offline orchestrator) lives inside Phase 3 US1 but is post-T045 and parallel with T046–T049; it adds local-dev affordance without delaying the curl-only Alice happy path that defines the MVP gate.
- T065 (NT-1), T062b (NT-3), T073b (NT-2) all live in Phase 4 US2 and do not affect MVP.

### Incremental Delivery

1. MVP (US1) → demo curl-only happy path (with optional offline-mode demo via T045b).
2. Add US2 → admin decision + in-domain loan account + in-domain disbursement + all 5 `loan.*` events; demo all three personas.
3. Add US3 → SSE live workflow viz, recompute, full `/loans` UI, Playwright E2E.
4. Polish → kustomize manifests, ADR, docs, smoke test at `${CUSTOM_DOMAIN}`.

### Parallel Team Strategy

After Phase 2 completes:

- Dev A: US1 backend (orchestrator + controllers) — owns T045b (offline orchestrator).
- Dev B: US2 backend (decisions, in-domain funding, 5-event publisher, loan-account read APIs) — owns T062b, T065, T073b.
- Dev C: US3 frontend (UI components and pages — depends only on contracts, not on backend completion).

---

## Notes

- [P] tasks touch different files with no incomplete-task dependencies.
- Every task has an exact file path so it is executable without additional context.
- Tests-first per NFR-8: contract/unit tests for a phase MUST fail before that phase's implementation tasks begin.
- The acceptance criterion "`account-opening-service`, `account-service`, `transaction-service` bit-for-bit unchanged" is enforced by *omission* — no task in this plan modifies any file under those service trees. **Funding (T075) writes only to in-domain Cosmos containers (`loan-accounts`, `loan-disbursements`); cross-domain communication is exclusively via the 5 Redis Stream events on `banking-events` per FR-14.**
- Task ID scheme: original tasks T001–T137 preserve numbering from the previous tasks.md (commit db1f60b). New tasks added per REMEDIATION.md use sub-IDs (`T003b`, `T045b`, `T062b`, `T073b`) and `T065` (which slots into the previously-empty Phase 4 test slot). Total: 80 tasks.
