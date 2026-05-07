# Tasks: Backlog Implementation Plan

**Input**: Design documents from `/specs/001-backlog-implementation-plan/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Included for US4 (Observability & Testing) per spec requirement. Other stories include validation checkpoints but not dedicated test tasks.

**Organization**: Tasks grouped by user story (US1–US8) with priorities from spec.md.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify environment is provisioned and code is ready to deploy

- [ ] T001 Verify Terraform state is clean — run `terraform plan` in infra/cloud/ and confirm no stale references from deleted RG
- [ ] T002 Run `terraform apply` in infra/cloud/ to provision all Azure resources (AKS, Cosmos, Redis, ACR, Key Vault, AI Foundry, networking)
- [ ] T003 Extract Terraform outputs and update deploy/kustomize/overlays/azure/ configmap with new Cosmos endpoint, Redis connection, OTEL endpoint

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: All containers built, deployed, and passing health checks — baseline working system

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 Build and push all .NET service containers to ACR using `az acr build` with repo root context in src/user-service/, src/account-service/, src/transaction-service/, src/transfer-service/
- [ ] T005 [P] Build and push Python service containers to ACR — src/chatbot-service/, src/anomaly-service/, src/budget-service/
- [ ] T006 [P] Build and push Go event-processor container to ACR — src/event-processor/
- [ ] T007 [P] Build and push UI app container to ACR — src/ui-app/
- [ ] T008 Create K8s secrets in banking-demo namespace — jwt-key, redis-connection-string, appinsights-connection-string (interim; replaced by KeyVault CSI in US2)
- [ ] T009 Deploy cluster-config: Istio gateway and VirtualService from cluster-config/istio/gateway/
- [ ] T010 Deploy all services via `kubectl apply -k deploy/kustomize/overlays/azure/`
- [ ] T011 Verify all 9 pods running 2/2 (Istio sidecar injected) and health endpoints responding in banking-demo namespace
- [ ] T012 Smoke test: register user → login → create account → list transactions → verify full auth flow works end-to-end

**Checkpoint**: Baseline system operational — all services deployed and auth flow working

---

## Phase 3: User Story 1 — Operational Readiness (Priority: P0) 🎯 MVP

**Goal**: Fix all known service bugs so every feature works correctly on AKS

**Independent Test**: All API endpoints return expected responses; no 500s or 503s on any service

### Implementation for User Story 1

- [ ] T013 [US1] Fix chatbot-service AI Foundry auth — verify Azure AI Developer role from infra/cloud/identity.tf is applied, restart chatbot pod, confirm /api/chat returns 200
- [ ] T014 [US1] Fix transfer-service partition key — ensure Cosmos container partition key matches code in src/transfer-service/Services/TransferService.cs (stored memory: partition key mismatch bug)
- [ ] T015 [US1] Fix chatbot→budget route mismatch — verify src/chatbot-service/app/main.py calls correct budget-service endpoint path per deploy/kustomize/base/configmap.yaml
- [ ] T016 [US1] Fix anomaly-service missing await — add await to async call in src/anomaly-service/app/main.py (stored memory: missing await bug)
- [ ] T017 [US1] Fix OTEL Collector restart loop — update deploy/kustomize/observability/otel-collector.yaml with increased initialDelaySeconds on liveness probe and memory limits per research R7
- [ ] T018 [US1] Run full endpoint smoke test: /api/users, /api/accounts, /api/transactions, /api/transfers, /api/chat, /api/anomalies, /api/budget — all must return 200

**Checkpoint**: All 9 services fully operational — zero 500/503 errors on any endpoint

---

## Phase 4: User Story 2 — Security Hardening (Priority: P1)

**Goal**: Harden Kubernetes with Istio mTLS, Cilium network policies, KeyVault CSI driver — zero secrets in K8s Secrets

**Independent Test**: `istioctl proxy-status` shows mTLS STRICT; `kubectl get secrets` shows no plain secrets; KeyVault CSI volumes mounted

### Implementation for User Story 2

- [ ] T019 [US2] Create Istio PeerAuthentication (STRICT mTLS) for banking-demo namespace in cluster-config/istio/peer-authentication.yaml
- [ ] T020 [P] [US2] Create Cilium network policies — deny-all default + allow rules per service in cluster-config/network-policies/
- [ ] T021 [US2] Create Azure Key Vault secrets via Terraform or CLI — jwt-signing-key, redis-connection-string, appinsights-connection-string in infra/cloud/keyvault.tf
- [ ] T022 [US2] Create SecretProviderClass manifest for KeyVault CSI in deploy/kustomize/base/secret-provider-class.yaml — map KV secrets to K8s volumes
- [ ] T023 [US2] Update all service manifests in deploy/kustomize/base/*.yaml to mount KeyVault CSI volumes instead of K8s Secret envFrom
- [ ] T024 [US2] Remove plain K8s Secret creation from deployment pipeline — secrets now come exclusively from KeyVault CSI
- [ ] T025 [US2] Verify Redis Entra auth works — confirm all services connect to Redis on port 10000/TLS using workload identity token (not connection string password)
- [ ] T026 [US2] Deploy and verify: `istioctl proxy-status` shows STRICT mTLS, network policies applied, no plain K8s Secrets remain

**Checkpoint**: Security hardening complete — mTLS, network policies, KeyVault CSI all verified

---

## Phase 5: User Story 3 — User Roles & RBAC (Priority: P1)

**Goal**: Add Admin/User roles to the application with JWT claim-based enforcement

**Independent Test**: Register user (gets User role) → Admin promotes user → JWT contains role claim → Admin-only endpoints reject User role

### Implementation for User Story 3

- [ ] T027 [US3] Add `Role` field (default "User") to User model in src/user-service/Models/User.cs per data-model.md
- [ ] T028 [US3] Update user registration in src/user-service/Services/UserService.cs to set default role="User" on new users
- [ ] T029 [US3] Update JWT token generation in src/user-service/Services/AuthService.cs to include `role` claim from User document
- [ ] T030 [US3] Add PATCH /api/users/:id/role endpoint (Admin-only) in src/user-service/Controllers/UsersController.cs per contracts/prompt-eval-api.md
- [ ] T031 [US3] Add GET /api/users/me endpoint returning current user with role in src/user-service/Controllers/UsersController.cs
- [ ] T032 [P] [US3] Add `[Authorize(Roles="Admin")]` to admin-only endpoints across all .NET services — transaction-service admin endpoints, user management
- [ ] T033 [P] [US3] Update UI app — add role display in profile, conditional admin menu in src/ui-app/src/components/AppShell.tsx and src/ui-app/src/pages/Dashboard.tsx
- [ ] T034 [US3] Rebuild and deploy user-service, verify role flow end-to-end: register → login (JWT has role) → promote → re-login (JWT has Admin role)

**Checkpoint**: Role-based access control working — Admin and User personas enforced

---

## Phase 6: User Story 4 — Observability & Testing (Priority: P2)

**Goal**: Document OTEL setup, add Playwright E2E tests to CI, add Trivy scanning

**Independent Test**: `npx playwright test` passes all specs; Trivy scan runs in CI; OTEL docs accurate

### Tests for User Story 4

- [ ] T035 [P] [US4] Review and fix existing Playwright E2E tests in tests/e2e/specs/auth/ — ensure login.spec.ts and registration.spec.ts pass against live environment
- [ ] T036 [P] [US4] Review and fix Playwright tests in tests/e2e/specs/core/ — dashboard.spec.ts, transfers-happy-path.spec.ts against live environment
- [ ] T037 [P] [US4] Review and fix Playwright tests in tests/e2e/specs/advanced/ — chatbot-interaction.spec.ts and others against live environment

### Implementation for User Story 4

- [ ] T038 [US4] Update docs/testing.md with OTEL observability documentation — trace propagation, App Insights queries, alert configuration per constitution VI
- [ ] T039 [P] [US4] Add Trivy container scanning step to .github/workflows/ci.yml — scan each service image after build
- [ ] T040 [P] [US4] Add Playwright E2E test step to .github/workflows/ci.yml — run after deployment with proper BASE_URL configuration
- [ ] T041 [US4] Add `dotnet test` and `pytest` steps to .github/workflows/ci.yml test job — currently only builds, doesn't run tests (stored memory: CI test job bug)
- [ ] T042 [US4] Verify CI pipeline runs end-to-end: build → scan → test → deploy → E2E

**Checkpoint**: CI pipeline complete with scanning, unit tests, and E2E tests

---

## Phase 7: User Story 5 — AI Admin Portal (Priority: P3)

**Goal**: Admin-only prompt evaluation UI using Azure AI Foundry Evaluation SDK

**Independent Test**: Admin logs in → navigates to eval page → submits prompt → sees quality scores and red team results

### Implementation for User Story 5

- [ ] T043 [US5] Create prompt-eval-service Python project scaffold in src/prompt-eval-service/ — FastAPI, Dockerfile, requirements.txt with azure-ai-evaluation SDK
- [ ] T044 [US5] Implement POST /api/evaluations endpoint in src/prompt-eval-service/app/main.py — submit prompt to target service, run evaluation per contracts/prompt-eval-api.md
- [ ] T045 [P] [US5] Implement GET /api/evaluations/:id and GET /api/evaluations (list) endpoints in src/prompt-eval-service/app/main.py
- [ ] T046 [P] [US5] Implement PromptTemplate CRUD endpoints (POST/GET/PUT/DELETE /api/templates) in src/prompt-eval-service/app/main.py
- [ ] T047 [US5] Implement batch evaluation endpoint POST /api/evaluations/batch in src/prompt-eval-service/app/main.py per contracts/prompt-eval-api.md
- [ ] T048 [US5] Add red teaming evaluation (jailbreak, hate speech, self-harm, violence) using azure-ai-evaluation SDK in src/prompt-eval-service/app/evaluator.py
- [ ] T049 [US5] Create Kustomize manifest deploy/kustomize/base/prompt-eval-service.yaml with workload identity, Admin-role JWT validation
- [ ] T050 [US5] Add Istio VirtualService route for /api/evaluations and /api/templates in cluster-config/istio/gateway/default-ingress.yaml
- [ ] T051 [P] [US5] Create Admin Eval UI page in src/ui-app/src/pages/AdminEval.tsx — prompt input, template management, results display with quality scores
- [ ] T052 [P] [US5] Add admin route guard and navigation in src/ui-app/src/App.tsx — only show Admin Eval for role=Admin
- [ ] T053 [US5] Build, deploy, and verify: Admin submits prompt eval → quality scores displayed → red team results shown

**Checkpoint**: AI Admin Portal functional — prompt evaluation and red teaming working

---

## Phase 8: User Story 6 — Developer Experience (Priority: P4)

**Goal**: DevContainer, workshop-style docs, architecture diagrams — clone to running in 15 minutes

**Independent Test**: New developer clones repo → opens in DevContainer → `docker-compose up` works → follows workshop docs to deploy to AKS

### Implementation for User Story 6

- [ ] T054 [P] [US6] Create .devcontainer/devcontainer.json with .NET 8, Go, Python 3.11, Node 18, Terraform, kubectl, Task — all prerequisites from quickstart.md
- [ ] T055 [P] [US6] Create .devcontainer/Dockerfile with all SDK installations and VS Code extensions
- [ ] T056 [US6] Rewrite docs/deployment-local.md in eShopOnAKS workshop format — concept → numbered steps → commands → expected output → challenges per research R8
- [ ] T057 [P] [US6] Rewrite docs/deployment-azure.md in eShopOnAKS workshop format — concept → steps → commands → output → challenges
- [ ] T058 [P] [US6] Rewrite docs/architecture.md with updated service diagram showing all 9 services, Istio mesh, Cosmos, Redis, AI Foundry connections
- [ ] T059 [US6] Create docs/README.md as Table of Contents hub — link to all workshop pages with learning path order
- [ ] T060 [US6] Validate quickstart.md instructions work in DevContainer — `docker-compose up` and all health checks pass

**Checkpoint**: Developer onboarding complete — clone → DevContainer → running in 15 minutes

---

## Phase 9: User Story 7 — Infrastructure Modernization (Priority: P4)

**Goal**: Modularize Terraform, enhance Taskfile, add chaos engineering

**Independent Test**: `terraform plan` works with modules; `task deploy` is idempotent; chaos experiment runs without breaking health checks

### Implementation for User Story 7

- [ ] T061 [US7] Create Terraform module infra/cloud/modules/aks/ — extract AKS resources from infra/cloud/aks.tf per research R6
- [ ] T062 [P] [US7] Create Terraform module infra/cloud/modules/redis/ — extract Redis resources from infra/cloud/redis.tf
- [ ] T063 [P] [US7] Create Terraform module infra/cloud/modules/cosmos/ — extract Cosmos resources from infra/cloud/cosmos.tf
- [ ] T064 [P] [US7] Create Terraform module infra/cloud/modules/keyvault/ — extract Key Vault resources from infra/cloud/keyvault.tf
- [ ] T065 [P] [US7] Create Terraform module infra/cloud/modules/ai-foundry/ — extract AI resources from infra/cloud/ai.tf
- [ ] T066 [US7] Refactor infra/cloud/main.tf to use module blocks with outputs wiring between modules
- [ ] T067 [US7] Verify `terraform plan` and `terraform apply` work correctly with modularized structure — no resource changes
- [ ] T068 [P] [US7] Enhance Taskfile.cloud.yml — add `deploy:cluster-config`, `deploy:observability`, `test:smoke`, `test:e2e` tasks for composable deployment
- [ ] T069 [P] [US7] Add chaos engineering experiment — pod failure test using `kubectl delete pod` with readiness verification in scripts/chaos/
- [ ] T070 [US7] Validate `task deploy` is idempotent — run twice, confirm no errors and same end state

**Checkpoint**: Infrastructure modernized — Terraform modularized, Taskfile composable, chaos tested

---

## Phase 10: User Story 8 — Agentic Showcase (Priority: P5)

**Goal**: Document agentic development practices — Squad usage, Copilot integration, ADRs

**Independent Test**: Docs are accurate, ADRs cover key decisions, showcase tells the story of how AI assisted the build

### Implementation for User Story 8

- [ ] T071 [P] [US8] Create docs/adr/ directory with ADR template and first ADRs: 001-istio-over-linkerd.md, 002-keyvault-csi-over-external-secrets.md, 003-jwt-claim-roles.md per research decisions
- [ ] T072 [P] [US8] Create docs/squad-guide.md documenting Squad agent configuration, agent types, and how they were used during development
- [ ] T073 [P] [US8] Create docs/copilot-integration.md documenting GitHub Copilot CLI usage, .github/copilot-instructions.md customization, speckit workflow
- [ ] T074 [US8] Update README.md with project overview, architecture summary, links to all docs, and agentic development callout

**Checkpoint**: Agentic showcase complete — project tells the story of AI-assisted development

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Final quality pass across all stories

- [ ] T075 [P] Update deploy/kustomize/base/configmap.yaml with any new service URLs (prompt-eval-service)
- [ ] T076 [P] Ensure all services have consistent health endpoints (/healthz, /readyz) per constitution VI
- [ ] T077 Run full E2E Playwright test suite against deployed environment — all specs must pass
- [ ] T078 Run Trivy scan on all container images — zero critical/high vulnerabilities
- [ ] T079 Validate quickstart.md end-to-end — both local and cloud deployment paths work
- [ ] T080 Final commit, PR creation, and CI pipeline verification

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 Operational Readiness (Phase 3)**: Depends on Foundational — should be first story (fixes bugs)
- **US2 Security Hardening (Phase 4)**: Depends on US1 (need working baseline)
- **US3 User Roles (Phase 5)**: Depends on Foundational only (can parallel with US2)
- **US4 Observability & Testing (Phase 6)**: Depends on US1 (need working services to test)
- **US5 AI Admin Portal (Phase 7)**: Depends on US3 (needs Admin role enforcement)
- **US6 Developer Experience (Phase 8)**: Can start after Foundational (docs independent of features)
- **US7 Infrastructure Modernization (Phase 9)**: Can start after Foundational (Terraform independent)
- **US8 Agentic Showcase (Phase 10)**: Can start anytime (documentation only)
- **Polish (Phase 11)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Setup → Foundational → US1 (P0) → US2 (P1) → US4 (P2)
                         ↓                       ↓
                       US3 (P1) ──────────→ US5 (P3)
                         
                     US6 (P4) ← can start after Foundational
                     US7 (P4) ← can start after Foundational
                     US8 (P5) ← can start anytime
```

### Within Each User Story

- Models/entities before services
- Services before API endpoints
- API endpoints before UI integration
- Core implementation before cross-service integration
- Story complete before moving to dependent stories

### Parallel Opportunities

- **Phase 2**: T005, T006, T007 can run in parallel (different service builds)
- **Phase 4 (US2)**: T020 (network policies) parallel with T019 (mTLS) — different files
- **Phase 5 (US3)**: T032, T033 parallel — different services and files
- **Phase 6 (US4)**: T035, T036, T037 parallel — different test spec files; T039, T040 parallel
- **Phase 7 (US5)**: T045, T046 parallel; T051, T052 parallel — different files
- **Phase 8 (US6)**: T054/T055 parallel with T056/T057/T058 — container vs docs
- **Phase 9 (US7)**: T062, T063, T064, T065 all parallel — different Terraform modules
- **Phase 10 (US8)**: T071, T072, T073 all parallel — different doc files
- **US6, US7, US8** can all run in parallel with each other (independent)

---

## Parallel Example: User Story 7 (Infrastructure Modernization)

```bash
# Launch all module extractions together (different directories):
Task: "Create Terraform module infra/cloud/modules/redis/"
Task: "Create Terraform module infra/cloud/modules/cosmos/"
Task: "Create Terraform module infra/cloud/modules/keyvault/"
Task: "Create Terraform module infra/cloud/modules/ai-foundry/"

# Then sequentially:
Task: "Refactor infra/cloud/main.tf to use module blocks"
Task: "Verify terraform plan with modularized structure"
```

---

## Implementation Strategy

### MVP First (US1 Only — Operational Readiness)

1. Complete Phase 1: Setup (Terraform apply)
2. Complete Phase 2: Foundational (build, deploy, verify)
3. Complete Phase 3: US1 — fix all known bugs
4. **STOP and VALIDATE**: All 9 services working, zero errors
5. This is the deployable baseline

### Incremental Delivery

1. Setup + Foundational → Environment ready
2. US1 → Bug-free baseline (MVP!) → Deploy
3. US2 → Security hardened → Deploy
4. US3 → Role-based access → Deploy
5. US4 → Tested and observable → Deploy
6. US5 → AI admin portal → Deploy
7. US6 + US7 + US8 → DX, infra, showcase (can parallel) → Deploy
8. Polish → Final quality pass

### Parallel Team Strategy

With Squad agents:

1. All complete Setup + Foundational together
2. Agent A: US1 (bugs) → US2 (security) → US4 (testing)
3. Agent B: US3 (roles) → US5 (AI portal)
4. Agent C: US6 (docs) + US7 (Terraform) + US8 (showcase)
5. All converge for Polish phase

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable after its checkpoint
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Infrastructure rebuild (Phase 1–2) is the current blocker — user is reprovisioning now
- Stored memories flagged known bugs: partition key mismatch, chatbot→budget route, missing await, CI test job
