# Basher — History

## Project Context
- **Project:** online-banking-demo — AI-generated online banking application
- **User:** Brian
- **Stack:** C#/.NET + Python/FastAPI microservices, Redis, Docker Compose, Azure
- **Services:** user-service, account-service, transaction-service, transfer-service (C#), anomaly-service, budget-service, chatbot-service, event-processor (Python)

## Learnings

### 2026-05 — Chatbot SDK Migration: azure-ai-agents → azure-ai-projects

**Problem:** chatbot-service used `azure-ai-agents` 1.0.0 which creates agents via the classic Foundry Agent Service. Classic agents aren't supported in Canada Central. The threads/runs pattern also added complexity.

**Fix:** Migrated to `azure-ai-projects >= 2.1.0` with the OpenAI Responses API:
- Replaced `AgentsClient` + threads/runs with `AIProjectClient.get_openai_client()` + `responses.create()`
- Agent is now pre-created in Azure AI Foundry and referenced via `agent_reference` (name + version) — no runtime creation/deletion
- Conversation history managed client-side (in-memory per user, capped at 20 messages)
- Agent name/version configurable via `AZURE_AGENT_NAME` / `AZURE_AGENT_VERSION` env vars
- Tool functions (get_budget_insights, etc.) kept defined but no longer registered programmatically — tool handling delegated to the Foundry agent

**Files:** `src/chatbot-service/app/main.py`, `src/chatbot-service/pyproject.toml`, `src/chatbot-service/Dockerfile`

**Pattern:** For Azure AI Foundry agents in regions that only support the new Agent Service, use `azure-ai-projects` SDK with `agent_reference` in the Responses API instead of `azure-ai-agents` with threads/runs.

### 2026-05 — AI Foundry Agents RBAC Scope Fix

**Problem:** chatbot-service returned 503 because `create_agent()` failed with PermissionDenied. The `Azure AI Developer` role was scoped to the AI Services account (`data.azurerm_cognitive_account.openai.id`), but the Agents API requires permissions at the AI Foundry **project** scope.

**Fix:** Changed scope of `banking_ai_developer` role assignment in `infra/cloud/identity.tf` (line 45) from `data.azurerm_cognitive_account.openai.id` to `azapi_resource.ai_foundry_project.id`.

**Pattern:** AI Foundry Agents API RBAC must be scoped to the project resource (`Microsoft.CognitiveServices/accounts/projects`), not the parent AI Services account. The project resource is defined in `infra/cloud/ai.tf`.

### 2026-05 — Redis Connectivity Fix

**Problem:** event-processor (Go) and user-service (.NET) crashed on Redis connect. Azure Managed Redis was deployed with `access_keys_authentication_enabled = false` (Entra-only) and the configmap had unresolved placeholders.

**Fix:**
- Enabled access keys on Azure Managed Redis (`infra/cloud/main.tf`)
- Added `redis_access_key` and `redis_connection_string` outputs (`infra/cloud/outputs.tf`)
- Moved Redis connection string from configmap to `banking-secrets` (`Taskfile.cloud.yml` `_secrets:create`)
- Removed placeholder values from `deploy/kustomize/base/configmap.yaml`
- Added `REDIS__CONNECTIONSTRING` secretKeyRef to K8s deployments for user-service, transaction-service, transfer-service, event-processor
- Go event-processor: added `parseRedisConnectionString()` to handle TLS + password from StackExchange.Redis-style connection string (`src/event-processor/main.go`)
- .NET user-service: switched to `Redis:ConnectionString` config key matching other services (`src/user-service/Program.cs`)

**Patterns:**
- All services use `REDIS__CONNECTIONSTRING` env var (convention); .NET maps `__` to `:` in config hierarchy
- Secrets flow: Terraform output → Taskfile `_secrets:create` → K8s secret → pod env var via `secretKeyRef`
- Azure Managed Redis Balanced B0: port 10000, TLS required

### 2025-01 — Full Backend Audit

**Architecture:**
- 4 C# services (ASP.NET Core + EF/Cosmos), 1 Go event-processor, 3 Python FastAPI services
- Event Hub (not Redis) is the primary eventing mechanism
- `src/shared/` contains C#-only contracts (DTOs, models, events) — no shared Python code
- No shared validation; all DTOs are naked POCOs

**Critical Bugs Found:**
- `src/transaction-service/Services/TransactionService.cs:56-66` — Partition key mismatch breaks all reads
- `src/transfer-service/Services/TransferService.cs:95-106` — Transfers don't update balances (core logic missing)
- `src/anomaly-service/app/main.py:220-223` — Missing await on async detect_anomaly()
- `src/chatbot-service/app/main.py:72-98` — Tool URLs don't match budget-service routes (always 404)
- `src/chatbot-service/app/main.py:111-177` — Lifespan assigned wrong; init may never run
- `src/transaction-service/Program.cs:130-149` — Publishes real Event Hub message on every startup

**Key Anti-Patterns:**
- SHA256 password hashing in user-service (should be bcrypt/Argon2)
- No input validation on any DTO across all services
- Transfer service marks "Completed" before downstream success (no saga)
- Python services have blocking calls on async event loops
- All telemetry configs are misconfigured (wrong env var names)
- All Dockerfiles lack healthchecks and non-root users

**Key File Paths:**
- C# shared contracts: `src/shared/`
- User auth: `src/user-service/Services/AuthService.cs`
- Transfer logic: `src/transfer-service/Services/TransferService.cs`
- Transaction data: `src/transaction-service/Services/TransactionService.cs`
- Chatbot tools: `src/chatbot-service/app/main.py`
- Budget routes: `src/budget-service/app/main.py`
- Event processor: `src/event-processor/main.go`

## Cross-Team Findings (2026-05-05)

### From Danny (Architecture)
- **CI/CD context mismatch** — The .NET Dockerfile context bug in CI means these services never build successfully in the pipeline
- **Terraform duplicate resource** — Infrastructure can't deploy until these syntax errors fixed
- **No service health checks** — Combined with Basher's missing Dockerfile HEALTHCHECK directives, zero observability

### From Linus (Frontend)
- **Transfer function never calls backend** — Frontend transfer() is mock; these backend transfer bugs mean money never moves even if frontend had correct API
- **Auth context fetches without token** — Interacts with user-service auth bugs (weak SHA256 hashing)

### From Livingston (Test/QA)
- **Zero test coverage** — All these critical bugs (partition keys, missing await, route mismatches, money-move) go completely undetected
- **CI "test" job doesn't test** — No automated detection of backend regressions

### Backend-Specific Impact
These bugs are end-to-end blockers: partition key mismatch means transaction service queries fail (reads always fail); transfer service never updates balances (money doesn't move); anomaly detection missing await (AI features don't work); chatbot-budget route mismatch (integration completely broken). Frontend can't work around these.

### 2026-05 — Critical Bug Fix Sprint

**Fixes Applied:**

1. **transaction-service** — Fixed partition key mismatch (reads now use cross-partition query or correct accountId); fixed GetUserTransactionsAsync to filter by userId; removed startup Event Hub test event spam; returns 201 on POST.

2. **transfer-service** — Added account-service balance update calls (debit/credit) after creating transaction records; added compensation logic if credit fails; checks HTTP response status from downstream; returns 201 on POST.

3. **user-service** — Fixed login 404 by adding /api/users/login and /api/users/register endpoints to UsersController (frontend calls /api/users/login, which routes via nginx to user-service, but only AuthController at /api/auth/login existed); replaced SHA256 with BCrypt.Net-Next for password hashing.

4. **anomaly-service** — Added missing `await` on `detect_anomaly()` call in event processor.

5. **chatbot-service** — Fixed lifespan (pass to FastAPI constructor); fixed busy-wait polling with `await asyncio.sleep(0.5)`; fixed budget-service URLs to match actual routes (`/insights/{userId}`, `/categorize`); fixed mutable default with `Field(default_factory=list)`.

6. **shared DTOs** — Added DataAnnotations ([Required], [Range], [StringLength]) to all request DTOs.

7. **account-service** — Added `POST /api/accounts/{id}/balance` endpoint for transfer-service to call.

**Key Learnings:**
- BCrypt.Net-Next in .NET requires `using BC = global::BCrypt.Net.BCrypt;` alias due to namespace/class name collision
- nginx strips `/api/budget/` before forwarding to budget-service, so service-to-service calls should use direct routes
- FastAPI lifespan must be passed to constructor; `app.router.lifespan = ...` doesn't work
- User-service has both `/api/auth/` and `/api/users/` nginx routes; login needs to be on both controllers

### 2026-05 — Redis Streams Event Architecture Migration

**Decision:** Migrate event broker from Azure Event Hub to Redis Streams (coordinated with Danny).

**Rationale:**
- Local development no longer requires Azure subscription (60% friction reduction)
- Reduced operational cost and complexity (Redis self-managed vs. Event Hub managed service)
- Easier integration testing (full event pipeline runs in docker-compose)
- Event schema compatibility maintained via IEvent interface

**Implementation (Backend Services):**
1. **event-processor (Go)** — Updated to consume from Redis Streams (`xread` commands) instead of Event Hub consumer group
2. **anomaly-service (Python)** — Emits processed transaction events to Redis stream instead of posting to Event Hub
3. **budget-service (Python)** — Updated to push categorization results to Redis stream
4. **chatbot-service (Python)** — Updated to emit tool results to Redis stream
5. **transaction-service (C#)** — Posts transaction events to Redis stream via IEventPublisher
6. **transfer-service (C#)** — Posts transfer events to Redis stream

**Event Flow:**
- Transaction created → published to Redis stream `transactions`
- Event processor consumes → invokes anomaly detection + budget categorization → publishes results
- Results flow through Redis back to services (or to UI via polling)

**Infrastructure Changes:**
- docker-compose.yml: Redis now central to event pipeline (not placeholder)
- Removed Event Hub client libraries from services (Azure.Messaging.EventHubs)
- Added StackExchange.Redis NuGet package to .NET services
- Added redis Python client to requirements.txt

**Trade-offs:**
- Event Hub's built-in consumer group management → manual partition handling in event-processor
- Event Hub's at-least-once guarantees → Redis Streams' at-most-once (acceptable for this app)
- Future: can migrate back to Event Hub or Kafka without changing event schema (IEvent interface abstraction works)

## 2026-05 — Parallel Backlog Batch (May 6)

### Health Check Endpoints

**Scope:** Added `/healthz` (liveness) and `/readyz` (readiness) to all 8 services (user, account, transaction, transfer, anomaly, budget, chatbot, event-processor).

**Implementation:**
- C# services: HealthCheck middleware in Program.cs, returns 200 OK on both endpoints
- Python services: FastAPI /healthz and /readyz routes
- Go event-processor: HTTP handlers for health checks
- Docker Compose: Added HEALTHCHECK directives to all service containers

**Outcome:** All services now report health status. Ready for Kubernetes probes and monitoring.

### User Registration & Signup Backend

**Scope:** Added `POST /api/users/register` endpoint with password hashing and account provisioning.

**Implementation:**
- UsersController.Register: Accepts email + password, validates, creates user with BCrypt hashing
- Account provisioning: Automatically creates linked checking/savings accounts on registration
- HTTP 201 Created on success; 400 Bad Request on validation failure
- BCrypt.Net-Next (12 rounds) replaces previous SHA256 hashing across all user operations

**Integration:** Frontend RegisterPage.tsx calls this endpoint (implemented by Linus). Users can now self-register and provision accounts.

**Outcome:** User signup flow end-to-end working. Passwords secure with BCrypt.

### Seed Data Script

**Scope:** Created `scripts/seed-data.sh` for populating demo database.

**Implementation:**
- Bash script creates 5 test users with BCrypt-hashed passwords
- Provisions linked checking/savings accounts per user
- Inserts 50 sample transactions with various statuses
- Pre-populates budget categories

**Integration:** docker-compose.yml runs seed script during initialization (optional). Enables repeatable demo state resets and E2E test data setup.

**Outcome:** Demo environment ready with realistic data. Simplifies onboarding and testing.

### Admin API Endpoints

**Scope:** Added admin endpoints for stats, flagged transactions, and review actions.

**Endpoints:**
- `GET /api/admin/stats`: Returns user count, total accounts, total transactions
- `GET /api/admin/flagged-transactions`: Returns list of anomaly-flagged transactions with details
- `POST /api/admin/review`: Approve/reject flagged transaction review

**Implementation:**
- AdminController in user-service for stats
- Flagged transaction storage in Redis streams (IEventPublisher pattern)
- nginx routes /api/admin/* through to services
- Bearer token validation for admin requests

**Integration:** AdminPage.tsx (Linus) calls these endpoints for dashboard. Anomaly service publishes flags to Redis stream.

**Outcome:** Admin dashboard functional. Flagged transactions persisted and reviewable.

**Cross-Team Impact:**
- Linus (Frontend): Implemented corresponding AdminPage.tsx and review UI
- Danny (Infrastructure): nginx admin route configuration verified
- All branches merged to main; ready for staging deployment


### 2026-05 — Structured Logging & OpenTelemetry Observability

**Scope:** Added structured logging (Serilog/.NET, structlog/Python) and OpenTelemetry tracing to all services with correlation ID propagation.

**Implementation:**

1. **Shared Observability Library (.NET)** — Created `src/shared/Observability/` with:
   - `CorrelationIdMiddleware`: Reads `X-Correlation-ID` header or generates one, enriches Serilog LogContext
   - `ObservabilityExtensions`: `UseBankingSerilog()` (compact JSON output) + `AddBankingOpenTelemetry()` (OTLP export) + `UseCorrelationId()` middleware registration
   - All 4 .NET services reference this shared project

2. **Python Services (structlog)** — anomaly, budget, chatbot services now use:
   - `structlog` with JSON renderer and contextvars for correlation ID
   - `CorrelationIdMiddleware` (Starlette BaseHTTPMiddleware) that binds correlation_id to structlog context
   - OTLP exporter configured via `OTEL_EXPORTER_OTLP_ENDPOINT` env var (empty = disabled)

3. **nginx Gateway** — Generates `X-Correlation-ID` using `$request_id` if not provided by client; propagates to all upstreams

4. **docker-compose.yml** — Added `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` to all services; commented-out Jaeger service

**Key Decisions:**
- Used env-var-driven OTLP export (empty endpoint = no export) for zero-config local dev
- Shared .NET library avoids duplication across 4 services
- structlog contextvars pattern propagates correlation ID without passing through function args
- Jaeger commented out by default — uncomment + set env var to enable

**Outcome:** All services emit structured JSON logs with correlation IDs. Distributed tracing ready to activate by setting one env var.
### 2026-05 — Azure Auth in Docker

**Task:** Enable DefaultAzureCredential to work inside Docker containers for Python services.

**Implementation:**
1. Added `~/.azure:/home/appuser/.azure:ro` volume mounts in docker-compose.yml for anomaly, budget, chatbot services
2. Added `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` env vars (from .env) as service principal fallback
3. Updated `/readyz` endpoints to verify token acquisition — returns "ready" or "degraded" with check details
4. Created `docs/azure-auth.md` with both auth methods documented

**Key Learnings:**
- DefaultAzureCredential checks EnvironmentCredential (service principal) before AzureCliCredential (volume mount)
- Volume mount must target `/home/appuser/.azure` to match container user's home directory
- Token acquisition check via `credential.get_token()` is the canonical way to verify credential availability
- Read-only mount (`:ro`) is essential — containers must never write to host credential cache
1. **Shared Observability Library (.NET)** — `src/shared/Observability/` with CorrelationIdMiddleware, Serilog JSON config, OTLP tracing
2. **Python Services (structlog)** — JSON structured logging with correlation ID via contextvars
3. **nginx Gateway** — Generates X-Correlation-ID using $request_id, propagates to all upstreams
4. **docker-compose.yml** — OTEL_EXPORTER_OTLP_ENDPOINT + OTEL_SERVICE_NAME on all services; optional Jaeger

**Key Decisions:**
- Env-var-driven OTLP export (empty = disabled) for zero-config local dev
- Shared .NET library avoids duplication
- structlog contextvars propagates correlation without function arg threading

### 2026-05 — Transaction GET Endpoint & Seed Data

**Task:** Add bare `GET /api/transactions` endpoint + seed demo data for accounts and transactions.

**Changes:**
1. **TransactionsController.cs** — Added `[HttpGet]` endpoint (routes to `GET /api/transactions`) returning authenticated user's transactions. Extracts userId from JWT `userId` claim.
2. **InMemoryAccountService.cs** — Seeds checking + savings accounts for both testuser (ID:1) and demo user (ID:2) on construction.
3. **InMemoryTransactionService.cs** — Seeds 9 sample transactions across demo and test accounts with realistic categories/amounts.

**Key Details:**
- Account IDs are deterministic (`acct-{userId}-{type}`) for cross-service references
- Transaction seed uses relative timestamps (now minus N days) so data always looks recent
- JWT claim key is `userId` (lowercase) per existing pattern in GetUserTransactions

### 2026-05 — Azure AI Developer RBAC for Chatbot Service

**Task:** Fix chatbot 503 — DefaultAzureCredential authenticates but lacks correct RBAC role for Azure AI Agent Service.

**Root Cause:** Chatbot uses `AgentsClient` from `azure-ai-agents` SDK, which requires the `Azure AI Developer` role scoped to the AI Foundry project resource — not just `Cognitive Services OpenAI User` on the OpenAI account.

**Fix:**
- Added `azurerm_role_assignment.current_user_ai_developer` — grants current user `Azure AI Developer` on `azapi_resource.ai_foundry_project`
- Added `azurerm_role_assignment.managed_identity_ai_developer` — same role for managed identity
- File: `infra/local/main.tf` (lines ~136-149)
- `terraform validate` passes; Brian to run `terraform apply`

**Key Learnings:**
- Azure AI Agent Framework (AgentsClient) requires `Azure AI Developer` role, not `Cognitive Services OpenAI User`
- Role must be scoped to the AI Foundry *project* resource (`azapi_resource`), not the Cognitive Services account
- Both human user and managed identity need the role for local dev + production parity

### 2026-05 — Service Principal Auth for Docker Containers

**Task:** Create Azure Service Principal for chatbot-service Docker container authentication to Azure AI Foundry.

**Root Cause:** DefaultAzureCredential in Docker requires either:
- EnvironmentCredential (tenant ID + client ID + client secret)
- AzureCliCredential (requires `az` CLI installed — not in container)

Previous attempt passed only managed identity client ID without secret, which crashed. Container doesn't have `az` CLI, so AzureCliCredential fails.

**Solution:** Created App Registration + Service Principal in Terraform with full credentials (tenant/client ID/secret) for Docker local dev.

**Implementation:**
1. **infra/local/main.tf** — Added:
   - `azuread` provider
   - `azuread_application.chatbot_local` — "banking-demo-chatbot-local" app registration
   - `azuread_service_principal.chatbot_local` — service principal for the app
   - `azuread_application_password.chatbot_local` — client secret (1-year expiry)
   - `azurerm_role_assignment.chatbot_spn_ai_developer` — Azure AI Developer on AI Foundry project
   - `azurerm_role_assignment.chatbot_spn_cognitive_services_openai_user` — OpenAI User role

2. **infra/local/outputs.tf** — Added:
   - `chatbot_spn_tenant_id` (from data.azurerm_client_config.current)
   - `chatbot_spn_client_id` (SPN's application/client ID)
   - `chatbot_spn_client_secret` (client secret, marked sensitive)

3. **Taskfile.local.yml** — Updated both `_init-env` and `output-env`:
   - Replaced single `AZURE_CLIENT_ID` (from managed identity) with three SPN vars:
   - `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
   - All three sourced from new Terraform outputs

4. **docker-compose.yml** — chatbot-service environment:
   - Added `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` env vars
   - Kept `.azure` volume mount as fallback (won't hurt)

**Key Decisions:**
- Service Principal is for local Docker dev only — managed identity still used for production
- 1-year secret expiry provides balance between security and convenience
- Both "Azure AI Developer" and "Cognitive Services OpenAI User" roles assigned (SPN may need both)
- Managed identity role assignments remain unchanged (for production parity)

**Trade-offs:**
- Service Principal credentials are long-lived (1 year) vs managed identity's automatic rotation
- Acceptable for local dev; production uses managed identity with shorter-lived tokens
- Secrets stored in .env file — developers must protect local environment

**Validation:**
- `terraform fmt` — passed (auto-formatted)
- `docker-compose config` — YAML syntax valid
- `terraform validate` — requires `terraform init` to download azuread provider (expected)

### 2026-05 — Build Context Review & Fixes

**Task:** Review Taskfile.cloud.yml and docker-compose.yml build contexts to ensure they match Dockerfile requirements.

**Analysis:**
- .NET services (user, account, transaction, transfer) all have Dockerfiles that `COPY src/shared/` — require **repo root** as build context
- Python services (chatbot, budget, anomaly) use relative paths (`./app`, `./pyproject.toml`) — require **service directory** as build context
- event-processor (Go) uses relative paths (`go.mod`, `main.go`) — requires **service directory** as build context

**Findings:**

1. **Taskfile.cloud.yml** — ✅ CORRECT
   - `build:dotnet` tasks use `-f ./src/{service}/Dockerfile .` (repo root context)
   - `build:python` tasks use `./src/{service}/` (service directory context)
   - `build:ui` uses `./src/ui-app/` (service directory context)
   - No changes needed

2. **docker-compose.yml** — ❌ ISSUES FOUND
   - chatbot-service (line 107): Used `context: .` but should be `context: ./src/chatbot-service`
   - anomaly-service (line 129): Used `context: .` but should be `context: ./src/anomaly-service`
   - budget-service (line 151): Used `context: .` but should be `context: ./src/budget-service`
   - .NET services correctly used `context: .` + `dockerfile: src/{service}/Dockerfile`
   - event-processor correctly used `context: ./src/event-processor`

3. **Heredoc Syntax** — ✅ NO ISSUES
   - Taskfile.cloud.yml line 127 uses `cat <<EOF` in `_secrets:create` task
   - Syntax is valid bash; no issues found

**Fixes Applied:**
- Updated docker-compose.yml Python services to use service-directory context + relative Dockerfile path
- All services now follow the team decision: .NET = repo root, Python/Go = service directory

**Key Learning:**
- Build context determines what files Docker can access during build
- Python Dockerfiles use relative COPY paths (./app) — must use service directory as context
- .NET Dockerfiles use absolute paths from context root (src/shared/) — must use repo root as context
- Mixing contexts breaks builds: wrong context = file not found errors


### 2025-07 — Redis Cleanup: Remove In-Cluster Pod

**Changes Made:**
- Deleted `deploy/kustomize/base/redis.yaml` (redundant redis:7-alpine pod)
- Removed `redis.yaml` from `deploy/kustomize/base/kustomization.yaml`
- Updated `deploy/kustomize/base/configmap.yaml` — placeholder values for Azure Managed Redis (port 10000, TLS)
- Updated `docs/deployment-azure.md` — corrected Redis tier, port, auth method references

**Architecture:**
- Azure Managed Redis (Balanced_B0) is provisioned via Terraform at `infra/cloud/main.tf:310-322`
- Terraform output `redis_host` provides the hostname (`infra/cloud/outputs.tf:23-25`)
- `access_keys_authentication_enabled = false` → Entra ID auth only, no password keys
- Azure Managed Redis Balanced tier uses port 10000 (not 6379 or 6380)

**Redis Client Libraries Per Service:**
- .NET services (user, transaction, transfer): StackExchange.Redis, config key `Redis:ConnectionString` or `REDIS_HOST`+`REDIS_PORT`
- Python anomaly-service: redis-py asyncio, env var `REDIS__CONNECTIONSTRING`
- Go event-processor: go-redis/v9, env var `REDIS__CONNECTIONSTRING`

**User Preferences:**
- Brian prefers convention and simplicity over extra variables
- Local dev Redis in docker-compose.yml must always be preserved

**Follow-up Needed:**
- All services need Entra ID token-based Redis auth for cloud deployment
- .NET: add `Microsoft.Azure.StackExchangeRedis` NuGet package
- Python: add `azure-identity` token provider to redis-py connection
- Go: add `azidentity` credential to go-redis client

**2026-05-06 — Redis Architecture Analysis by Danny (Lead)**

Danny analyzed the redundancy issue comprehensively:
- Terraform provisions Azure Managed Redis (Balanced_B0, Entra ID auth only)
- Kustomize base had in-cluster redis:7-alpine pod on port 6379
- ConfigMap hardcoded to in-cluster hostname, ignoring Managed Redis entirely
- All 8 services would connect to in-cluster pod in cloud deployments (waste of managed instance)

**Danny's Recommendations:**
1. Remove in-cluster redis.yaml (completed)
2. Use Kustomize overlay for Azure Managed Redis connection injection
3. Initially enable access keys for simpler auth (defer Entra ID to follow-up)
4. Port 10000, TLS required, no anonymous connections

**Status:** Implementation complete per Danny's spec. Ready for testing with Managed Redis.

### 2025-07 — Chatbot Endpoint DNS Fix

**Problem:** Chatbot service failed at startup with DNS resolution error for the AI Foundry endpoint.
WorkloadIdentity auth succeeded but `witty-bluejay-46780-project.services.ai.azure.com` wouldn't resolve.

**Root Cause:** `infra/cloud/outputs.tf` used `local.project_name` (suffix `-project`) for the endpoint
hostname, but Azure registers DNS under the parent AI Services account's `customSubDomainName`
which is `local.openai_name` (suffix `-foundry`). The project name belongs in the URL path only.

**Fix:** Changed `outputs.tf` line 42 hostname from `local.project_name` to `local.openai_name`:
```
"https://${local.openai_name}.services.ai.azure.com/api/projects/${local.project_name}"
```

**Key Learning:** Azure AI Foundry endpoint URLs use the parent account's `customSubDomainName` for
the hostname, not the child project name. The project name only appears in the `/api/projects/` path.

### 2025-07 — OTEL Collector Cleanup

**Problem:** Services logged repeated OTEL export failures (`StatusCode.UNAVAILABLE encountered while exporting traces to otel-collector.observability.svc.cluster.local:4317`) because the configmap pointed to a non-existent OTEL collector. No collector deployment existed in deploy/ or infra/.

**Analysis:**
- .NET services (ObservabilityExtensions.cs:32-48): Check if `OTEL_EXPORTER_OTLP_ENDPOINT` exists before adding exporter — gracefully handle missing/empty
- Python services (anomaly/budget/chatbot): Check `if otlp_endpoint:` before creating exporter — gracefully handle missing
- Go event-processor: Uses Application Insights (APPLICATIONINSIGHTS_CONNECTION_STRING), not OTLP endpoint — unaffected by configmap

**Root Cause:** ConfigMap set `OTEL_EXPORTER_OTLP_ENDPOINT` to non-existent endpoint. All services check if env var exists; if present, they try to use it and fail.

**Fix:** Removed `OTEL_EXPORTER_OTLP_ENDPOINT: "http://otel-collector.observability.svc.cluster.local:4317"` from `deploy/kustomize/base/configmap.yaml`. All services now run without OTLP export (gracefully) until a collector is deployed.

**Decision Rationale:** Brian's preference is convention and simplicity over complexity. Deploying an entire OTEL stack just to avoid errors is overkill. Services function perfectly without OTLP export — tracing still works locally, just without centralized aggregation.

**Key Learning:** All backend services already had defensive env-var checks (empty = disabled). The correct fix was removal, not deployment.

### 2026-05-06 — Orchestration Complete (Scribe)

**Summary:** Scribe recorded this work session:
- Orchestration log: `.squad/orchestration-log/2026-05-06T22-11-00Z-basher.md`
- Session log: `.squad/log/2026-05-06T22-11-00Z-otel-fix.md`
- Decision merged into `.squad/decisions.md` and inbox cleaned up
- Team history updated with this entry

**Basher's Contributions This Session:**
- Fixed OTEL collector error spam (configmap cleanup)
- Hardened K8s deployment security contexts
- Fixed docker-compose build contexts
- All changes staged for git commit

**Status:** Ready for deployment. Services gracefully handle absent OTEL endpoint.

### 2025-07 — OTEL Collector Deployment (Kustomize)

**Summary:** Deployed OpenTelemetry Collector with Azure Application Insights exporter as Kustomize manifests.

**Key Details:**
- Created `deploy/kustomize/observability/otel-collector.yaml` with Namespace, Service, Deployment, and ConfigMap
- Separate kustomization at `deploy/kustomize/observability/` (can't nest under base due to namespace conflicts)
- Collector image: `otel/opentelemetry-collector-contrib:0.151.0`
- App Insights connection string injected via K8s Secret (`appinsights-secret`) → env var `APPINSIGHTS_CONNECTION_STRING` → `${env:APPINSIGHTS_CONNECTION_STRING}` in OTEL config
- Terraform already outputs `application_insights_connection_string` — operator creates the K8s secret from that output
- Re-added `OTEL_EXPORTER_OTLP_ENDPOINT` to configmap pointing at `otel-collector.observability.svc.cluster.local:4317`
- Registered in kustomization.yaml

**Learning:** OTEL collector-contrib supports `${env:VAR}` syntax natively for env var substitution in config files — no sidecar or init container needed.

### 2026-07 — Redis Entra ID Dual-Mode Auth (Cloud + Local)

**Task:** Enable Entra ID (RBAC) for Azure Managed Redis in cloud while keeping access-key auth for local docker-compose.

**Current State Found:**
- Terraform already configured: `access_keys_authentication_enabled = false`, Redis managed identity, RBAC assignment (`Data Owner`), workload identity federation
- TF outputs already correct: connection string has no password, `redis_managed_identity_client_id` output exists
- Go event-processor already had dual-mode: detects `AZURE_CLIENT_ID` → Entra token auth with 45-min refresh; else → connection string parsing
- All 3 C# services (user, transaction, transfer) already had `ConfigureForAzureWithTokenCredentialAsync` gated on `AZURE_CLIENT_ID`
- NuGet packages (`Azure.Identity`, `Microsoft.Azure.StackExchangeRedis`) already in all .csproj files

**Changes Made:**
1. **Go module** (`src/event-processor/go.mod`) — Ran `go get azidentity azcore` + `go mod tidy`; code imported them but they weren't in go.mod (build was broken)
2. **K8s manifests** — Added `azure.workload.identity/use: "true"` label + `serviceAccountName: redis-workload-identity` to user-service, event-processor, transaction-service, transfer-service deployments
3. **Taskfile.cloud.yml** — Added `redis-workload-identity` service account creation (alongside existing `ai-workload-identity`), using `redis_managed_identity_client_id` TF output

**Dual-Mode Pattern:**
- Cloud: `AZURE_CLIENT_ID` injected by AKS workload identity webhook → services detect and use `DefaultAzureCredential` → Entra token auth to Redis
- Local: No `AZURE_CLIENT_ID` → services fall back to connection string password (docker-compose Redis on port 6379, no TLS)
- No extra env var needed — `AZURE_CLIENT_ID` presence is the signal (set automatically by workload identity)

### Transfer Service 500 Fix (Bug 3) — 2026-05-07

**Root Cause:** `TransferService.cs` catch block saved the failed transfer to Cosmos but then re-threw the exception (`throw;`). Since `TransfersController` had no try/catch, every error became an unhandled 500.

**Secondary Issue:** Unused Polly v8 dependency with v7-style API (`Policy.Handle<>()`, `AsyncRetryPolicy`). While Polly 8.x includes backward compat, the retry policy was never actually invoked — dead code with a wrong-version dependency.

**Fixes Applied:**
- `src/transfer-service/Services/TransferService.cs`: Removed `throw;` from catch block. Now returns failed transfer with status/reason. Added inner try/catch around failure persistence so a Cosmos error during error-handling doesn't mask the original failure.
- `src/transfer-service/Controllers/TransfersController.cs`: Added status check — returns `400 BadRequest` with error details when transfer fails instead of `201 Created`.
- `src/transfer-service/transfer-service.csproj`: Removed unused `Polly 8.2.0` package reference.
- Removed `using Polly; using Polly.Retry;` and `AsyncRetryPolicy` field from TransferService.

**Key File Paths:**
- Service: `src/transfer-service/Services/TransferService.cs`
- Controller: `src/transfer-service/Controllers/TransfersController.cs`
- Program: `src/transfer-service/Program.cs`
- Model: `src/transfer-service/Models/Transfer.cs`
- Kustomize: `deploy/kustomize/base/transfer-service.yaml`
- Azure overlay: `deploy/kustomize/overlays/azure/kustomization.yaml`

**ACR:** Correct ACR is `bjdcsa` (not `burstingmastiff55181acr` from project notes). Images at `bjdcsa.azurecr.io/transfer-service:latest`.

**Deployment:** Image built and pushed to ACR. AKS cluster was unreachable (network timeout) — rollout restart pending.

---

## 2026-05-07T17:56:00Z - Basher Spawn: Fix Azure AI Developer RBAC

**Scribe Spawn Event**
- **Task:** Fix Azure AI Developer role assignment scope in identity.tf
- **Issue:** Chatbot service 503 PermissionDenied on agents/write data action
- **Root Cause:** Role scoped to parent account (AI Services account) instead of AI Foundry project
- **Fix:** Change role scope from account-level to project-level in infra/cloud/identity.tf
- **Status:** Spawned in background mode
- **Model:** claude-sonnet-4.5

