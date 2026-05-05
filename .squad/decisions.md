# Squad Decisions

## Audit Session 2026-05-05T16-30

### Critical Infrastructure Decisions

#### Decision: CI/CD Build Context Strategy
**Status:** Pending Action  
**Priority:** P0 — Blocks Deployment  
**Scope:** `.github/workflows/ci.yml` and `src/*/Dockerfile`  

**Context:** .NET Dockerfiles use `COPY src/shared/` patterns requiring repo root context, but CI matrix uses per-service context (`./src/${{ matrix.service }}`). This causes build failures.

**Options:**
1. Change .NET Dockerfiles to use relative paths (complex, error-prone)
2. Change CI matrix to build from repo root with service-specific Dockerfile paths (recommended)
3. Use Docker BuildKit and multi-stage builds to isolate context

**Recommendation:** Option 2 — Align CI context with docker-compose.yml (both use repo root). Service isolation handled by Dockerfile stage targets.

---

#### Decision: Terraform IaC Syntax Errors
**Status:** Pending Action  
**Priority:** P0 — Blocks Infrastructure  
**Scope:** `infra/cloud/main.tf`

**Issues:**
- Duplicate `azurerm_user_assigned_identity.openai_managed_identity` resource (lines ~118 and ~334)
- `azurerm_federated_identity_credential` missing `user_assigned_identity_id` attribute

**Resolution:** Remove duplicate identity, ensure all federations reference correct identity IDs. Verify with `terraform validate`.

---

### Backend Architecture Decisions

#### Decision: Transfer Service Transaction Semantics
**Status:** Pending Implementation  
**Priority:** P0 — Core Logic Missing  
**Scope:** `src/transfer-service/Services/TransferService.cs`

**Current State:** Transfer records created but balances never updated; HTTP failures from transaction-service ignored.

**Options:**
1. Direct balance updates (non-atomic, race condition risk)
2. Saga pattern with compensating transactions (resilient, complex)
3. Two-phase commit via distributed transaction (not viable with Cosmos)

**Recommendation:** Implement Saga pattern with event-driven compensation. Transfer marks "Pending", posts "MoneyTransferred" event; event processor triggers balance updates. Failure causes rollback event.

---

#### Decision: Service Integration Contracts
**Status:** Pending Action  
**Priority:** P0 — Budget-Chatbot Broken  
**Scope:** `src/budget-service/` and `src/chatbot-service/`

**Issue:** Route mismatch — budget service exposes `/insights/{userId}` and `/categorize`, but chatbot hardcodes `/api/budget/insights` and `/api/budget/categorize`.

**Resolution:** Establish service contract documentation (OpenAPI/Swagger). Budget service routes must match chatbot expectations OR update chatbot to use correct routes.

---

### Frontend Architecture Decisions

#### Decision: State Management Restructure
**Status:** Pending Action  
**Priority:** P1 — Architectural  
**Scope:** `src/ui-app/src/context/AuthContext.tsx`

**Current State:** Single AuthContext holds auth state + domain data (accounts, transfers). God object pattern.

**Recommendation:** Split into `AuthContext` (user, token, login/logout) and `AccountsContext` (accounts, transfers, balance). Enables independent testing, reuse, and state isolation.

---

#### Decision: Transfer Persistence
**Status:** Pending Action  
**Priority:** P1 — Data Loss Risk  
**Scope:** `src/ui-app/src/context/AuthContext.tsx:61-72`

**Current State:** `transfer()` function is client-only mock; never calls backend API. Transfers lost on page refresh.

**Resolution:** Implement backend transfer API call with success/error handling. Wire to backend `/api/transfers` POST endpoint. Update local state only after server confirms.

---

### Testing Strategy Decisions

#### Decision: Test Coverage Foundation
**Status:** Pending Implementation  
**Priority:** P1 — Risk Management  
**Scope:** All services

**Current State:** Only broken CRA boilerplate test exists. CI "test" job doesn't run tests.

**Recommendation:**
- **Phase 1:** Create test projects for critical paths (auth, transfers, balance)
- **Phase 2:** Add integration tests using docker-compose
- **Phase 3:** Add security/load tests

| Service | Framework | Target Coverage |
|---------|-----------|-----------------|
| .NET (4 services) | xUnit + Moq | 70% critical paths |
| Python (3 services) | pytest | 60% API + AI logic |
| Go (event-processor) | stdlib testing | 80% event handling |
| React (UI) | Jest + Testing Library | 70% components |

---

## Governance

- **Decision Authority:** Team consensus required for P0 decisions
- **Review Cycle:** Weekly squad sync to track implementation status
- **Update Process:** Orchestration logs capture weekly progress; history.md tracks learnings

## Active Tracking

| Decision | Owner | Target Date | Status |
|----------|-------|-------------|--------|
| CI/CD build context fix | Infrastructure | Week of 2026-05-12 | Pending |
| Terraform syntax fixes | Infrastructure | Week of 2026-05-12 | Pending |
| Transfer logic implementation | Basher | Week of 2026-05-19 | Pending |
| Budget-Chatbot route alignment | Basher | Week of 2026-05-12 | Pending |
| AuthContext refactor | Linus | Week of 2026-05-19 | Pending |
| Test framework setup | Livingston | Week of 2026-05-12 | Pending |
