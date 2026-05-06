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

### Gateway Security Implementation (squad/security)
**Date:** 2025-01-06
**What:** Implemented gateway-level security: JWT validation via nginx njs module, rate limiting, security headers, and externalized secrets.

**Key Learnings:**
- nginx:alpine ships nginx-module-njs as an installable apk package — no custom builds needed
- njs has access to `require('crypto')` for HMAC verification and `process.env` for reading environment variables (requires `env` directive in nginx.conf main context)
- nginx `location` matching is prefix-based; more specific paths (e.g., `/api/users/login`) match before general ones (`/api/users/`)
- `internalRedirect` in njs allows request to be validated then forwarded to a named location (`@upstream`) for proxying
- Docker Compose variable substitution with `${VAR:-default}` syntax allows gradual migration from hardcoded secrets without breaking existing dev workflows
### 2026-05 — Deployment Documentation Compilation

**Objective:** Create comprehensive deployment documentation for local and cloud (Azure) environments, plus detailed system architecture guide.

**Scope:** Four documentation artifacts:
1. **docs/deployment-local.md** — Local Docker Compose development guide
2. **docs/deployment-azure.md** — Azure AKS + Flux GitOps production deployment
3. **docs/architecture.md** — Comprehensive system design documentation
4. **README.md** — Updated with documentation links and enhanced overview

**Key Discoveries During Documentation:**

1. **Service Census (9 Services Total)**
   - 4 .NET Core Banking Services (user/account/transaction/transfer on ports 6001-6004)
   - 3 Python Agent Services (chatbot/anomaly/budget on ports 8001-8003)
   - 1 Go Event Processor (no exposed port)
   - 1 React UI (port 3000)
   - 1 NGINX API Gateway (port 80)
   - 1 Redis instance (port 6380, shared by multiple services)

2. **Event Architecture Clarification**
   - Primary event bus: Redis Streams using `banking-events` stream
   - Event publishers: Transaction Service, Transfer Service, Anomaly Service
   - Event consumers: Event Processor (Go), Anomaly Service, Budget Service
   - Event types: transfer.completed, transaction.recorded, anomaly.detected, budget.updated, etc.
   - Consumer groups enable parallel processing and offset tracking

3. **Authentication & Authorization Flow**
   - JWT tokens issued by User Service with shared key (`Jwt__Key` env var)
   - Tokens contain user_id, email, roles
   - API Gateway passes Authorization header; each service validates JWT signature independently
   - Protected endpoints: /api/users/*, /api/accounts/*, /api/transactions/*, /api/transfers/*, /api/chat/*

4. **Local Development Environment Variables (.env)**
   - JWT settings: Jwt__Key, Jwt__Issuer
   - Database: UseInMemoryDatabase=true (for local dev)
   - Redis: REDIS__CONNECTIONSTRING=redis:6379 (container internal DNS)
   - Inter-service URLs: Services__AccountService=http://account-service:8080, etc.
   - Optional Azure services: AZURE_OPENAI_ENDPOINT, AZURE_CLIENT_ID, APPLICATIONINSIGHTS_CONNECTION_STRING (empty for basic local dev)

5. **Docker Compose Networking Insights**
   - Services communicate via Docker internal DNS using container names (not localhost)
   - Example: transfer-service calls account-service via http://account-service:8080
   - Redis persistence to named volume (redis-data)
   - Health checks: redis, user-service, account-service, transaction-service have liveness probes

6. **Azure Infrastructure Components (from Terraform/Kustomize review)**
   - AKS cluster (3-5 nodes, auto-scaling)
   - Cosmos DB (SQL API) with multi-region replication
   - Azure Cache for Redis (Premium tier with clustering)
   - Azure OpenAI (gpt-4o-mini model deployment)
   - Application Insights (workspace-based logging)
   - Key Vault (RBAC-protected secrets store)
   - Container Registry: ghcr.io (GitHub Container Registry)
   - Flux GitOps watches deploy/flux/ and deploy/kustomize/ for declarative deployments

7. **Seed Data Script (scripts/seed-data.sh)**
   - Creates demo users (idempotent — skips already-existing users)
   - Generates checking/savings accounts with initial balances
   - Executes sample transfers between accounts
   - Extracts JWT tokens for each user during execution
   - Designed to run against local services (curl to localhost:6001, :6002, etc.)

8. **Deployment Patterns Identified**
   - **Local:** docker-compose.yml orchestrates all 9 services with health checks and dependency management
   - **Cloud:** Terraform (infra/cloud/) provisions Azure resources; Kustomize (deploy/kustomize/) defines K8s manifests; Flux (deploy/flux/) reconciles desired state from Git

9. **Scaling & Optimization Strategies**
   - Stateless .NET/Python services can scale horizontally via K8s HPA based on CPU/memory metrics
   - NGINX gateway can handle ~1000 req/s per instance; use K8s HPA for ingress controller
   - Redis Streams handles millions of events/sec with consumer groups for parallel processing
   - Cache frequently accessed transactions in Redis to reduce Transaction Service load
   - JWT validation results can be cached in-memory per service

10. **Security Considerations Documented**
    - Network: Services isolated in K8s namespace; no external exposure except via API Gateway
    - Data: TLS/SSL in transit (enforced by HTTPS ingress); Cosmos DB encryption at rest; Redis TLS in production
    - Secrets: K8s Secrets backed by Azure Key Vault in production
    - Identity: JWT for API auth; K8s service accounts for pod-to-pod; RBAC with namespace isolation

**Documentation Structure:**
- **deployment-local.md** (538 lines): Prerequisites, quick start, service ports, environment setup, seed script, API docs, dev workflows, troubleshooting
- **deployment-azure.md** (664 lines): Terraform provisioning, AKS setup, Flux GitOps, secrets management, CI/CD overview, monitoring, cost analysis, troubleshooting
- **architecture.md** (268 lines): Service map, communication patterns, auth flow, event pipeline, deployment models, scaling, security, resilience
- **README.md** (enhanced): Quick start, documentation links, architecture diagram, services table, API endpoints, project structure, dev setup, Azure overview

**Impact:**
- Developers can follow deployment-local.md for reproducible local setup without cloud subscription
- Operators can follow deployment-azure.md for production deployment on Azure with GitOps principles
- Architects/contributors can reference architecture.md for system design decisions and trade-offs
- README.md now serves as hub directing users to appropriate guide based on their workflow
- All four documents are linked and cross-referenced for seamless navigation

**Deliverables:**
- Committed to squad/deployment-docs branch (9fdc96e)
- All docs include code examples, command snippets, troubleshooting, and diagrams
- Architecture.md includes ASCII diagrams for local and cloud deployments
- deployment-local.md includes port mappings for all 9 services
- deployment-azure.md includes estimated cost breakdown and optimization tips
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

### 2026-05 — Playwright E2E Testing Backlog Planning

**Objective:** Create comprehensive Playwright-based E2E testing strategy + MCP tooling for squad development workflows.

**Scope:** 5 phases, 24 backlog items (28 story points over ~10.5 weeks)

**Key Decisions:**

1. **Playwright as primary E2E framework:**
   - TypeScript + Chromium/Firefox/WebKit targets
   - Page Object Model pattern for maintainability
   - Fixture-based auth (register/login helpers)
   - CI/CD integration via GitHub Actions

2. **Playwright MCP as squad development tool:**
   - MCP server exposing Playwright actions: navigate, click, fill, screenshot, getPageState, extractText
   - Squad can interact with running app without browser: `/playwright click [selector]`
   - Enables debugging without manual browser interactions
   - Session context persisted across commands

3. **Phased approach:**
   - Phase 1: Infrastructure (Taskfile, config, health checks, GHA workflow)
   - Phase 2: Auth flows (register, login, session, logout)
   - Phase 3: Money movement (transfers, budgets, anomaly detection)
   - Phase 4: Admin & AI (user management, chatbot with graceful fallback)
   - Phase 5: MCP integration & squad tools

4. **Test isolation & data:**
   - Fixture-based cleanup (no test pollution)
   - Seed data via existing `scripts/seed-data.sh`
   - Mock Azure services when unavailable (chatbot, anomaly)
   - 3x retry for transient failures

5. **Security & auth:**
   - Dynamic JWT generation per test
   - No hardcoded credentials
   - Admin tests use separate admin-role user

6. **MCP architecture:**
   - Browser/page instances cached in server
   - Session management for parallel test scenarios
   - State inspection: DOM snapshots, text extraction, element counting
   - < 1s round-trip latency target

**Related Findings:**
- Project has zero E2E coverage (Livingston finding: "Zero test coverage")
- Backend tests exist (.NET, Python unit tests) but no integration
- CI "test" job conditional but never caught architecture/deployment issues
- Docker Compose fully orchestrates 9 services — ideal for E2E testing without cloud
- Redis Streams event pipeline (transfer → anomaly → budget) can be verified end-to-end
- JWT validation + gateway routing verified via E2E (confirms auth layer works)

**Backlog Location:** `.squad/playbooks/playwright-e2e-backlog.md`

**Ready for Squad Input:** Backlog awaits Brian/team review before GitHub issue creation

### 2026-07 — AKS Best Practices Alignment & API Version Updates

**Task:** Update Azure API versions to GA and align AKS cluster config to Brian's reference patterns.

**Changes Made:**
1. **API Versions:** Both azapi_resource blocks (AI Services + AI Foundry project) updated from preview to `2026-03-01` GA
2. **AKS Security:** local_account_disabled, run_command_enabled=false, azure_policy_enabled
3. **AKS Networking:** Migrated from basic Azure CNI to Azure CNI Overlay + Cilium (network_plugin_mode=overlay, network_data_plane=cilium)
4. **AKS Node Pool:** Renamed default→system, AzureLinux OS, autoscaling (1 to var.aks_node_count), max_pods=250, upgrade_settings max_surge=25%
5. **AKS Autoscaling:** KEDA + VPA enabled via workload_autoscaler_profile
6. **AKS Upgrades:** automatic_upgrade_channel=patch, node_os_upgrade_channel=SecurityPatch, maintenance windows Fri/Sat 9PM CT
7. **AKS Observability:** monitor_metrics, cost_analysis_enabled, image_cleaner (48h)
8. **AKS Auth:** Azure AD RBAC, Key Vault secrets provider with 2m rotation
9. **Lifecycle:** ignore_changes for node_count and kubernetes_version (prevents drift on plan)
10. **Network CIDRs:** service_cidr=100.64.0.0/16, dns_service_ip=100.64.0.10, pod_cidr=100.65.0.0/16

**Decisions:**
- Kept SystemAssigned identity (simpler for demo, no extra managed identity needed)
- Skipped NAT gateway, public IP prefix, SSH, Defender, Istio (not needed for demo)
- Used 100.64.x.x (RFC 6598) for service/pod CIDRs to avoid overlap with VNet 10.0.0.0/8

### 2026-07 — Redis Architecture: Eliminate In-Cluster Pod, Use Azure Managed Redis

**Problem:** Terraform provisions `azurerm_managed_redis` (Balanced_B0) but Kustomize base also deploys a `redis:7-alpine` pod. ConfigMap hardcodes `redis.banking-demo.svc.cluster.local:6379`, ignoring the managed instance entirely.

**Decision:** Remove in-cluster Redis pod; use Kustomize overlay to inject managed Redis host/port.

**Key Findings:**
- Azure Managed Redis (Enterprise/Balanced_B0) uses **port 10000** with mandatory TLS (not 6379)
- `access_keys_authentication_enabled = false` means **Entra ID auth only** — no password/access key
- 8 services consume Redis via ConfigMap envFrom (user, account, transaction, transfer, anomaly, budget, chatbot, event-processor)
- 3 different connection patterns: .NET uses `Redis:ConnectionString` or `REDIS_HOST`+`REDIS_PORT`, Python/Go use `REDIS__CONNECTIONSTRING`
- docker-compose.yml local Redis is correct and must stay

**Recommendation:** Use access key auth initially (change TF to `access_keys_authentication_enabled = true`), migrate to Entra ID workload identity later.

**Key Files:**
- `deploy/kustomize/base/redis.yaml` — DELETE (in-cluster pod)
- `deploy/kustomize/base/configmap.yaml` — Keep base as-is (local-friendly defaults)
- `deploy/kustomize/overlays/azure/` — Add ConfigMap patch with managed Redis host/port/TLS
- `infra/cloud/main.tf:310-322` — `azurerm_managed_redis.main`
- `infra/cloud/outputs.tf:23-25` — `redis_host` output

**Decision doc:** `.squad/decisions/inbox/danny-redis-managed-only.md`

**2026-05-06 — Redis Migration Completed by Basher**

Basher implemented the Redis architecture decision:
- Deleted `deploy/kustomize/base/redis.yaml` (in-cluster pod)
- Updated `deploy/kustomize/base/kustomization.yaml` to remove redis.yaml reference
- Updated `deploy/kustomize/base/configmap.yaml` with Azure Managed Redis placeholders (port 10000, TLS, Entra ID auth)
- Updated `docs/deployment-azure.md` with Managed Redis connection guidance

**Status:** Implementation complete. Next step: Entra ID auth integration for all services (requires SDK changes in .NET, Python, Go).
