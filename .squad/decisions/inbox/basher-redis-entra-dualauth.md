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
