# Implementation Plan: Backlog Implementation

**Branch**: `001-backlog-implementation-plan` | **Date**: 2026-05-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-backlog-implementation-plan/spec.md`

## Summary

Implement the full prioritized backlog (22 items, P0–P5) to evolve online-banking-demo from a working prototype into a production-grade, secure, observable AKS showcase with workshop-style documentation. Execution follows a layer-cake approach: each priority level builds on the previous, with Squad agents executing in parallel where possible.

## Technical Context

**Languages**: C# (.NET 8), Go 1.22+, Python 3.11 (FastAPI), TypeScript (React 18)
**Primary Dependencies**: ASP.NET Core, Gin/stdlib, FastAPI, React + MUI v9, OTEL SDK
**Storage**: Azure Cosmos DB (Serverless), Azure Managed Redis (Balanced B0, port 10000/TLS)
**Testing**: dotnet test, pytest, Jest (CRA), Playwright (E2E)
**Target Platform**: AKS (Linux nodes), Azure cloud services
**Project Type**: Microservices web application (9 services + gateway + UI)
**Performance Goals**: <500ms p95 for API calls, <3s page load, 100+ concurrent users
**Constraints**: All traffic via private networking, zero public endpoints except Istio ingress
**Scale/Scope**: 9 microservices, 3 languages, single AKS cluster, ~50 Terraform resources

## Constitution Check

*GATE: All items PASS — implementation proceeds.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Security by Design | ✅ PASS | Layers 1/1b implement mTLS, network policies, KV CSI, Trivy scanning |
| II. Private Networking | ✅ PASS | Layer 2 adds private endpoints; Layer 1 adds default-deny NetworkPolicy |
| III. Entra ID Auth | ✅ PASS | Redis Entra already implemented; KV CSI uses workload identity |
| IV. Coding Best Practices | ✅ PASS | Each service follows language conventions; structured logging enforced |
| V. Convention over Config | ✅ PASS | Single `resource_name` local, Kustomize overlays, Taskfile composition |
| VI. Observability First | ✅ PASS | OTEL Collector deployed; all services emit traces/metrics/logs |

## Project Structure

### Documentation (this feature)

```text
specs/001-backlog-implementation-plan/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: technology research
├── data-model.md        # Phase 1: entity models for User Roles
├── quickstart.md        # Phase 1: developer quickstart
└── contracts/           # Phase 1: API contracts for new endpoints
```

### Source Code (repository root)

```text
src/
├── account-service/          # .NET — account CRUD
├── account-service.Tests/    # .NET unit tests
├── user-service/             # .NET — auth, user management, ROLES (P1)
├── user-service.Tests/       # .NET unit tests
├── transaction-service/      # .NET — transaction history
├── transfer-service/         # .NET — fund transfers
├── transfer-service.Tests/   # .NET unit tests
├── event-processor/          # Go — Redis Streams consumer
├── chatbot-service/          # Python — AI chatbot
├── budget-service/           # Python — budget analysis
├── anomaly-service/          # Python — anomaly detection
├── ui-app/                   # React + MUI frontend
└── shared/                   # .NET shared contracts

deploy/
├── kustomize/
│   ├── base/                 # Base K8s manifests (all services)
│   └── overlays/azure/       # Cloud-specific patches
├── cluster-config/           # NEW: Istio, cert-manager, network policies
│   ├── istio/
│   ├── cert-manager/
│   └── network-policies/
└── observability/            # OTEL Collector + dashboards

infra/
├── cloud/                    # Terraform (to be modularized in P4)
│   ├── main.tf
│   ├── outputs.tf
│   └── variables.tf
└── local/                    # Local AI setup

tests/
└── e2e/                      # Playwright E2E tests
    ├── playwright.config.ts
    └── tests/

docs/                         # Workshop-style documentation
├── architecture.md
├── prerequisites.md          # NEW
├── infrastructure.md         # NEW
├── build.md                  # NEW
├── deployment-azure.md       # ENHANCED
├── monitoring.md             # NEW
├── testing.md                # NEW
└── toc.md                    # NEW: navigation hub

.assets/                      # NEW: architecture diagrams
.devcontainer/                # NEW: Codespaces setup
```

**Structure Decision**: Microservices multi-language layout following existing conventions. New directories (`deploy/cluster-config/`, `.assets/`, `.devcontainer/`) added per eShopOnAKS patterns.

---

## Implementation Phases

### Phase 0a: Terraform Cleanup & Reorganization

**Goal**: Split the monolithic 511-line `main.tf` into logical files, fix naming inconsistencies, and remove dead code — WITHOUT changing any resource behavior or triggering state changes.
**Owner**: Basher (Backend)
**Dependencies**: None — unblocks everything.

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 0a-1 | Split main.tf into logical files | `providers.tf`, `locals.tf`, `networking.tf`, `aks.tf`, `cosmos.tf`, `redis.tf`, `ai.tf`, `keyvault.tf`, `monitoring.tf`, `acr.tf`, `identity.tf` | Basher |
| 0a-2 | Consolidate to ONE managed identity | Replace `redis_managed_identity` + `openai_managed_identity` with single `banking_services_identity`. Grant it: Redis Data Contributor, Cosmos DB Data Contributor, Cognitive Services OpenAI User, Key Vault Secrets User. Single federated credential + single K8s service account (`banking-workload-identity`) | Basher |
| 0a-3 | Fix naming inconsistencies | Standardize `this` vs `main` resource naming; use `main` consistently | Basher |
| 0a-4 | Remove dead/unused outputs | Clean `outputs.tf` — remove references to non-existent attributes (e.g. `primary_access_key`) | Basher |
| 0a-5 | Organize variables with validation | Group variables in `variables.tf`, add descriptions and validation blocks | Basher |
| 0a-6 | Update Kustomize service accounts | Replace `redis-workload-identity` and `ai-workload-identity` SAs with single `banking-workload-identity` SA annotated with the consolidated identity client ID | Basher |
| 0a-7 | Run `terraform plan` — confirm expected changes only | Identity consolidation WILL change resources (destroy 2 identities, create 1). Verify only identity-related changes, no unintended drift | Basher |
| 0a-8 | Run `terraform validate` — confirm clean | No warnings or errors | Basher |

**Key Constraint**: This is a PURE reorganization. `terraform plan` MUST show zero infrastructure changes after the split. No resource renames that would trigger destroy/recreate.

**File Layout After**:
```
infra/cloud/
├── providers.tf        # terraform block, provider configs
├── locals.tf           # locals block, random resources
├── variables.tf        # all input variables (grouped)
├── outputs.tf          # all outputs (cleaned)
├── networking.tf       # VNet, subnet
├── aks.tf              # AKS cluster, role assignments
├── acr.tf              # Container registry + ACR pull role
├── cosmos.tf           # Cosmos DB account, database, containers
├── redis.tf            # Managed Redis, identity, RBAC (azapi)
├── ai.tf               # AI Foundry, OpenAI models, identities
├── keyvault.tf         # Key Vault resource
└── monitoring.tf       # Log Analytics, App Insights
```

**Verification**:
- `terraform validate` passes
- `terraform plan` shows 0 additions, 0 changes, 0 destructions
- All existing `task apply` workflow continues to work

---

### Phase 0 (P0): Operational Readiness

**Goal**: Get the current codebase running correctly on AKS.
**Owner**: Basher (Backend) + Danny (Coordination)
**Dependencies**: Phase 0a complete.

| # | Task | Service/File | Squad Member |
|---|------|-------------|--------------|
| 1 | Rebuild event-processor container | `src/event-processor/` | Basher |
| 2 | Rebuild user-service container | `src/user-service/` | Basher |
| 3 | Run `terraform apply` (validates Redis azapi RBAC) | `infra/cloud/` | Basher |
| 4 | Redeploy all services to AKS | `Taskfile.cloud.yml` | Basher |
| 5 | Verify all pods Running + healthy | kubectl checks | Basher |
| 6 | Fix OTEL Collector liveness probe (terminated signal) | `deploy/observability/` | Basher |

**Verification**: All 9 services + OTEL Collector show `Running` with correct container count.

---

### Phase 1 (P1): Security Hardening + User Roles

**Goal**: Harden the cluster and add RBAC.
**Dependencies**: Phase 0 complete.
**Parallel tracks**: Layer 1 (Istio/NetworkPolicies) ∥ Layer 1b (KV CSI) ∥ User Roles

#### Track A: Kubernetes Hardening (Layer 1)

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 7 | Enable Istio service mesh addon | `infra/cloud/main.tf` — add `service_mesh_profile` block | Basher |
| 8 | Create `deploy/cluster-config/` structure | Istio config, gateway, cert-manager, network policies | Basher |
| 9 | Update namespace with Istio sidecar injection label | `deploy/kustomize/base/namespace.yaml` | Basher |
| 10 | Create Istio Gateway + VirtualService | Replace nginx ingress | Basher |
| 11 | Create default-deny + allow network policies | `deploy/cluster-config/network-policies/` | Basher |
| 12 | Add `deploy:cluster-config` Taskfile task | `Taskfile.cloud.yml` | Basher |
| 13 | Verify mTLS between pods (2/2 containers) | kubectl + istioctl | Basher |

#### Track B: KeyVault CSI Driver (Layer 1b)

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 14 | Add KV secrets in Terraform | 6 `azurerm_key_vault_secret` resources | Basher |
| 15 | Add RBAC: AKS identity → KV Secrets User | `azurerm_role_assignment` | Basher |
| 16 | Create SecretProviderClass manifest | `deploy/kustomize/base/secretproviderclass.yaml` | Basher |
| 17 | Update pod specs with CSI volume mounts | All 9 service deployments | Basher |
| 18 | Update .NET services to read `/mnt/secrets/` | user, account, transaction, transfer services | Basher |
| 19 | Update Python services to read `/mnt/secrets/` | chatbot, budget, anomaly services | Basher |
| 20 | Update Go service to read `/mnt/secrets/` | event-processor | Basher |
| 21 | Remove `kubectl create secret` from Taskfile | `Taskfile.cloud.yml` | Basher |

#### Track C: User Roles & RBAC

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 22 | Design role model (Admin, User) | `specs/001-backlog-implementation-plan/data-model.md` | Danny |
| 23 | Add `Role` entity to Cosmos DB schema | user-service data model | Basher |
| 24 | Implement role-based middleware (.NET) | `src/user-service/Middleware/` | Basher |
| 25 | Add `[Authorize(Roles="Admin")]` to admin endpoints | user-service, account-service | Basher |
| 26 | Add role claims to JWT token generation | `src/user-service/Services/AuthService.cs` | Basher |
| 27 | Frontend role-based route guards | `src/ui-app/src/` — ProtectedRoute component | Linus |
| 28 | Admin UI sidebar (conditional navigation) | `src/ui-app/src/components/AppShell.tsx` | Linus |

#### Track D: Redis Entra Verification

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 29 | Verify Redis Entra auth works end-to-end on AKS | Test event-processor + .NET services | Basher |
| 30 | Verify dual-auth fallback for docker-compose | Local dev without AZURE_CLIENT_ID | Basher |

**Verification**:
- All pods show 2/2 (Istio sidecar injected)
- `kubectl get secretproviderclass` shows `banking-demo-secrets`
- No K8s Secrets contain credentials
- Admin user can access admin endpoints; regular user gets 403
- Network policies block cross-namespace traffic

---

### Phase 2 (P2): Observability & Testing

**Goal**: Complete observability docs, E2E testing, and container scanning.
**Dependencies**: Phase 1 (services stable with security hardening).

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 31 | Write OTEL/monitoring documentation | `docs/monitoring.md` — workshop-style | Danny/Scribe |
| 32 | Implement Playwright E2E test suite | `tests/e2e/tests/` — login, transfer, dashboard flows | Livingston |
| 33 | Add Playwright to GitHub Actions CI | `.github/workflows/ci.yml` — E2E job | Livingston |
| 34 | Add Trivy container scanning to CI | `.github/workflows/ci.yml` — scan job | Basher |
| 35 | Create Trivy config (severity thresholds) | `.trivyignore`, `trivy.yaml` | Basher |
| 36 | Document testing strategy | `docs/testing.md` — workshop-style | Danny/Scribe |

**Verification**:
- E2E tests pass in CI (login → navigate → transfer → verify)
- Trivy scan blocks deployment on CRITICAL/HIGH CVEs
- `docs/monitoring.md` follows eShopOnAKS workshop pattern

---

### Phase 3 (P3): AI Admin Portal

**Goal**: Admin prompt testing UI with Foundry Evals integration.
**Dependencies**: Phase 1 Track C (User Roles — Admin role must exist).

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 37 | Design prompt evaluation API contract | `specs/001-backlog-implementation-plan/contracts/` | Danny |
| 38 | Create prompt-eval-service (Python) | New service: FastAPI + Azure AI Evaluation SDK | Basher |
| 39 | Integrate Foundry Evals SDK | `azure-ai-evaluation` package — run evaluations | Basher |
| 40 | Integrate Foundry Red Teaming SDK | Adversarial testing of prompts | Basher |
| 41 | Admin UI: Prompt Testing page | `src/ui-app/src/pages/AdminPromptTesting.tsx` | Linus |
| 42 | Admin UI: Evaluation results dashboard | `src/ui-app/src/pages/AdminEvalResults.tsx` | Linus |
| 43 | Add prompt-eval-service K8s manifests | `deploy/kustomize/base/prompt-eval-service.yaml` | Basher |
| 44 | Document AI evaluation workflow | `docs/ai-evaluation.md` | Danny/Scribe |

**Verification**:
- Admin can submit prompts to any AI service from the UI
- Evaluation results show quality metrics (groundedness, relevance, coherence)
- Red team results show safety/vulnerability scores
- Regular users get 403 on admin prompt testing endpoints

---

### Phase 3.5 (Spike): Security & Best Practices Audit

**Goal**: Full security and coding best practices analysis of the entire codebase before investing in DX/documentation. Identify vulnerabilities, anti-patterns, and technical debt that must be resolved.
**Owner**: Danny (Lead) + Livingston (Tester) + Basher (Fixes)
**Dependencies**: Phases 0–3 complete (audit the hardened codebase, not the pre-hardened one).

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| S1 | Static Application Security Testing (SAST) | Run CodeQL/Semgrep across all 9 services; document findings | Livingston |
| S2 | Dependency vulnerability scan | `dotnet list package --vulnerable`, `pip audit`, `npm audit`, `govulncheck` | Livingston |
| S3 | Secret scanning audit | Verify no secrets in git history; scan for hardcoded credentials/keys | Livingston |
| S4 | Container image analysis | Trivy scan all built images; document CRITICAL/HIGH findings | Livingston |
| S5 | Kubernetes security posture | `kubescape scan` or `kube-bench`; assess pod security standards, RBAC | Livingston |
| S6 | .NET code quality review | Analyze DI patterns, async/await usage, error handling, input validation across all .NET services | Danny |
| S7 | Python code quality review | Type hints coverage, error handling, async patterns, input validation in chatbot/budget/anomaly | Danny |
| S8 | Go code quality review | Error handling, context propagation, goroutine safety in event-processor | Danny |
| S9 | Frontend security review | XSS vectors, auth token handling, CSP headers, dependency audit in ui-app | Danny |
| S10 | API security review | Auth bypass paths, rate limiting, input validation, CORS config across all endpoints | Danny |
| S11 | Infrastructure security review | Terraform misconfigurations, over-permissive RBAC, missing encryption-at-rest | Danny |
| S12 | Produce audit report with prioritized fixes | `docs/security-audit.md` — findings, severity, remediation plan | Danny |
| S13 | Implement critical/high fixes | Address all CRITICAL and HIGH findings from the audit | Basher |

**Output**: `docs/security-audit.md` with:
- Executive summary (pass/fail per category)
- Findings table (severity, location, description, remediation)
- Prioritized fix list (CRITICAL → HIGH → MEDIUM)
- Best practices gap analysis (per language/framework)

**Verification**:
- Zero CRITICAL findings remain after S13
- All HIGH findings either fixed or documented with accepted-risk justification
- Each service passes its language-specific linter with zero errors
- No secrets in git history (verified by `gitleaks` or equivalent)
- Kubernetes security posture score ≥80% (kubescape)

---

### Phase 4 (P4): Developer Experience & Infrastructure

**Goal**: Modernize DX and infrastructure maintainability.
**Dependencies**: Phase 3.5 (ensure code is clean before documenting it).

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 45 | Create `.devcontainer/` configuration | Codespaces-ready with all tools pre-installed | Linus |
| 46 | Modularize Terraform into modules | `infra/cloud/modules/` — aks, redis, cosmos, kv, ai | Basher |
| 47 | Create workshop-style docs (7 pages) | prerequisites, infrastructure, build, deploy, certificates, monitoring, testing | Danny/Scribe |
| 48 | Create architecture diagrams | `.assets/` — service mesh, data flow, deployment pipeline | Danny |
| 49 | Create `docs/toc.md` navigation hub | Table of contents linking all docs | Danny/Scribe |
| 50 | Enhanced Taskfile commands | `status`, `restart`, `logs`, `dns` tasks | Basher |
| 51 | Azure Chaos Studio experiments | `experiments/` — pod failure, network latency, AZ failure | Livingston |
| 52 | AKS hardening (image cleaner, Defender) | Terraform additions | Basher |

**Verification**:
- Codespaces launches and passes health checks within 5 minutes
- `terraform plan` with modules produces same output as monolith
- All docs follow workshop pattern with navigation links
- Chaos experiments defined and documented

---

### Phase 5 (P5): Agentic Showcase

**Goal**: Document the agentic development approach.
**Dependencies**: Phases 0–4 (showcase requires working features to document).

| # | Task | Detail | Squad Member |
|---|------|--------|--------------|
| 53 | Squad documentation | `docs/squad.md` — how agents collaborate | Danny/Scribe |
| 54 | Copilot integration guide | `docs/copilot-integration.md` — setup, workflows | Danny/Scribe |
| 55 | Architecture Decision Records | `docs/adr/` — key decisions with context | Danny |
| 56 | Developer onboarding guide | `docs/onboarding.md` — clone to running in 15 min | Danny/Scribe |
| 57 | Enhanced Taskfile documentation | README section on available tasks | Scribe |

**Verification**:
- New contributor can follow onboarding guide and have app running in 15 minutes
- ADRs exist for: service mesh choice, secret management, AI evaluation, auth strategy

---

## Execution Strategy

### Parallel Opportunities

```
Phase 0: Sequential (must unblock everything)
Phase 1: Track A ∥ Track B ∥ Track C ∥ Track D (4 parallel tracks)
Phase 2: Tasks 31-36 all parallelizable (different files/services)
Phase 3: API design → Backend ∥ Frontend (after API contract)
Phase 4: Terraform modules ∥ Docs ∥ DevContainer ∥ Chaos (all independent)
Phase 5: All tasks parallelizable (pure documentation)
```

### Squad Assignment Summary

| Member | Primary Responsibility | Phases |
|--------|----------------------|--------|
| **Danny** | Architecture, documentation, coordination | All |
| **Basher** | Backend services, Terraform, K8s config | 0, 1, 2, 3, 4 |
| **Linus** | Frontend UI, DevContainer, Playwright specs | 1C, 3, 4 |
| **Livingston** | E2E test implementation, chaos engineering | 2, 4 |
| **Scribe** | Documentation writing (workshop-style) | 2, 4, 5 |

### Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Istio sidecar breaks existing services | Deploy to staging namespace first; verify health checks |
| KV CSI mount delays cause pod startup failures | Implement graceful fallback + init container timeout |
| Terraform module refactor breaks state | Use `terraform state mv` with plan comparison |
| Foundry SDK breaking changes | Pin SDK version; abstract behind service interface |
| E2E tests flaky in CI | Use Playwright retry + trace-on-failure |

---

## Complexity Tracking

> No constitution violations identified. All work aligns with the 6 principles.

| Decision | Rationale | Alternative Rejected |
|----------|-----------|---------------------|
| New prompt-eval-service (10th service) | Foundry SDK is Python-only; chatbot-service has different responsibility | Merging into chatbot-service would violate single-responsibility |
| Hybrid KV CSI + K8s Secret sync | Gradual migration reduces blast radius | Big-bang file-mount-only would require all 9 services updated simultaneously |
| Istio AKS addon (not standalone) | Managed lifecycle, automatic upgrades, Brian's eShopOnAKS pattern | Standalone Istio requires more ops overhead |
