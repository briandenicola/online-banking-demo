# Decision: Remove In-Cluster Redis Pod — Use Azure Managed Redis

**Date:** 2025-07-18  
**Author:** Basher  
**Priority:** P1  
**Status:** Implemented

## Context

The project provisions Azure Managed Redis (Balanced_B0) via Terraform (`infra/cloud/main.tf:310-322`) but the Kustomize base deployment also deployed a `redis:7-alpine` pod in-cluster via `deploy/kustomize/base/redis.yaml`. The configmap hardcoded the in-cluster hostname (`redis.banking-demo.svc.cluster.local:6379`), making every cloud deployment ignore the managed Redis instance.

## Decision

1. **Deleted** `deploy/kustomize/base/redis.yaml` (the redundant in-cluster Redis pod + service)
2. **Removed** `redis.yaml` reference from `deploy/kustomize/base/kustomization.yaml`
3. **Updated** `deploy/kustomize/base/configmap.yaml` to use placeholder values for Azure Managed Redis:
   - `REDIS_HOST`: placeholder for Terraform `redis_host` output
   - `REDIS_PORT`: `10000` (Balanced tier port, not 6379)
   - `REDIS__CONNECTIONSTRING`: placeholder with `ssl=True,abortConnect=False`
4. **Updated** `docs/deployment-azure.md` to reflect Managed Redis (port 10000, Entra ID auth, correct `az` commands)
5. **Preserved** `docker-compose.yml` Redis for local development

## Auth Implications

The Terraform config sets `access_keys_authentication_enabled = false`, meaning Azure Managed Redis uses **Entra ID authentication only** (no password keys). This has implications for all services:

| Service | Client Library | Current Auth | Entra ID Support |
|---------|---------------|-------------|-----------------|
| user-service (.NET) | StackExchange.Redis | None (no password) | Needs `Microsoft.Azure.StackExchangeRedis` |
| transaction-service (.NET) | StackExchange.Redis | None | Needs `Microsoft.Azure.StackExchangeRedis` |
| transfer-service (.NET) | StackExchange.Redis | None | Needs `Microsoft.Azure.StackExchangeRedis` |
| anomaly-service (Python) | redis-py (asyncio) | None | Needs `azure-identity` token provider |
| event-processor (Go) | go-redis/v9 | None | Needs `azidentity` token credential |

**Follow-up needed (separate task):** Add Entra ID token-based auth to all Redis clients. The current code connects without authentication — this works for local dev Redis but will fail against Managed Redis with Entra ID.

## Rationale

- Eliminates redundant infrastructure (pod was never used in cloud)
- Aligns Kustomize deployment with Terraform-provisioned resources
- Azure Managed Redis provides HA, backups, and monitoring out of the box
- Balanced_B0 is right-sized for this workload

## Trade-offs

- ConfigMap now has placeholder values that **must** be replaced during deployment (via Kustomize overlay, sed, or deployment script)
- Services need code changes to support Entra ID auth (tracked as follow-up)
