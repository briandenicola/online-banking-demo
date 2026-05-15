# Implementation Plan: Loan Origination — Multi-Agent Workflow Underwriting

**Branch**: `017-loan-origination-workflow` | **Date**: 2026-05-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/017-loan-origination-workflow/spec.md`

## Summary

Add a `loan-origination-service` (.NET 10 / ASP.NET Core) that implements multi-agent loan underwriting using the **workflow / code-based coordinator** pattern from `briandenicola/loan-originations-demo`. Six versioned `PromptAgentDefinition` agents are registered in the existing Foundry project (`gpt-5.4-mini`), called sequentially by an orchestrator that compiles their outputs into a brief and passes it to an underwriting agent for the final `APPROVE` / `CONDITIONAL` / `DECLINE` recommendation.

The applicant is an **existing authenticated user** — account opening, KYC, and identity verification are upstream concerns owned by `account-opening-service` and are not invoked by this feature. On approval, loan-origination-service creates a `LoanAccount` (loan principal owed) and a `LoanDisbursement` (initial funding accounting entry) in its **own** Cosmos containers — no deposit account is created, no transaction is written to the deposit-side ledger, and no existing service receives a single line of code change. Lifecycle changes are announced via `loan.approved` / `loan.funded` events on the existing `banking-events` Redis Stream.

This feature is **purely additive** — it does not provision new Azure resources and does not modify any existing service. It reuses the Foundry account, capability host, and BYO connections from spec **001-azure-private-endpoints** and the `gpt-5.4-mini` deployment. The classic / agentic orchestration variant from the source repo is **out of scope**.

## Technical Context

**Language/Version**: C# / **.NET 10.0** (ASP.NET Core Web API) — matches all existing .NET services in this repo (`net10.0` TFM, `mcr.microsoft.com/dotnet/aspnet:10.0-alpine` runtime base). Frontend additions: React 19 + TypeScript + MUI v9.
**Primary Dependencies**:
- `Azure.AI.Projects` 2.0.0-beta.x (`AIProjectClient`, `PromptAgentDefinition`, `CreateAgentVersionAsync`) — same prerelease SDK already in `prompt-eval-service`.
- `Microsoft.Azure.Cosmos` 3.x (Newtonsoft serializer to match other .NET services).
- `Azure.Identity` (`DefaultAzureCredential` → workload identity in cluster).
- `Microsoft.AspNetCore.Authentication.JwtBearer` (HS256 with shared `Jwt__Key`).
- `OpenTelemetry.Extensions.Hosting` + OTLP exporter (matches existing .NET services).
- Frontend: existing MUI v9 + `@mui/x-data-grid` (already in `ui-app`); new SSE consumption via native `EventSource`.

**Storage** (**all six containers owned exclusively by loan-origination-service**):
- `loan-applications` (PK `/id`)
- `loan-runs` (PK `/applicationNo`)
- `underwriting-decisions` (PK `/applicationNo`)
- `loan-policy` (PK `/id`) — seed data
- `loan-accounts` (PK `/userId`) — replaces "create account in `accounts` container"
- `loan-disbursements` (PK `/loanAccountId`) — initial funding + future payments
- **Does NOT** read or write `accounts`, `transactions`, `transfers`, or any other domain's container.
- Read-only FK reference to `users.id` (validated lazily on first run via `user-service` `GET /api/users/{id}` — same pattern `account-service` already uses).
- No blob storage, no Search indexes.

**Testing**:
- xUnit for the service (mirrors `account-service.Tests`, `prompt-eval-service.Tests`).
- Playwright for E2E (extends `tests/e2e/`).
- Mock `IAIProjectClient` via interface seam in tests; mock Cosmos via `Microsoft.Azure.Cosmos.Container` test fakes.

**Target Platform**: Linux (Docker), runs on AKS in the `banking-demo` namespace under Workload Identity. Local dev via `docker-compose` with synthetic `Foundry__Mode=offline` flag that returns canned recommendations.

**Project Type**: Web service + frontend addition. New backend service + new React route.

**Performance Goals**:
- Workflow run p95 < 60s (six sequential agent calls against `gpt-5.4-mini`).
- Cosmos reads/writes p95 < 50ms (single-region, Direct mode).
- SSE first-byte < 500ms (start of S01).

**Constraints**:
- All Foundry / Cosmos traffic stays on private endpoints (constitution §II).
- Workload Identity only — no connection-string secrets (constitution §III).
- All endpoints emit OTEL traces with `application_no` and `run_id` baggage (constitution §VI).
- The classic / `ConnectedAgentTools` pattern is explicitly excluded.

**Scale/Scope**:
- Demo workload: ~10s of applications/day, single AKS replica (HPA at 1–3).
- Cosmos containers sized at 400 RU/s shared throughput across the new four (matches existing demo pattern).

## Constitution Check

| Principle | Compliance | Notes |
|---|---|---|
| **I. Security by Design** | ✅ PASS | All endpoints JWT-authenticated; `userId` always derived from JWT claim, never accepted from request body; admin-only on decision/list-all; input validation at controller boundary via DataAnnotations + manual checks; container scanned by existing Trivy step in `task cloud:build`. |
| **II. Private Networking Always** | ✅ PASS | No new Azure resources. Foundry calls go via the private endpoint provisioned by spec 001. Cosmos and Redis calls use the existing private endpoints. No new public IPs. |
| **III. Entra ID for Service Authentication** | ✅ PASS | `DefaultAzureCredential` resolves to workload identity in cluster. Foundry RBAC (`Cognitive Services User`) granted to existing `banking-workload-identity` service account. Cosmos RBAC (`Cosmos DB Built-in Data Contributor`) is at the database scope so the new containers inherit access — no new role assignments needed if database-scope grant is in place. Redis uses Entra-token auth with the same workload identity. |
| **IV. Coding Best Practices** | ✅ PASS | Mirrors `prompt-eval-service` and `account-service` patterns: DI, async/await, records for DTOs, structured JSON logging, repository pattern over Cosmos. .NET 10 (matches the rest of the .NET fleet — `net10.0` TFM). |
| **V. Convention over Configuration** | ✅ PASS | Service name `loan-origination-service` follows `{domain}-service` convention. Image name derived from the service name in `Taskfile.build.yml`. Istio route `/api/loans/*` matches the existing `/api/{domain}/*` pattern. Cosmos containers named with the existing `{domain}-{noun}` convention (`loan-applications`, `loan-runs`, `loan-accounts`, `loan-disbursements`, etc.). Redis Stream events use the existing `banking-events` stream and `{domain}.{verb}` event-type convention. |
| **VI. Observability First** | ✅ PASS | `/healthz` + `/readyz` on day one. OTEL traces auto-instrumented for ASP.NET Core, Cosmos SDK, Redis client, and HttpClient; manual spans wrap each S01–S10 step with `agent.name` attributes. App Insights only via the existing OTEL Collector. |

**Additional architectural gate — Separation of Concerns:**

| Boundary check | Status | Notes |
|---|---|---|
| No code changes to `account-opening-service`, `account-service`, `transaction-service`, `transfer-service`, `user-service`, `ai-service`, `chatbot-service`, `budget-service`, `event-processor`, or `prompt-eval-service` | ✅ PASS | Verified by acceptance criterion: `git diff main -- src/{above}/` returns empty. |
| loan-origination-service owns 100% of its data | ✅ PASS | Six dedicated Cosmos containers, all PK'd within the loan domain. No reads/writes to other domains' containers. |
| Cross-domain communication is read-only or async | ✅ PASS | Read: `GET /api/users/{id}` for FK validation. Async: publish `loan.approved` / `loan.funded` to `banking-events`. No synchronous mutations into other services. |
| Loan funding is internal accounting | ✅ PASS | `LoanDisbursement` lives in `loan-disbursements` (loan domain). No deposit account credit. No `transactions`-container write. |
| Foundry agents are namespaced | ✅ PASS | Hyphenated agent names (`credit-profile-agent`, etc.) are unique within the shared project. Other services' agents use distinct names — no collision risk. |

**No violations. No complexity-tracking entries required.**

## Project Structure

### Documentation (this feature)

```text
specs/017-loan-origination-workflow/
├── spec.md              # Feature spec (already written)
├── plan.md              # This file
├── research.md          # Phase 0 — orchestration & SDK decisions
├── data-model.md        # Phase 1 — Cosmos entities, state diagrams
├── quickstart.md        # Phase 1 — operator onboarding
├── contracts/
│   └── loan-origination-api.json   # OpenAPI 3.0 contract for /api/loans/*
└── tasks.md             # Phase 2 — generated by /speckit.tasks
```

### Source Code (repository root)

```text
src/
├── loan-origination-service/                  # NEW — .NET 9 ASP.NET Core
│   ├── LoanOrigination.csproj
│   ├── Program.cs
│   ├── Dockerfile
│   ├── appsettings.json
│   ├── Controllers/
│   │   ├── LoansController.cs                 # POST/GET applications, run, run-stream
│   │   ├── DecisionsController.cs             # POST/GET decisions, recompute
│   │   └── LoanAccountsController.cs          # NEW — GET loan accounts + disbursements (read-only)
│   ├── Models/
│   │   ├── LoanApplication.cs
│   │   ├── LoanAccount.cs                    # NEW — loan principal record (NOT a deposit account)
│   │   ├── LoanDisbursement.cs               # NEW — funding entry (NOT a deposit-side transaction)
│   │   ├── LoanLifecycleEvent.cs             # NEW — Redis Stream event payload
│   │   ├── CreditProfile.cs
│   │   ├── IncomeVerification.cs
│   │   ├── FraudSignals.cs
│   │   ├── PolicyThreshold.cs
│   │   ├── ProductPricing.cs
│   │   ├── UnderwritingRecommendation.cs
│   │   ├── WorkflowStep.cs
│   │   ├── DecisionRecord.cs
│   │   └── AgentRunResponse.cs
│   ├── Repositories/
│   │   ├── ICosmosRepository.cs
│   │   ├── CosmosLoanApplicationRepository.cs
│   │   ├── CosmosLoanRunRepository.cs
│   │   ├── CosmosDecisionRepository.cs
│   │   ├── CosmosPolicyRepository.cs
│   │   ├── CosmosLoanAccountRepository.cs    # NEW container — loan-accounts
│   │   └── CosmosLoanDisbursementRepository.cs  # NEW container — loan-disbursements
│   ├── Services/
│   │   ├── EnrichmentService.cs              # Synthetic credit/income/fraud generators (replaces CsvDataService)
│   │   ├── PricingService.cs                 # Risk-tier → APR table, monthly payment formula
│   │   ├── PolicyEvaluationService.cs        # POL-001..POL-010 evaluator
│   │   ├── UserLookupService.cs              # READ-ONLY HttpClient → user-service GET /api/users/{id}
│   │   └── LoanEventPublisher.cs             # Publishes loan.approved / loan.funded to banking-events Redis Stream
│   ├── Agents/
│   │   ├── ILoanAgentOrchestrator.cs
│   │   ├── LoanAgentOrchestrator.cs          # Code-based coordinator
│   │   ├── PromptLoader.cs                   # Loads prompts from ./prompts/*.txt
│   │   └── AgentRegistration.cs              # Idempotent CreateAgentVersionAsync at startup
│   ├── prompts/                              # ← Ported verbatim from source repo
│   │   ├── CreditProfileAgentPrompt.txt
│   │   ├── IncomeVerificationAgentPrompt.txt
│   │   ├── FraudScreeningAgentPrompt.txt
│   │   ├── PolicyEvaluationAgentPrompt.txt
│   │   ├── PricingAgentPrompt.txt
│   │   ├── UnderwritingAgentPrompt.txt
│   │   └── HealthCheckAgentPrompt.txt
│   ├── Telemetry/
│   │   └── WorkflowTelemetry.cs              # ActivitySource + step-span helpers
│   └── seed/
│       ├── policy-rules.json                 # POL-001..POL-010 seed for loan-policy container
│       └── product-pricing.json              # Risk-tier APR matrix
├── loan-origination-service.Tests/            # NEW — xUnit
│   ├── LoanOrigination.Tests.csproj
│   ├── OrchestratorTests.cs
│   ├── PolicyEvaluationTests.cs
│   ├── PricingTests.cs
│   ├── EnrichmentTests.cs
│   ├── AccountIntegrationTests.cs
│   └── ControllerTests.cs
└── ui-app/                                   # MODIFIED (additive only)
    └── src/
        ├── api/loans.ts                      # NEW — typed REST client + EventSource wrapper
        ├── pages/
        │   ├── LoansIntakePage.tsx           # NEW — /loans/apply
        │   ├── MyLoansPage.tsx               # NEW — /loans/accounts (user's loan accounts; SEPARATE from /accounts)
        │   ├── LoanWorkflowPage.tsx          # NEW — /loans/applications/:appNo (live SSE viz)
        │   └── LoanReviewPage.tsx            # NEW — /loans/admin/review (admin dashboard + decision panel)
        ├── components/loans/
        │   ├── LoanIntakeForm.tsx
        │   ├── WorkflowStepList.tsx
        │   ├── RecommendationCard.tsx
        │   ├── DecisionPanel.tsx
        │   ├── LoanAccountCard.tsx
        │   └── DisbursementHistory.tsx
        └── App.tsx                           # MODIFIED — add /loans/* routes only; existing /accounts route untouched

deploy/kustomize/base/
├── loan-origination-service.yaml             # NEW — Deployment, Service, ServiceAccount binding
├── kustomization.yaml                        # MODIFIED — add resource + image entry only
├── istio/loan-origination-vs.yaml            # NEW — VirtualService /api/loans/* → service
└── configmap.yaml                            # MODIFIED — add LOAN_ORIGINATION_SERVICE_URL for ui-app + USER_SERVICE_URL for loan-origination-service (if not already present)

infra/cloud/
├── cosmos.tf                                 # MODIFIED — add 6 new containers (loan-applications, loan-runs, underwriting-decisions, loan-policy, loan-accounts, loan-disbursements). Verify database-scope RBAC covers them.
└── identity.tf                               # MODIFIED IF NEEDED — verify Foundry RBAC on workload identity (likely already present from spec 002)

tests/e2e/
└── loan-origination.spec.ts                  # NEW — Playwright happy-path + zero-deposit-accounts variant

docs/
├── architecture.md                           # MODIFIED — add Loan Origination section + service to map
└── adr/007-loan-workflow-coordinator.md      # NEW — ADR justifying workflow-only port (no classic) and the in-domain ownership model

scripts/
└── seed-data.sh                              # MODIFIED — add 3 loan applications for existing demo users (Alice/Bob/Charlie). Does NOT create users via account-opening-service — uses the existing user-creation path.

# DELIBERATELY UNCHANGED — verified by acceptance criterion:
# - src/account-opening-service/    (zero diff)
# - src/account-service/            (zero diff)
# - src/transaction-service/        (zero diff)
# - src/transfer-service/           (zero diff)
# - src/user-service/               (zero diff)
# - src/ai-service/                 (zero diff)
# - src/chatbot-service/            (zero diff)
# - src/budget-service/             (zero diff)
# - src/event-processor/            (zero diff)
# - src/prompt-eval-service/        (zero diff)
```

**Structure Decision**: Single new .NET 10 service + frontend additions to the existing React app. Mirrors the structure of the existing `prompt-eval-service` (a .NET 10 service that also uses `Azure.AI.Projects` against the existing Foundry project). **Zero modifications to any existing service** — verified by an explicit acceptance criterion. No new top-level subsystems.

## Phases

### Phase 0 — Outline & Research

See [research.md](./research.md). Topics resolved:

- **R1.** Confirm `Azure.AI.Projects` 2.0.0-beta.1 is the right SDK (vs. `Microsoft.Agents.AI.AzureAI.Persistent` used in classic).
- **R2.** Decide whether agent registration runs in an init container (like `account-opening-service`) or in the service `Program.cs` `lifetime`.
- **R3.** Decide whether to mirror the source SSE endpoint (`text/event-stream`) or use Azure SignalR / WebSockets.
- **R4.** Decide whether `loan-applications` should embed the latest run + decision or keep them in separate containers.
- **R5.** Confirm reuse of the existing Foundry capability host without a second project.
- **R6.** Choose the synthetic data strategy for credit / income / fraud signals (deterministic per `applicationNo`).
- **R7.** Confirm RBAC additions for the existing `banking-workload-identity` service account (Foundry + new Cosmos containers).
- **R8.** Domain-ownership boundaries — why the loan domain owns its own accounts and disbursements end-to-end and never touches `account-service` / `transaction-service` / `account-opening-service`.

**All NEEDS CLARIFICATION items resolved in research.md. No open clarifications remain.**

### Phase 1 — Design & Contracts

**Prerequisites:** research.md complete (✅).

1. **Data model** — see [data-model.md](./data-model.md). Defines four Cosmos entities (`LoanApplication`, `LoanRun`, `Decision`, `PolicyRule`), the application status state machine (`submitted → enriched → recommended → decided → funded`), and the workflow step lifecycle.

2. **Interface contracts** — see [contracts/loan-origination-api.json](./contracts/loan-origination-api.json). OpenAPI 3.0 spec covering:
   - `POST /api/loans/applications`
   - `GET /api/loans/applications`
   - `GET /api/loans/applications/{applicationNo}`
   - `POST /api/loans/applications/{applicationNo}/run`
   - `GET /api/loans/applications/{applicationNo}/run-stream` (SSE)
   - `POST /api/loans/applications/{applicationNo}/recompute`
   - `POST /api/loans/applications/{applicationNo}/decisions`
   - `GET /api/loans/applications/{applicationNo}/decisions`
   - `GET /healthz`, `GET /readyz`

3. **Quickstart** — see [quickstart.md](./quickstart.md). Operator guide for local-dev, building/deploying to AKS, seeding policy rules and demo applicants, and verifying via the React UI.

4. **Agent context update** — `.specify/scripts/bash/update-agent-context.sh copilot` is run during plan execution to add the new tech entries.

**Output:** data-model.md, contracts/loan-origination-api.json, quickstart.md, updated `.github/copilot-instructions.md`. ✅

### Phase 2 — Tasks (NOT generated by this command)

`/speckit.tasks` will decompose this plan into ordered, dependency-aware work items. Anticipated task buckets:

1. **Infra** — extend Cosmos containers via Terraform; verify RBAC.
2. **Service scaffold** — `LoanOrigination.csproj`, Program.cs, JWT auth, Cosmos client wiring.
3. **Models + Repositories** — port `LoanModels.cs` from source; add Cosmos repositories.
4. **Enrichment + Pricing + Policy services** — port from source `CsvDataService` + `UnderwritingService`, replace CSV with deterministic synthetic generators.
5. **Agent registration** — `AgentRegistration.cs` calls `CreateAgentVersionAsync` for the 6 specialists + health-check at startup.
6. **Orchestrator** — port `LoanAgentOrchestrator.cs` (workflow path only) with `Microsoft.Azure.Cosmos` persistence and `ActivitySource` instrumentation.
7. **Controllers** — `LoansController` + `DecisionsController` + SSE.
8. **Cross-service integration** — `UserLookupService` for the read-only FK validation against `user-service`. `LoanEventPublisher` for `loan.approved` / `loan.funded` events on the `banking-events` Redis Stream. **No `AccountIntegrationService`** — loan funding is internal to the loan domain.
9. **Tests** — xUnit for orchestrator/policy/pricing/controllers.
10. **Kustomize manifests** — Deployment + Service + VirtualService.
11. **Frontend** — `/loans` route, intake form, SSE workflow viz, admin dashboard.
12. **Seed data** — POL-001..POL-010 + product pricing JSON; demo applicants in `seed-data.sh`.
13. **E2E test** — Playwright happy-path.
14. **Docs** — architecture.md updates + ADR-007.
15. **Smoke test** — verify against `${CUSTOM_DOMAIN}`.

## Complexity Tracking

> No constitutional violations. This section is intentionally empty.
