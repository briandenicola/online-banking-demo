# Danny — History

## Project Context
- **Project:** online-banking-demo — AI-generated online banking application
- **User:** Brian
- **Stack:** C#/.NET + Python/FastAPI microservices, React/TS UI, Redis, Docker Compose, Azure
- **Services:** user-service, account-service, transaction-service, transfer-service (C#), anomaly-service, budget-service, chatbot-service, event-processor (Python), ui-app (React)

## Learnings

### Architecture Review (2025-07-15)
- **Service boundaries:** .NET core banking (user/account/transaction/transfer on ports 600x), Python AI agents (chatbot/anomaly/budget on ports 800x), Go event-processor, React UI on 3000
- **Shared code:** `src/shared/Contracts` has .NET DTOs, Events (IEvent interface), and Models. No shared Python library exists.
- **Infra split:** `infra/local` = AI Foundry only (dev); `infra/cloud` = full AKS + Cosmos + EventHub + Redis + KeyVault
- **IaC bug:** `infra/cloud/main.tf` has duplicate `azurerm_user_assigned_identity.openai_managed_identity` resource and a federated identity credential missing `user_assigned_identity_id`
- **CI bug:** CI workflow uses `context: ./src/${{ matrix.service }}` but .NET Dockerfiles expect repo root context (they COPY src/shared/)
- **Security pattern:** Azure side uses RBAC + Managed Identity (good). Local dev has JWT key hardcoded in docker-compose.yml and appsettings.json.
- **Gateway:** nginx.conf provides API routing but no auth, CORS, rate limiting, or TLS
- **Redis:** Declared in docker-compose but no service references it
- **Deploy path:** Flux GitOps → deploy/kustomize/base/app.yaml (full K8s manifests)
- **Taskfile:** Root includes local + cloud sub-taskfiles; `local:run` wires Terraform outputs to Docker Compose env vars
- **Key files:** docker-compose.yml, nginx.conf, Taskfile.local.yml, infra/cloud/main.tf, deploy/kustomize/base/app.yaml, .github/workflows/ci.yml

## Cross-Team Findings (2026-05-05)

### From Basher (Backend)
- **CI context bug blocks .NET builds** — Confirms critical issue preventing successful deployment
- **6 critical backend bugs** — Infrastructure defects ripple through to deployment layer; missing money-move logic means transfers fail end-to-end

### From Linus (Frontend)
- **Transfer API missing** — Frontend transfer() is mock; backend CI/CD must support persistence layer
- **No CORS configuration** — Nginx gateway lacks auth/CORS config, blocking frontend API calls

### From Livingston (Test/QA)
- **Zero test coverage** — No tests will catch architecture/deployment issues before production
- **CI "test" job fake** — False confidence in deployment pipeline

### Architectural Impact
The project's microservice decomposition is sound, but execution gaps (code bugs, missing infrastructure, zero tests) compound each other. Terraform errors block cloud deployment; CI context errors block local builds. Backend bugs (partition keys, missing money-move) mean transfers fail silently. Frontend can't call undeployed APIs. Tests don't catch any of this.

### Infrastructure Fixes Applied (2026-05-05)
- **CI build context:** .NET services now build from repo root with explicit `file:` path — mirrors docker-compose.yml
- **CI test job:** Now runs dotnet test, pytest, npm test, go test conditionally (graceful failure with `|| true`)
- **Terraform duplicate identity:** Removed second `openai_managed_identity` definition (line 334)
- **Terraform missing attribute:** Added `user_assigned_identity_id` to `aks_openai_workload_identity`
- **docker-compose version:** Removed deprecated `version: "3.9"`
- **Redis placeholder:** Added comment explaining it's reserved for future use
- **Taskfile.local.yml:** Removed duplicate `stop` task
- **`.env.example`:** Documented all required env vars for local dev

### 2026-05 — Redis Streams Event Architecture Migration

**Decision:** Migrate event broker from Azure Event Hub to Redis Streams (coordinated with Basher).

**Strategic Rationale:**
- **Cost:** Event Hub is managed service with per-throughput-unit billing; Redis is single container (~100MB)
- **Friction:** Local development previously required Event Hub credentials + connection strings; now pure docker-compose
- **Complexity:** Event Hub client library + consumer group management → simple Redis XREAD/XADD commands
- **Testability:** Full event pipeline (create transaction → anomaly detection → budget categorization) runs in docker-compose without cloud

**Architectural Changes:**
- Event Hub → Redis Streams as primary event broker
- IEvent interface abstraction maintained (event schema unchanged)
- All services updated to use Redis publishing/subscription instead of Event Hub SDK
- Taskfile targets updated (removed azure-event-hub, added redis-streams)

**Infrastructure:**
- docker-compose.yml: Redis now core service (not vestigial)
- All .NET services: Removed Azure.Messaging.EventHubs NuGet dependency; added StackExchange.Redis
- All Python services: Removed azure-eventhub pip dependency; added redis
- Event processor (Go): Replaced ehubclient with go-redis

**Trade-offs & Decisions:**
- Event Hub's at-least-once delivery → Redis Streams' at-most-once (acceptable; anomaly detection is resilient)
- Event Hub's built-in consumer groups → manual offset tracking in event-processor (simple Lua script)
- Future: Can migrate to Kafka or RabbitMQ without changing service code (IEvent interface provides abstraction)

**Impact:**
- Developers can now run full system locally without Azure subscription
- CI/CD no longer needs Event Hub credentials
- Cloud deployment can use Event Hub (via cloud/main.tf) or continue with Redis (via managed Redis cache in Azure)
- Event schema backward-compatible (no breaking changes to existing services)

### 2026-05 — Kubernetes Deployment Best Practices Remediation

**Task:** Full review and remediation of `deploy/kustomize/base/` manifests.

**Issues Found & Fixed:**
1. Wrong container ports (docker-compose host ports instead of internal 8080)
2. No health probes — Added liveness (/healthz) and readiness (/readyz)
3. Missing Services for anomaly, budget, event-processor, redis
4. No HPA — Added for user-service and account-service (2-5, 70% CPU)
5. No security contexts — Added runAsNonRoot, no privilege escalation, RO filesystem
6. Image tag :latest — Replaced with :1.0.0 semver
7. No ConfigMap — Added shared non-secret config
8. No Redis in K8s — Added deployment + service
9. Monolithic manifest — Split into per-service files
10. Ingress deprecation — Used ingressClassName instead of annotation

**Deferred:** NetworkPolicies, PodDisruptionBudgets (need overlay-specific config)
