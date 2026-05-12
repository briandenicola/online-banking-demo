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
