# Turk — History

## Project Context
- **Project:** online-banking-demo
- **User:** Brian
- **Stack:** C#/.NET (user-service, account-service, transaction-service, transfer-service), Python/FastAPI (ai-service, budget-service, chatbot-service), Go (event-processor), React/TypeScript (ui-app), Redis, Docker Compose, Azure AKS
- **Joined:** 2026-05-07
- **Focus:** Python service config fixes and cross-service consistency

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
