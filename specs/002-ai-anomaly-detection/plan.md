# Implementation Plan: AI Admin Portal (US5)

**Branch**: `002-ai-anomaly-detection` | **Date**: 2026-05-08 | **Spec**: `specs/005-ai-admin-portal/spec.md`

## Summary

Build a new C#/.NET 9 `prompt-eval-service` that uses Azure AI Foundry's Evaluation SDK (`Azure.AI.Projects`) to let admins evaluate and tune the AI prompts used for risk scoring and categorization. Adds a new "AI Evaluation" tab to the existing Admin page. Admins can view/edit prompts, run evaluations against real transactions, and compare quality + safety scores across runs.

## Technical Context

**Language/Version**: C# / .NET 9.0 (ASP.NET Core Web API)
**Primary Dependencies**: Azure.AI.Projects (prerelease), Microsoft.Azure.Cosmos, Azure.Identity, Microsoft.AspNetCore.Authentication.JwtBearer
**Storage**: Azure Cosmos DB — new containers `prompt-templates` and `evaluation-runs`
**Testing**: dotnet test (xUnit)
**Target Platform**: Linux container on AKS
**Project Type**: Web service (microservice)
**Constraints**: Evaluation runs are async (server-side in Foundry) — UI must poll for completion
**Scale/Scope**: Admin-only feature, low throughput (<10 concurrent eval runs)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Security by Design | ✅ PASS | All endpoints require Admin JWT. No anonymous access. |
| II. Private Networking | ✅ PASS | Service runs in AKS, communicates via K8s DNS. Cosmos via private endpoint. |
| III. Entra ID for Auth | ✅ PASS | Workload Identity for Foundry + Cosmos. Dual-mode for local dev. |
| IV. Coding Best Practices | ✅ PASS | ASP.NET Core DI, async/await, structured logging. |
| V. Convention over Config | ✅ PASS | Same patterns as account-service, user-service. Derives config from existing env vars. |
| VI. Observability First | ✅ PASS | OTEL instrumentation, health endpoints. |

**Post-design re-check**: All gates still pass. No violations.

## Project Structure

### Documentation

```text
specs/005-ai-admin-portal/
├── spec.md
├── plan.md → this is in specs/002-ai-anomaly-detection/plan.md (same branch)
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── prompt-eval-api.md
└── tasks.md (generated separately)
```

### Source Code

```text
src/prompt-eval-service/
├── Controllers/
│   ├── EvaluationsController.cs    # Eval run endpoints
│   └── PromptsController.cs       # Prompt template CRUD
├── Models/
│   ├── PromptTemplate.cs
│   ├── EvaluationRun.cs
│   └── Dtos.cs                    # Request/response DTOs
├── Services/
│   ├── IPromptTemplateService.cs
│   ├── PromptTemplateService.cs   # Cosmos DB operations
│   ├── IEvaluationService.cs
│   └── EvaluationService.cs       # Azure AI Foundry eval execution
├── Program.cs
├── Dockerfile
├── prompt-eval-service.csproj
├── appsettings.json
└── appsettings.Development.json

src/ui-app/src/pages/
└── AdminPage.tsx                   # New "AI Evaluation" tab added

deploy/kustomize/base/
└── prompt-eval-service.yaml        # K8s Deployment + Service

cluster-config/istio/gateway/
└── default-ingress.yaml            # Add /api/evaluations route
```

**Structure Decision**: Follows existing .NET service pattern (same as account-service, user-service). New microservice with controllers, models, services. Shared Contracts project reference for JWT validation consistency.
