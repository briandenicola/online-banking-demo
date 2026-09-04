# Turk — History

## Project Context
- **Project:** online-banking-demo
- **User:** Brian
- **Stack:** C#/.NET (user-service, account-service, transaction-service, transfer-service), Python/FastAPI (ai-service, budget-service, chatbot-service), Go (event-processor), React/TypeScript (ui-app), Redis, Docker Compose, Azure AKS
- **Joined:** 2026-05-07
- **Focus:** Python service config fixes and cross-service consistency

## Session Log

### 2026-06-05 — UI App Port Mismatch from Stale Docker Image

**Issue:** `curl http://localhost:3000` → "Connection reset by peer" after MCR base image migration. UI container running but not serving.

**Root Cause:** `task local:run` used `docker compose up -d` without `--build`, reusing 4-week-old cached ui-app image (Alpine nginx:1.29 on port 80) instead of current MCR-based Dockerfile (Azure Linux nginx:1.28 on port 8080). Port mismatch: compose maps 3000→8080, stale container listening on 80.

**Secondary Issues:** React build failed (TS2882: CSS type declarations missing). Azure Linux nginx has different permissions than Alpine (no `/var/cache/nginx`, different log paths).

**Fixes:**
1. Added `src/ui-app/src/custom.d.ts` — CSS module type declarations
2. Updated `src/ui-app/Dockerfile` — removed chown of non-existent directories
3. Updated `src/ui-app/nginx.conf` — `error_log stderr; access_log off;`
4. Updated `tasks/Taskfile.local.yml` — added `--build` to `local:run` task

**Verification:** `curl http://localhost:3000` → HTTP 200, responds with `<title>Online Banking Demo</title>`.

**Durable Fix:** `task local:run` now always rebuilds images with `--build`, preventing stale image issues during active development.

**Key Learning:** Always rebuild after base image migrations. Stale cached images silently break stacks even when Dockerfiles are correct. Add `--build` to dev run commands.

## Core Context

**Core Python/FastAPI Patterns:**
- Env vars: All Python services use SCREAMING_SNAKE_CASE (JWT_KEY, REDIS_CONNECTION_STRING, COSMOS_DB_ENDPOINT). Referenced in kustomize manifests and docker-compose.
- Layered architecture: `app/config.py` (logging/telemetry), `app/models/`, `app/services/`, `app/routes/`, with `main.py` only wiring app/middleware/routers/lifespan.
- Service modules retain shared state (analyzer pipeline, agent sessions, in-memory stores) for behavior preservation.

**Core Cross-Service Patterns:**
- Balance validation: Transaction/transfer services call account-service before debit. Fail-open if unreachable (graceful degradation).
- Events: InsufficientFundsAttempt events published to Redis "banking-events" stream for anomaly/audit consumption.
- Kustomize ConfigMap: `deploy/kustomize/base/configmap.yaml` — central source of truth for env vars, services, replicas, image refs.

**Core Infrastructure Patterns:**
- Redis: Azure Managed (port 10000, TLS). Dual-mode auth: AZURE_CLIENT_ID → Entra token (AKS), else password from conn string (local).
- Secrets: KeyVault + CSI driver syncs to K8s Secret `banking-secrets` via `SecretProviderClass`. Kubelet identity RBAC needed.
- Go slog: event-processor uses stdlib slog with JSON handler for structured logging.

## Learnings
- Azure Managed Redis (Balanced B0) uses port 10000 with TLS, not standard 6379
- Redis auth is dual-mode: AZURE_CLIENT_ID presence triggers Entra ID token auth (cloud/AKS), absence uses connection string password (local docker-compose)
- Go event-processor (src/event-processor/main.go) has the reference implementation for dual-mode Redis connection parsing
- .NET services use REDIS__CONNECTIONSTRING env var with format: host:10000,ssl=True,abortConnect=False
- Python services need to parse this .NET-style connection string into host/port/ssl components
- ConfigMap is at deploy/kustomize/base/configmap.yaml
- Brian's directive: all fixes must maintain docker-compose local development compatibility
- Transaction-service now calls account-service for balance validation before debit transactions
- InsufficientFundsException (src/transaction-service/Services/InsufficientFundsException.cs) is thrown by service layer, caught by controller → 400 Bad Request
- Both Cosmos and InMemory transaction service implementations validate balance via HTTP to account-service
- Transfer-service already had insufficient funds check in TransferService.cs; InMemoryTransferService was updated by Basher with same pattern
- InsufficientFundsAttempt events are published to Redis "banking-events" stream for anomaly/audit consumption
- Services:AccountService config is now set in transaction-service appsettings.json and docker-compose.yml
- Balance validation is fail-open: if account-service is unreachable, transaction proceeds with a warning log (graceful degradation)
- Secrets migrated from kubectl create to Azure KeyVault + CSI Secret Store driver (keyvault-secrets.tf, secret-provider-class.yaml)
- CSI driver uses kubelet managed identity (not workload identity) — requires separate RBAC role assignment on KeyVault
- JWT key now generated once via Terraform random_password, stored in KV — no longer regenerated every deploy
- SecretProviderClass syncs KV secrets into K8s Secret named banking-secrets with same keys — zero change to deployment env var references
- Placeholder pattern for secret-provider-class.yaml: REPLACE_WITH_KEYVAULT_NAME, REPLACE_WITH_TENANT_ID, REPLACE_WITH_AZURE_CLIENT_ID (sed + git checkout, same as configmap.yaml)
- Observability namespace keeps kubectl create for its single appinsights-connection-string secret (simpler than a second SecretProviderClass)
- key_vault_name output added to infra/cloud/outputs.tf for Taskfile consumption
- Content Understanding Service uses the same three AI private DNS zones (cogservices/openai/services.ai) even when deployed cross-region with a local PE
- Taskfile.build.yml builds Python services using service-directory contexts; account-opening-service now follows this pattern.
- Python/FastAPI services now use SCREAMING_SNAKE env vars (`JWT_KEY`, `REDIS_CONNECTION_STRING`, `COSMOS_DB_ENDPOINT`) with docker-compose + kustomize updated in deploy/kustomize/base/*-service.yaml
- Python services follow layered layout: `app/config.py`, `app/routes/`, `app/services/`, `app/models/` with `main.py` as entrypoint (src/{ai,budget,chatbot,account-opening}-service/app/)
- Go event-processor logs via stdlib slog JSON handler (src/event-processor/main.go)
- FastAPI services should store mutable state on `app.state` and expose dependencies via `Depends()` helpers (use async locks for in-memory caches).

### 2026-05-08 — KeyVault CSI Driver Secrets Migration

**Feature:** Migrated all banking-demo namespace secrets from kubectl create to Azure KeyVault + CSI Secret Store driver.

**Key architecture decisions:**
1. **Terraform manages all secrets** — 4 secrets (jwt-key, openai-endpoint, redis-connection-string, appinsights-connection-string) now created as `azurerm_key_vault_secret` resources in `keyvault-secrets.tf`
2. **JWT key is stable** — Generated once via `random_password`, stored in KeyVault. No longer regenerated on every deploy (eliminates session invalidation on redeploy)
3. **CSI driver syncs to K8s Secret** — `SecretProviderClass` maps KV secrets into a K8s Secret named `banking-secrets` with identical keys. Zero change to deployment manifest env var references
4. **Kubelet identity RBAC** — CSI driver uses AKS kubelet managed identity (not workload identity). Separate "Key Vault Secrets User" role assignment required on KeyVault for kubelet service principal
5. **Placeholder pattern** — Uses existing `sed`/`git checkout` pattern for REPLACE_WITH_KEYVAULT_NAME, REPLACE_WITH_TENANT_ID, REPLACE_WITH_AZURE_CLIENT_ID (same as configmap.yaml)
6. **Observability namespace keeps kubectl** — Simple `kubectl create secret` for single appinsights-connection-string (second CSI provider would be overkill)

**Key files created/modified:**
- `infra/cloud/keyvault-secrets.tf` — New Terraform for 4 KeyVault secrets + CSI RBAC
- `deploy/kustomize/base/secret-provider-class.yaml` — SecretProviderClass mapping KV → K8s Secret
- All 8 service deployments — Added CSI volume + volumeMount
- `infra/cloud/outputs.tf` — Added `key_vault_name` output
- `Taskfile.cloud.yml` — Simplified `_secrets:create` task, updated deploy pipeline

**Pattern:** CSI driver uses kubelet identity (not workload identity) — check kubelet service principal in Key Vault RBAC config, not workload identity webhook.
**Pattern:** JWT key is now stable. Applications that cache secrets at startup will persist across redeploys (feature, not bug).

### 2026-05-11 — Redis Private Endpoint DNS Zone Fix

**Issue:** event-processor (Go) and ai-service (Python) both failing to connect to Azure Managed Redis with "Connection reset by peer" on port 10000. Services successfully acquired Entra ID tokens but TCP connection was refused.

**Root cause:** Wrong private DNS zone in Terraform. `private-endpoints.tf` used `privatelink.redisenterprise.cache.azure.net` (for old Azure Cache for Redis Enterprise) instead of `privatelink.redis.azure.net` (for Azure Managed Redis / `azurerm_managed_redis`). The PE's A record could not auto-register in the wrong zone, so pods resolved to the public IP (4.172.66.86) which has public access disabled → connection reset.

**Fix:**
1. Changed DNS zone in `private-endpoints.tf` from `privatelink.redisenterprise.cache.azure.net` to `privatelink.redis.azure.net`
2. Applied incrementally via az CLI: created correct zone, linked VNet, updated PE DNS zone group, cleaned up old zone
3. Restarted event-processor and ai-service deployments — both confirmed Redis connectivity

**Key learning:** Azure has THREE Redis products with different PE DNS zones:
- Azure Cache for Redis (standard/premium): `privatelink.redis.cache.windows.net`
- Azure Cache for Redis Enterprise (old): `privatelink.redisenterprise.cache.azure.net`
- Azure Managed Redis (new, `azurerm_managed_redis`): `privatelink.redis.azure.net`

**Pattern:** Always cross-reference the [Azure PE DNS zone table](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns) when adding new private endpoints. The zone name is product-specific and easy to confuse between similar services.

### 2026-05-11 — Redis Private Endpoint DNS Zone Fix

**Issue:** All services connecting to Azure Managed Redis failing with "Connection reset by peer" on port 10000. DNS resolution from inside AKS pods returning public IP instead of PE's private IP (10.220.4.13).

**Root cause:** Wrong private DNS zone in Terraform. `infra/cloud/private-endpoints.tf` used `privatelink.redisenterprise.cache.azure.net` (for old Azure Cache for Redis Enterprise) instead of `privatelink.redis.azure.net` (for Azure Managed Redis / `azurerm_managed_redis`). The PE's A record could not auto-register in the wrong zone, so pods resolved to the public IP (4.172.66.86) which has public access disabled.

**Fix:**
1. Changed DNS zone in `private-endpoints.tf` from `privatelink.redisenterprise.cache.azure.net` to `privatelink.redis.azure.net`
2. Applied incrementally via az CLI: created correct zone, linked VNet, updated PE DNS zone group, cleaned up old zone
3. Restarted event-processor and ai-service deployments

**Verification:** DNS from pod now resolves to PE private IP 10.220.4.13. TCP to port 10000 succeeds. Services confirm Redis connectivity via logs.

**Cross-team note:** Basher worked on the Istio sidecar port exclusion in parallel. Both fixes required for full Redis connectivity.

**Key files modified:** `infra/cloud/private-endpoints.tf` (DNS zone name, line 20)
**Commit:** 65c7197

**Pattern:** Azure has THREE Redis products with different PE DNS zones:
- Azure Cache for Redis (standard/premium): `privatelink.redis.cache.windows.net`
- Azure Cache for Redis Enterprise (old): `privatelink.redisenterprise.cache.azure.net`
- Azure Managed Redis (new, `azurerm_managed_redis`): `privatelink.redis.azure.net` ← This one

Always cross-reference the [Azure PE DNS zone table](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns).

### 2026-05-11 — AI Foundry Private Endpoint DNS Zone Fix

**Issue:** chatbot-service couldn't resolve `loyal-moose-4702-foundry.services.ai.azure.com` to PE private IP. DNS returned public IP (20.48.193.198) instead of PE IP (10.220.4.14).

**Root cause:** Missing `privatelink.services.ai.azure.com` private DNS zone. Azure AI Foundry uses the `services.ai.azure.com` domain (not `cognitiveservices.azure.com` or `openai.azure.com`), which requires its own dedicated private DNS zone for the CNAME chain to resolve through the PE.

**Fix:**
1. az CLI: Created `privatelink.services.ai.azure.com` zone, linked to VNet, added A record, added to AI PE's DNS zone group
2. Terraform: Added `services_ai` key to `private_dns_zones` map and included it in the AI PE's `private_dns_zone_ids` (now 3 zones: cogservices, openai, services_ai)
3. Verified from chatbot-service pod: DNS now resolves to private IP in PE subnet

**Key learning:** Azure AI Foundry / AI Services PEs need THREE private DNS zones:
- `privatelink.cognitiveservices.azure.com` — for `cognitiveservices.azure.com` domain
- `privatelink.openai.azure.com` — for `openai.azure.com` domain
- `privatelink.services.ai.azure.com` — for `services.ai.azure.com` domain (AI Foundry endpoints)

**Commit:** da6e714

## Cross-Agent Coordination (2026-05-11)

### Related Team Updates
- **Basher (Backend):** Implemented admin promote bootstrap escape hatch + email lookup document pattern for uniqueness — user-service now self-healing for initial admin
- **Linus (Frontend):** Created AdminUserManagementTab.tsx and AdminLoginAuditTab.tsx — new admin tabs ready
- **Livingston (QA):** Created smoke test suite (15 total @smoke tests) — post-deployment gates now enabled

### 2026-05-11 — Account-Opening Agent Consumer TYPE_CHECKING Cleanup

**Issue:** Account-opening worker CrashLoopBackOff due to `TypeError: Can't instantiate abstract class IdentityVerificationConsumer with abstract method process_event`. Root cause was `process_event` being placed inside `if TYPE_CHECKING:` blocks, making it invisible at runtime.

**State when assigned:** A partial fix had already moved `process_event` out of the `if TYPE_CHECKING:` blocks with correct indentation. The remaining issue was unused `TYPE_CHECKING` imports and a stray `if TYPE_CHECKING:` block in provisioning.py.

**Fix:** Removed unused `TYPE_CHECKING` from imports in all three agent consumer files and deleted the stray `if TYPE_CHECKING:` block at end of provisioning.py.

**Key files:** `src/account-opening-service/app/agents/{identity_verification,compliance_check,provisioning}.py`
**Base class:** `src/account-opening-service/app/consumer.py` — defines `@abc.abstractmethod process_event`

**Learning:** Never place runtime-required method implementations inside `if TYPE_CHECKING:` blocks — those blocks are stripped at runtime by design. Use string-quoted type annotations (e.g., `"DefaultAzureCredential | None"`) for forward references instead of `TYPE_CHECKING` imports when the type is only needed in signatures.

### 2026-05-12 — Sample Documents Phases 4-5 (Issue #16)

**Feature:** Implemented proof of address PDF generator and unified CLI script for sample document generation.

**What was built:**
1. **T007-T008 (Phase 4):** `tests/fixtures/sample-documents/generate_proof_of_address.py` — portrait A4 utility bill PDF with header (Springfield Electric Utility), account info, service address (Name/Address labels matching normalization mapping), billing summary, and a table breakdown using fpdf2 `table()` context manager.
2. **T009-T010 (Phase 5):** `tests/fixtures/sample-documents/generate.py` — unified CLI with `argparse`, `--profile` flag (default: `applicants/john-smith.json`), generates both photo_id.pdf and proof_of_address.pdf, prints summary with file sizes.

**Key files:**
- `tests/fixtures/sample-documents/generate_proof_of_address.py` — proof of address generator
- `tests/fixtures/sample-documents/generate.py` — CLI entry point
- `tests/fixtures/sample-documents/john-smith/proof_of_address.pdf` — generated utility bill (1,885 bytes)

**Patterns followed:**
- Same function signature pattern as `generate_photo_id.py`: `(profile, spec, output_path) -> None`
- Same import style: `from models import ...`, `from fpdf import FPDF`
- Same `if __name__ == "__main__"` guard with `out_dir` naming convention
- Field labels `Name` and `Address` match normalization mapping exactly
- All data sourced from profile JSON via `load_profile()`, never hardcoded
- Module-level docstrings and type hints added (covers T011)

**Gotcha:** fpdf2 Helvetica font doesn't support em dash (U+2014) — use regular dash instead in text cells. Got `FPDFUnicodeEncodingException` until replaced `—` with `-`.

### 2026-05-12 — Entra Agent ID Auth-Sidecar Activation (Issue #20)

**Feature:** Activated the Entra Agent ID auth-sidecar in the account-opening-worker kustomize deployment.

**What was done:**
1. Uncommented and fully configured the `entra-agent-id` sidecar container (port 5000, readiness probe on `/health`, resources 32Mi/25m → 128Mi/100m, security context)
2. Added `AGENT_ID_SIDECAR_URL: "http://localhost:5000"` env var to worker container
3. Added `AGENT_ID_AGENT_IDENTITY: "REPLACE_WITH_AZURE_CLIENT_ID"` to shared configmap (sed-substituted at deploy time)
4. Added Istio `excludeInboundPorts: "5000"` annotation on worker pod template
5. Extended `_configmap:update` Taskfile task with AZURE_CLIENT_ID sed substitution

**Key files:**
- `deploy/kustomize/base/account-opening-service.yaml` — sidecar + worker env vars + Istio annotation
- `deploy/kustomize/base/configmap.yaml` — AGENT_ID_AGENT_IDENTITY placeholder
- `tasks/Taskfile.cloud.yml` — _configmap:update sed + var

**Pattern:** Sidecar gets AZURE_CLIENT_ID from workload identity webhook (pod has `azure.workload.identity/use: "true"` label). No manual client ID wiring needed on the sidecar itself.
**Pattern:** Pod-specific URLs (localhost sidecar) go as explicit env vars on the container, not in the shared configmap.

### 2026-05-12 — Deep Security Audit (Issue #18)

**Scope:** All Python/FastAPI services (budget, chatbot, ai-service) + Go event-processor + prompt-eval-service (.NET, not Python as initially assumed).

**Key findings:**
1. **CRITICAL: Zero auth on all 3 Python FastAPI services** — budget-service, chatbot-service, ai-service have no JWT/Bearer middleware. All endpoints including admin routes are publicly accessible.
2. **HIGH: LLM identity confusion** — chatbot-service tool functions accept `user_id` from the LLM, enabling indirect prompt injection for cross-user data access.
3. **HIGH: Redis TLS verification disabled** — both Go (`InsecureSkipVerify: true`) and Python (`ssl_cert_reqs=None`) skip cert validation.
4. **HIGH: Event processor loses messages** — ACKs before successful processing; failed events are permanently lost.
5. **MEDIUM: PII in AI prompts and telemetry** — account IDs, transaction descriptions, and user messages flow into LLM endpoints and OTEL spans.

**Architecture observations:**
- prompt-eval-service is .NET/C#, not Python — it's the only service with proper `[Authorize]` attributes
- Budget service uses in-memory storage (`defaultdict(list)`) — not production-ready
- No shared auth module exists across Python services — each would need its own implementation
- AI service's `/api/admin/prompts` endpoint returns full system prompt text — security anti-pattern

**Proposed decision:** Create shared JWT auth dependency for all Python services before adding features. Filed to `.squad/decisions/inbox/turk-security-audit.md`.

**Full report:** `.squad/decisions/inbox/turk-security-audit.md` — 3 CRITICAL, 9 HIGH, 14 MEDIUM, 7 LOW, 4 INFO findings with remediation roadmap.

### 2026-05-12 — JWT Authentication for Python/FastAPI Services (Issue #26)

**Feature:** Added JWT Bearer authentication to all three Python/FastAPI services (budget-service, chatbot-service, ai-service), closing the CRITICAL zero-auth finding from the security audit.

**What was built:**
1. **Shared auth module** (`src/shared/auth.py`, copied into each service's `app/auth.py`):
   - `verify_jwt` — FastAPI `Depends()` that validates Bearer tokens using PyJWT (HMAC-SHA256)
   - `require_admin` — wraps `verify_jwt` with role == "admin" check (403 if not)
   - `UserContext` dataclass (user_id, username, role) extracted from JWT claims
   - Reads `Jwt__Key`, `Jwt__Issuer`, `Jwt__Audience` env vars — matching .NET `Jwt:Key` config pattern
   - Handles both .NET ClaimTypes.Role URI and short "role" claim names

2. **budget-service:** Auth on `/insights/{userId}` and `/categorize`. userId now derived from JWT, path param ignored (prevents IDOR).

3. **chatbot-service:** Auth on `/api/chat`, `/api/chat/new`, `/api/chat/history/{user_id}` (with user_id ownership check), `/api/chat/admin/foundry-status` (admin-only).

4. **ai-service:** Auth on `/detect`. Admin-only on all `/api/admin/*` endpoints (stats, transactions, flagged-transactions, scored-transactions, rescore, review, prompts, evaluate). Prompts endpoint now returns names/types only — system prompt text stripped (security fix).

5. **Environment config:**
   - docker-compose.yml: Added `Jwt__Key`, `Jwt__Issuer`, `Jwt__Audience` env vars to all 3 Python services (same default as .NET services)
   - Kustomize: Added `Jwt__Key` secretKeyRef to budget-service.yaml, chatbot-service.yaml, ai-service.yaml (from banking-secrets/jwt-key)
   - Dockerfiles: Added `PyJWT` to pip install for all 3 services
   - pyproject.toml: Added `PyJWT = "^2.8.0"` dependency to all 3 services

**Health endpoints (`/healthz`, `/readyz`, `/health`) remain unauthenticated** — required for K8s probes.

**Key patterns:**
- Auth module is placed in each service's `app/auth.py` because Dockerfiles build from per-service contexts
- `src/shared/auth.py` is the canonical source of truth
- Never trust client-supplied user_id — always derive from JWT `sub`/`userId` claims
- Admin endpoints use `require_admin` dependency (stacked on `verify_jwt`)

**Commit files:** `src/shared/auth.py`, `src/{budget,chatbot,ai}-service/app/{auth,main}.py`, `src/{budget,chatbot,ai}-service/{pyproject.toml,Dockerfile}`, `docker-compose.yml`, `deploy/kustomize/base/{budget,chatbot,ai}-service.yaml`

### 2026-05-12 — Security Batch Fixes (Issues #36, #37, #38, #44)

**Scope:** LLM security, Redis TLS, event processor reliability, exception leaking — across Python FastAPI services and Go event-processor.

**Issue #36 — LLM Security (chatbot-service + ai-service):**
1. **chatbot-service:** Removed `user_id` parameter from `get_budget_insights`, `get_spending_pattern`, `get_user_transactions`, and `get_user_accounts` tool functions. LLM can no longer supply arbitrary user IDs via prompt injection. Tools now forward the JWT via Authorization header (using `_current_auth_token` ContextVar) and let downstream services resolve the user from the token.
2. **ai-service /detect:** Replaced raw `await request.json()` with strict `DetectRequest` Pydantic model (typed fields: transactionId, accountId, amount, type, description, category).
3. **ai-service PII:** Masked accountId to last 4 chars (`****XXXX`) before sending to LLM risk assessment prompt. Only amount, type, description, category, and masked account sent to Foundry.
4. **ai-service admin prompts:** Already fixed in issue #26 — endpoint returns names/types only, no system prompt text.

**Issue #37 — Exception Leaking:**
- chatbot-service: Replaced `detail=str(e)` with `detail=f"Internal error. Correlation ID: {correlation_id}"`. Full exception logged server-side with `exc_info=True`.
- budget-service and ai-service had no `detail=str(e)` patterns.

**Issue #38 — Redis TLS:**
- **Go event-processor:** Replaced `InsecureSkipVerify: true` with `ServerName` set to the Redis host extracted from the connection string. Proper certificate verification now enabled.
- **Python ai-service:** Replaced `ssl_cert_reqs=None` with `ssl_cert_reqs="required"` in both Azure cluster and local fallback paths.
- **budget-service and chatbot-service:** Don't use Redis directly — no changes needed.
- **Istio port exclusion:** Verified `traffic.sidecar.istio.io/excludeOutboundPorts: "10000"` is already configured on all relevant services (ai-service, event-processor, transaction-service, user-service, transfer-service, account-opening-service).

**Issue #44 — Event Processor ACK-before-process:**
- **Go event-processor:**
  - `processMessage` now returns `error` instead of silently logging
  - XACK moved to AFTER successful processing; failed messages stay in pending list
  - Dead-letter mechanism: after N failed attempts (`DLQ_MAX_RETRIES` env var, default 3), message moves to `banking-events-dlq` stream, then original is ACKed
  - Added `sync.WaitGroup` for graceful shutdown — drains in-flight messages before exit
  - Startup retry loop now uses `select` on `ctx.Done()` instead of `time.Sleep`
  - Consumer loop backoff also respects context cancellation
- **Python ai-service:** Same ACK-after-process + dead-letter pattern applied to the async Redis stream consumer

**Key patterns:**
- `_current_auth_token` ContextVar is the mechanism for passing JWT from HTTP handler to tool functions in chatbot-service
- Dead-letter stream naming convention: `{original-stream}-dlq`
- `DLQ_MAX_RETRIES` env var controls retry threshold (both Go and Python)
- Redis TLS: In Azure mode, use proper cert verification with system CA bundle. In local docker-compose mode (no AZURE_CLIENT_ID), plain connections allowed.

### 2026-05-12 — Python Dependency Pinning (Issue #42)

**Feature:** Fixed Python dependency management across all 4 Python services.

**Key changes:**
1. **Pinned all dependencies to exact versions** — Replaced `^`, `>=`, and `*` wildcards with `==x.y.z` in all pyproject.toml files
2. **Single source of truth** — Dockerfiles now use `pip install .` from pyproject.toml instead of inline package lists
3. **Fixed ghost dependency** — `opentelemetry-instrumentation-azure` doesn't exist on PyPI; replaced with `azure-core-tracing-opentelemetry` in budget-service and chatbot-service
4. **Reconciled Dockerfile/pyproject.toml mismatches** — Added packages that were in Dockerfiles but missing from pyproject.toml (agent-framework, agent-framework-foundry, redis, aiohttp, azure-cosmos, azure-storage-blob, opentelemetry-instrumentation-requests)
5. **Poetry lockfiles skipped** — Poetry CLI not available in environment; pyproject.toml pinning is the critical fix
6. **.NET side untouched** — Directory.Packages.props already handled by Basher

**Learnings:**
- `opentelemetry-instrumentation-azure` is a non-existent package; the correct name is `azure-core-tracing-opentelemetry`
- Poetry-core as build backend works with plain `pip install .` — pip auto-installs build deps from `[build-system].requires`
- Local environment has Python 3.10 but Docker images use 3.11-slim — can't do full local pip install validation

### 2026-05-12 — Deep Code Quality Audit (All Python/FastAPI Services)

**Scope:** budget-service, chatbot-service, ai-service, account-opening-service

**Key findings (45 total: 5 critical, 26 medium, 14 low):**

1. **All 4 services are monolithic** — routes, business logic, data access, config, and telemetry live in single main.py files (ai-service is 1,400+ lines)
2. **account-opening-service has hardcoded JWT fallback secret** — anyone reading source can mint valid tokens (🔴 P0)
3. **budget-service has broken user-data isolation** — `accountId.startswith(userId[:8])` prefix matching can cross user boundaries (🔴 P0)
4. **All 4 services block the event loop** — sync `DefaultAzureCredential.get_token()`, Cosmos sync SDK, and blob uploads called inside async handlers
5. **All 4 services swallow exceptions broadly** — `except Exception` catch-all blocks mask real failures; ai-service has 12+ such blocks
6. **All 4 services use module-global mutable state** — incompatible with multi-worker deploys, hard to test
7. **Env var naming is inconsistent** — account-opening uses .NET-style `CosmosDb__Endpoint`, others use SCREAMING_SNAKE; should standardize

**Output:** Full findings written to `.squad/decisions/inbox/turk-python-audit.md`

**Learnings:**
- All Python services share the same structural anti-patterns — any refactoring should establish a common template/cookiecutter
- `asyncio.to_thread()` is the right wrapper for unavoidable sync SDK calls in async FastAPI handlers
- FastAPI tuple-return `(dict, status_code)` pattern doesn't work — must use `Response(status_code=...)` or `HTTPException`
- Pydantic mutable defaults (`flags: list[str] = []`) are still a common bug source; need `Field(default_factory=list)`

### 2026-05-12 — Python P1 Fixes (Issues #86, #87, #88, #90)

**Issues fixed:**
1. **#86 — Dead shared/auth.py + diverged copies**: Deleted unused `src/shared/auth.py`. Fixed account-opening-service's case-sensitive `!= "Admin"` role check to use `.lower()` (auth.py + routes.py). All 4 services now use case-insensitive role checks.
2. **#87 — Blocking sync I/O**: Wrapped all `credential.get_token()`, `CosmosClient()`, `upsert_item()`, `query_items()`, `upload_blob()`, and `embeddings_client.embed()` calls with `asyncio.to_thread()` across all 4 Python services.
3. **#88 — Broad except-Exception**: Narrowed catches where genuinely harmful (httpx tool calls → `httpx.RequestError|HTTPStatusError`, Redis ops → `redis.RedisError`, JSON parsing → `json.JSONDecodeError|KeyError|ValueError`, token decode → `json.JSONDecodeError|ValueError`). Kept broad catches for startup graceful degradation and consumer loop last-resort handlers.
4. **#90 — No global exception handler**: Added `@app.exception_handler(Exception)` to all 4 Python services. Standardized error response: `{"error": ExcType, "message": "... Correlation ID: ...", "status_code": 500}`.

**Key patterns established:**
- `asyncio.to_thread()` is the standard wrapper for Azure SDK sync calls (get_token, CosmosClient, blob upload)
- Global exception handlers use structlog correlation ID from contextvars
- Error response shape: `{"error": str, "message": str, "status_code": int}`
- Broad catches acceptable in: startup init (graceful degradation), background loop outer handler, health checks
- Narrow catches required in: request handlers, tool functions, data parsing

### 2026-05-13 — Deployment Lessons from P1 Wave (Session 2026-05-13T02:47)

**Lessons learned during containerization and AKS deployment:**

1. **Always use `task cloud:deploy` — never `kubectl apply -k` directly**
   - The Taskfile handles critical placeholder substitution for `configmap.yaml` and `secret-provider-class.yaml`
   - Direct kubectl apply skips this substitution, leaving broken configs in the cluster
   - Risk: Services fail to connect to Cosmos, Redis, or KeyVault due to unresolved placeholders like `REPLACE_WITH_KEYVAULT_NAME`

2. **Python service dependencies must be declared in both pyproject.toml and Dockerfile**
   - `account-opening-service` was missing `python-multipart` (needed for multipart form uploads) and `aiohttp` (async HTTP client)
   - Added both to pyproject.toml; Docker images now install via `pip install .`

3. **.dockerignore must exclude stale build artifacts**
   - Old .NET builds accumulate in `obj.old/` directories as root-owned files
   - These bloat layers unnecessarily; added `**/obj.old/` to .dockerignore
   - Impact: Smaller images, faster builds

4. **Entra agent sidecar listens on port 8080, not 5000**
   - `account-opening-worker` was probing the sidecar on port 5000 but it listens on port 8080
   - Updated sidecar port mapping and health probe config
   - Impact: Worker now successfully obtains Entra-authenticated tokens via sidecar

5. **Beta package versions must be explicitly allowed**
   - `azure-ai-inference` has no stable release; only beta versions exist (>=1.0.0b9)
   - Constraint was `>=1.0.0,<2.0.0` which excluded betas; changed to `>=1.0.0b9,<2.0.0`
   - This applies to any Azure preview service SDK

**Implications for future work:**
- Always validate placeholder substitution in configmaps after deployment
- Update Taskfile if new services are added
- Keep `[build-system]` and `[project].dependencies` in sync with Dockerfiles
- Review .dockerignore before building images
- Check env var references in health probes and startup configs

---

## 2026-05-12 — P2 Wave 1 Completion

**Wave:** squad/p2-wave-1 (with Basher, Linus)  
**Issues:** #108, #93, #106

**Scope:**
- #108: Standardized Python env vars to SCREAMING_SNAKE_CASE across all FastAPI services
- #93: Extracted layered architecture (config, models, services, routes) for Python services
- #106: Migrated Go event-processor from log.Printf to stdlib slog with JSON handler

**Outcome:** ✓ All Python services import, Go builds clean, test pass. Commits: 3e215af, 9b0912d, 512db07, 065994c.

**Team:** Coordinated with Basher (.NET standardization) and Linus (frontend cleanup) to ensure cross-service consistency. Wave complete; PR pending merge to main.

---

## 2026-05-13 — Issue #115: Python Test Repairs After Wave 1

**Branch:** squad/p2-wave-3  
**Issue:** #115 — Repair Python service tests after Wave 1 #93 service-layer extraction

**Problem:**
Wave 1 extraction moved Python service code from monolithic `app/main.py` into layered modules (`app/routes/`, `app/services/`, `app/models/`), but test fixtures still imported from old locations and relied on module-level globals that no longer existed. All 4 services (ai, budget, chatbot, account-opening) had failing tests.

**Fixes Applied:**

1. **ai-service** (002e24b):
   - Updated test imports to use new module structure (`app.services.anomaly_service`, `app.models.*`)
   - Result: All tests passing

2. **budget-service** (3481962):
   - Added JWT auth fixtures to `conftest.py` (matching user-service token format)
   - Updated imports to match extracted routes
   - Result: 21/21 tests passing

3. **chatbot-service** (c7435e8):
   - Updated test imports from `app.main` to `app.services.*`
   - Result: All tests passing

4. **account-opening-service** (e4fc3b4):
   - Restored missing audit trail endpoint (`GET /applications/{id}/audit`) accidentally dropped during Wave 1 extraction
   - Added FastAPI dependency overrides to `conftest.py` using async functions
   - Overrode: `get_repository`, `get_redis_client`, `get_blob_service_client`, `get_state_machine`
   - Result: 136/136 tests passing

**Key Learning — FastAPI Dependency Override Pattern:**
When FastAPI routes use `Depends()` with async dependency functions, test fixtures must override them with **async functions**, not lambda returns:

```python
# ❌ WRONG — sync lambda
app.dependency_overrides[get_repository] = lambda: mock_repo

# ✅ CORRECT — async function
async def override_repository():
    return mock_repo

app.dependency_overrides[get_repository] = override_repository
```

This pattern applies to all Python services using the FastAPI DI pattern introduced in Wave 1 and refined in Wave 2 (#94).

**Gotchas:**
- Async dependency functions in `dependencies.py` require async override functions, even if the returned object is not itself awaitable
- Missing endpoints from extraction can cause tests to pass with wrong status codes (e.g., 404 vs 403 when endpoint is missing entirely)
- Always verify extracted routes against original monolithic `main.py` to ensure nothing was dropped

**Outcome:** Issue #115 closed. All Python service tests green on branch `squad/p2-wave-3`.

## 2026-05-13 — Issue #109: OpenAPI Specs for Python Services

**Issue:** #109 — Add OpenAPI/Swagger API documentation (Python/FastAPI portion)

**Context:** No OpenAPI spec files committed despite architecture.md referencing Swagger endpoints. Frontend developers must read backend source to understand API contracts.

**What was done:**
1. Verified all 4 FastAPI services already expose `/docs` (Swagger UI) and `/openapi.json` endpoints by default (FastAPI behavior)
2. Created `scripts/generate-openapi.py` — Python script that imports each service's FastAPI app and calls `app.openapi()` to generate specs
3. Generated and committed OpenAPI specs to `docs/api/` for:
   - ai-service-openapi.json (24KB)
   - budget-service-openapi.json (24KB)
   - chatbot-service-openapi.json (24KB)
   - account-opening-service-openapi.json (24KB)
4. Updated `docs/architecture.md` with API documentation references and regen instructions
5. Pushed to branch `squad/p2-wave-3`, commented on issue

**Key files:**
- `scripts/generate-openapi.py` — regenerates all 4 specs by importing each service's FastAPI app
- `docs/api/{service}-openapi.json` — committed specs
- `docs/architecture.md` — updated "Communication Patterns" section

**Pattern:** FastAPI `app.openapi()` method generates full OpenAPI 3.1.0 spec with all routes, schemas, and metadata from the FastAPI app definition at import time. Script must add each service's `src/{service-name}` path to `sys.path` before importing `app.main.app`.

**Gotcha:** Script emits experimental warnings from Azure AI SDK (`MemoryStore`, `SkillResource`) during import — these are harmless and don't affect spec generation.

**Outcome:** Python portion of #109 complete. Waiting for Basher to finish .NET services.

## Learnings
- FastAPI automatically generates OpenAPI 3.1.0 specs at runtime via `app.openapi()` method — no external tools needed
- OpenAPI generation requires importing the FastAPI app, which triggers all module-level code (logging setup, telemetry init, etc.) — acceptable for offline spec generation
- Azure AI SDK emits experimental warnings at import time for preview features (MemoryStore, SkillResource) — suppress with PYTHONWARNINGS=ignore if needed
- Committed OpenAPI specs serve as API contract documentation for frontend developers without requiring service runtime access
- Pattern: Store specs in `docs/api/{service-name}-openapi.json` for cross-team discoverability

### 2026-05-13 — JWT Email-Based Login Support (Dashboard Smoke Test Fix)

**Issue:** All E2E dashboard smoke tests failing with 401 Unauthorized. Frontend sends `username: email` in login requests, but backend only supported username lookup.

**Root cause:** Frontend `AuthContext.tsx` POSTs to `/api/auth/login` with `{ username: email, password }` (line 2 of login function). Backend `AuthController.Login` called `GetUserByUsernameAsync(request.Username)` which only queries the Username field in Cosmos DB, not the Email field. When users registered with a different username than their email, login failed.

**Why it surfaced now:** E2E test fixtures were recently updated to extract usernames from emails ("e2e-default@banking-demo.com" → "e2e-default"), but database had existing users registered with the full email as username. This created a mismatch:
- Test registers user with username="e2e-default" → 409 (email already exists)
- Test ignores 409 error (intended behavior)
- Test tries to login with username="e2e-default@banking-demo.com" → user not found

**Fix:** Updated `AuthController.Login` to try email lookup if username lookup fails:
```csharp
var user = await _userService.GetUserByUsernameAsync(request.Username);
if (user == null)
{
    user = await _userService.GetUserByEmailAsync(request.Username);
}
```

**Verification:**
- Manual curl tests confirm both username and email login now work
- All 4 dashboard smoke tests pass: `BASE_URL=https://onlinebankingdemo.bjdazure.tech NODE_TLS_REJECT_UNAUTHORIZED=0 npx playwright test --project=smoke --grep "Dashboard"`
- JWT structure unchanged (still uses actual username in claims, not the login identifier)

**Pattern:** Backend now supports login with EITHER username OR email, matching common auth UX patterns. Password validation always uses the actual username from the user record.

**Commit:** 25fe743
**Files modified:** `src/user-service/Controllers/AuthController.cs`
**Deployment:** Built and deployed user-service:latest to AKS via `task cloud:build:user-service && task cloud:deploy`

### 2026-05-13 — Login Email Fallback (Smoke Test Support)

**Issue:** Dashboard smoke tests failing with 401 Unauthorized after frontend test fixture updates. Frontend sends email as login identifier (`username` parameter), backend only checks Username field against Cosmos DB.

**Problem:** User registered with `username="e2e-default"`, `email="e2e-default@banking-demo.com"`. Frontend tried to login with `username="e2e-default@banking-demo.com"`. Backend lookup failed because no user had that username exactly.

**Fix:** Updated `AuthController.Login` to fall back to email lookup if username lookup fails:
```csharp
var user = await _userService.GetUserByUsernameAsync(request.Username);
if (user == null)
{
    user = await _userService.GetUserByEmailAsync(request.Username);
}
```

**Rationale:**
- Frontend compatibility — UI already sends email; changing frontend would add complexity
- Common UX pattern — Most auth systems accept email OR username
- Minimal change — 3 lines in AuthController; no schema changes
- No security regression — Password still validated, JWT still contains actual username

**Files changed:** `src/user-service/Controllers/AuthController.cs`

**Deployment:** Built user-service:latest, pushed to ACR, deployed to AKS

**Result:** ✅ Dashboard smoke tests now pass; users can login with either username or email; backward-compatible

**Commit:** `25fe743`


### 2026-05-13 — Issue #118: ai-service Foundry agents 'Agent not initialized'

**Branch:** squad/p2-wave-3  
**Commit:** 0cb17b8

**Symptom:** Admin AI Foundry Connectivity panel reported both `transaction-categorizer` and `risk-assessor` as 🔴 ERROR / "Agent not initialized".

**Diagnosis path:**
1. Init container `provision-agents` succeeded — agents exist in Foundry project ✅ (rules out possibility #1)
2. Main container startup logs revealed: `❌ Foundry initialization failed: No module named 'aiohttp'`
3. Health-check code in `app/routes/api.py::_check_agent` correctly detects `_ready=False` (rules out possibility #3)

**Root cause:** `agent-framework-foundry`'s `FoundryAgent` uses `aiohttp.ClientSession` internally but does not declare it transitively. ai-service's `pyproject.toml` was missing `aiohttp`. The `try/except` in lifespan swallowed the ImportError, leaving both `FoundryRiskAnalyzer` and `FoundryCategorizer` with `_ready=False`.

**Fix:** Added `aiohttp = "^3.10.0"` to `src/ai-service/pyproject.toml`. Built via `task cloud:build:ai-service`, deployed via `task cloud:deploy`, then `kubectl rollout restart` (image tag `:latest` → deployment otherwise unchanged).

**Verification:**
```
✅ Foundry risk agent created (persistent)
✅ Foundry categorizer agent created (persistent)

GET /api/admin/foundry-status
{"status":"ok","agents":{"transaction-categorizer":{"status":"ok"},"risk-assessor":{"status":"ok"}}}
```

**Pattern (recurring — third time now):**
Azure AI / agent-framework Python SDKs frequently rely on `aiohttp` without declaring it. Whenever a service depends on `agent-framework-foundry` or related packages, **explicitly add `aiohttp` to pyproject.toml**. chatbot-service had it; account-opening-service was fixed earlier; ai-service was the latest miss. Suggests a checklist item for any new Python AI service.

**Gotcha:** `task cloud:deploy` after a rebuild leaves the Deployment manifest "unchanged" because the `:latest` image tag and yaml are identical — `kubectl rollout restart` is required to pull the freshly-pushed image. Worth considering image digests in the deploy task.

### 2026-05-13 — Coordinator Integration: Rollout Restart in cloud:deploy (commits e57d5f0, 1a989f2)

**Pattern:** The Coordinator has permanently integrated `kubectl rollout restart deployment/<svc>` into the `task cloud:deploy` target as of commit e57d5f0. This eliminates the manual `kubectl rollout restart` workaround after every cloud build/deploy cycle.

**Historical context:** The registration smoke failures (Linus's stale-bundle trap) and JWT forwarding verification both required manual rollout restarts because `:latest` image tags don't trigger rolling updates when the manifest is unchanged. The Coordinator fixed this in the Taskfile itself — no more manual step needed.

**For you:** Any service you build/deploy via `task cloud:deploy` will now automatically restart pods as part of the deploy job. If you ever bypass `task cloud:deploy` and use `kubectl apply -k` directly, you lose this guarantee. Always use the task.

**Additional refactor (commit 1a989f2):** The Taskfile's `NAMESPACE` variable is now hoisted to task-level scope, eliminating hardcoded `banking-demo` strings throughout the deploy targets. This makes it easier to test against different namespaces.

**Files that changed (Taskfile):**
- Added rollout restart commands for ui-app, user-service, account-service, transaction-service, transfer-service, ai-service, chatbot-service, budget-service, account-opening-service, prompt-eval-service post-kustomize-apply
- Hoisted NAMESPACE to global task var

**Verification:** After next deployment, running `kubectl logs deploy/<svc>` should show pod startup logs timestamped *after* the deploy command finished (not old logs from pre-deploy pod).


### 2026-05-13 — Issue #121: Chatbot "couldn't retrieve your accounts" — wrong endpoint URL

**Branch:** squad/p2-wave-3

**Symptom:** Chatbot replied "I'm sorry, I couldn't retrieve your account balances right now because the account service returned an error." for every "what's my balance" question.

**Initial hypothesis (wrong):** Suspected JWT was not being forwarded (per #117 pattern). It actually was — `chat_service.handle_chat` extracts the bearer token and `agent_tools.get_user_accounts` reads it from a ContextVar and sets `Authorization: Bearer <jwt>` on the httpx call.

**Root cause:** The chatbot's `get_user_accounts` tool called `GET {ACCOUNT_SERVICE_URL}/api/accounts/my` — a path that does **not** exist on `account-service`. The .NET `AccountsController` exposes `[HttpGet] /api/accounts` (it derives the user from the JWT `userId` claim — there is no `/my` suffix). Result: 404 from account-service → tool returned `{"error":"Account service returned 404"}` → agent translated it to the friendly "couldn't retrieve" message.

**Secondary issue spotted in same function:** Sanitizer read `acct["type"]`, but the account-service JSON field is `accountType`. Every sanitized account would have had an empty `type`. Fixed in the same patch with a fallback (`accountType` → `type`) so contract drift in either direction won't break it.

**Fix:** `src/chatbot-service/app/services/agent_tools.py`:
- Changed URL `/api/accounts/my` → `/api/accounts`.
- `_sanitize_account_data` now reads `accountType` first, falls back to `type`.

**Verification (live, https://onlinebankingdemo.bjdazure.tech):**
Before: `"I'm sorry, I couldn't retrieve your account balances right now because the account service returned an error."`
After: `"Here are your current balances by account, using masked account numbers: - Checking ****5852: $28,033.96 - Savings ****8917: $350,000.00 ..."` — masked account numbers, real balances, all 29 accounts returned.

**Deploy:** `task cloud:build:chatbot-service` → `task cloud:deploy` (auto rollout restart per Coordinator integration in Taskfile commit e57d5f0).

## Learnings
- Always verify the **exact** downstream URL/path against the producing controller before assuming a deeper auth/identity bug. The #117 JWT-forwarding pattern was a tempting hypothesis but a `git grep` of the controller's routes ruled it out in 30 seconds.
- The chatbot tool error path swallows the HTTP status code into a generic "couldn't retrieve" message visible to users. Worth considering surfacing the status (or at least logging at error not warning) so the next 4xx vs 5xx is faster to triage from logs alone — current logger emits at WARN with the body truncated to 200 chars, which was sufficient here but only because we re-reproduced from the cluster.
- Cross-service JSON contract drift (`accountType` vs `type`) silently produced empty fields. Defensive `.get(primary, .get(legacy, default))` is the lightweight fix until a shared schema/types story exists. A future improvement would be Pydantic models for inbound data in chatbot tools, mirroring what frontend already enforces.

---

**2026-05-13 18:17:36Z** — Scribe note: Basher proved your #121 chatbot fix was correct (no revert needed). The Accounts page regression was unrelated (pre-existing Cosmos serializer-casing drift in account-service). Now tracking #124 (Account Opening Agent Stages).

### 2026-05-13 — Account-Opening Stages Projection (Issue #124)

**Issue:** Admin dashboard rendered "No stage data available" and "Risk Tier: —" for every account-opening application — even those that had successfully run the full Foundry agent pipeline.

**Root cause (option d — API field-name mismatch):** The persisted document stores agent outputs in `agentResults[]` (one entry per agent, with `riskTier` nested inside the compliance-check entry's `findings` dict). The admin UI in `AdminApplicationsTab.tsx` reads top-level `application.stages[]` (with `name/status/confidence/reasoning`) and `application.riskTier`. Neither field was ever projected on the API response, so completed pipelines looked broken.

**Fix:** Added `app/services/projection.py` with `project_application()` that derives the four canonical pipeline stages (document-extraction → identity-verification → compliance-check → provisioning) from `agentResults`. Completed entries surface confidence/reasoning/timestamp plus a `details` summary string (KYC, Risk, Flags); missing entries fall back to `in_progress` (when the application status maps to that agent) or `pending`. `riskTier` is pulled from the compliance-check `findings.riskTier`. Wired into all four application-returning endpoints. Persistence schema unchanged.

**Key files:**
- `src/account-opening-service/app/services/projection.py` — new projection helper
- `src/account-opening-service/app/routes/api.py` — call `project_application()` / `project_applications()` on the way out
- `src/account-opening-service/tests/test_projection.py` — 6 unit tests

**Pattern (reusable):** When the storage schema and the UI contract diverge, add a thin **outbound projection** in `app/services/` rather than mutating the model or the persisted documents. Keeps reads/writes symmetric and lets the UI evolve without a Cosmos migration.

**Workflow gating note:** Many applications stuck at `submitted` are not a bug — Document Extraction triggers on the `document_uploaded` event, so applications where the user never uploaded ID/proof-of-address legitimately never advance. The new projection now surfaces this state as four `pending` stages instead of an empty placeholder.

**Commit:** 4dc6762

### 2026-05-13 — Foundry Eval 500 (Issue #126)

**Issue:** `POST /api/admin/evaluate` in ai-service returned 500 with `AttributeError: type object 'Message' has no attribute 'system'`.

**Root cause:** Code used `Message.system(...)` / `Message.user(...)` factory methods that the `agent_framework.Message` class does not expose. Verified live signature in pod: `Message(role: 'RoleLiteral | str', contents: 'Sequence[Content | str | Mapping[str, Any]] | None' = None, ...)`. Only public Message helpers are `from_dict`, `from_json`, `text`, `to_dict`, `to_json` — no role-named factories.

**Bonus bug found while verifying:** The same `EvalItem(input=[...], output="")` call also used wrong kwargs. Live signature: `EvalItem(conversation: list[Message], tools=None, context=None, expected_output=None, ...)`. Without this fix the 500 would just turn into a different `TypeError`.

**Fix (single hunk in `src/ai-service/app/routes/api.py`):**
```python
EvalItem(
    conversation=[
        Message("system", [request.system_prompt]),
        Message("user", [prompt]),
    ],
)
```
Note `[request.system_prompt]` (list-wrapped) — `Message`'s `contents` is a `Sequence`, so passing a bare string causes Python to iterate it character-by-character and produce N `TextContent` parts.

## Learnings

- **`agent_framework.Message` API shape:** Construct positionally as `Message(role, contents)` where `role` is `"system"|"user"|"assistant"` (string literal) and `contents` is a **list** of strings / `Content` objects. Do NOT use `Message.system(...)` or `Message.user(...)` — those don't exist. Always wrap a single string in a list, otherwise iteration over the string produces one TextContent per character.
- **`agent_framework._evaluation.EvalItem` API shape:** `EvalItem(conversation=[...messages...], expected_output=..., tools=..., context=...)`. Not `input=`/`output=`.
- **Verification trick:** `kubectl exec deploy/<svc> -- python -c "import inspect; from X import Y; print(inspect.signature(Y.__init__))"` is the fastest way to nail down a prerelease SDK's true API when docs are stale.

**Commit:** (see #126)

---

### 2026-05-13 — Wave 3 Closeout — Issue #126 Merged (Scribe Orchestration)

**Status:** Wave 3 orchestration complete. Issue #126 (ai-service Message API drift) now documented in decisions.md and live-verified on onlinebankingdemo.bjdazure.tech.

**Related:** Basher shipped concurrent fixes #123 (dashboard zeros) and #125 (accounts regression). Foundry raisvc 403 follow-up from #126 now tracked on Danny's infra plate.

**Decision Drop:** Merged turk-126-message-api.md into decisions.md. Bonus learning: `EvalItem` kwarg drift (input → conversation) caught and fixed in same session.

**Live Verification:** `/api/admin/evaluate` now passes request validation and reaches Foundry backend. 403 is infra-side (role assignment), not Python API usage.

---

### 2026-05-13 — Issues #125 & #130: Cosmos Casing Drift + Redis Counter Flicker

**Branch:** squad/p2-wave-3  
**Commits:** 243457f (#125), 8fc8c76 (#130)

#### Issue #125: Cosmos Serializer-Casing Drift

**Context:** Basher fixed account-service to OR both PascalCase and camelCase field names in Cosmos queries (`c.UserId OR c.userId`) after discovering Brian's accounts were invisible due to serializer drift. This was a hot-fix to restore read functionality.

**Task:** Audit ALL .NET services for the same drift, pin serializers, document migration plan.

**Audit findings:**
- **transaction-service:** Used camelCase only (`c.accountId`, `c.userId`, `c.timestamp`) — silently missing PascalCase docs
- **user-service:** Used PascalCase only (`c.Username`, `c.Email`, `c.Role`, `c.CreatedAt`) — also in bootstrap admin queries in Program.cs
- **prompt-eval-service:** Used camelCase only (`c.userId`, `c.templateId`, `c.updatedAt`, `c.createdAt`)
- **account-service:** Already fixed by Basher (OR pattern)
- **transfer-service:** Only point-reads by `id` — no user-scoped queries, no fix needed

**Fix pattern (applied to 3 services):**
1. Repository queries: `WHERE c.UserId = @x OR c.userId = @x` (both casings)
2. Iterator drain: Replace `.ReadNextAsync() → .FirstOrDefault()` with `while (iterator.HasMoreResults) { AddRange(...) }` to prevent silent truncation at ~100 docs
3. Serializer pin: Add explicit `CosmosSystemTextJsonSerializer` with `PropertyNamingPolicy.CamelCase` to all `CosmosClient` registrations in `Program.cs`

**Why camelCase?** Matches API surface (ASP.NET Core defaults to camelCase JSON), frontend expectations (React/TS convention), and the majority of recent docs.

**Decision drops:**
- `.squad/decisions/inbox/turk-125-cosmos-migration-plan.md` — One-shot migration plan for normalizing PascalCase docs to camelCase (Brian to execute)
- `.squad/decisions/inbox/turk-cosmos-serializer-pin.md` — Convention going forward for all .NET services

**Integration test issue:** Filed via `gh issue create` (title: "test(integration): assert API write → direct Cosmos query field casing match", labels: squad) — Livingston's domain. Would have caught both the original drift and the reader incompatibility.

**Post-migration cleanup:** Once all docs are normalized, remove the OR-pattern and revert to single-casing queries for cleaner SQL and faster execution.

#### Issue #130: aiCallsToday Counter Flicker

**Root cause:** Counter lived in process memory (`self._ai_calls_today`) in `FoundryRiskAnalyzer`. With HPA min=2 replicas, each pod has its own count → dashboard value flickered between 17 and 68 depending on which pod responded.

**Fix:** Moved counter to Redis:
- Key pattern: `ai:metrics:calls:{YYYY-MM-DD}` (UTC date)
- Increment: `INCR` on **SUCCESS path only** (NOT 429s, NOT 500s) — inside `FoundryRiskAnalyzer.analyze()`
- TTL: 36 hours (covers UTC day boundary + buffer) — set via `EXPIRE` if `TTL` returns -1
- Read: `GET` in dashboard endpoint via new `get_ai_calls_today_from_redis(redis_client)` helper
- Old in-memory counter: Removed `_ai_calls_today`, `_ai_calls_date`, `_ai_calls_lock` from `FoundryRiskAnalyzer`
- Signature change: `AnalyzerPipeline.assess()` now accepts optional `redis_client` kwarg, passes it to `FoundryRiskAnalyzer.analyze()`

**Key files:**
- `src/ai-service/app/services/anomaly_service.py` — counter logic moved to Redis
- `src/ai-service/app/routes/api.py` — dashboard endpoint now calls `get_ai_calls_today_from_redis(state.redis_client)`

**Verification (Brian will run):**
- Dashboard refresh 10x → monotonically non-decreasing, no flicker
- Cross-pod check: `kubectl exec` into each ai-service pod and hit `/api/admin/dashboard` directly — same value from each
- TTL visible: `redis-cli TTL ai:metrics:calls:2026-05-13`
- New key auto-creates at UTC midnight

**Tests:** No tests asserted on the in-memory counter — nothing to update.

## Learnings: Cosmos Serializer Drift

**Cross-service audit methodology:**
1. `grep -n "WHERE c\." **/*.cs` to find all Cosmos queries
2. Identify field casings used (PascalCase vs camelCase)
3. Apply OR-both-casings pattern to ALL queries (defensive)
4. Drain iterators with `while (HasMoreResults)` — `.ReadNextAsync()` alone silently truncates at page size
5. Pin `CosmosSystemTextJsonSerializer` with explicit `PropertyNamingPolicy` in **every** `CosmosClient` registration

**Why OR-both-casings is temporary:** It's defensive but inefficient (Cosmos can't use indexes optimally when ORing field variants). The correct long-term fix is:
1. Normalize storage (one-shot migration)
2. Pin serializer to prevent future drift
3. Revert queries to single-casing

**Pattern for future .NET services:** ANY service that writes to Cosmos MUST pin the serializer at registration time. Default `CosmosClient()` behavior is non-deterministic (SDK version-dependent).

## Learnings: Redis Daily Counter Pattern

**Pattern:**
```python
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
counter_key = f"ai:metrics:calls:{today}"
await redis_client.incr(counter_key)

# Set TTL to 36 hours on first increment
ttl = await redis_client.ttl(counter_key)
if ttl == -1:  # Key exists but has no TTL
    await redis_client.expire(counter_key, 36 * 60 * 60)
```

**Why 36 hours?** Covers UTC day boundary + a buffer. Keys auto-expire after they're no longer relevant.

**Why check TTL == -1?** `INCR` creates the key but doesn't set TTL. First caller sets the TTL; subsequent `INCR`s leave it alone. `-1` means "key exists but no TTL set" (vs `-2` = "key doesn't exist").

**When to use:** Any per-day metric that needs to be **cross-replica consistent** (counters, rate limits, usage tracking). Don't use in-memory for metrics read from multiple pods.

**Counter semantics:** Increment ONLY on success path. Don't count retries, 429s, or 500s — this keeps the counter meaningful (actual work done, not attempts).

**Alternative (if you need per-hour):** Use key pattern `ai:metrics:calls:{YYYY-MM-DD}:{HH}` with 25-hour TTL (covers hour overlap).


## Cross-Agent Update — 2026-05-13 SDK Pinning Convention (Basher)

**Relevant to:** Python service dependency management (your domain)

Basher's eval-403 RCA (issue #137) established a **new exception to the repo's standard dependency versioning**:

### Convention: Preview-Channel SDKs Require Exact Pins

- **Stable dependencies** (fastapi, pydantic, redis, etc.) continue using range constraints (`^`, `>=min,<next-major`)
- **Preview-channel SDKs** (agent-framework-core, agent-framework-foundry, azure-ai-inference beta releases) require exact pins (e.g., `"1.2.2"`, not `"*"` or `">=1.0.0,<2.0.0"`)
- **Reason:** Preview channels break semver between minor versions (1.2.2 → 1.3.0 breaking change caused eval-403). Wildcard/range pins allow arbitrary upgrades on every rebuild, introducing non-determinism.

### Applied To
- src/ai-service/pyproject.toml: agent-framework-core/foundry pinned to 1.2.2, azure-ai-inference pinned to 1.0.0b9
- src/chatbot-service/pyproject.toml: same
- src/account-opening-service/pyproject.toml: same

### Remediation Going Forward
- Add pre-commit lint rule to block agent-framework wildcard constraints
- Enable Dependabot with explicit upgrade PRs for preview SDKs
- Require eval smoke-test before merging any preview-SDK version bump

### Watch Out For
If you touch any Python service's pyproject.toml and encounter agent-framework or azure-ai-inference dependencies, treat them as preview-channel and use exact pins. Don't fall back to range constraints.

### 2026-05-12 — Crash Fix: ORDER BY + Composite Index Requirement

**Issue:** prompt-eval-service crashed on startup after #125 fix:
```
CosmosException: BadRequest (400)
Reason: The order by query does not have a corresponding composite index
Container: PromptTemplates
```

**Root Cause:** Commit 243457f introduced OR-both-casings queries (`c.userId = 'global' OR c.UserId = 'global'`) with ORDER BY clauses (`ORDER BY c.updatedAt DESC, c.CreatedAt DESC`). Cosmos DB requires a **composite index** to serve OR-pattern + ORDER BY queries efficiently.

**Learning:** Combining OR-pattern defensive queries with ORDER BY forces a composite index requirement:
- Composite indexes must be pre-defined in Terraform
- Blocks deployment until Brian runs `terraform apply`
- Couples code changes to infra changes (bad)
- Only justified for high-traffic, large-result-set queries

**Fix Applied (Option A):** Removed ORDER BY from Cosmos queries, sorted in-memory instead:
- `CosmosEvaluationRunRepository.GetAllAsync()` → fetch all, then `.OrderByDescending(r => r.CreatedAt).ToList()`
- `CosmosPromptTemplateRepository.GetAllAsync()` → fetch all, then `.OrderByDescending(t => t.UpdatedAt).ToList()`

**Rationale:** These are **admin tables** (global templates, evaluation runs) with ~10-50 total docs max. In-memory sort is perfectly acceptable and avoids infra coupling.

**Files Changed:**
- `src/prompt-eval-service/Repositories/CosmosEvaluationRunRepository.cs`
- `src/prompt-eval-service/Repositories/CosmosPromptTemplateRepository.cs`
- `.squad/skills/cosmos-casing-audit/SKILL.md` — added "ORDER BY Pitfall" section

**Verification:** `dotnet build` succeeded with 0 errors.

**Decision:** `.squad/decisions/inbox/turk-orderby-composite-index.md`

**Key Takeaway:** For small admin tables, prefer in-memory sort over composite indexes. Reserve composite indexes for user-scoped queries with 100s-1000s of docs per user.

---

### 2026-05-14T02:03:23Z: Cross-team notification — #137/#130 resolved

**By:** Scribe (Orchestration)  
**Topics:** FoundryAgent SDK contract, unified fix scope

Issues #137 (eval failures) and #130 ("AI Calls Today" counter stuck at 0) are now CLOSED and verified in production. Root cause: FoundryAgent constructor signature drift in both account-opening-service and ai-service.

**New contract:** When instantiating any `FoundryAgent(...)`, pass model via `default_options={"extra_body": {"model": "<deployment_name>"}}` — do NOT pass `model=` as a direct kwarg (SDK 1.2.2 rejects it).

**Verification:** Both pods now succeed end-to-end. Prevention: runtime `TestFoundryAgentSignatureContract` tests added to both services.

Your `turk-orderby-composite-index` decision has been merged into the decisions log as canonical reference. No follow-up work scoped.

---

**2026-05-14 16:57 Scribe:** Heads-up: #141 filed — Foundry Managed VNet migration plan from Danny. See decisions.md for context.

---

### 2026-05-14T19:20:00Z: Admin Users 500 Fix — Missing Composite Index

**Issue:** Admin Console "User Management" tab returned 500 Internal Server Error. Browser showed:
```
GET https://onlinebankingdemo.bjdazure.tech/api/admin/users 500 (Internal Server Error)
```

**Root Cause:** `CosmosUserRepository.GetAllUsersAsync()` used multi-field ORDER BY without a composite index:
```csharp
"SELECT * FROM c WHERE NOT STARTSWITH(c.id, 'email-lookup:') ORDER BY c.CreatedAt DESC, c.createdAt DESC"
```

Cosmos threw `BadRequest (400)`:
> "The order by query does not have a corresponding composite index that it can be served from."

**Why This Happened:**
1. Users container in `infra/cloud/cosmos.tf` defines no indexing policy → uses Cosmos default automatic indexing
2. Default indexing does NOT include composite indexes
3. Multi-field ORDER BY requires a composite index

**Additional Code Smell:** Query ordered by both `c.CreatedAt` and `c.createdAt` (case redundancy) — likely defensive casing but wasteful for ORDER BY.

**Fix Applied:** Removed ORDER BY from query (lines 110-124 of `CosmosUserRepository.cs`):
```csharp
// Removed ORDER BY to avoid requiring composite index in Cosmos.
// If sorted results are needed, either:
//   1. Add composite index to infra/cloud/cosmos.tf (Users container)
//   2. Sort in-memory after retrieval
var query = new QueryDefinition(
    "SELECT * FROM c WHERE NOT STARTSWITH(c.id, 'email-lookup:')");
```

**Rationale:** Users table is small (~10-100 users in typical deployment). Unsorted retrieval is acceptable for admin dashboard — UI can sort client-side if needed. Avoids infra coupling (adding composite index requires Terraform apply + container reindex).

**Files Changed:**
- `src/user-service/Repositories/CosmosUserRepository.cs`

**Verification:** Code change verified by grep/view. Local build blocked by permission issues (Brian will verify via deployment).

**Decision:** `.squad/decisions/inbox/turk-admin-users-500.md`

**Key Pattern:** Same as prompt-eval-service crash (2026-05-12): ORDER BY on small tables → remove it, sort in-memory if needed. Reserve composite indexes for high-volume user-scoped queries.

---

### 2026-05-14 — Basher Eval Workaround Test: FAILED (Scribe Relay)

**From Basher (Agent: basher-eval-workaround-prototy):**

Attempted `project_client.datasets.upload_file()` workaround for Foundry PE-only storage bug. API returns HTTP 200 + `file_id`, but **zero blobs written to storage**. Eval runs stuck in "Starting" status indefinitely.

**Root Cause Confirmed:** Whether client uses:
- Inline dataset upload (original bug), OR  
- `project_client.datasets.upload_file()` + `file_id` reference (this workaround),

Both hit the same broken Foundry backend service that cannot access private-endpoint-only blob storage.

**Next:** Test direct blob write + `azureml://` URI (Option 1, HIGH RISK) OR escalate to Microsoft support.

**Full RCA:** `.squad/decisions/decisions.md` (appended 2026-05-14T21:57:29Z)

### 2026-05-14 — Microsoft.OpenApi 2.x Namespace Migration (Swashbuckle 10.x)

**Issue:** Dependabot upgraded Swashbuckle.AspNetCore → 10.1.7, which pulled Microsoft.OpenApi → 2.4.1. Build failed with CS0234: "The type or namespace name 'Models' does not exist in the namespace 'Microsoft.OpenApi'". All 5 .NET services affected.

**Root Cause:** Microsoft.OpenApi 2.x removed the `.Models` sub-namespace. Types moved from `Microsoft.OpenApi.Models.*` to root `Microsoft.OpenApi.*` namespace.

**Learning — Microsoft.OpenApi 2.x Breaking Changes:**
1. **Namespace consolidation:** `Microsoft.OpenApi.Models.OpenApiInfo` → `Microsoft.OpenApi.OpenApiInfo` (and all related types)
2. **New helper type:** Swashbuckle 10.x introduced `OpenApiSecuritySchemeReference(referenceId, document)` to replace manual `OpenApiSecurityScheme { Reference = new OpenApiReference { ... } }` pattern
3. **Lambda requirement:** `AddSecurityRequirement` now expects `Func<OpenApiDocument, OpenApiSecurityRequirement>` to pass document context for references
4. **Collection type:** `OpenApiSecurityRequirement` dictionary value changed from `string[]` to `List<string>` (use collection expression `[]` or `new List<string>()`)

**Fix Pattern:**
```csharp
// OLD (Microsoft.OpenApi 1.x / Swashbuckle 6.x):
using Microsoft.OpenApi.Models;
c.AddSecurityRequirement(new OpenApiSecurityRequirement
{
    {
        new OpenApiSecurityScheme { Reference = new OpenApiReference { Id = "Bearer", Type = ReferenceType.SecurityScheme } },
        Array.Empty<string>()
    }
});

// NEW (Microsoft.OpenApi 2.x / Swashbuckle 10.x):
using Microsoft.OpenApi;
c.AddSecurityRequirement(doc => new OpenApiSecurityRequirement
{
    {
        new OpenApiSecuritySchemeReference("Bearer", doc),
        []
    }
});
```

**Files Updated:**
- user-service/Program.cs
- account-service/Program.cs
- transaction-service/Program.cs
- transfer-service/Program.cs
- prompt-eval-service/Program.cs

**Verification Method:**
1. Created isolated test project in /tmp to validate new API patterns
2. Used `dotnet nuget why` to trace Microsoft.OpenApi 2.4.1 dependency chain
3. Examined Swashbuckle 10.1.7 source code examples in GitHub repo
4. Used `strings` on Microsoft.OpenApi.dll to confirm type availability

**Outcome:** ✅ Microsoft.OpenApi.Models namespace errors eliminated. Build still fails due to **unrelated NuGet package version issues** (deferred per Brian's request):
- OpenTelemetry packages (1.15.x versions not stable yet)
- Microsoft.AspNetCore.Authentication.JwtBearer 10.0.8 (doesn't exist)
- Azure SDK packages (requested versions not published)

**Process Pattern for Future Major-Version Upgrades:**
1. Isolate the specific error (namespace, type, method signature)
2. Create throwaway test project to validate new API patterns
3. Check official migration guides + source code examples
4. Grep all occurrences before bulk edit
5. Apply fixes consistently across all affected files
6. Document both the fix and the verification method

**Decision:** `.squad/decisions/inbox/turk-openapi-2x-namespace-fix.md`

### 2026-05-15 — MCR Base Image Migration (Docker Hub Rate Limit Fix)

**Issue:** ACR build hit Docker Hub anonymous pull rate limit:
```
toomanyrequests: You have reached your unauthenticated pull rate limit.
```

All service Dockerfiles used Docker Hub base images (python:3.11-slim, node:20-alpine, nginx:alpine, golang:1.26-alpine, alpine:latest). ACR build agents pull anonymously → 100 pulls per 6 hours per IP limit.

**Decision:** Migrate ALL base images from Docker Hub to Microsoft Container Registry (MCR). MCR has no rate limits for Azure customers, no auth required, and provides Microsoft-maintained, security-scanned images on Azure Linux 3.0.

**Dockerfiles updated (7 files):**
1. `src/budget-service/Dockerfile`
2. `src/chatbot-service/Dockerfile`
3. `src/ai-service/Dockerfile`
4. `src/account-opening-service/Dockerfile`
5. `src/ai-service/Dockerfile.eval-debug`
6. `src/ui-app/Dockerfile`
7. `src/event-processor/Dockerfile`

**Image mappings (verified via MCR API):**
- `python:3.11-slim` → `mcr.microsoft.com/azurelinux/base/python:3.12` (3.11 not available, bumped to 3.12)
- `node:20-alpine` → `mcr.microsoft.com/azurelinux/base/nodejs:20`
- `nginx:alpine` → `mcr.microsoft.com/azurelinux/base/nginx:1.28`
- `golang:1.26-alpine` → `mcr.microsoft.com/oss/go/microsoft/golang:1.26-azurelinux3.0` (Microsoft Build of Go)
- `alpine:latest` (Go runtime) → `mcr.microsoft.com/azurelinux/distroless/base:3.0` (distroless for security)

**Azure Linux changes:**
1. **User creation:** `adduser` (Debian) → `useradd -r -s /sbin/nologin -M` (Azure Linux uses shadow-utils)
2. **Package manager:** `apt-get` / `apk` → `tdnf` (Azure Linux package manager)
3. **Package names:** 
   - `dnsutils` → `bind-utils`
   - `iputils-ping` → `iputils`
   - `procps` → `procps-ng`
4. **Cleanup:** `rm -rf /var/lib/apt/lists/*` / `apk --no-cache` → `tdnf clean all`

**Python 3.11 → 3.12 compatibility:**
- Checked all `pyproject.toml` files: NONE specify `requires-python` constraint
- FastAPI, Pydantic, Azure SDKs all support Python 3.12
- No breaking changes in stdlib
- Risk: LOW

**Distroless for Go (event-processor):**
- Changed runtime from `alpine:latest` to `mcr.microsoft.com/azurelinux/distroless/base:3.0`
- Benefits: No shell, no package manager, minimal attack surface, includes ca-certificates
- `CGO_ENABLED=0` ensures static binary (no dynamic lib dependencies)
- `USER nobody` (UID 65534) exists in distroless
- Risk: MEDIUM (more restrictive than alpine, but static binary mitigates)

**Local build verification:** Skipped (Docker/Podman unavailable locally). Verification deferred to ACR build. All MCR images verified available via API.

**Key files created:**
- `.squad/decisions/inbox/turk-mcr-base-image-migration.md` — full decision doc with rationale, risks, mitigations
- `.squad/skills/mcr-base-image-migration/SKILL.md` — comprehensive reference guide for future migrations

**Expected outcome:** ACR builds succeed without Docker Hub rate limit errors. No runtime changes (services run identically).

**Critical path services to monitor on first ACR build:**
1. event-processor (distroless change - highest risk)
2. ai-service eval-debug (az CLI + tdnf package changes)
3. ui-app (multi-stage node+nginx)
4. budget-service (representative Python service)

## Learnings: MCR Base Image Migration

- **MCR has no rate limits** for Azure customers — unlimited pulls, no auth required from ACR build agents
- **Azure Linux 3.0** is Microsoft's minimal, RPM-based distro (replaces Mariner)
- **Python 3.11 not available** on Azure Linux base images — only 3.12+ (checked via MCR API)
- **Azure Linux uses `tdnf`** package manager (not apt-get/apk) — RPM-based, similar to dnf/yum
- **Package name differences:** `dnsutils`→`bind-utils`, `iputils-ping`→`iputils`, `procps`→`procps-ng`
- **User creation:** Azure Linux uses `useradd` (shadow-utils), not Debian's `adduser` wrapper. Flags: `-r` (system user), `-M` (no home), `-s /sbin/nologin`
- **Distroless for Go:** `mcr.microsoft.com/azurelinux/distroless/base:3.0` is perfect for static Go binaries — no shell, no package manager, includes ca-certificates, has `nobody` user (UID 65534)
- **Microsoft Build of Go:** `mcr.microsoft.com/oss/go/microsoft/golang` includes FIPS support by default (1.25+)
- **MCR API for tags:** `curl -s 'https://mcr.microsoft.com/v2/<repo>/tags/list'` returns JSON list of all available tags
- **Az CLI install script** (`https://aka.ms/InstallAzureCLIDeb`) detects distro via `/etc/os-release` — should work on Azure Linux (RPM-based)
- **Node.js/nginx on Azure Linux:** Direct replacements for alpine versions, no package manager changes needed (no custom packages in our Dockerfiles)
- **Cleanup commands:** Azure Linux uses `tdnf clean all` (not `rm -rf /var/lib/apt/lists/*` or `apk --no-cache`)
- **.NET services already use MCR:** `mcr.microsoft.com/dotnet/{sdk,aspnet}:10.0-alpine` — prior decision (consistent with team pattern)


## Learnings

### Azure Linux Base Images
- Azure Linux base/python:3.12 ships without shadow-utils — use numeric `USER 1001` instead of `useradd`.
- Numeric UIDs are the recommended approach for minimal container images (no dependencies, simpler security model).
- Kubernetes handles numeric UIDs without issues — no need for named users in most cases.

## 2026-05-19 — Fix useradd Build Failures in Python Dockerfiles (Post-MCR Migration)

**Status:** COMPLETED

**Task:** Turk was spawned in background mode to fix `useradd: command not found` build failures across 5 Python Dockerfiles after MCR base-image migration. Root cause: Azure Linux base/python images don't ship shadow-utils.

**Solution Implemented:**
- Replaced `RUN useradd -r -s /sbin/nologin -M appuser` + `USER appuser` with direct numeric UID (`USER 1001` or `USER 1000`)
- Numeric UIDs are the recommended best practice for minimal container images — they require no package dependencies
- Updated `.squad/skills/mcr-base-image-migration/SKILL.md` with a comprehensive "Common Gotchas" section (lines 291-325) documenting:
  - Why Azure Linux base images don't ship shadow-utils
  - When and how to use numeric UIDs (`USER 1001` standard, `USER 1000` for k8s runAsUser: 1000)
  - Why numeric UIDs are better: no dependencies, portable, Kubernetes-safe, smaller attack surface
  - File ownership guidance for when apps need writable paths

**Files Modified:**
1. `src/chatbot-service/Dockerfile` → `USER 1001`
2. `src/budget-service/Dockerfile` → `USER 1001`
3. `src/ai-service/Dockerfile` → `USER 1001`
4. `src/account-opening-service/Dockerfile` → `USER 1001`
5. `src/ai-service/Dockerfile.eval-debug` → `USER 1000`
6. `.squad/skills/mcr-base-image-migration/SKILL.md` — added "Common Gotchas" section

**Decision Record:** Merged `.squad/decisions/inbox/turk-mcr-base-image-migration.md` into `.squad/decisions.md`. Full rationale, risks, mitigations, and rollback plan documented.

**Verification:** Deferred to ACR build (Docker/Podman unavailable locally). All MCR images pre-verified via API. No breaking changes expected.

**Learnings:**
- Numeric UIDs are the minimal-image best practice — Microsoft recommends this pattern for containers with no shell access
- Azure Linux's design philosophy: exclude user-management tools, encourage immutable image semantics
- When running on Kubernetes: match `runAsUser` in deployment manifests (e.g., if deployment has `runAsUser: 1000`, use `USER 1000` in Dockerfile)
- Microsoft Build of Go enables GOEXPERIMENT=systemcrypto by default (requires CGO_ENABLED=1). For static binaries targeting distroless runtimes, use GOEXPERIMENT=ms_nocgo_opensslcrypto with CGO_ENABLED=0 to keep openssl crypto backend without cgo.

## 2026-05-19 — event-processor Build Failure: Microsoft Build of Go CGO Requirement

**Status:** COMPLETED

**Task:** Spawned in background mode to fix build failure in `src/event-processor/Dockerfile` caused by Microsoft Build of Go's `GOEXPERIMENT=systemcrypto` requiring `CGO_ENABLED=1`.

**Root Cause:**
- Microsoft Build of Go (mcr.microsoft.com/oss/go/microsoft/golang) enables `GOEXPERIMENT=systemcrypto` by default for FIPS/openssl integration
- This experiment requires `CGO_ENABLED=1` to link against system openssl
- Conflicts with static binary requirement for distroless runtime (mcr.microsoft.com/azurelinux/distroless/base:3.0)

**Solution Implemented:**
- Added `GOEXPERIMENT=ms_nocgo_opensslcrypto` to `src/event-processor/Dockerfile` line 14
- Keeps `CGO_ENABLED=0` for static binary compilation
- Uses openssl crypto backend without cgo dependency
- Preserves FIPS-friendly crypto while maintaining distroless compatibility

**File Modified:**
- `src/event-processor/Dockerfile` line 14 — added environment variable

**Verification:** Docker verification skipped (daemon not running in sandbox). MCR images pre-verified via API.

**Decision Record:** No new decision — implementation of existing MCR base-image migration strategy. Gotcha documented in `.squad/skills/mcr-base-image-migration/SKILL.md` lines 293-321.

## 2026-06-05 — Fix Docker Python Exec Error: MCR Azure Linux Missing Bare `python` Symlink

**Status:** COMPLETED

**Task:** Brian ran `task local:run` and got `exec: "python": executable file not found in $PATH` error. All Python services and account-opening-worker failing to start after MCR Azure Linux migration (commit 59b4342).

**Root Cause Verified:**
- MCR `azurelinux/base/python:3.12` ships with `/usr/bin/python3` and `/usr/bin/python3.12`, but NO bare `/usr/bin/python` symlink
- uvicorn console-script shebang (generated by pip) expects `#!/usr/bin/python` in PATH
- docker-compose.yml `account-opening-worker` explicitly invokes `command: ["python", "-m", "app.worker"]`
- Both break with "executable file not found" error

**Solution Implemented:**
- Added `RUN ln -sf /usr/bin/python3 /usr/bin/python` to all 4 Python service Dockerfiles AFTER pip install, BEFORE `USER 1001`
- Symlink created in root-owned `/usr/bin/` (writable before switching to non-root user)
- Same Dockerfiles used in AKS — symlink is safe and transparent for K8s deployments

**Files Modified:**
1. `src/ai-service/Dockerfile` — line 9 (after pip install, before EXPOSE)
2. `src/account-opening-service/Dockerfile` — line 9
3. `src/budget-service/Dockerfile` — line 9
4. `src/chatbot-service/Dockerfile` — line 9

**Verification:**
- Built test image: `docker build -t banking-ai-service:test src/ai-service`
- Confirmed symlink works: `python --version` → Python 3.12.9, `uvicorn --version` → uvicorn 0.32.1
- Started stack: `docker compose up -d redis ai-service account-opening-worker budget-service chatbot-service`
- All containers started successfully — NO "exec: python: not found" errors in logs
- Worker running `python -m app.worker` confirmed operational (logs show config errors from missing Azure env, not exec failures)

**Learnings:**
- **MCR Azure Linux Python images do NOT provide a bare `python` executable** — only `python3` and `python3.12`
- This breaks pip-installed console scripts (uvicorn, pytest, etc.) whose shebangs expect `#!/usr/bin/python`
- **Standard fix pattern:** Add `RUN ln -sf /usr/bin/python3 /usr/bin/python` after dependencies are installed, before dropping to non-root user
- Symlink in `/usr/bin/` (not `/usr/local/bin/`) aligns with where python3 actually lives
- This is a one-time fix — once symlink is in the image layer, all subsequent layers (including USER switch and CMD) have bare `python` available

**Decision Record:** `.squad/decisions/inbox/turk-python-symlink-fix.md`

**Skill Extraction:** Updated `.squad/skills/mcr-base-image-migration/SKILL.md` with "Python Symlink" gotcha section.

## 2026-06-05: Fixed UI App Port Mismatch from Stale Docker Image

**Problem:** `curl http://localhost:3000` → connection reset. The banking-ui-app container was "Up" but not serving HTTP requests.

**Root Cause:** 
1. `task local:run` ran `docker compose up -d` WITHOUT `--build`, reusing a 4-week-old cached Alpine nginx image (listening on port 80) instead of the current MCR Azure Linux nginx Dockerfile (listening on port 8080).
2. docker-compose.yml maps host 3000 → container 8080, but stale container listened on 80 → connection reset.
3. React build failed with missing CSS module type declarations (`TS2882`).
4. Azure Linux nginx has different directory structure - no `/var/cache/nginx`, and `/var/log/nginx/` not writable by nginx user.

**Solution:**
1. Added `src/ui-app/src/custom.d.ts` with CSS module type declarations to fix TypeScript build.
2. Fixed `src/ui-app/Dockerfile` - removed chown of non-existent directories (`/var/cache/nginx`, `/var/log/nginx`).
3. Fixed `src/ui-app/nginx.conf` - changed `error_log stderr;` and `access_log off;` to avoid permission errors.
4. Rebuilt and redeployed: `docker compose build ui-app && docker compose up -d ui-app` → HTTP 200 ✅
5. **Durable fix:** Updated `tasks/Taskfile.local.yml` `run:` task to use `--build` flag so stale images never silently break the stack again.

**Learnings:**
- **Always rebuild after base image migration** - stale cached images can silently serve wrong configs even when Dockerfiles are correct.
- **Azure Linux nginx log paths** - use `error_log stderr;` and `access_log off;` when running as USER nginx.
- **Azure Linux nginx directories** - no `/var/cache/nginx`, only `/var/cache/ldconfig`.
- **Add `--build` to dev tasks** - prevents stale image issues during active development or migrations.

**Files Changed:**
- `src/ui-app/src/custom.d.ts` (new)
- `src/ui-app/Dockerfile`
- `src/ui-app/nginx.conf`
- `tasks/Taskfile.local.yml`

**Documentation:**
- Created `.squad/decisions/inbox/turk-uiapp-port-rebuild.md`
- Updated `.squad/skills/mcr-base-image-migration/SKILL.md` with nginx log permissions and stale image prevention



## Previous Session: 2026-05-12 — Build Break Fix

**Summary:** Commit 243457f (#125) used internal `CosmosSystemTextJsonSerializer` type, causing CS0122 build failures across all 5 .NET services (user-service, account-service, transaction-service, transfer-service, prompt-eval-service).

**Key Learning:** The public API for camelCase serialization pinning is `CosmosClientOptions.SerializerOptions = new CosmosSerializationOptions { PropertyNamingPolicy = CosmosPropertyNamingPolicy.CamelCase, IgnoreNullValues = true }`. Never use internal types. Decision documented in `.squad/decisions/turk-serializer-public-api.md` and skill updated with DO NOT USE warning.


## 2026-06-05 — Local API Gateway DNS Search Leak Fix

**Problem:** Local same-origin `/api/*` calls through docker-compose returned 404/502 even though direct container-to-container backend calls worked.

**Solution:** Kept Azure/AKS untouched, restored the image-baked `src/ui-app/nginx.conf`, mounted a local-only UI nginx override in docker-compose, and set `dns_search: ["."]` on both `gateway` and `ui-app` so Docker containers do not inherit host search domains.

## Learnings
- Docker Compose containers can inherit host DNS search domains; host `search denicolafamily.com` plus Docker `options ndots:0` can make nginx `resolver` + variable `proxy_pass` resolve a short service name like `user-service` as an external wildcard host, causing misleading backend 404s.
- Fix the leak locally with `dns_search: ["."]`; if nginx still cannot safely resolve dynamic upstreams, use startup-resolved static upstreams only for services guaranteed to be running.
- AKS-safe local proxy pattern: never edit image-baked `src/ui-app/nginx.conf` for local `/api/*` proxying; mount a local-only override such as `infrastructure/local/ui-app.nginx.conf` from docker-compose while Azure/AKS continues using Istio ingress routing.

## 2026-06-10 — Foundry AI Search Outbound Rule Fix (Infra)

**Problem:** `terraform apply` failed with HTTP 400: "already an outbound rule to the same destination" when provisioning AI Search backing-service connection in Foundry Managed VNet.

**Root Cause (Danny investigation):** Azure AI Foundry CognitiveSearch connections **auto-create** managed-VNet outbound rules. Explicit rule duplication → conflict.

**Solution:** Removed explicit `azapi_resource.aisearch_outbound_rule` + intermediate sleep; repointed dependencies to auto-created rule via `aisearch_connection`.

**Files:** `infra/cloud/foundry-managed-vnet.tf`, `infra/cloud/ai-connections.tf`

**Pattern Discovery:** CognitiveSearch behaves differently from Storage/Cosmos — connections manage their own outbound rules automatically. Not documented in Microsoft public docs.

**Status:** terraform validate ✅; ready for apply.


## 2026-06-10 — Agent Framework 1.8.1 Upgrade (Preview SDK Pin Fix)

**Problem:** Dependabot PRs failing `preview-sdk-pin-guard` CI check because `src/ai-service/pyproject.toml` had open-ended `^1.3.0` ranges for agent-framework packages (violates exact-pin rule). Guard scans ALL pyproject.toml whenever any is touched, so one violation red-X'd every Python Dependabot PR.

**Affected Services:**
- `src/account-opening-service/pyproject.toml` — pinned at 1.7.0
- `src/ai-service/pyproject.toml` — **^1.3.0** (the culprit)
- `src/chatbot-service/pyproject.toml` — pinned at 1.7.0

**Solution:** Upgraded ALL THREE services to exact-pin `"1.8.1"` (Brian's decision — upgrade to latest stable + fix pin-guard).

**Breaking Changes Discovered:**
- **NONE!** Agent Framework 1.8.1 is backward-compatible with 1.7.0 and 1.3.0.
- All imports (`Agent`, `Message`, `FoundryAgent`, `FoundryChatClient`, `EvalItem`, `EvalResults`, `enable_instrumentation`) work without modification.
- All API patterns remain stable: `project_endpoint=`, `credential=`, `default_options={"extra_body": {"model": ...}}`, `usage_details` attributes.

**Test Results:**
- **ai-service:** 113 passed, 1 skipped (all tests pass with 1.8.1)
- **account-opening-service:** 150 passed (all tests pass with 1.8.1)
- **chatbot-service:** 27 passed (all tests pass with 1.8.1)
- **Pin-guard check:** ✅ PASSES — no violations found after upgrade

**Files Modified:**
1. `src/account-opening-service/pyproject.toml` — `1.7.0` → `"1.8.1"`
2. `src/ai-service/pyproject.toml` — `"^1.3.0"` → `"1.8.1"` (removed caret)
3. `src/chatbot-service/pyproject.toml` — `1.7.0` → `"1.8.1"`

**Verification:**
```bash
# Pin-guard check (must return NOTHING)
grep -nHE '^agent-framework[a-z-]*[[:space:]]*=[[:space:]]*"(\*|[\^~>].*|>=.*)"' src/*/pyproject.toml
# Result: no output ✅

# Service-by-service testing with 1.8.1 installed in isolated venvs
# ai-service: python -m pytest tests/ -q → 113 passed
# account-opening-service: python -m pytest tests/ -q → 150 passed
# chatbot-service: python -m pytest tests/ -q → 27 passed
```

**Key Learnings:**
- **Agent Framework 1.7.0 → 1.8.1 is a clean upgrade** — no breaking API changes, all existing code works as-is.
- **Preview SDK exact-pin discipline works** — upgrading from open-range `^1.3.0` to exact `"1.8.1"` prevents future drift without requiring code changes.
- **Version-matched constraint still holds** — `agent-framework-core` and `agent-framework-foundry` MUST stay on the same version (all three services now at 1.8.1).
- **Pin-guard enforcement is effective** — scanning all pyproject.toml on every Python Dependabot PR catches violations early.

**Documentation:**
- Created `.squad/decisions/inbox/turk-af-181-upgrade.md` (upgrade + API stability summary)
- No skill extraction needed (clean upgrade with no gotchas)

### 2026-06-18 — Dependabot Backend Dependency Resolution (10 PRs)

**Task:** Resolve 10 Dependabot PRs for Go, .NET, and Python services with REAL adoption validation (build/test with new versions, not just version guards).

**PRs Processed:**

1. **PR #212 (Go)** — go-redis v9.20.0 → v9.20.1 in event-processor
   - ✅ PASS: `go get`, `go build`, `go vet`, `go test` all clean
   - No code changes needed

2. **PR #217 (.NET)** — Central package bumps in Directory.Packages.props
   - Microsoft.AspNetCore.Authentication.JwtBearer 10.0.8 → 10.0.9
   - OpenTelemetry.Extensions.Hosting 1.15.3 → 1.16.0
   - OpenTelemetry.Exporter.OpenTelemetryProtocol 1.15.3 → 1.16.0
   - ✅ PASS: All 5 services (user, account, transaction, transfer, prompt-eval) build clean
   - ✅ PASS: Test suites pass (user-service.Tests: 38 passed, account-service.Tests: 29 passed)
   - **Issue:** OTel 1.16.0 not in local NuGet cache initially; `--force-evaluate` resolved
   - No code changes needed (clean upgrade)

3. **PRs #213, #214, #218, #219 (Python FastAPI)** — FastAPI cap bumps to allow 0.137.x
   - ai-service: `>=0.115,<0.137` → `>=0.115,<0.138` ✅
   - budget-service: `^0.115.0` → `>=0.115,<0.138` ✅
   - account-opening-service: `>=0.115,<0.137` → `>=0.115,<0.138` ✅
   - chatbot-service: `>=0.115,<0.137` → `>=0.115,<0.138` ✅
   - **Validated:** Each service tested with FastAPI 0.137.2 actual install and successful import
   - No breaking changes in FastAPI 0.137.x (imports and app initialization clean)

4. **PR #216 (Python pytest)** — pytest bump in budget-service
   - `^8.3.0` → `>=8.3,<10.0`
   - ✅ PASS: pytest 9.1.0 installed, 21 tests passed in 0.35s
   - No test breakage from pytest 8.x → 9.x

**Key Learnings:**
- **OpenTelemetry 1.16.0** exists in NuGet (released recently) but required cache flush (`--force-evaluate`) for fresh resolution
- **FastAPI 0.137.x** is a clean upgrade path from 0.115+; no API breakage observed in our services
- **pytest 9.x** backward compatible with 8.x tests (no hook/marker breakage in budget-service suite)
- **Validation Workflow:** For Python, `uv venv --python 3.11` + `uv pip install` + `uv run python -c "import ..."` proved faster than full poetry workflows (no lockfile regen needed)

**Commands Used (for future reference):**
```bash
# Go validation
cd src/event-processor && GOTOOLCHAIN=auto go get github.com/redis/go-redis/v9@v9.20.1 && go build ./... && go vet ./... && go test ./...

# .NET validation (per service)
cd src/<service> && dotnet restore --force-evaluate && dotnet build --no-restore
cd src/<service>.Tests && dotnet test --no-restore

# Python FastAPI validation (per service)
cd src/<service> && uv venv --python 3.11 .venv && uv pip install --python .venv 'fastapi>=0.137,<0.138' && uv pip install --python .venv -e .
uv run --python .venv python -c "import fastapi; import app.main; print(f'{fastapi.__version__}')"

# Python pytest validation
uv pip install --python .venv 'pytest>=8.3,<10.0' && uv run --python .venv pytest
```

**No Code Changes Required:** All 10 PRs were clean upgrades with no breaking API changes.


## 2026-09-04 — Banker Copilot Policy Engine Design Spike

**Deliverable:** `docs/design/banker-copilot-policy-engine.md` (design only — no service code written).

### Learnings

**Foundry stack in this repo is Python-only, and that decides the language question.**
Measured, not assumed: `ai-service`, `chatbot-service`, and `account-opening-service` all pin
`agent-framework-core 1.16.0` + `agent-framework-foundry 1.10.0`; chatbot and account-opening also
carry `azure-ai-projects >= 2.1.0`. The one .NET service touching Foundry (`prompt-eval-service`,
`net10.0`) has **no** agent SDK at all — it uses `IHttpClientFactory` and raw REST. So any .NET
harness would mean hand-rolling the agent loop, which directly contradicts the "not a hand-rolled
orchestrator" directive. When a language decision comes up for agent work here, check
`pyproject.toml` vs `.csproj` first — the answer is already in the dependency files.

**The single shared JWT audience is this repo's biggest latent authorization gap.**
All services validate `ValidIssuer = user-service` and one audience value, against a symmetric
HS256 key shared via the `jwt-key` secret. There is currently **no way to express** "this principal
may call the mediator but not transfer-service" — any bearer-token holder can call any service.
Minting a *second audience* is the cheapest possible fix because every service already validates
audience; it just needs a different value. Remember this any time someone proposes a service that
must be prevented from reaching its peers.

**`serviceAccountName: banking-workload-identity` is shared by every deployment.**
Combined with `istio.io/rev: asm-1-28` on the namespace, this means the mesh is present but
*cannot distinguish workloads* — every pod presents the same identity, so per-service
`AuthorizationPolicy` is currently unwritable. Any design relying on mesh-level source-principal
rules must first split the KSA.

**Cosmos native TTL is the wrong tool when expiry has semantics.**
Native TTL deletes. If "expired" must mean "denied" — observable, auditable, visible in UI — a
delete is indistinguishable from "never existed." Correct pattern: (1) **lazy read-side expiry**
as the actual safety control (every read compares `expiresAt` before acting, so sweeper lag can
never permit a late action), (2) a sweeper as pure housekeeper emitting the state transition, and
(3) native TTL set **only on terminal documents** for retention purge, with live docs at `ttl: null`
so a stalled sweeper can never silently delete pending work. Never let a background job be both a
housekeeper and a security control.

**Audit stream schema divergence found (worth a separate ticket).**
The Go `event-processor` reads `banking-events` and unmarshals `message.Values["payload"]` (a single
stream field holding the whole `{eventType,timestamp,data}` envelope). All .NET `RedisEventPublisher`
classes match. But `account-opening-service/app/events.py` publishes **flat** fields
(`eventType`/`applicationId`/`timestamp`/`data`) to a **different** stream (`account-opening-events`).
Anything new that publishes in the account-opening style to `banking-events` would be silently
invisible to the audit consumer. Always copy the .NET `payload`-envelope form for audit events.

**Monotonicity is provable if you make downgrade unrepresentable.**
Rather than reviewing policy rules for "does this lower authority?", give the rule grammar only
`raise_to` / `min_signers` / `min_seniority` and fold with `max` over a total order. Then
"escalators can only raise" is a property of the schema, not a discipline. Add code-level floors
(`signers >= 1`) *after* all config input so the worst possible misconfiguration is "too strict,"
never "no human signed."

**Money in canonical hashing: deviate from RFC 8785 deliberately.**
JCS uses ES6 double serialization, which is unsafe for currency. Canonicalize money as fixed-scale
decimal strings and reject floats outright in money positions. Also: omit `null` and absent fields
identically so `{"memo": null}` and `{}` cannot produce two different hashes.

**Validation trick used here:** the policy YAML embedded in the design doc was extracted and parsed
programmatically to confirm every `threshold("x")` reference resolves, every threshold declares an
`env` override, every `default` is a string (not a YAML float), every evidence key is defined and
used, and no `batchable` action has a non-L1 base rung. Design docs containing config examples
should be machine-checked — a spec with an inconsistent example teaches the wrong thing.

---

#### Cross-cutting findings from Banker Copilot ideation (2026-09-04)

**Finding 1: Single shared JWT audience is the repo's biggest latent authorization gap**

Today all services validate a single audience (`banking-demo`) against a shared HS256 key. This means a compromised agent holding a banker token can call `POST /api/transfers` directly, and the Banker Copilot approval ladder is pure decoration. 

Remediation: Introduce a second `banking-copilot` audience minted by user-service for harness-only authentication. This requires splitting the shared `banking-workload-identity` KSA to enable per-service Istio AuthorizationPolicy (currently impossible because KSA is shared). Identified by Turk during policy-engine spike. **Status: NOT STARTED; open question O7 to Danny for priority.**

**Finding 2: nginx configs lack `proxy_buffering off` — SSE trace streaming silently batches**

`infra/local/gateway.nginx.conf` and `ui-app.nginx.conf` have no `proxy_buffering off` on any `/api/` location. Without it, the entire SSE trace stream arrives as one lump when the run ends, silently defeating the live-harness illusion. The banker sees no events during the run, then the entire trace dumps at the end.

Remediation: Add `proxy_buffering off;` to all location blocks serving `/api/` paths carrying SSE streams. Identified by Linus during frontend-UX spike. **Status: BLOCKING; this is the single highest-risk non-frontend dependency in the epic and needs an owner now.**

## 2026-09-04 — Q1 ruling: policy version bound into the signature (amendment)

Brian ruled on Q1 and Danny overruled my §1.3 language recommendation. Both written into
`docs/design/banker-copilot-policy-engine.md`.

### Learnings

**Version a config artifact by content hash of the RESOLVED config, not the file bytes, and not
a hand-maintained semver.** This project makes every threshold env-overridable, which means a
ConfigMap edit changes behaviour with a byte-identical file on disk. A file hash reports "no
change" and is actively misleading. A semver is a field someone must remember to bump in the same
commit as the rule they changed — they will not, and the failure is silent. Hash the resolved
values. Exclude provenance fields (`effective_from`, `owner`) so redeploying an unchanged ruleset
does not manufacture a new version. Keep the human label (`policy_id`) alongside it: one identity
for correctness, one for conversation, neither load-bearing for the other.

**Deliberately make the version comparable but NOT ordered.** Equal/unequal only, no
newer/older arithmetic. Ordering invites `if current_version > signed_version:` special-case logic,
which is exactly the divergence the ruling was written to prevent. Denying yourself an operator is
a legitimate design move when the operator's existence is what tempts the wrong implementation.

**When a signature must survive config drift, split which version each check reads.** The rule that
makes the whole thing consistent, and the thing I would most expect an implementer to get backwards:
- **Hash recompute uses the version STORED on the record** — it verifies *what was signed*, a
  historical fact that cannot change.
- **Authority re-evaluation uses the CURRENT version** — it decides *whether it may still execute*,
  a present-tense judgement.
Share one input between them and every config edit invalidates everything, including comment
reflows. Signature verification is archaeology; authority is live.

**Key an invalidation decision off the re-evaluated OUTCOME, not off version inequality.** Version
inequality is the obvious implementation and it is wrong: it voids all pending work on every edit,
including cosmetic ones, and bankers learn that the system randomly rejects their work. Keying off
"does the current evaluation require more authority?" makes loosening and cosmetic churn free, and
confines blast radius to records that actually cross a newly-tightened value. Same shape as the
monotonic escalator rule — one principle over two axes, which is why no separate temporal rule
was needed.

**Blast radius should be simulatable before rollout.** Because evaluation is a pure function over
data already on the record, "what would this policy change cost?" is answerable by replay. Shipped
as a dry-run endpoint returning the exact affected set with reasons. It **warns and never blocks** —
gating a policy *tightening* behind pending work runs the incentive exactly backwards.

**Never let one mechanism be both housekeeper and safety control.** Applied for the second time in
this design (first for TTL expiry, now for policy voiding): the eager sweep on reload exists to
*notify*, the lazy check at use time is the *guarantee*. If the sweep stalls, correctness is
unaffected. This is becoming a reliable pattern for anything where a background job and a
request-path check appear to do "the same thing."

**Reconciling a doc to an overruled premise: add a mapping note, don't do 40 rewrites.** My design
said "mediator" throughout for what is now a separate .NET `authority-service`. A total,
mechanical terminology table at the top plus surgical rewrites of only the places where the old
premise was *load-bearing* (topology diagram, the network-policy hedge, the Cosmos casing warning,
which service owns the sweeper, endpoint ownership) preserved the argument's integrity and left the
overruled reasoning readable. Scattered find-and-replace would have produced sentences that no
longer parsed as arguments.

**A split-language design turns a documented hazard into an active one.** The approval store is now
written by .NET (Newtonsoft) and read by Python (`azure-cosmos`). Cosmos field paths are
case-sensitive and a mismatch returns **zero rows, not an error** — see
`.squad/skills/cosmos-casing-audit`. When a decision moves a shared store across two runtimes, a
round-trip test (write from one, read from the other) stops being optional. I had flagged the
config/serializer-drift cost when arguing against the split; the argument lost, so the mitigation is
now mine to insist on rather than mine to feel vindicated about.

**Audit the discarding of a human signature explicitly.** `ApprovalVoidedByPolicyChange` carries the
full `discardedSignatures[]` (who, which slot, when). "A machine threw away a human's approval" is
precisely the fact an incident review or regulator asks about, and it must not be reconstructible
only by inference from a superseded document.

**Resist the bulk-remediation button.** After a policy change voids N approvals, the natural product
instinct is "re-approve all." That reconstitutes blanket approval by the back door, at the moment of
maximum approval fatigue — the worst possible time to offer one click. Bulk *re-proposal* is fine;
bulk *signing* is not. Worth watching for the general shape: a cleanup affordance that quietly
undoes a control the system was built around.

---

## 2026-09-04T14:25:00Z — Applied policyVersion binding ruling to policy engine design

**Session:** Banker Copilot Round 2 orchestration

Implemented Brian's asymmetric policyVersion binding ruling into the policy-engine design document. Reconciled single-service draft with two-service split (authority-service .NET, banker-copilot-service Python). Corrected my own Q1 recommendation and documented the gap honestly.

**Key changes in `docs/design/banker-copilot-policy-engine.md`:**

1. **PolicyVersion derivation — content hash (§6.2.1).** Format: `pv1:<sha256[:16]>`. Recommended over hand-maintained semver because: (a) cannot be forgotten on edit, (b) **covers env-var overrides** (ConfigMap threshold edits are real policy changes with byte-identical YAML), (c) deliberately not ordered so nobody can write temporal special-casing.

2. **Placement in canonical preimage** — domain-separation prefix after `action_id`, not as key inside projected object. Avoids collision with literal `policyVersion` payload field. Scheme tag bumped `bcp.v1` → `bcp.v2`.

3. **Execution-time re-evaluation (§3.6)** — `authorize_execution()` pseudocode, reusing same `evaluate()` and `RUNG_ORDER` as propose-time. No `else` branch on loosened path — policy relaxation is not an event.

4. **CRITICAL IMPLEMENTATION DETAIL (§6.4):** Hash recompute uses STORED policy version; rung re-evaluation uses CURRENT version. If hash recompute used current, every edit would fail hash comparison for every pending approval, directly contradicting ruling. Signature verification is archaeology; authority is live; they cannot share an input. Documented as two-row table, cannot be skimmed past.

5. **Narrowed blast radius (§6.6)** — key off re-evaluated rung, not version inequality. Cosmetic edits and policy *loosening* void nothing. Only approvals crossing newly-tightened value affected. Keying off version inequality would nuke everything on every edit; called out twice.

6. **Operations (§6.6)** — eager sweep for notification, lazy execute-time check as correctness guarantee (same separation as expiry design). New `POST /api/copilot/policy/impact` dry-runs candidate policy and returns exactly which approvals would void and why. **Warns, never blocks.**

7. **No bulk re-sign.** Re-proposal may be bulk; signing may not. "Re-approve all 40" button reconstitutes blanket approval at moment of maximum fatigue — worst possible timing.

8. **Audit (§7.2)** — `ApprovalVoidedByPolicyChange` carries full `discardedSignatures[]`. "Machine discarded human's signature" is exactly what incident reviews ask about.

**Two-service reconciliation (O1 closed).** Added terminology-mapping note up front (mediator → `authority-service`, harness → `banker-copilot-service`) and rewrote load-bearing places: topology diagram, Layer 3 hedge, Cosmos casing warning, sweeper owner, endpoint table. Split makes §4 stronger: Layer 3 was previously hedged (one pod = one mesh identity); two pods make it genuine network partition. O7 (split shared KSA) now hard prerequisite.

**Self-correction on Q1 (critical).** Standing recommendation: symmetric ("void if rung changes"). Ruling is asymmetric, and asymmetric is right. Voiding on downward change punishes banker for policy *relaxation* and generates re-signing churn. Signature given was for strictly *more* scrutiny than now required — safe by construction. Pattern-matched to "any drift invalidates" instead of deriving from existing monotonic principle (I-4). Failure mode is reusable: **when new rule feels like its own shape, check whether existing invariant already generates it.**

**Discovered hang-togethers:**
- **O9 (new, Danny's call):** Policy-voided approvals persist as `denied` + terminalReason (my choice) or get first-class `voided` lifecycle state? Former matches how supersede-by-re-plan works; latter arguably cleaner for auditors.
- **O10 (new, Danny's call):** Tempting to wire `/policy/impact` into CI as required check, but runs against empty approval store (false confidence worse than no check). Ship endpoint for operators; defer gate.

**For Linus:** Distinct treatment for policy-voided vs. expired vs. denied; banker-facing copy *"approval policy changed while pending — now requires supervisor co-signature (L1 → L2)"* with threshold and env key; post-reload digest; provenance on re-proposals.

**Cosmos round-trip test added (§10, item 8).** Approval store written by .NET (Newtonsoft), read by Python (`azure-cosmos`). Case-sensitive mismatch returns zero rows, not error. Round-trip test is now mandatory.

**Config keys added (§10):** `POLICY_RELOAD_MODE`, `POLICY_IMPACT_WARN_COUNT`, `POLICY_RELOAD_SWEEP_BATCH_SIZE` (no hardcoded values).

**Status:** SUCCESS. Phase 1 signature path unblocked. All Q1 questions closed. Policy engine design fully reconciled to two-service split with honest documentation of corrected reasoning.

**Orchestration log:** `.squad/orchestration-log/2026-09-04T14-25-00Z-turk.md`

---

## Verified Finding: Shared JWT audience blocks Layer 2

All 9 services validate audience `banking-demo` with one shared symmetric key (HS256 + SymmetricSecurityKey). **Every service can forge tokens, not merely verify.** Worse than initially reported "shared audience" framing. Layer 2 (broker-only claim) cannot be built until landed. → **#334**, sequenced Phase 3.

---

## Verified Finding: Event-processor audit gap

`src/event-processor/main.go:403-410` handles only "TransactionCreated" and "TransferInitiated"; other published event types silently unaudited. → **#335**.

---

## Verified Finding: Shared workload identity blocks Layer 1 isolation

One KSA (`banking-workload-identity` → `banking_services` UAMI) for all 11 pods. Layer 1 "no domain Cosmos role assignment" not achievable; tool-shape isolation degrades to ConfigMap convention. → **#336**, Phase 1 takes smallest slice (dedicated identity for `authority-service`).

## 2026-09-04 — Final rulings: lifecycle collapse, hash display, denial reasons, self-cosign (amendment)

### Learnings

**Collapsing a redundant state is cheap before the queries exist and expensive after.** `expired`
carried a distinction `terminalReason` already carried. The fix was nearly free today; once
dashboards, Cosmos queries, and UI branches are written against a state value, it is a migration.
When a state and an adjacent discriminator field encode the same fact, collapse *immediately* — and
collapse it **everywhere at once**, because a principle applied to one case and not its identical
twin is worse than not applying it: the next reader cannot tell which rule is real.

**Collapsing a state makes its semantics less visible — compensate deliberately.** "Expiry means
denied, never auto-approved" was self-evident when `expired` was its own state. Folded into
`denied` + `TTL_EXPIRED`, it becomes an invariant a reader can lose. I gave it its own call-out
box. General rule: when you remove a structure that was *carrying* a meaning, write the meaning
down louder, in the place the structure used to be.

**Watch for the discriminator that isn't a constant.** The supersede reason was
`"superseded_by:<newId>"` — an interpolated string masquerading as an enum value. It defeats the
enum, defeats indexing, and defeats aggregation. **Any "enum" value containing an id, a timestamp,
or a count is not an enum.** Split it: constant in the reason field, variable data in its own field.
Cheap to spot, and a good thing to grep for whenever someone declares an enum "closed."

**Cosmos NoSQL cannot enforce an enum, and you should say so rather than write "enforced at the
persistence layer."** No CHECK constraints, no column types, no server-side schema. What actually
works, in descending order of weight: (1) **funnel all writes through one repository type** and add
an architecture test forbidding raw container writes elsewhere — this is the layer doing the real
work; (2) a typed enum with a serializer that throws on unknown values in *both* directions;
(3) a guard query that alerts and **deliberately does not self-heal**, because a silent repair
erases the evidence of whatever wrote the bad value; (4) readers fail closed, so an unknown value
means "refuse to act," never "proceed." Being honest about what a datastore cannot do is more useful
than a reassuring sentence that will be believed.

**Collapsing states changes index shape — check it, don't assume.** `status = 'expired'` was one
predicate on a default-indexed field. `status='denied' AND terminalReason='TTL_EXPIRED' ORDER BY
terminalAt` is two predicates plus a sort, and **Cosmos will not use a composite index unless every
filter and ORDER BY path appears in it, in order.** Missing it means a cross-partition scan that is
free at demo volume and expensive in production. Any time a filter goes from one predicate to two,
re-derive the composite index rather than assuming the old one still serves.

**A collapsed state weakens the field it collapsed into.** `status='denied'` used to be one of five
meaningful buckets; it is now one large bucket that means nothing without `terminalReason`. Every
query, metric, or alert filtering on it alone is now probably a bug — blending timeouts into a
denial-rate metric makes an operational problem look like human judgement. Worth auditing for
explicitly after any state collapse, not just documenting.

**Two status-ish fields will collide; define the mapping before someone infers it.** Adding
`executed` as a lifecycle state next to an existing `execution.state` needed an explicit table. The
load-bearing call: **a failed execution does not advance the lifecycle** — signatures stay valid, a
retry needs no new human. Making failure terminal would either strand valid signatures or require a
"reopen" transition, and reopening a terminal state is the exact edge a closed enum exists to
prevent.

**Minimum-length text validation is under-specified in three ways that matter.** (1) Normalize NFC,
trim, and collapse internal whitespace *for measurement only* — otherwise `"a" + 19 spaces + "b"`
passes. (2) Measure **grapheme clusters**, not bytes or UTF-16 code units, or a reason written in
Japanese or Arabic needs three times the substance and an emoji counts as five characters. (3) Add a
**repeated-unit check** — length plus distinct-character rules are both satisfied by
`asdfasdfasdfasdfasdf`, and the repetition check is the rule that actually stops keyboard mashing.
And say the limit out loud: validation stops *lazy* input, never *determined* garbage. A fluent
fabricated sentence passes every rule. If the data needs to be trustworthy rather than non-empty,
that is a sampling/review problem, and someone will otherwise assume the data is clean because the
endpoint has rules.

**"MFA proves who, not how many."** The cleanest one-line refusal I have for the recurring request
to let step-up auth substitute for a second approver. Identity assurance and multi-party review are
different controls answering different questions. The failure is total rather than local: the moment
step-up can stand in for a second human, the second rung becomes the first rung wearing a hat, for
every action — not just the one where the exception was granted. Keep enforcing it structurally
(the "different signer" constraint has no policy verb that can empty it) rather than by rule, same
as the no-lowering-verb principle.

**Retain event names when collapsing states.** `ApprovalExpired` stays, even though the state is now
`denied`. The audit stream is append-only and renaming an event type is a breaking change for
consumers. The event name records *what happened*; the reason field records *what it means*. Those
are allowed to diverge, and pretending otherwise costs a consumer migration for zero benefit.

---

## 2026-09-04: Banker Copilot Final Rulings Implementation — Four Rulings Applied to Policy Engine

**Session:** Banker Copilot epic #332 final ruling round + vocabulary reconciliation  
**Task:** Apply four final rulings (Q2, Q3, Q4, expired collapse) to policy engine design  
**Status:** COMPLETE

Applied all four final rulings to `docs/design/banker-copilot-policy-engine.md` with three important corrections to own earlier specifications.

### Canonical Vocabulary (Ratified for Implementation)

Use these names consistently in code, config, and schema:

| Concept | Canonical | Notes |
|---------|-----------|-------|
| Core entity | `approval` | Never `proposal` (noun). `proposed` status, `propose` verb only. |
| Requester identity | `requesterId` | Over `actorId`. |
| Supersede link | `supersededByApprovalId` | Holds id, points to approval. Never interpolate id in reason. |
| Terminal reasons | `PAYLOAD_SUPERSEDED`, `HUMAN_DENIED`, `POLICY_RUNG_ESCALATED`, `TTL_EXPIRED` | Closed enum. No additions without spec change. |
| Action identifier format | `<domain>.<entity>.<verb>` | E.g., `account_opening.account.create`, `transaction.flag.review`. |
| Endpoint prefixes | `/api/authority/*` or `/api/copilot/*` | One per service. |

### Four Rules Applied

**1. Lifecycle Collapse (§5.3.1, §5.4)**  
No `expired` state. `proposed → pending → signed → executed`, `denied` single terminal with four-value enum. Sweeper unchanged in mechanism (still runs), now writes `denied + TTL_EXPIRED`. Expiry still means denied, never auto-approved (explicit call-out because visibility loss when state collapsed).

**2. Q2: payloadHash Permanent (§8.5.1)**  
Every approval representation: list, detail, sign response, SSE events. Marked non-removable. Server computes `payloadHashShort` for safe truncation (UI never truncates security value).

**3. Q3: Denial Reason Required (§8.7.1)**  
Applied to `HUMAN_DENIED` only. Server validates in `authority-service`. Six-layer validation:
1. NFC-normalize
2. Trim whitespace
3. Collapse internal for measurement only
4. Measure in grapheme clusters (not bytes/UTF-16)
5. Repeated-unit check
6. Minimum letter count

All six config keys with env overrides (no literals):
- `DENIAL_REASON_MIN_LENGTH` (default: 20)
- `DENIAL_REASON_MAX_LENGTH`
- `DENIAL_REASON_MIN_DISTINCT_CHARS`
- `DENIAL_REASON_MAX_REPEAT_UNIT`
- `DENIAL_REASON_MIN_LETTERS`

**4. Q4: Step-up Auth Cannot Substitute (§8.6.1)**  
**NO** at L2. Banker's own second signature never suffices, MFA included. SoD means different people. Enforced structurally: `mustDifferFrom` built by evaluator, no policy verb can empty it.

### Three Things That Did Not Hang Together (All Corrected)

**(a) Supersede Reason Was Encoded in Value**  
Wrote `superseded_by:<newId>` — not a closed constant, cardinality = number of supersedes. Reason becomes thousands of one-row buckets and grouping rule silently dies. **Corrected: reason is `PAYLOAD_SUPERSEDED`; id moves to `supersededByApprovalId`.** This find is worth remembering: the requirement making a ruling safe can be defeated by a data shape that looks harmless.

**(b) "Enforce Enum at Persistence Layer" Unachievable in Cosmos**  
Cosmos is schemaless, no CHECK constraints, no server-side schema. Will store `terminalReason: "banana"`. **Corrected to four-layer application-side enforcement:**
1. C# `enum` with converter throwing on unknown (both directions)
2. Single-writer repository type (no raw `Container.ReplaceItemAsync` elsewhere); architecture test enforces
3. Guard query alerts on unknown (no self-heal; evidence preservation)
4. Readers fail closed — unknown reason = "denied and not executable" (never implicit proceed)

**(c) `executed` as Lifecycle Status Collides With `execution.state` Field**  
Failed execution does NOT move `status`. Stays `signed` with `execution.state = failed`. **Retry needs no new human signature but DOES re-enter policy re-evaluation gate (§5.3.2),** so signatures survive downstream failure but not policy escalation.

### Technical Implementations

**Cosmos Index:** Query `status='denied' AND terminalReason=? ORDER BY terminalAt` needs composite index `(status, terminalReason, terminalAt)`. Without it, cross-partition scan (cheap at demo, expensive later). `terminalAt` must be reliably populated on every terminal transition (was nullable-and-ignored).

**Config Keys Added (Both Manifests):**  
`deploy/kustomize/base/configmap.yaml` and `docker-compose.yml`:
- `DENIAL_REASON_MIN_LENGTH`
- `DENIAL_REASON_MAX_LENGTH`
- `DENIAL_REASON_MIN_DISTINCT_CHARS`
- `DENIAL_REASON_MAX_REPEAT_UNIT`
- `DENIAL_REASON_MIN_LETTERS`

**Event Names:** Retained `ApprovalExpired` even though state collapsed to `denied` (append-only stream, renaming breaks consumers). Event says what happened; reason says what it means.

### For Linus (UI Implementation)

**Requirement got stronger, not weaker.** All four terminal reasons now share `status = "denied"`, so branching on `status` alone is a bug — **the four must be visually distinct.**

Plus permanent `payloadHash` display on every approval card. When policy escalation causes a re-sign, the changed hash explains it rather than appearing arbitrary.

---


---

## Session: authority-service Phase 1 implementation (epic #332)

### Learnings

**The service exists and runs.** `src/authority-service/` builds clean (0 warnings, 0 errors) on
net10.0, 94/94 unit tests pass in `src/authority-service.UnitTests/`, and I ran the real thing
over HTTP: propose → sign → co-sign → deny, plus a 250,000 payload correctly escalating L1 → L2,
plus same-human double-sign rejected with 403, plus a short denial reason rejected with 400. The
policy loads and `/readyz` reports `pv1:92590557c5772211`.

**Fail-closed is verified, not asserted.** Pointing `POLICY_FILE_PATH` at a missing file crashes
the process at startup with an explicit message rather than starting permissive. That is the one
behaviour I refused to take on trust, because a policy engine that starts without a policy is
worse than no policy engine — it looks like a control.

**Two bugs the tests caught that reading would not have.**

1. `ExecuteAsync` originally rejected any approval where the requester was also a signer. That is
   correct at L2 and *wrong at L1*, where the agent proposes and the banker who requested it is
   the legitimate single approver. Separation of duties is a property of a **slot**
   (`mustDifferFrom`), not of the document. I had generalised a rule from the case that motivated
   it — the classic way a safety control becomes a bug.
2. `transaction.flag.review` had `hashFields: [transactionId, decision, note]` — **`amount` was
   not in the signed hash**, while `amount` is exactly what drives the rung. A signature would
   have bound everything except the number that decided how many humans were needed. Caught only
   because a tampering test refused to fail. Rule for the rest of Phase 2: **every field any
   escalator reads must be in `hashFields`.** I want that enforced by the loader, not by review.

**A missing hash field is now refused rather than hashed as absent.** The canonicalizer used to
walk a missing path and shrug. That makes `{}` and `{amount: 0}` produce different approvals a
signer cannot tell apart. Declared field absent → refuse the propose.

**Where the §5.3.2 split actually lives.** At execute, the payload **hash** is recomputed under
the `policyVersion` **stored on the approval** (hash fields, money fields and currency scale are
frozen onto the document at propose time), while the **rung** is re-derived under the **live**
policy. Get these backwards and every policy edit invalidates every outstanding approval as
"tampered". This is the single subtlest thing in the service and it deserves the test that
guards it in both directions.

**V4 was unreachable and the config proved it.** With `ReasonMaxRepeatUnit = 4` and
`ReasonMinDistinctChars = 5`, any string that IS a repeat of a ≤4-character unit has ≤4 distinct
characters, so V3 always fires first and the repeated-unit rule can never be observed. Raised the
repeat-unit bound to 8. A validation rule that cannot fire is not a strict rule — it is a rule
that is lying about being enforced, and only writing the test for it exposed that.

**Danny's schema arbitration cost me a refactor I earned.** I had flattened `policyVersion`,
`baseRung`, `requiredRung` and `firedEscalators` to the top level; the ratified shape nests them
under `policy`. Restored via a real `ApprovalPolicySnapshot` with `[JsonIgnore]` façade
properties, so the 137 call sites still read `approval.RequiredRung` while the wire shape matches
the contract. `ApprovalDocumentShapeTests` now pins it, including that `policyVersion` appears
**exactly once** in the serialized document. Danny is right about the mechanism: a flat namespace
is what invites the second copy.

**Cosmos path mismatches return zero rows, not errors.** Everything the composite indexes in
`infra/cloud/cosmos.tf` address — `status`, `createdAt`, `expiresAtEpoch`, `awaitingSeniority`,
`terminalReason`, `terminalAt` — stays top level, and there is a test asserting so. In a service
that gates money movement, "the supervisor's inbox is empty" and "the query is broken" must never
look the same.

**Zero hardcoded thresholds, enforced at load rather than by discipline.** Magnitude operators
(`gte`/`gt`/`lte`/`lt`/`countGte`) must name a threshold; the loader rejects the policy if one
carries a bare number. Only equality and membership may carry literals, and only non-numeric
ones. I also had to add `defaults.supervisorSeniority` and `defaults.retentionSeconds` as named
threshold references so that not even a threshold *name* is a literal in code.

**`raiseBy: 1` compounds, and that is load-bearing for the property test.** Two firing escalators
take L1 → L2 → L3, and L3 is not proposable — so a many-escalator subset produces a *refusal*,
not a decision with more signers. The monotonicity property therefore asserts rung monotonicity
unconditionally but signer monotonicity only between admissible subsets.

**The local environment lied to me for ten minutes.** `AZURE_CLIENT_ID` is set in Brian's shell,
so the dual-mode Redis/Cosmos path chose Entra ID and died on a Conditional Access policy — with
a 500 whose message was "Failed to acquire token" and no clue which dependency. Dual-mode auth
that switches on ambient env vars needs to *log which mode it chose at startup*. Filed as a
decision note; it will burn the next person on any of our services, not just this one.


---

## Session: Danny's schema arbitration applied (epic #332)

### Learnings

**Danny's two removals landed, and the mechanism behind them found three more.** He ruled out
`execution.signedUnderPolicyVersion` (a second copy of `policy.policyVersion` in the same
document) and `distinctIdentitiesRequired` (a head count that always equalled `requiredSigners`).
Applying the *rule* rather than the *instances* immediately turned up three more of the same
class that neither of us had listed:

- `signatureSlots[].boundPolicyVersion` — a per-slot copy of `policy.policyVersion`.
- `signatureSlots[].rungSatisfied` — a per-slot copy of `policy.requiredRung`.
- `target.pathParams` — the same fact as `target.resolvedPath`, in a second representation.

All three are provably-equal duplicates for the same reason as Danny's: under §5.3.2 a change to
the rung or the policy version **voids the signatures and creates a replacement approval**, so a
filled slot's values can never diverge from the document's own. They could only ever be stale.
All are gone from the document and all are still on the audit events, which are standalone flat
records that must be readable without joining back.

**`distinctIdentitiesRequired` HAD entered my code** — Danny's note assumed it was epic-only. It
was in the evaluator, the decision object, the document, the API responses and the signing quorum
check. Reporting "confirmed absent" would have been the easy answer and the wrong one. The
signing check is now `filledSlots >= requiredSigners` with separation of duties enforced entirely
by `mustDifferFrom` per slot.

**Danny's reasoning generalises and I applied it to the policy file too.** A count is satisfied
by arithmetic; naming the excluded identity is a set-membership test against a specific subject.
So the `distinctIdentities` knob is gone from the rung schema — and the loader now **rejects** a
policy that still declares it rather than ignoring it. Silently ignoring the key would let an
operator write `distinctIdentities: 1`, read it back, and believe they had turned dual control
off, when separation of duties is no longer reachable from the policy file at all. **A dead knob
that looks live is worse than no knob.**

**§5.3.1b, and the two serializer settings that would have broken it silently.** The contract test
now reduces both the design doc's canonical block and a document the service **actually wrote** to
sorted sets of dotted field paths and asserts equality. Building it exposed the Cosmos client
configuration as the real hazard:

- `PropertyNamingPolicy = CamelCase` layered a naming policy over my explicit `[JsonProperty]`
  attributes. It happens to agree today. If a property ever loses its attribute, the policy would
  quietly rename the Cosmos path instead of letting the mismatch surface.
- `IgnoreNullValues = true` **dropped every null field from the document.** `terminalReason: null`
  and no `terminalReason` at all are different things to a Cosmos predicate, and a path-set
  comparison cannot see a field that was never written.

Both are gone. There is now one explicit `JsonSerializerSettings`, used by the Cosmos serializer,
the in-memory repository and the contract test, so the document the SDK writes is the document the
test asserts. **Explicit and asserted, not inherited** — because a Cosmos path mismatch returns
zero rows rather than an error, and in a service that gates money movement "the supervisor's inbox
is empty" must never be indistinguishable from "the query is broken".

**Three of my own negative tests were mutating nothing.** They did
`File.ReadAllText(policy).Replace(x, y)` and `Replace` is a silent no-op when `x` is absent — so a
test could load an *unmutated* policy, see no exception, and report that an invariant holds when
it had never been challenged. One of them was already in that state after I edited the policy
file. Every negative policy test now goes through `TestHarness.MutatedPolicyYaml`, which **throws**
if the text is not found, and there is a test that the helper itself throws. A test that cannot
fail is worse than a missing test, because it is counted.

**`cosignerId` never existed in my code** — no field, no API parameter, no hash input, nothing in
the queue. The cross-partition query keys on `awaitingSeniority`. Danny's security argument is the
one I want to remember: a pointer keyed on the co-signer requires knowing *who* will co-sign at
proposal time, which hands the requester the ability to **choose their own reviewer** — the exact
self-dealing pattern L2 exists to prevent. Performance optimisations that need to name a person
in advance should be treated as security changes.

**Final state:** builds clean, 99/99 unit tests pass, live HTTP run re-verified after the
serializer change (L2 escalation, same-human double-sign rejected, co-sign completes, execution
gate reached). `policyVersion` moved to `pv1:47381f84ae616f46` because the resolved policy changed
— which is the version doing its job.


### Two role models, one of them wrong (2026-09-04)

Brian found a privilege escalation pair in `config/authority-policy.yaml`: `banker.claimValues`
listed `user`/`User` — the retail customer claim, seniority 0 in the ratified hierarchy — so a
customer token satisfied an L1 signature; and `admin` sat at seniority 3 with L2 co-sign rights, so
one admin identity could fill both slots of a dual-control approval.

**The lesson is not "check role lists more carefully".** Both files were internally coherent, and
Rusty's tests locking `admin` out of banking authority passed the whole time — they test his file.
I had re-derived the role model in mine. A model stated twice is a model wrong once, and nothing in
either service could see it, because the defect only exists *between* them.

What I changed my mind about: I had assumed a config file that "just names roles" is cheap
duplication. It is not — a claim-to-seniority map **is** the authorization decision, written in
data. So the loader now consumes `role-hierarchy.yaml` and refuses to start on any disagreement,
`seniority:` in the policy is a hard error rather than an ignored key, and a `claimValue` may only
be a case variant of its own role's name (which kills cross-role aliases structurally rather than
by review).

Three things I would not have predicted going in:

- **One integer could not carry two meanings.** `admin` needed L3 standing, so someone gave it a
  number; a number that beats supervisor beats supervisor *everywhere*, including the L2 co-sign
  check. Bug 2 was not a typo, it was a modelling collapse. L3 is now `outOfHarness` with
  `platformRoles`, a different concept from banking `seniority`.
- **The audit found a third copy.** An env-overridable `supervisor_seniority` threshold set the L2
  bar — dual control lowerable to peer level by setting a number, with no role file touched and no
  test failing. Derived from `cosignerRoles` now. When you go looking for one duplicate you should
  expect to find the rest; I found four more.
- **Proposing had no floor at all.** A customer could put an entry in a supervisor's queue that
  read as though a banker raised it. Fixed, but I only noticed because a test I wrote to assert
  "admin cannot propose" failed by *not* throwing. The test I expected to be redundant was the
  one that found something.

Also fixed from Livingston's pass: `RaiseBy` computed in `long` (an escalation could overflow into
a downgrade), `.IgnoreUnmatchedProperties()` removed so a misspelled escalator key is a startup
failure rather than a rule that silently does nothing, and an honest comment on `VerifyStoredHash`
saying it is a self-consistency check — the real control is that `ExecuteAsync` accepts no payload.

---

## Phase 2 — `banker-copilot-service` (epic #332, issue #332 Phase 2)

Built the harness that sits in front of the ladder I built in Phase 1: FastAPI on 8005, dual-mode
auth, fail-closed tool manifest, planner loop, SSE, `CopilotEventEnvelope`, session/run/artifact
persistence. 88 tests of mine pass. Livingston's independent project runs 212 green against it.

**The design decision I am most confident about: I made a write tool unspellable.**

I did not add a check that rejects write tools. I removed the vocabulary. The manifest schema has
no `mode`, no `actionId`, no `authority`, no `idempotencyKeyFrom` — an allowlist at every level,
so an unrecognised key is a startup failure. `method` is constrained to `{"GET"}` and
`capabilityScope` must end in `.read`. The keys someone would reach for when adding a write are
refused **by name, with the reason**, because a silently-dropped key is indistinguishable from one
that worked. This matters more than the runtime assertion: a check is a line someone can delete
during a refactor and nothing else changes. A schema that cannot express the concept is defended
by every parse.

The runtime assertion still exists, and it is itself tamper-tested — I poison a registry via
`dataclasses.replace` and assert `assert_zero_write_tools()` fires. Without that, the assertion
could quietly become a no-op and all 88 tests would still be green.

**Phase 1's V4 bug came back, in my own code, within the hour.** The `capabilityScope` check ran
*before* `_parse_target`, so on a realistic write entry the scope guard tripped first and the
**method guard could never fire**. Both guards were correct; the ordering made one unreachable. My
own tests caught it only because I had written a test per guard *in isolation* — a single test
using a realistic malformed entry would have passed on the wrong guard and told me the method
check worked. **A guard proven only by a realistic input is not proven; it is alibi'd by its
neighbour.** Test each guard with an input that trips exactly that one.

**A test that asserts an ordering is not a test that asserts a set.**
`test_shipped_manifest_registers_exactly_the_expected_tools` asserts set *equality*. A subset
check passes when someone adds a tool; a superset check passes when someone removes one. Both
directions or it is not a test. Same reasoning as Phase 1's count-vs-membership lesson, applied to
a different artifact.

**The bugs were all in seams, again. Every single one.**

- **`if False:`** was sitting where the session-ownership check belonged. Any banker could read any
  other banker's session. My own test caught it, and I had watched that test pass earlier in the
  session — so it was live for a while. The lesson is not "write the check"; it is that a guard
  degraded to a constant is invisible to review, greps as present, and reads as intentional. I now
  grep my own diff for `if False`/`if True`/`return True  #` before calling anything done.
- **The SSE `id:` field carried `event.id`, and the client resumes with `Last-Event-ID`.** Two
  cursors both meaning "where you got to", in different alphabets. A resume would have been
  uninterpretable and the client would have silently replayed from zero — rendering duplicates
  that look like the agent repeating itself. `id:` is now the seq. One cursor.
- **The stream 404'd when no run existed yet**, but Linus's client opens the stream *then*
  dispatches the turn. An ordinary race answered with an error that trips reconnect backoff, which
  then hides the opening frames of the run it attached to watch. Now it attaches and heartbeats.
- **Then my fix introduced a double-subscribe**: backlog yielded, then a second `subscribe()` ran
  unconditionally and yielded it all again. Livingston caught it (F2-6) before I did. Duplicate
  seq frames look *plausible* — that is what makes them expensive.

**Livingston's strict-xfail markers are the best cross-lane mechanism I have seen here.** He pinned
`xfail(strict=True)` to the double-subscribe finding, so the moment I fixed it his suite went
**red on three tests that now pass**. A marker that cannot outlive the defect. That is the same
shape as "reject a retired config key rather than ignore it", applied to test infrastructure.

**Duplication, avoided by asking instead of copying.** `requiredEvidence`, rungs, thresholds,
dollar amounts and the action catalogue are *not* in my manifest — the planner fetches
`GET /api/authority/policy` at runtime. Roles are not re-derived: `require_banker` consumes the
`effectiveRoles` claim and **refuses a token that lacks it** rather than re-expanding the
hierarchy. Phase 1 cost hours to a second role model; the fix is not "keep them in sync", it is
"have one". The one cross-file test I do have asserts the *seam*: evidence tool ids in
`config/authority-policy.yaml` must be a subset of registered tools. Two internally coherent files
can still disagree, and only a test that spans them can see it.

**Redaction that silently matches nothing is worse than no redaction.** My JSONPath subset accepted
`$..ssn` and quietly degraded it to a top-level field match — a rule that reads as "scrub every
ssn anywhere" and scrubs almost nothing. Unsupported expressions now raise at manifest load. Found
by a parametrised test I nearly did not write because "the supported cases all work".

**Two upstream facts worth carrying forward:** `httpx.Response.elapsed` is inaccessible under
`MockTransport` (timing moved to `time.monotonic()`), and `TestClient` never reports
`is_disconnected()`, so any SSE generator that waits unconditionally will hang the suite rather
than fail it. A hang is a worse test outcome than a failure because it carries no information;
every wait in that generator now has a bound.

**What I could not verify:** the Docker daemon is not running in this environment, so I have not
built the image. I booted the app under uvicorn instead and drove it over real HTTP — readyz
reporting `writeTools: 0`, attach-before-run, the full ordered trace, cross-banker isolation, and
`cosignerId` rejected 422 — which is better evidence of behaviour but says nothing about whether
the Dockerfile builds. Reporting it as unverified rather than assumed.

### Addendum — Rusty's env contract found two bugs my 98 tests could not

He declared the platform-side env names and partition keys rather than guessing mine. Two of my
defects were invisible to every test I own, because both only manifest against real Cosmos:

- **`sessionId` was conditional on the persisted trace frame.** His eval-replay index is
  `WHERE sessionId = @sessionId ORDER BY ts ASC`. A frame missing that path is not a query error,
  it is silently absent from the replay. Now unconditional, and `to_document()` raises without it.
- **`list_artifacts` passed the run id as the partition key** to a container partitioned by
  `/sessionId`. **Zero rows, no error** — the exact Cosmos failure mode I wrote into my own Phase 1
  lessons, and I made it anyway three weeks later. Knowing a failure mode does not protect you from
  it; only a test or a declared contract that spans the boundary does, and mine ran in-memory where
  partition keys are meaningless.

The general lesson: **in-memory test doubles erase precisely the constraints the real store
enforces.** My store fake made partition keys a no-op, so 98 green tests said nothing about the
one thing that would have failed in cloud. Where a fake removes a constraint, the constraint needs
a test of its own shape — I now assert the *document shape and key paths* directly, since that is
the part the fake cannot lie about.

Also: I declined two IAM grants he offered (Cosmos reader on `copilot-approvals`, and Redis). I do
not read either. Standing permission with no consumer is how a boundary erodes — the argument for
refusing capability is the same one the whole epic rests on.

**And a warning to whoever reads this next: the `if False:` on the session-ownership check came
back a second time after I fixed it.** Something in this workspace reverted that exact line while
other lanes were active. I re-applied it and re-verified after the suite ran. If you are working
in `app/routes/sessions.py`, grep for `if False` before you trust it — a guard degraded to a
constant greps as present, reads as intentional, and is invisible to review.

### Addendum 2 — the double erases the constraint, part two

Rusty audited my stores against his Terraform and found three real bugs. Same root cause as his
first pass, and I want it recorded plainly because I have now made this mistake twice in one day:

**`asdict()` on a snake_case dataclass is a persistence bug waiting for a query.** `Artifact`
persisted `run_id` while `list_artifacts` filtered `c.runId`. Zero rows, no error, forever.
`Session` and `Run` "worked" only because someone had hand-patched two camelCase keys on top of
the snake_case document — so those documents carried BOTH spellings of the same fact, and the
pattern stayed correct only while everyone remembered to patch each new field. Artifact is what
happens the first time someone forgets. I did not apply the suggested three-line patch; I
declared the casing once per entity and deleted `asdict()` from the persistence path, because
patching the instance would have left the mechanism intact.

**A fake that is more permissive than the real store launders partition bugs into green tests.**
My in-memory store ignored partition keys entirely, so 110 passing tests said nothing about
whether `partition_key=run_id` addressed a container partitioned by `/sessionId`. The fake now
enforces the same scoping. Where a double removes a constraint, either the double enforces it or
the constraint needs a test of a shape the double cannot fake — I did both: document-shape
assertions, and a session-scoped lookup test on the fake.

**I broke something by fixing it, an hour before he told me.** I had replaced `get_run`'s
cross-partition query with a point read on `partition_key=run_id` — correct under PK `/id`, which
is what the epic said. He had already moved the container to `/sessionId` (correctly: runs live
there too, so `/id` would give every run its own partition). My "optimisation" would have
returned nothing in cloud and everything in tests. **An optimisation that depends on a fact you
did not verify is a bug you cannot see.** I now read the Terraform, not the epic, for anything
about physical storage.

**The bug behind the bugs: the write path did not exist.** The planner emitted
`artifact.created` and never called `save_artifact`, and there was no route to read artifacts
back. All the casing and partition-key defects he found were latent behind a write that never
happened — which is also why no test of mine could have caught them. A trace event announcing a
thing that was never stored is a lie the UI repeats. Persist first, then emit.

**Environment: `app/routes/sessions.py` was silently reverted three times** during this session —
twice the ownership check went back to `if False:`, once my whole artifacts route vanished after
being applied. Surrounding edits survived each time. Lesson that generalises: when a workspace is
shared with other agents, **verify against a running process, not against the file you just
wrote**. `curl`ing `/openapi.json` is what told me the route was gone; the file read would have
told me too, but I only thought to check because the live probe 404'd. Trust the process, not the
buffer.

### Phase 2, addendum 3 — a contract that finds the bug you were not looking for

Brian asked me to extend Danny's §5.3.1b path-set contract to the harness's Cosmos containers. I was
expecting it to re-prove the two bugs Rusty had already found and I had already fixed. It found a
third, which is the entire argument for writing it.

`copilot-sessions` is indexed `(bankerId ASC, updatedAt DESC)` — "my sessions, most recently active
first", the left-hand session list. My session document had `actorId` and no `updatedAt` whatsoever.
Not a typo: a modelling gap. The platform lane had built an index for a query my model could not
answer, and nothing anywhere would have raised a hand. The pane would have rendered sessions in
arbitrary order and looked plausible.

Three things I want to carry forward.

**An orphaned index is quieter than a wrong one.** A field-path mismatch on a *filter* returns zero
rows, which at least looks odd. A mismatch on an *ORDER BY* returns the right rows in the wrong
order by full scan. Correct-looking output, wrong ordering, growing cost. There is no failure signal
at any point.

**Derive, do not restate — and I had already broken my own rule.** I had a `PARTITION_KEYS` dict in
my platform-contract tests, written the same hour I was telling myself duplication is the bug. It
was a third copy of a fact that lives in Terraform and is depended on in the store. It happened to
be right, which is exactly why it was dangerous: it would have gone on being right until the day it
was not, and it would have been the copy nobody thought to check. Deleted; the tests parse the
Terraform now, and there is one parser shared by both modules rather than two.

**Put the invariant in the store, not the call sites.** `updatedAt` is only correct if *every*
mutation advances it. As a rule at each call site it is right N times and wrong at N+1. Moved into
`save_session`, where it cannot be forgotten. The general form: if a field must be maintained on
every write, maintain it on the write path, not in the callers' heads.

Also worth recording: the fail-closed startup is not theoretical. Booting the service without the
six `DOWNSTREAM__*` URLs refused to start and named all six missing services. I hit it by accident
while live-verifying, which is the best way to find out a guard works.

### Phase 2, addendum 4 — the boundary I enforced, and the one I forgot to

Livingston found path-parameter traversal in my tool executor (F2-7). I had spent the whole phase
making it structurally impossible to register a write tool — allowlists at every level, refused keys
rejected by name, a tamper-tested assertion — and then substituted model-controlled strings into the
URL path with `str.replace()`.

His framing is the one worth keeping: **the declared path IS the capability scope; if an argument
can leave it, the scope is advisory.** I had been thinking of a tool's identity as its *method* and
its *scope string*, and treating the path as an implementation detail of where the data lives. It is
not. `/api/transactions/{id}` is a narrower permission than `/api/*`, and the only thing expressing
that narrowing was a template hole with nothing guarding it.

**Guard the reach, not just the shape.** I checked what kind of thing a tool was allowed to be, and
never checked how far a call could travel once it was allowed. Both are needed; the second is the
one that is easy to forget because it does not appear in the schema.

**`pattern` is a search, not a full match.** `[A-Za-z0-9_-]+` looks like a safe id constraint and
matches `../../admin` — the substring is enough. I could have written that pattern into the manifest
myself, reviewed it, and passed it. So the loader does not read the pattern; it *proves* the pattern
by running it against a corpus of values that leave a path segment, and names the ones that get
through. Do not review a regex you can execute against hostile input instead.

**Fix at the vocabulary, not the routine.** Percent-encoding at substitution time would have closed
the hole. Requiring a `pattern` at load closes it and keeps it closed, because a sanitiser has to
remember and a schema cannot forget. Third time this phase that the fail-closed loader-side version
beat the careful-code version.

**One honest note.** His F2-5 test for the invoke-time guard reaches into `registry._by_id`, an
attribute my `ToolRegistry` does not have, so it fails on `AttributeError` and can never flip no
matter what I do. I fixed the defect anyway and proved it in my own suite. A strict-xfail marker is
only as good as the assertion under it — a test that fails for the wrong reason looks identical to
one that fails for the right reason, and the marker makes it look intentional.
