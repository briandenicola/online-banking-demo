
---

# Decision: Deploy OTEL Collector with App Insights Exporter

**Author:** Basher
**Date:** 2025-07
**Status:** proposed

## Context

Brian requested an OpenTelemetry Collector deployment to centralize traces/metrics/logs and export them to Azure Application Insights. The App Insights resource and Terraform output already exist.

## Decision

1. **Single manifest file** (`deploy/kustomize/observability/otel-collector.yaml`) containing Namespace (`observability`), Service, Deployment, and ConfigMap. Separate kustomization directory since base enforces `namespace: banking-demo`.
2. **Secret-based connection string** — The collector reads `APPINSIGHTS_CONNECTION_STRING` from a K8s Secret (`appinsights-secret` in `observability` namespace). The OTEL config uses native `${env:APPINSIGHTS_CONNECTION_STRING}` substitution.
3. **Operator responsibility** — The K8s secret must be created out-of-band (e.g., via Terraform's `kubernetes_secret` resource or a CI step using the existing `application_insights_connection_string` output).
4. **Image pinned** to `otel/opentelemetry-collector-contrib:0.151.0`.
5. **OTEL endpoint re-added** to the shared configmap so all services can send telemetry to the collector.

## Alternatives Considered

- Hardcoding connection string in ConfigMap — rejected (secret material).
- Helm chart for collector — rejected (project uses Kustomize).
- Deploying in `banking-demo` namespace — rejected (separation of concerns).

## Consequences

- All services can now export OTLP telemetry to the collector.
- Operator must create `appinsights-secret` in `observability` namespace before deploying.
- Future: consider adding a `SealedSecret` or External Secrets Operator for GitOps-friendly secret management.

---

# Decision: Redis Entra ID Dual-Mode Authentication

**Author:** Basher (Backend Dev)
**Date:** 2026-07
**Status:** Proposed

## Context

Azure Managed Redis (Balanced_B0) is configured with `access_keys_authentication_enabled = false` — meaning no password-based auth. Cloud services must authenticate via Entra ID (RBAC). Local docker-compose uses plain Redis 7 with no auth.

## Decision

Use `AZURE_CLIENT_ID` presence as the dual-mode signal:
- **Cloud (AKS):** Workload identity webhook injects `AZURE_CLIENT_ID` → `DefaultAzureCredential` → Entra token auth to Redis
- **Local (docker-compose):** No `AZURE_CLIENT_ID` → connection string with optional password (plain Redis, port 6379)

No additional `REDIS__USE_ENTRA` env var needed. The workload identity mechanism already provides the signal.

## Implementation

### Go (event-processor)
- Checks `os.Getenv("AZURE_CLIENT_ID")` → `azidentity.NewDefaultAzureCredential()` → token as password
- Token refresh goroutine every 45 minutes via Redis `AUTH` command
- Fallback: `parseRedisConnectionString()` for local dev

### C# (user-service, transaction-service, transfer-service)
- Checks `Environment.GetEnvironmentVariable("AZURE_CLIENT_ID")` → `DefaultAzureCredential` + `ConfigureForAzureWithTokenCredentialAsync`
- Fallback: `ConnectionMultiplexer.Connect(configOptions)` with password from connection string

### K8s
- Services use `redis-workload-identity` service account (annotated with Redis managed identity client ID)
- Pod labels: `azure.workload.identity/use: "true"`
- Federated credential subject: `system:serviceaccount:banking-demo:redis-workload-identity`

### Terraform
- `azurerm_user_assigned_identity.redis_managed_identity` — dedicated managed identity for Redis
- `azurerm_managed_redis_database_access_policy_assignment` — Data Owner role
- `azurerm_federated_identity_credential.aks_redis_workload_identity` — links K8s SA to Azure MI

## Consequences

- No secrets to rotate for Redis in cloud (Entra tokens auto-expire, auto-refresh)
- Local dev works with zero Azure dependencies (plain Redis, no auth)
- Separate managed identity for Redis (not sharing with AI services) — proper least-privilege

---

# Decision: Redis Connection via Secrets (Not ConfigMap)

**Date:** 2026-05-07
**Author:** Basher
**Status:** Implemented

## Context
Azure Managed Redis requires TLS + auth credentials. Storing these in a ConfigMap exposed placeholders that were never replaced at deploy time, causing service crashes.

## Decision
- Enable access keys on Azure Managed Redis (simpler than Entra ID auth for a demo)
- Store the full Redis connection string in `banking-secrets` Kubernetes secret
- All services consume `REDIS__CONNECTIONSTRING` from secretKeyRef (not configmap)
- Connection string format: `host:10000,ssl=True,abortConnect=False,password=KEY`

## Rationale
- Matches existing pattern for cosmos/appinsights/jwt secrets
- Credentials never appear in plaintext configmaps
- Single env var convention (`REDIS__CONNECTIONSTRING`) across Go, .NET, and Python services
- .NET's `__` → `:` config mapping means `Redis:ConnectionString` works automatically

## Impact
- All Redis-dependent services (user, transaction, transfer, event-processor) now connect correctly
- Deploy task (`Taskfile.cloud.yml`) handles Redis secret creation automatically

---

# Decision: Transfer Service Error Handling Pattern

**Author:** Basher (Backend Dev)
**Date:** 2026-05-07
**Context:** Bug 3 — POST /api/transfers returning 500

## Decision

Service methods should **return error states** (e.g., `transfer.Status = "Failed"`) rather than throwing exceptions for business logic failures. Controllers should inspect the returned object's status and map to appropriate HTTP codes (`400` for failed transfers, `201` for success).

## Rationale

The transfer service was catching exceptions, persisting a "Failed" transfer record to Cosmos, then re-throwing — causing the controller to return a raw 500. This is the worst of both worlds: the failure is recorded but the client gets no useful response.

## Pattern

```csharp
// Service: catch, persist failure, return (don't throw)
catch (Exception ex)
{
    transfer.Status = "Failed";
    transfer.FailureReason = ex.Message;
    await _container.CreateItemAsync(transfer, ...);
    return transfer;
}

// Controller: check status, return appropriate HTTP code
if (transfer.Status == "Failed")
    return BadRequest(new { error = transfer.FailureReason, transfer });
return CreatedAtAction(..., transfer);
```

## Impact

- All .NET services should follow this pattern for operations that have explicit failure states
- Removes need for global exception handling middleware to produce meaningful error responses
- Failed records are still persisted for audit/debugging

## Additional Note

The correct ACR for this project is `bjdcsa` (`bjdcsa.azurecr.io`), not `burstingmastiff55181acr` as noted in some project docs.

---

### 2026-05-06T22:37:11Z: User directive — Secure deployment backlog
**By:** Brian (via Copilot)
**What:** Backlog item for production-grade network security:
- Private Endpoints and Private DNS zones for all Azure services
- AI Agent Service Standard tier with Capacity Host and VNet Injection
- NSG Rules for subnet-level traffic control
- **Stretch:** API Management and App Gateway in front of the cluster

**Why:** User request — captured as future work item for hardening the demo deployment beyond current public-endpoint configuration.

---

### 2026-05-06T22:39:52Z: User directive — Reference architectures for secure deployment
**By:** Brian (via Copilot)
**What:** Use these repos as guidance for the secure deployment backlog:
- **Agent Service Standard + VNet Injection:** https://github.com/briandenicola/ai-application-architectures/tree/main/infrastructure/agent-service
- **Cluster config (certs, Istio, KEDA, Prometheus):** https://github.com/briandenicola/eShopOnAKS/tree/main/cluster-config
- **APIM + App Gateway:** https://github.com/briandenicola/azure-multi-region-proof-of-concept/tree/main/infrastructure

**Why:** User request — these are Brian's existing proven patterns to follow for Private Endpoints, DNS, NSG, Agent Service Standard, and the APIM/Gateway stretch goal.

---

### 2026-05-07T17:27:44Z: User directive
**By:** Brian (via Copilot)
**What:** One issue at a time. Do not jump ahead or make assumptions. Investigate first, confirm with Brian, then fix. No parallel bug fixes — sequential, verified, one at a time.
**Why:** User request — codebase has many interrelated bugs; rushing causes cascading mistakes

---

### 2026-05-06T23:30:56Z: User directive
**By:** Brian (via Copilot)
**What:** Redis auth is dual-mode: use Entra ID/RBAC for Azure Cloud deployments, use access keys for container/local (docker-compose) deployments. Services must support both auth paths.
**Why:** User request — Azure Managed Redis supports Entra, but local Redis containers don't.

---

### 2026-05-06T23:33:24Z: User directive
**By:** Brian (via Copilot)
**What:** Add to backlog: Replace K8s secrets (`kubectl create secret`) with AKS KeyVault CSI driver (`SecretProviderClass`). Key Vault is already provisioned and the CSI driver addon is enabled on AKS — just needs wiring (secrets in KV, SecretProviderClass manifests, pod volume mounts).
**Why:** User request — secrets should come from Key Vault, not Taskfile piping. Fits naturally as part of the security hardening plan.

---

### 2026-05-07T01:46:29Z: User directive
**By:** Brian (via Copilot)
**What:** Add User Roles (Admin & User) to the backlog — implement role-based access control with at least two roles: Admin and standard User.
**Why:** User request — captured for team memory and secure deployment plan backlog.

---

### 2026-05-07T01:47:17Z: User directive
**By:** Brian (via Copilot)
**What:** Admin Role should have the ability to test multiple prompts for the various AI services and tie into Azure AI Foundry's Evals/Red teaming via the SDK to assess how their prompts are performing.
**Why:** User request — captured for team memory and backlog. Enables admins to iterate on AI prompts with built-in evaluation and safety testing through Foundry's evaluation framework.

---

### 2026-05-07T07:00:00Z: Reference — Proper RBAC with Azure Managed Redis

**By:** Brian (via Copilot)
**For:** Basher (Phase 0a Terraform cleanup)
**What:** Example Terraform showing correct pattern for Azure Managed Redis with RBAC via azapi_resource.

Key patterns to follow:
1. User Assigned Managed Identity for the workload
2. `azurerm_redis_cache` (or `azurerm_managed_redis`) for the cache resource
3. `azapi_resource` with type `Microsoft.Cache/redis/accessPolicyAssignments` for RBAC assignment
4. Properties: `accessPolicyName = "Data Contributor"`, `objectId` from identity principal, `objectIdAlias` from identity name

```hcl
resource "azurerm_user_assigned_identity" "uami" {
  name                = "redis-uami"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

# Redis resource (azurerm_managed_redis or azurerm_redis_cache)
# ...

# RBAC via azapi — this is the correct pattern since azurerm doesn't support it
resource "azapi_resource" "redis_access_policy_assignment" {
  type      = "Microsoft.Cache/redis/accessPolicyAssignments@2024-11-01"
  name      = "redis-uami-access"
  parent_id = azurerm_managed_redis.main.id

  body = {
    properties = {
      accessPolicyName = "Data Contributor"
      objectId         = azurerm_user_assigned_identity.uami.principal_id
      objectIdAlias    = azurerm_user_assigned_identity.uami.name
    }
  }
}
```

**Why:** Current `infra/cloud/main.tf` already uses this pattern (lines 333-344) but Basher should ensure it stays consistent during the Phase 0a Terraform reorganization into `redis.tf`.

---

# Decision: eShopOnAKS-Derived Backlog for Agentic Showcase

**Author:** Danny (Lead/Architect)
**Date:** 2026-05-06
**Status:** Proposed

## Context

Brian wants online-banking-demo to evolve into a showcase for agentic coding AND secure cloud-native applications. Deep analysis of briandenicola/eShopOnAKS identified 23 concrete backlog items organized as "Layer 5: Agentic Showcase & Documentation" in the secure deployment plan.

## Decision

Add Layer 5 to the secure deployment plan with the following priority categories:

### Must Have (High Impact)
1. Workshop-style documentation overhaul (prerequisites, infrastructure, build, deploy, monitoring guides)
2. Table of Contents navigation hub
3. Architecture diagrams in `.assets/`
4. DevContainer / Codespaces setup
5. Playwright E2E test suite + GitHub Actions workflow
6. Observability documentation (OTEL, Prometheus, Grafana, App Insights)

### Should Have (Medium Impact)
7. Terraform module refactoring (break monolith main.tf)
8. Cluster-config restructuring (platform vs app separation)
9. Trivy container scanning in CI
10. Chaos Engineering (Azure Chaos Studio)
11. Enhanced Taskfile (status, restart, logs, dns)
12. AKS hardening additions (image cleaner, Defender, maintenance windows)

### Agentic Showcase (Differentiator)
13. Squad documentation — how Danny/Basher/Linus/Livingston work together
14. Copilot integration guide
15. Architecture Decision Records directory
16. Developer onboarding ("clone to running in 15 minutes")

## Key Patterns to Adopt from eShopOnAKS
- Workshop-style docs: concept → steps → manual commands → example output → challenges
- Convention-based naming with Terraform outputs driving scripts
- Flux GitOps with ordered kustomizations for cluster-config
- Playwright E2E with login setup fixture
- OTEL Collector → Azure Monitor pipeline

## Patterns NOT to Adopt
- Helm charts (we use Kustomize — simpler)
- PowerShell scripts (Taskfile + bash is cross-platform)
- Manual DNS (we should automate via Azure DNS zone)

## Impact
- Full analysis: `docs/eshop-analysis.md`
- Updated plan: `docs/secure-deployment-plan.md` (Layer 5 section)

## For Team
- **Basher:** E2E tests, Trivy scanning, enhanced Taskfile commands
- **Linus:** DevContainer setup, shell aliases, Playwright test specs
- **Livingston:** E2E test implementation, chaos engineering experiments
- **Danny:** Documentation overhaul, ADRs, architecture diagrams, Terraform module planning

---

# Decision: Remove Legacy Gateway Directory

**Date:** 2025-07-16
**Author:** Danny (Lead/Architect)
**Status:** Implemented
**Requested by:** Brian

## Context

The `gateway/` directory contained an nginx reverse proxy with njs-based JWT validation (`jwt_validate.js`). This component was superseded by Istio ingress gateway, which now handles ingress routing, mTLS, and authorization policy at the mesh level.

## Decision

Remove the entire `gateway/` directory and all references to it:

- **Deleted:** `gateway/Dockerfile`, `gateway/jwt_validate.js`
- **Cleaned:** `docker-compose.yml` — removed the `gateway` service block (build, ports, env, volumes, depends_on) and the `depends_on: gateway` from `ui-app`
- **Retained:** Root-level `nginx.conf` (still used by docker-compose for local API routing)
- **No action needed:** CI/CD workflows, kustomize manifests, and Taskfile references were already clean (Taskfile.e2e.yml references Istio's `aks-istio-ingressgateway-external`, not the legacy gateway)

## Rationale

- Dead code increases maintenance burden and confuses onboarding
- JWT validation in njs was a local-only workaround; Istio `RequestAuthentication` + `AuthorizationPolicy` is the production path
- Reduces docker-compose surface area and build time

## Risks

- **Local dev without Istio:** The `ui-app` service no longer depends on a gateway. For local docker-compose usage, the root `nginx.conf` still provides routing. If JWT auth is needed locally, it must be added to individual services or a new lightweight proxy.

## Commit

`chore: remove legacy gateway — replaced by Istio ingress`

---

# Decision: KeyVault CSI Driver — Replace K8s Secrets (Backlog)

**Date:** 2026-07-15  
**Proposed by:** Danny (Lead Architect)  
**Status:** BACKLOG ITEM (Layer 1b of Secure Deployment Plan)  
**Scope:** Security hardening; zero breaking changes to applications (requires code changes but backward-compatible)

## Problem

Current secret management uses `kubectl create secret` to store credentials in Kubernetes Secrets (etcd-backed). This is less secure than Azure Key Vault because:

1. **etcd compromise risk** — If etcd is compromised, all plaintext secrets leak
2. **No central auditing** — Key Vault provides fine-grained audit logs; K8s Secrets do not
3. **No automatic rotation** — Secrets are static in etcd; Key Vault rotates on-demand
4. **Unused infrastructure** — AKS cluster already has CSI driver addon enabled (`secret_rotation_enabled = true`, 2m interval) but no services use it

Current secrets stored via kubectl:
- `cosmos-connection-string`
- `appinsights-connection-string`
- `jwt-key`
- `openai-endpoint`

## Solution: AKS KeyVault CSI Driver

**Why this approach:**

- **Already provisioned:** Key Vault exists (`infra/cloud/main.tf:360`); CSI driver addon is enabled on AKS
- **Native K8s:** SecretProviderClass is K8s-native (no external controller needed)
- **Pod identity:** Uses AKS managed identity (already configured for system components)
- **2m automatic rotation:** CSI driver rotates mounted secrets every 2 minutes (requires K8s Secret `banking-secrets` sync feature)
- **Audit trail:** Azure Key Vault audit logs all secret access
- **No breaking changes:** Applications read from mounted files instead of env vars (backward-compatible with CI/CD)

## Architecture

```
┌─────────────────────────────────────────┐
│       Azure Key Vault                   │
│  (6 secrets: cosmos, redis, jwt, etc)   │
└────────────────┬────────────────────────┘
                 │
                 │ (AKS managed identity)
                 ▼
┌─────────────────────────────────────────┐
│     AKS CSI Secrets Provider            │
│   (secret_rotation_interval = 2m)       │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│   banking-demo SecretProviderClass      │
│   (maps KV secrets → pod volume mounts) │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│       Pod Volume Mount                  │
│   /mnt/secrets/cosmos-connection-string │
│   /mnt/secrets/jwt-key                  │
│   /mnt/secrets/appinsights-connection   │
│   /mnt/secrets/openai-endpoint          │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Application Reads from /mnt/secrets/   │
│  (at startup or on-demand)              │
└─────────────────────────────────────────┘
```

## Implementation Layers

**Layer 1b (Kubernetes Hardening sub-layer):**

1. **Terraform:** Store secrets in Key Vault; grant AKS managed identity read access
2. **Kustomize:** Create SecretProviderClass manifest; update pod specs with volume mounts
3. **Application Code:** Update .NET, Python, Go services to read secrets from files (not env vars)
4. **Taskfile:** Replace `kubectl create secret` with Terraform-based secret storage

## Key Decisions

1. **Mount secrets as files (not env vars):**
   - ✅ Prevents secrets from leaking in `ps`, `env`, process memory dumps
   - ✅ Automatic rotation works naturally (file contents change every 2m, app reads fresh on next access)
   - ⚠️ Requires application code changes (read file at startup or cache)

2. **Use K8s Secret sync feature (optional):**
   - If `secretObjects` is defined in SecretProviderClass, CSI driver auto-syncs to K8s Secret `banking-secrets`
   - Allows gradual migration: some services read from files, others read from Secret (env vars)
   - Hybrid model reduces code change scope initially

3. **2-minute rotation interval:**
   - AKS CSI driver rotates mounted files every 2m (already configured)
   - Applications that cache secrets at startup will have stale secrets after 2m
   - Solution: Implement lazy-load with cache TTL < 2m, or re-read on each request

4. **No changes to CI/CD:**
   - Secrets are stored in Key Vault via Terraform, not in GitHub Actions
   - `TF_VAR_jwt_key_secret` and `TF_VAR_openai_api_key` read from GitHub Actions secrets
   - Taskfile task `deploy:secrets` handles Key Vault population

## Dependencies & Assumptions

- **Terraform:** Existing `infra/cloud/main.tf` with `azurerm_key_vault` resource (line 360)
- **AKS:** CSI driver addon enabled with `secret_rotation_enabled = true`, 2m interval
- **RBAC:** AKS managed identity has Key Vault Secrets User role (new RBAC grant)
- **Applications:** Can be updated to read from `/mnt/secrets/` (no binary changes, config only)
- **Secrets variable passing:** CI/CD (GitHub Actions) supplies `TF_VAR_jwt_key_secret` and `TF_VAR_openai_api_key`

## Implementation Steps

1. **Phase 1: Terraform + RBAC (Basher)**
   - Add 6 `azurerm_key_vault_secret` resources (cosmos, redis, appinsights, jwt, openai-endpoint, openai-api-key)
   - Add `azurerm_role_assignment` for AKS managed identity → Key Vault Secrets User
   - Add Terraform variables `jwt_key_secret` and `openai_api_key`

2. **Phase 2: Kustomize Manifests (Linus)**
   - Create `deploy/kustomize/base/secretproviderclass.yaml`
   - Update pod specs to add `volumes.csi` and `volumeMounts`
   - Create new Kustomize files or patch existing ones

3. **Phase 3: Application Code (Basher + Linus + DevOps)**
   - Update .NET services to read secrets from `/mnt/secrets/` at startup
   - Update Python services similarly
   - Update Go event-processor
   - Test locally with docker-compose mock secrets

4. **Phase 4: Taskfile & CI/CD (Basher)**
   - Add `deploy:secrets` task to `Taskfile.cloud.yml`
   - Update `deploy` task to call `deploy:secrets`
   - Remove old `kubectl create secret` commands
   - Update GitHub Actions to pass `TF_VAR_*` variables

5. **Phase 5: Verification & Documentation (Danny)**
   - Verify all secrets mounted correctly in running pods
   - Verify CSI driver rotates secrets every 2m
   - Update `docs/deployment-azure.md` with CSI driver setup instructions
   - Document cache invalidation strategy for applications

## Testing Strategy

- **Local dev:** docker-compose uses plaintext secrets in `.env` (unchanged)
- **CI:** No local secrets needed; Terraform stores in Key Vault
- **E2E tests:** Mount mock secrets via test SecretProviderClass or use docker-compose for integration tests
- **Production:** Live Key Vault integration; CSI driver provides real secret rotation

## Rollback Plan

If CSI driver fails:
1. Keep old K8s Secret `banking-secrets` (generated by `secretObjects` sync)
2. Applications can revert to reading from Secret env vars (fallback code path)
3. Terraform removes new secrets; old Taskfile commands recreate K8s Secrets
4. No downtime if fallback is implemented

## Future Enhancements

1. **Entra ID pod identity:** Instead of AKS managed identity, use workload identity federation per service
2. **Secret auto-generation:** Rotate DB passwords, API keys annually via Terraform automation
3. **Audit compliance:** Export Azure Key Vault audit logs to Log Analytics for SIEM integration
4. **Multi-region failover:** Replicate Key Vault across regions for disaster recovery

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Application startup delay waiting for CSI driver to mount secrets | Add health check with timeout; graceful fallback to K8s Secret if file not found |
| Cache invalidation — app caches secret at startup, CSI rotates after 2m, app uses stale secret | Implement cache TTL < 2m or re-read on each request (perf trade-off) |
| Code change scope across 9 services | Use hybrid model: K8s Secret sync for quick adoption, gradual code migration per service |
| Terraform variable passing in CI/CD | Use GitHub Actions secrets → TF_VAR_* env vars; document in CI/CD runbook |
| Key Vault RBAC misconfiguration | Test locally with `az keyvault secret show` before deploying; verify CSI driver logs |

## Success Criteria

- ✅ All 6 secrets stored in Key Vault (verified via `az keyvault secret list`)
- ✅ SecretProviderClass created and pods mount `/mnt/secrets/` volumes
- ✅ Applications read secrets from mounted files (verified in logs)
- ✅ CSI driver rotates secrets every 2m (verified by checking secret version history)
- ✅ No `kubectl create secret` commands in Taskfile
- ✅ All services connect to backing stores without errors
- ✅ No secrets in CI/CD logs or Git history
- ✅ Documentation updated with setup + troubleshooting steps

## References

- [AKS KeyVault CSI Provider Documentation](https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-driver)
- [AKS Secrets Best Practices](https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-driver-best-practices)
- [SecretProviderClass API](https://secrets-store-csi-driver.sigs.k8s.io/concepts#secretproviderclass)
- Current AKS cluster config: `infra/cloud/main.tf` lines 160–180 (CSI provider block)

---

# Decision: Remove gateway proxy from ui-app nginx.conf

**Date:** 2026-05-07
**Author:** Linus (Frontend Dev)
**Status:** Implemented

## Context

The ui-app nginx config contained a `location /api/` block that proxied requests to `http://gateway:80`. The gateway service was deleted when the project moved to Istio service mesh routing. The Istio VirtualService in `cluster-config/istio/gateway/default-ingress.yaml` now handles all `/api/*` routing at the mesh level, so API traffic never reaches the ui-app pod's nginx.

The stale `proxy_pass` reference caused nginx to crash on startup in Kubernetes (DNS resolution failure for non-existent `gateway` service), putting the pod into CrashLoopBackOff.

## Decision

Remove the entire `location /api/ { ... }` block and the `location @fallback_api { ... }` block from `src/ui-app/nginx.conf`. No replacement routing logic was added — if an API request somehow reaches the pod directly, nginx returns its default 404.

## What Was Removed

1. **`location /api/`** — proxy_pass to gateway:80, proxy headers, 2s connect timeout, 502→@fallback_api error page
2. **`location @fallback_api`** — 503 JSON response for when gateway was unavailable

## What Remains

- `worker_processes auto` and pid path
- `/tmp` temp paths for read-only root filesystem
- Static file serving at `/` with SPA fallback (`try_files $uri $uri/ /index.html`)

## Rationale

- Istio VirtualService owns all `/api/*` routing; nginx proxy was redundant
- The deleted gateway service caused hard crashes — removal is the correct fix
- No new proxy or routing logic needed; simpler config = fewer failure modes

---

