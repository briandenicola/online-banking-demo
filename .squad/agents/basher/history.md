# Basher — History

## Project Context
- **Project:** online-banking-demo — AI-generated online banking application
- **User:** Brian
- **Stack:** C#/.NET + Python/FastAPI microservices, Redis, Docker Compose, Azure
- **Services:** user-service, account-service, transaction-service, transfer-service (C#), ai-service, budget-service, chatbot-service, event-processor (Python)

## Learnings

### 2026-05 — Account-opening agent pipeline (Foundry + Content Understanding)

**Pattern:** Account-opening worker runs four Redis-stream consumers (document extraction, identity verification, compliance check, provisioning). Foundry agents are provisioned via init container (`app.agents.init_agents`) using `AIProjectClient.create_version`, while runtime uses `FoundryAgent` only. Content Understanding uses `ContentUnderstandingClient` with analyzer `prebuilt-documentSearch` and `update_defaults()` at startup.

**Key files:**
- `src/account-opening-service/app/agents/document_extraction.py` — CUS extraction + `document_extracted` events
- `src/account-opening-service/app/agents/identity_verification.py` — Foundry identity checks
- `src/account-opening-service/app/agents/compliance_check.py` — Foundry KYC assessment
- `src/account-opening-service/app/agents/provisioning.py` — Foundry decision + user/account provisioning
- `src/account-opening-service/app/worker.py` — worker wiring, Foundry connectivity check, signal handling
- `deploy/kustomize/base/account-opening-service.yaml` — init container + CUS/Foundry env vars

### 2026-05 — Duplicate email registration TOCTOU fix (email lookup document pattern)

**Problem:** Concurrent registration requests could bypass the email uniqueness check because Cosmos DB has no unique constraint on non-PK fields. The check-then-create pattern allowed two requests to both pass the email query before either wrote.

**Fix:** Introduced an "email lookup document" pattern. Before creating the user document, we create a deterministic lookup document with `id = "email-lookup:{email.ToLowerInvariant()}"`. Since `id` is the partition key, Cosmos returns 409 Conflict on duplicates — this is atomic and race-proof. If the subsequent user document creation fails, we clean up the lookup doc. `DeleteUserAsync` also removes the lookup doc. `GetAllUsersAsync` and `IsContainerEmptyAsync` queries now exclude `email-lookup:` documents. `GetUserByEmailAsync` query is now case-insensitive via `LOWER()`. `InMemoryUserService` uses a `ConcurrentDictionary<string, string>` keyed by email (case-insensitive) with atomic `TryAdd`.

**Key files:**
- `src/user-service/Services/UserService.cs` — lookup doc create/cleanup in `CreateUserAsync`, cleanup in `DeleteUserAsync`, query exclusions
- `src/user-service/Services/InMemoryUserService.cs` — `_emailIndex` ConcurrentDictionary with `TryAdd`

### 2026-05 — Istio sidecar blocks Azure Managed Redis TLS (port 10000)

**Problem:** All services using Redis were failing to connect on AKS. The Istio Envoy sidecar intercepts all outbound traffic and can't handle Redis's TLS protocol on port 10000, causing ECONNRESET during TLS handshake. The event-processor (Go) crashed in a loop; .NET services degraded but stayed alive.

**Root cause:** No `traffic.sidecar.istio.io/excludeOutboundPorts` annotation on pod templates. Istio tried to proxy Redis TLS traffic and broke it.

**Fix:**
- Added `traffic.sidecar.istio.io/excludeOutboundPorts: "10000"` to all 5 Redis-using deployments (event-processor, transaction, user, transfer, ai-service)
- Restructured event-processor to start health server BEFORE Redis retry loop
- Readiness probe now returns 503 until Redis is connected
- Removed `log.Fatalf` crash — retries indefinitely with capped 30s backoff
- Increased probe failureThresholds

**Key files:**
- `deploy/kustomize/base/*.yaml` — all 5 deployment manifests updated
- `src/event-processor/main.go` — startup resilience + health probe fix

**Pattern:** Azure Managed Redis uses port 10000 with TLS. Always exclude port 10000 from Istio sidecar when deploying to AKS with managed Istio.

### 2026-05 — TLS on Istio Ingress with cert-manager (3-phase flow)

**Setup:** TLS termination on Istio ingress gateway using cert-manager + Let's Encrypt HTTP-01.

**3-Phase Architecture (Brian's explicit preference):**
- **Phase 1** (`infra:config` → `_infra:cert-manager`): Install cert-manager via Helm, apply ClusterIssuer (HTTP-01), apply HTTP-only gateway, output ingress IP for DNS.
- **Phase 2** (MANUAL): User creates DNS A record pointing `$CUSTOM_DOMAIN` → ingress IP.
- **Phase 3** (`tls:enable`): Apply Certificate, wait for ACME solver, route challenge traffic via VirtualService hack, wait for cert, cleanup solver VS, apply TLS gateway.

**Key decisions:**
- HTTP-01 solver with `class: istio` — Brian explicitly rejected DNS-01 and Gateway API
- VirtualService routing hack for ACME challenge traffic is intentional (managed Istio limitation)
- No `infra:tls:identity` needed — HTTP-01 doesn't require managed identity/workload identity
- ClusterIssuer YAML no longer uses `envsubst` (no env vars needed for HTTP-01)
- `CUSTOM_DOMAIN` only needed at Phase 3 (`tls:enable`)
- cert-manager installed via Helm (Taskfile tasks), not Terraform — operational tooling stays in Taskfile
- TLS secret (`banking-demo-tls`) lives in `aks-istio-ingress` namespace (required for managed Istio)

**Key files:**
- `cluster-config/cert-manager/clusterissuer.yaml` — HTTP-01 ClusterIssuer (class: istio)
- `cluster-config/cert-manager/certificate.yaml` — Certificate resource (uses `${CUSTOM_DOMAIN}`)
- `cluster-config/istio/gateway/istio-ingress-gateway.yaml` — HTTP-only gateway
- `cluster-config/istio/gateway/istio-ingress-gateway-tls.yaml` — TLS gateway (HTTPS + redirect)
- `tasks/Taskfile.cloud.yml` — `_infra:cert-manager`, `tls:enable`, `tls:status`, `_tls:*` internal tasks

**Pattern:** For managed AKS Istio, TLS certs must be in `aks-istio-ingress` namespace. The `credentialName` on the Gateway server references the cert-manager Secret name directly.

**Pattern:** For managed AKS Istio, TLS certs must be in `aks-istio-ingress` namespace. The `credentialName` on the Gateway server references the cert-manager Secret name directly.

**Why DNS-01 over HTTP-01:** HTTP-01 requires DNS already pointing to the gateway AND a VirtualService hack to route `.well-known/acme-challenge/` traffic through Istio to the solver pod. DNS-01 creates a TXT record in Azure DNS — no HTTP traffic, no solver routing, works day-0.

### 2026-05 — Option C: Move balance updates into transaction-service (eliminate service-to-service JWT problem)

**Problem:** During transfers, transaction-service called account-service via HTTP to validate and update balances. The sender's JWT was forwarded, but the ownership check on account-service rejected credit transactions to the destination account (sender doesn't own it). This is the service-identity problem.

**Fix (Option C — chosen by Brian):** Transaction-service now reads/writes account balances directly via Cosmos DB instead of HTTP calls to account-service. This eliminates the JWT forwarding problem entirely.

**Changes:**
- `src/transaction-service/Services/TransactionService.cs` — Removed `IHttpClientFactory`, `IHttpContextAccessor`, `IConfiguration` deps. Added `_accountsContainer` (second Cosmos container). `ValidateBalanceAsync` and `UpdateAccountBalanceAsync` now do direct Cosmos DB reads/writes via `AccountRecord` model. Removed `AccountInfo` inner class.
- `src/transaction-service/Services/InMemoryTransactionService.cs` — Removed HTTP deps. Added `ConcurrentDictionary<string, decimal> _accountBalances` seeded with same balances as `InMemoryAccountService`. Balance validation/updates are now local.
- `src/transaction-service/Program.cs` — Removed `AddHttpClient()` and `AddHttpContextAccessor()` registrations.
- `src/transaction-service/appsettings.json` — Added `CosmosDb:AccountsContainerName`, removed `Services:AccountService`.
- `docker-compose.yml` — Transaction-service: replaced `Services__AccountService` with `CosmosDb__AccountsContainerName`.
- `deploy/kustomize/base/configmap.yaml` — Added `CosmosDb__AccountsContainerName: "Accounts"`.
- `src/transaction-service.Tests/FailClosedSecurityTests.cs` — Updated fail-closed test: now expects `InvalidOperationException` (Cosmos DB errors) instead of `HttpRequestException` (HTTP errors). Test name updated to reflect accounts container unreachability.

**Pattern:** When a service needs to read/write another service's data for atomic operations, direct Cosmos DB access (shared database, separate container) is cleaner than service-to-service HTTP with JWT forwarding. The `AccountRecord` model in transaction-service mirrors the account-service `Account` model for Newtonsoft serialization compatibility.

**Key config:** `CosmosDb:AccountsContainerName` — the Cosmos container name for accounts, read by transaction-service to get a second container reference from the singleton CosmosClient.

### 2026-05 — Chatbot SDK Migration: v2.x azure-ai-projects (final)

**Problem:** chatbot-service used the old `create_agent()` / `threads.create()` / `messages.create()` / `runs.create_and_process()` API which no longer exists in azure-ai-projects 2.1.0.

**Fix:** Full rewrite of `main.py` to use the v2.x SDK:
- `agents.create_version(agent_name, definition=PromptAgentDefinition(...))` to register agent at startup
- `project_client.get_openai_client(agent_name=...)` to get an OpenAI-compatible client pointed at the agent endpoint
- `openai_client.responses.create(model=agent_name, input=messages)` for chat (OpenAI Responses API)
- Client-side conversation history (in-memory per user, capped at 20 messages) replaces server-side threads
- `agents.delete(agent_name=...)` on shutdown for cleanup
- `AIProjectClient(..., allow_preview=True)` required for agent_name-based OpenAI client
- Graceful 503 degradation preserved when no Azure endpoint configured

**Key v2.x API surface verified by introspection:**
- `AgentsOperations`: create_version, delete, get, list, etc.
- `BetaAgentsOperations`: create_session, get_session_log_stream (for compute sessions, not chat)
- Chat goes through `get_openai_client(agent_name=...)` → OpenAI Responses API

**Files:** `src/chatbot-service/app/main.py`, `src/chatbot-service/Dockerfile` (unchanged)

**Pattern:** In azure-ai-projects 2.x, agents are versioned resources (`create_version` + `PromptAgentDefinition`). Chat uses the OpenAI Responses API via `get_openai_client(agent_name=...)`, not threads/runs.

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
- `src/ai-service/app/main.py:220-223` — Missing await on async detect_anomaly()
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

4. **ai-service** — Added missing `await` on `detect_anomaly()` call in event processor.

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
2. **ai-service (Python)** — Emits processed transaction events to Redis stream instead of posting to Event Hub
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
   - ai-service (line 129): Used `context: .` but should be `context: ./src/ai-service`
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
- Python ai-service: redis-py asyncio, env var `REDIS__CONNECTIONSTRING`
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

### 2026-05 — Login 401 Investigation

**Problem:** Brian reported 401 on `POST /api/auth/login`. User exists in Cosmos (re-registration fails), but login returns 401. User-service logs showed no login requests.

**Root Cause Analysis:** Multiple contributing issues found:
1. **Global 401 interceptor bounce-back** (`src/ui-app/src/api/client.ts:20-29`): Catches ALL 401s from any service, clears token, hard-redirects to /login. After login succeeds, `AccountProvider` immediately fires `GET /api/accounts` — if any downstream service returns 401, user gets bounced back.
2. **Zero logging in login path** (`src/user-service/Controllers/AuthController.cs:42-61`): No log statements + `Microsoft.AspNetCore: Warning` level = login requests invisible in logs. The "no login request in logs" observation was a logging gap, not proof of routing failure.
3. **`UseHttpsRedirection()` in all .NET services**: Runs before auth middleware. Behind Istio, logs warning but passes through. Not the direct cause.
4. **Duplicate login endpoints**: `AuthController /api/auth/login` and `UsersController /api/users/login` — identical code, maintenance hazard.

**Key Files:**
- `src/user-service/Controllers/AuthController.cs` — login endpoint (no logging)
- `src/user-service/Controllers/UsersController.cs` — duplicate login endpoint
- `src/ui-app/src/api/client.ts` — 401 interceptor
- `src/ui-app/src/contexts/AccountContext.tsx` — fires GET /api/accounts on token change
- `src/user-service/Program.cs:123` — UseHttpsRedirection()
- `cluster-config/istio/gateway/default-ingress.yaml` — Istio routing (correct)

**Architecture Notes:**
- JWT config is consistent across services (same key from `banking-secrets.jwt-key`, same issuer `user-service`, audience `banking-demo`)
- Istio VirtualService correctly routes `/api/auth` → user-service:80 → targetPort 8080
- No Istio AuthorizationPolicy or RequestAuthentication policies
- nginx in ui-app serves static only, no API proxy
- user-service Cosmos SDK is preview version `3.59.0-preview.0` — property serialization uses Newtonsoft default (PascalCase)

- chatbot-service: Rewrote from pre-created agent_reference pattern to programmatic agent creation via `project_client.agents.create_agent()` at startup, with `delete_agent()` on shutdown
- chatbot-service: Switched chat endpoint from OpenAI Responses API to agents threads/runs pattern (`threads.create`, `messages.create`, `runs.create_and_process`)
- chatbot-service: Conversation history now managed by Azure AI threads (one thread per user) instead of in-memory message lists
- chatbot-service: Removed `openai_client` global; `project_client` handles all agent interactions

### 2026-05 — Anomaly-Service Redis Connection Fix

**Problem:** ai-service admin endpoints (`/api/admin/stats`, `/api/admin/flagged-transactions`) returned 500. The Python code blindly prepended `redis://` to the `REDIS__CONNECTIONSTRING` env var, but AKS provides a .NET-style connection string (`host:10000,ssl=True,abortConnect=False,password=xxx`).

**Fix:** Replaced `redis.from_url()` with `redis.Redis()` using parsed connection parameters:
- `_parse_redis_connection_string()` extracts host, port, ssl, password from .NET format (mirrors Go `parseRedisConnectionString()` in event-processor)
- Entra ID token auth when `AZURE_CLIENT_ID` is set: uses `DefaultAzureCredential` with Redis scope, extracts OID from JWT for username
- Token refresh every 45 minutes via background task
- TLS enabled when `ssl=True` in connection string
- Falls back to simple host:port for local docker-compose

**Files:** `src/ai-service/app/main.py`

**Pattern:** All services connecting to Azure Managed Redis must parse .NET connection strings and support Entra ID auth. Go event-processor (`src/event-processor/main.go:305-336`) is the reference implementation.

### 2026-05 — Balance Update Fix: Transaction-Service Owns Balance Side Effects

**Problem:** When transactions were created (direct or via transfer), account balances were NOT updated. The transaction-service only recorded transactions without adjusting balances. The InMemoryTransferService was a stub with no real transfer logic.

**Fix:**
- Transaction-service now calls `POST /api/accounts/{id}/balance` on account-service after every transaction creation, using JWT forwarded from the incoming request
- Transfer-service no longer duplicates balance updates — removed direct balance calls from Cosmos TransferService
- InMemoryTransferService rebuilt with full transfer logic: account lookup, balance validation, transaction creation via HTTP calls (mirroring Cosmos version)
- Both TransferService implementations now use `IHttpClientFactory` + `IHttpContextAccessor` for authenticated service-to-service calls
- Added `HttpClient`, `IHttpClientFactory`, and `IHttpContextAccessor` DI registrations in both transaction-service and transfer-service `Program.cs`

**Key files:**
- `src/transaction-service/Controllers/TransactionsController.cs` — balance update call after CreateTransaction
- `src/transaction-service/Program.cs` — HttpClient + HttpContextAccessor DI
- `src/transfer-service/Services/TransferService.cs` — removed balance calls, added auth forwarding
- `src/transfer-service/Services/InMemoryTransferService.cs` — full transfer logic with HTTP calls
- `src/transfer-service/Program.cs` — HttpClient + HttpContextAccessor for both InMemory and Cosmos branches
- `src/account-service/Controllers/AccountsController.cs` — existing `POST {id}/balance` endpoint (unchanged)

**Pattern:** Transaction-service is the single owner of balance side effects. Any code that creates a transaction (direct or via transfer) gets automatic balance updates. Transfer-service only orchestrates creating debit/credit transaction pairs.

**Pattern:** Service-to-service calls must forward the incoming JWT via `IHttpContextAccessor` to satisfy `[Authorize]` on downstream services.

### 2026-05-07 — Transfer Service Account Lookup Fix

**Problem:** Transfers failed with "From account not found" — both `fromAccountId` and `toAccountId` were null.

**Root causes (two bugs):**
1. **Missing port in docker-compose inter-service URLs:** .NET 9 containers default to port 8080. `Services__AccountService=http://account-service` (no port = port 80) caused connection refused. Fixed by adding `:8080` to all service URLs in docker-compose.yml.
2. **Ownership check on `GetAccountByNumber` blocked cross-user transfers:** The account-service endpoint returned 403 for the destination account since it belongs to a different user. Removed ownership check — account-by-number lookups are needed for service-to-service calls (transfers).

**Files changed:**
- `docker-compose.yml` — added `:8080` to `Services__AccountService` and `Services__TransactionService` URLs
- `src/account-service/Controllers/AccountsController.cs` — removed ownership check from `GetAccountByNumber`

**Pattern:** .NET 9 containers listen on 8080 by default (not 80). All inter-service URLs in docker-compose must include `:8080`.
**Pattern:** Account-by-number lookup must not enforce ownership — it's used for cross-user transfers.

### 2026-05-08 — TLS Cert-Manager on Istio Ingress

**Feature:** Added automated TLS termination to the Istio ingress gateway using cert-manager with Let's Encrypt.

**Architecture choices:**
- cert-manager installed via Helm (Taskfile), not Terraform — keeps operational tooling in Taskfile
- ClusterIssuer with HTTP-01 challenge and `class: istio` — works with managed AKS Istio without DNS provider config
- TLS secret lives in `aks-istio-ingress` namespace (required by managed Istio for gateway credential reference)
- Gateway keeps HTTP (port 80) with `httpsRedirect: true`, adds HTTPS (port 443) with SIMPLE TLS mode
- `CUSTOM_DOMAIN` env var drives certificate domain via `envsubst`

**Key files created:**
- `cluster-config/cert-manager/clusterissuer.yaml` — Let's Encrypt production ClusterIssuer
- `cluster-config/cert-manager/certificate.yaml` — Certificate resource template (uses `${CUSTOM_DOMAIN}`)
- `cluster-config/istio/gateway/istio-ingress-gateway.yaml` — Updated with HTTPS server + redirect
- `Taskfile.cloud.yml` — Added `tls:install-cert-manager`, `tls:setup`, `tls:status` tasks
- `.env.example` — Added `CUSTOM_DOMAIN` variable

**Pattern:** For managed AKS Istio, TLS certs must be in `aks-istio-ingress` namespace. The `credentialName` on the Gateway server references the cert-manager Secret name directly. HTTP-01 solver class `istio` works without DNS configuration.

### 2026-05 — Private Endpoints for All Azure Services

**Problem:** Subscription policy blocks public endpoints. Key Vault returned "Forbidden — Public network access is disabled" for the managed identity. All 6 Azure services needed private endpoints.

**Changes made:**
1. Created `infra/cloud/private-endpoints.tf` — new PE subnet (`cidrsubnet(local.vnet_cidr, 8, 4)`), 7 private DNS zones, VNet links, and 6 private endpoints (Key Vault, Cosmos DB, Redis, ACR, AI Services, Storage)
2. Modified 6 existing resource files to disable public network access:
   - `keyvault.tf` — `public_network_access_enabled = false` + `network_acls { bypass = "AzureServices", default_action = "Deny" }` + optional deployer IP
   - `cosmos.tf` — `public_network_access_enabled = false`
   - `redis.tf` — `public_network_access = "Disabled"` (different attribute name for azurerm_managed_redis)
   - `acr.tf` — SKU upgraded `Basic` → `Premium` (required for PE), public access kept enabled
   - `ai.tf` — `publicNetworkAccess = "Disabled"` in azapi body properties
   - `storage.tf` — `public_network_access_enabled = false`
3. Added `pe_subnet_cidr` to `locals.tf`, `deployer_ip` variable to `variables.tf`

**Key decisions:**
- ACR keeps public access enabled (push from CI/CD) but also gets a PE for in-VNet pulls
- Key Vault `network_acls.bypass = "AzureServices"` lets managed identities access it via PE
- `deployer_ip` variable (defaults to empty) lets Brian allow Terraform through KV firewall during apply
- AI Services gets two DNS zones: `privatelink.cognitiveservices.azure.com` and `privatelink.openai.azure.com`
- Redis uses `public_network_access` (not `public_network_access_enabled`) — different attribute name for azurerm_managed_redis

**Key files:**
- `infra/cloud/private-endpoints.tf` — all PE infrastructure
- `infra/cloud/variables.tf` — `deployer_ip` variable
- `infra/cloud/locals.tf` — `pe_subnet_cidr`

### 2026-05-10 — TLS Architecture Revision: DNS-01 → HTTP-01 3-Phase Flow

**Problem:** DNS-01 ACME approach (previous decision) required external Azure DNS zone dependency + managed identity + workload identity federation. Brian explicitly requested simpler HTTP-01 approach with clear operational phases.

**Changes made:**
1. Restructured TLS into 3-phase flow:
   - **Phase 1 (`infra:config`):** cert-manager installed, HTTP-01 ClusterIssuer applied, HTTP-only gateway deployed, ingress IP output for user
   - **Phase 2 (Manual):** User creates DNS A record pointing domain to ingress IP
   - **Phase 3 (`tls:enable`):** Certificate applied, ACME challenge routed via VirtualService hack, waits for validation, cleanup, TLS gateway applied

2. Reverted `clusterissuer.yaml`: Changed from `dns01.azureDNS` solver back to `http01` with `class: istio`

3. Updated `Taskfile.cloud.yml`:
   - Removed `infra:tls` (monolithic task) and `infra:tls:identity` (DNS-01 specific)
   - Added `_infra:cert-manager` (Phase 1), `tls:enable` (Phase 3)
   - Added helper tasks: `_tls:wait-for-solver`, `_tls:route-solver`, `_tls:cleanup-solver`

4. Removed env vars: `AZURE_SUBSCRIPTION_ID`, `DNS_ZONE_RG`, `DNS_ZONE_NAME`, `CERT_MANAGER_CLIENT_ID` (no longer needed)

**Key insight:** HTTP-01 is operationally simpler for initial deployments (no external DNS zone), but requires VirtualService routing trick for managed Istio because default Istio behavior doesn't auto-forward `.well-known/acme-challenge` traffic to solver pods. The 3-phase flow explicitly separates infra concerns from DNS/cert concerns, improving debugging and user understanding.

**Pattern:** For any ACME setup on managed Istio without pre-configured DNS, HTTP-01 + manual DNS phase is lower-friction than DNS-01 + external zone dependency. VirtualService solver routing is a standard workaround.


### 2026-05-11 — Event Processor Pod Failure: Istio Sidecar Blocking Redis TLS

**Issue:** event-processor pod crash-looping on AKS. All 5 Redis-using services (event-processor, transaction, user, transfer, ai-service) failing to connect to Azure Managed Redis.

**Diagnosis:** Istio Envoy sidecar was intercepting outbound TLS traffic to port 10000 and breaking the Redis TLS handshake. The sidecar attempts to re-encrypt already-encrypted Redis traffic, causing the connection to drop with ECONNRESET.

**Solution:** Added `traffic.sidecar.istio.io/excludeOutboundPorts: "10000"` annotation to all 5 pod templates. This bypasses Istio's Envoy proxy for Redis traffic while keeping all other traffic within the mesh.

**Restructured event-processor health/retry logic:**
- Start HTTP health server **before** attempting Redis connection (doesn't block startup)
- Report readiness based on actual Redis state
- Retry indefinitely instead of crashing after 10 attempts
- Allows graceful degradation if Redis is temporarily unavailable

**Cross-team note:** Turk identified the root DNS zone issue in parallel. Both fixes required for full Redis connectivity.

**Key files modified:** 5 deployment manifests + `src/event-processor/main.go`
**Commit:** f2cac3b

### 2026-05 — First user auto-promoted to admin

**Problem:** `CreateUserAsync` in both `UserService.cs` (Cosmos DB) and `InMemoryUserService.cs` always assigned `Role = "user"` (the model default). The first registered user in a fresh system had no admin privileges, breaking initial setup.

**Fix:**
- `UserService.cs`: Added `IsContainerEmptyAsync()` — runs `SELECT VALUE COUNT(1) FROM c` before user creation. If count is 0, sets `Role = "admin"`.
- `InMemoryUserService.cs`: Checks `_users.IsEmpty` before creation. Same admin promotion logic.
- Both paths log the auto-promotion for auditability.

**Key files:**
- `src/user-service/Services/UserService.cs` — Cosmos path
- `src/user-service/Services/InMemoryUserService.cs` — in-memory path

**Pattern:** First-user-is-admin is a simple count check, no config flags needed. Always log role escalation.

### 2026-05 — Admin promotion endpoint with bootstrap escape hatch

**Problem:** brian@sample.com was created before the first-user-is-admin auto-promotion logic, so they were stuck as `role: "user"` with no way to become admin.

**Solution:** Added `POST /api/admin/promote` endpoint to AdminController:
- Accepts `{ "email": "..." }` or `{ "userId": "..." }`
- Bootstrap escape hatch: if zero admins exist in DB, allows unauthenticated promotion
- Once admins exist, requires `[Authorize(Roles = "admin")]`
- Returns 404/409/403 as appropriate
- Logs promotions at Warning level

**Key files:**
- `src/user-service/Controllers/AdminController.cs` — promote endpoint
- `src/user-service/Services/IUserService.cs` — PromoteToAdminAsync, GetAdminCountAsync
- `src/user-service/Services/UserService.cs` — Cosmos DB implementation
- `src/user-service/Services/InMemoryUserService.cs` — in-memory fallback

**Pattern:** Bootstrap escape hatches should be self-closing — once the first admin exists, the permissive path is permanently locked out.

## Cross-Agent Coordination (2026-05-11)

### Related Team Updates
- **Linus (Frontend):** Created AdminUserManagementTab.tsx for user lock/unlock/reset-password — requires Basher's admin endpoints (`/api/admin/users`, `PUT /api/admin/users/{id}/lock|unlock|reset-password`, `DELETE /api/admin/users/{id}`)
- **Livingston (QA):** Created smoke test suite (15 total @smoke tests) — now post-deployment verification gate
- **Turk (Infrastructure):** Fixed AI Services PE DNS zones (now 3 zones) — all AI Foundry services resolve through PE

### 2026-05-11 — Init container for Foundry agent provisioning

**Problem:** `FoundryAgent` from `agent_framework_foundry` requires agents to be pre-registered in Azure AI Foundry. The `risk-assessor` and `transaction-categorizer` agents were returning 404.

**Fix:** Created a K8s init container that provisions both prompt agents before the main ai-service starts.

**Approach:**
- `src/ai-service/app/init_agents.py` — standalone script using `httpx` + `DefaultAzureCredential` to call Foundry REST API directly
- REST API pattern: GET `/agents/{name}/versions/{version}?api-version=v1` (check), POST `/agents/{name}/versions?api-version=v1` (create)
- Uses `PromptAgentDefinition` body with `kind: "prompt"`, model, and instructions
- Idempotent: check-then-create, safe to re-run
- `deploy/kustomize/base/ai-service.yaml` — added `provision-agents` init container with same image, env vars, service account, and secrets-store volume

**Key decisions:**
- Used REST API via `httpx` instead of `azure-ai-projects` SDK (per project directive: only agent-framework packages)
- System prompts duplicated in init script to keep it standalone — the main container loads them from class constants
- Init container shares workload identity for seamless Entra auth

**Key files:**
- `src/ai-service/app/init_agents.py`
- `deploy/kustomize/base/ai-service.yaml`

### 2026-05 — Foundry connectivity validation endpoints

**Task:** Added `GET /api/admin/foundry-status` endpoints to ai-service and chatbot-service for Admin Panel Foundry connectivity checks.

**ai-service approach:** Endpoint looks up `foundry-risk` and `foundry-categorizer` from `_analyzer_pipeline`, sends a minimal "ping" prompt via `create_session()` + `run()` to each FoundryAgent. Returns per-agent status (`ok`/`error`) with overall status (`ok`/`degraded`/`error`). Never crashes — all exceptions caught and reported.

**chatbot-service approach:** Same pattern but for the single `FinancialAdvisor` agent. Checks SDK availability and agent readiness before attempting connectivity test. Returns agent name, status, and message.

**Key pattern:** Using `create_session()` + `run("ping")` is the lightest real connectivity test — it validates credential, endpoint, and agent reachability without processing real data.

**Key files:**
- `src/ai-service/app/main.py` — `foundry_status()` endpoint at `/api/admin/foundry-status`
- `src/chatbot-service/app/main.py` — `foundry_status()` endpoint at `/api/admin/foundry-status`

### 2026-05-11 — ai-service init container recovery verification

**Context:** System crashed during a previous session fixing ai-service ImagePullBackOff. The init container YAML had already been updated with the correct ACR image reference (`loyalmoose4702acr.azurecr.io/ai-service:latest`).

**Findings:** On reconnection, the ai-service pod was already Running (2/2 containers). The `provision-agents` init container completed successfully (exit code 0). The `ai-service:latest` image exists in ACR. The `init_agents.py` entry point exists at `src/ai-service/app/init_agents.py`. No rebuild or restart was needed — the fix from the previous session had already taken effect.

**Lesson:** Always verify pod state before rebuilding. A previous fix may have already propagated during the crash window.

## Foundry Status Endpoint Patterns (2026-05-11)

### Implementation Details
- **ai-service:** Implements `GET /api/admin/foundry-status` endpoint
  - Looks up `foundry-risk` and `foundry-categorizer` agents from analyzer pipeline
  - Sends minimal "ping" prompt via `create_session()` + `run()` to each agent
  - Returns per-agent status (`ok`/`error`) with overall system status (`ok`/`degraded`/`error`)
  - All exceptions caught — never crashes on degraded services

- **chatbot-service:** Implements `GET /api/admin/foundry-status` endpoint
  - Tests single `FinancialAdvisor` agent
  - Checks SDK availability and agent readiness before connectivity test
  - Returns agent name, status, and message

### Key Pattern
Using `create_session()` + `run("ping")` is lightest real connectivity test:
- Validates Azure credential
- Validates endpoint reachability
- Validates agent reachability
- No real data processing required

### Integration
- Admin panel uses these endpoints to display Foundry service health in System Health tab
- Smoke tests can hit these endpoints to monitor Foundry availability without failing on transient issues
- Graceful degradation: Services operate in "degraded" mode when agents unavailable

### 2026-05 — Account Opening Phase 1 Skeleton
- Added FastAPI account-opening-service scaffolding at `src/account-opening-service/` (models, repository, state machine, Redis events/consumer base, worker entrypoint).
- Deployment assets: `deploy/kustomize/base/account-opening-service.yaml` + kustomization image mapping; docker-compose adds account-opening-service + worker.
- API gateway routing updated: `nginx.conf` now forwards `/api/account-opening` to `account-opening-service:8004`.

### 2026-05 — AI System Prompt Security Hardening
- Hardened all AI agent system prompts across 5 files for prompt injection resistance.
- **Chatbot** (`src/chatbot-service/app/main.py`): Added identity anchoring, explicit injection resistance (blocks "ignore previous instructions", "DAN mode", etc.), output boundary (no code/essays/stories), PII echo-back protection, and scope redirect phrasing.
- **Account-opening agents** (`src/account-opening-service/app/agents/`): Added role anchoring, untrusted-input warnings, and strict output format enforcement to identity_verification.py, compliance_check.py, and provisioning.py.
- **init_agents.py**: Updated AGENT_SPECS instructions to stay consistent with runtime SYSTEM_PROMPTs (role anchoring + input distrust + output strictness).
- Pattern: User-facing prompts need the heaviest hardening (identity anchor, injection resistance, output boundary, PII masking). Backend agent prompts need role anchoring, input distrust, and output format enforcement.

### 2026-05-11 — Redis Entra ID auth + init_agents SDK fix

**Bug 1: Redis "Authentication required"**
- Root cause: `main.py` and `worker.py` used `redis.asyncio.Redis` with password-only auth. Azure Managed Redis requires Entra ID token auth via `RedisCluster`.
- Fix: Extracted shared `app/redis_client.py` module. When `AZURE_CLIENT_ID` is set, creates `RedisCluster` with JWT OID as username and token as password, TLS on port 10000, and a background token refresh every 20 minutes. Falls back to plain `redis.Redis` for local dev.
- Follows the same pattern as the Go event-processor (`src/event-processor/main.go`).
- Redis scope: `acca5fbb-b7e4-4009-81f1-37e38fd66d78/.default`

**Bug 2: init_agents.py `agent_version` parameter error**
- Root cause: `azure-ai-projects` SDK v2.1.0 changed `agents.get()` and `agents.create_version()` — `agent_name` and `agent_version` are positional args, not kwargs.
- Fix: Changed to positional args: `client.agents.get(name, version)` and `client.agents.create_version(name, version, ...)`.
- Also made provisioning errors non-fatal (exit 0) so init container doesn't CrashLoopBackOff when agents already exist or SDK has transient issues.

### 2026-05 — Istio Gateway/VirtualService kustomize manifests

**Problem:** Istio Gateway, VirtualService, and cert-manager Certificate were applied via `kubectl` directly and not tracked in kustomize manifests. They would be lost on redeployment.

**Solution:** Created proper kustomize manifests:
- `deploy/kustomize/ingress/gateway.yaml` — Certificate + Gateway (namespace: `aks-istio-ingress`)
- `deploy/kustomize/ingress/kustomization.yaml` — separate kustomization to preserve `aks-istio-ingress` namespace
- `deploy/kustomize/base/virtualservice.yaml` — VirtualService (namespace: `banking-demo`)

**Key decision:** Gateway/Certificate live in a separate `deploy/kustomize/ingress/` kustomization (not under `base/`) because the main base has `namespace: banking-demo` which would override `aks-istio-ingress` on the ingress resources. Kustomize propagates namespace transformations to all sub-resources including subdirectories.

**Pattern:** For cross-namespace kustomize resources, use separate kustomization directories. Never rely on a sub-directory to escape a parent's `namespace:` directive — kustomize will override it.

### 2026-05 — Sample Documents for Account Opening (Issue #16, Phases 1-3)

**What was built:** Test fixture generator for account-opening E2E tests. Created Python tooling under `tests/fixtures/sample-documents/` that produces text-based PDFs from JSON applicant profiles. Implemented Phases 1-3: directory structure, data models, applicant profile JSON, and photo ID (driver's license) PDF generation.

**Key files:**
- `tests/fixtures/sample-documents/requirements.txt` — fpdf2==2.8.7 dependency
- `tests/fixtures/sample-documents/applicants/john-smith.json` — single-source-of-truth applicant profile with ApplicantProfile, PhotoIdSpec, ProofOfAddressSpec, and ApplicationFormData
- `tests/fixtures/sample-documents/models.py` — Python dataclasses with validation (ISO dates, 4-digit SSN, 2-letter state, 5-digit ZIP, account type enum) + `load_profile()` loader
- `tests/fixtures/sample-documents/generate_photo_id.py` — fpdf2-based driver's license generator, landscape layout, Helvetica font
- `tests/fixtures/sample-documents/john-smith/photo_id.pdf` — generated PDF (1.4KB, text-based)

**Design decisions applied:**
- D1: All text is native PDF text (not images) — Azure AI Content Understanding can extract without OCR
- D2: Field labels match normalization mapping: `Name`, `Date of Birth`, `Address`, `License Number`, `Expiry Date`
- D3: All data sourced from john-smith.json, never hardcoded in generators
- D4: Generated PDFs committed to repo (not .gitignored) for direct E2E test consumption

**Gotcha:** fpdf2 core Helvetica font doesn't support Unicode em-dash (U+2014). Used ASCII hyphen in header "STATE OF ILLINOIS - DRIVER LICENSE" instead of "—". If Unicode is needed, must embed a TTF font via `add_font()`.

### 2026-05 — Account opening smoke tests (Issue #21, PR #23)

**What:** Added account-opening coverage to the existing smoke test suite in `tests/e2e/specs/smoke/smoke.spec.ts` and `tests/e2e/utils/testHelpers.ts`.

**Tests added:**
- Health check: `/api/account-opening/healthz` added to both `waitForAllServices()` and the `@smoke Health checks` test
- Submit application: POST to `/api/account-opening/applications` with john-smith fixture data, verify `id` + `status === "submitted"`
- Upload document: Create application then multipart POST `photo_id.pdf` to `/applications/{id}/documents`, verify `type === "photo_id"`

**Pattern:** Graceful degradation — all account-opening tests wrap in try-catch and treat 5xx as "service not deployed." Supports `ACCOUNT_OPENING_URL` env var for separate service URL (same pattern as `AI_SERVICE_URL`).

**Key files:**
- `tests/e2e/specs/smoke/smoke.spec.ts` — 3 new test points
- `tests/e2e/utils/testHelpers.ts` — health check array
- `tests/fixtures/sample-documents/john-smith/photo_id.pdf` — used in document upload test
- `tests/fixtures/sample-documents/applicants/john-smith.json` — application form data source

### 2026-05 — Account-opening upload PermissionError fix

**Problem:** `upload_document` endpoint returned 500 because `Path("/app/data/documents/...").mkdir()` failed — `/app` is root-owned but the container runs as `appuser` (UID 1000). The Dockerfile copies files as root then switches to `USER appuser`, so `/app/data` never existed with correct ownership.

**Fix (two layers):**
1. **Kustomize:** Added `emptyDir` volume (`upload-data`) mounted at `/app/data` on the API deployment only. The pod `fsGroup: 1000` makes it writable. Worker deployment left untouched (no uploads).
2. **Dockerfile:** Added `RUN mkdir -p /app/data && chown appuser:appuser /app/data` before `USER appuser` so local Docker runs also work.

**Pattern:** When a non-root container needs a writable directory under a root-owned WORKDIR, use `emptyDir` + `fsGroup` in K8s and pre-create with `chown` in the Dockerfile. Don't `chmod 777` — maintain least-privilege.

**Key files:**
- `deploy/kustomize/base/account-opening-service.yaml` — emptyDir volume on API deployment
- `src/account-opening-service/Dockerfile` — mkdir + chown before USER switch

### 2026-05 — Replace local file write with Azure Blob Storage

**Change:** Document upload endpoint now uses `BlobServiceClient` with `DefaultAzureCredential` instead of writing to local filesystem. BlobServiceClient initialized once in app lifespan (similar to redis pattern). Removed `/app/data` directory from Dockerfile since it's no longer needed.

**Key decisions:**
- Sync `BlobClient.upload_blob()` used (runs in threadpool) — avoids async SDK complexity
- Blob path convention: `{application_id}/{document_type}/{filename}`
- `blobUrl` returns real Azure Blob URL consumed by downstream AI Content Understanding Service
- Storage account name injected via `AZURE_STORAGE_ACCOUNT_NAME` env var (configmap placeholder pattern)

### 2026-05 — Entra Agent ID sidecar credential wrapper (Issue #20)

**Pattern:** Created `SidecarTokenCredential` class (`app/sidecar_credential.py`) that conforms to Azure `TokenCredential` protocol. Fetches bearer tokens from the Entra Agent ID auth-sidecar HTTP endpoint (`GET /AuthorizationHeaderUnauthenticated/{api_name}?AgentIdentity=...`) with 3-attempt retry/backoff. JWT exp claim decoded for `expires_on`.

**Wiring:** Worker.py creates `SidecarTokenCredential` when `AGENT_ID_SIDECAR_URL` + `AGENT_ID_AGENT_IDENTITY` env vars are set; falls back to `DefaultAzureCredential` otherwise. Only the 3 Foundry consumers use sidecar cred; Cosmos, Blob, connectivity check, and DocumentExtraction keep DAC.

**K8s ordering constraint:** `init_agents.py` MUST use `DefaultAzureCredential` because init containers run before sidecars start.

**Key files:**
- `src/account-opening-service/app/sidecar_credential.py` — new TokenCredential implementation
- `src/account-opening-service/app/worker.py` — credential routing logic
- `src/account-opening-service/app/agents/init_agents.py` — DAC kept with comment
- `src/account-opening-service/app/agents/{identity_verification,compliance_check,provisioning}.py` — removed DAC fallback, credential now required

### 2026-05 — Documentation update for Account Opening Service (Issue #19)

**Task:** Added Account Opening Service documentation across all 6 lab docs (README.md, docs/README.md, architecture.md, deployment-local.md, deployment-azure.md, testing.md).

**Key doc patterns:**
- Service listed under "Python Agent Services" alongside chatbot, ai-service, budget
- Architecture section includes full 4-stage pipeline flow diagram (CUS → identity → compliance → provisioning)
- Entra Agent ID sidecar pattern documented in both architecture.md and deployment-azure.md
- Local dev uses DefaultAzureCredential (no sidecar) — noted in deployment-local.md
- Account opening API runs on port 6005 locally (mapped from 8004)
- Unit tests in `src/account-opening-service/tests/`, E2E smoke test at `tests/e2e/specs/core/account-opening.spec.ts`
- Cosmos DB container: `account-applications` (partition key `/id`)
- No dedicated Taskfile build command yet — builds with the python group

### 2026-05 — Deep .NET Services Security Audit (Issue #18)

**Scope:** Audited all 5 .NET service directories (user-service, account-service, transaction-service, transfer-service, shared) — 30+ C# files.

**Critical findings (4):**
- `X-User-Id` header forgery bypass in account-service (`Controllers/AccountsController.cs:28-29`)
- Unprotected `POST /api/accounts/{id}/balance` endpoint — any user can modify any balance
- Fail-open balance validation in transaction-service (`Services/TransactionService.cs:213-216`) — transactions proceed when account-service unreachable
- Anonymous admin promotion when `adminCount == 0` (`user-service/Controllers/AdminController.cs:33-47`)

**Systemic patterns found:**
- All services leak `ex.Message` to clients in error responses (6+ locations)
- All services fall back to Cosmos DB connection strings if endpoint not configured
- No ownership/IDOR checks on read endpoints across account, transaction, and transfer services
- transaction-service has `ValidateIssuer = false` while all others have `true`
- No rate limiting on auth endpoints
- No retry/circuit breaker on service-to-service HTTP calls
- PII (emails, balances) logged in several services

**Good patterns confirmed:**
- Cosmos queries are parameterized (no NoSQL injection)
- CosmosClient registered as singleton (correct lifecycle)
- No dangerous Newtonsoft TypeNameHandling
- OTEL instrumentation via shared library is consistent

**Key files:** Report at `.squad/decisions/inbox/basher-security-audit.md`

**Pattern:** account-opening-service and ai-service have no .NET code — both are Python-only.

### 2026-05 — Critical Auth Vulnerability Fixes (Issues #25 + #27)

**Problem:** Multiple authorization bypass vulnerabilities across .NET services:
1. X-User-Id header forgery — account-service fell back to untrusted header when JWT claim was missing
2. Missing ownership checks — several endpoints returned resources without verifying the authenticated user owned them
3. InMemoryTransactionService.GetUserTransactionsAsync ignored the userId parameter, returning all transactions
4. Fail-open balance validation — transaction-service allowed transactions to proceed when balance check failed

**Fix:**
- Removed X-User-Id header fallback in AccountsController; user identity now comes exclusively from JWT claims
- Added ownership checks to all read/write endpoints: GetAccountByNumber, UpdateBalance, GetTransaction, GetAccountTransactions, GetTransfer
- All ownership failures return 404 (not 403) to prevent resource enumeration
- Fixed InMemoryTransactionService to actually filter by userId
- Added UserId field to Transfer model for ownership tracking
- Transfer service now verifies FromAccountId belongs to authenticated user before processing
- Changed fail-open to fail-closed in both TransactionService and InMemoryTransactionService — if balance cannot be validated, transaction is rejected

**Key files:**
- `src/account-service/Controllers/AccountsController.cs` — X-User-Id removal, ownership checks
- `src/transaction-service/Controllers/TransactionsController.cs` — ownership checks on GET endpoints
- `src/transaction-service/Services/TransactionService.cs` — fail-closed balance validation
- `src/transaction-service/Services/InMemoryTransactionService.cs` — userId filter fix, fail-closed
- `src/transfer-service/Controllers/TransfersController.cs` — ownership check on GET
- `src/transfer-service/Services/TransferService.cs` — account ownership verification, userId storage
- `src/transfer-service/Services/InMemoryTransferService.cs` — same ownership verification
- `src/transfer-service/Models/Transfer.cs` — added UserId property

**Breaking change:** Adding ownership checks to `GET /api/accounts/number/{accountNumber}` and `POST /api/accounts/{id}/balance` will break service-to-service calls where the forwarded user JWT doesn't own the target account (e.g., credit side of a transfer). This needs a service-identity solution (see decision doc).

### 2026-05 — Security & SDK hardening batch (#28, #32, #35, #37)

**Issue #28 — Anonymous admin promotion removed:**
Removed `[AllowAnonymous]` from `POST /api/admin/promote`. Admin bootstrap now happens at startup via `Admin__BootstrapEmail` config/env var, falling back to first-user convention. The endpoint itself requires admin JWT.

**Issue #32 — Hardcoded demo passwords eliminated:**
`InMemoryUserService` now reads `Demo__Password` from config. Falls back to a random 16-char password logged at startup. No more `password123`.

**Issue #35 — Cosmos SDK stabilized + central package management:**
Replaced `Microsoft.Azure.Cosmos 3.59.0-preview.0` with stable `3.58.0` across all 5 services. Created `Directory.Packages.props` at repo root for centralized version management of all shared NuGet packages (Cosmos, Azure.Identity, OpenTelemetry, xunit, etc.). Unified Azure.Identity from mixed 1.13.2/1.16.0 to 1.16.0.

**Issue #37 — Exception message leaking stopped:**
All `.NET` controllers now return generic error messages with `correlationId` (from `HttpContext.TraceIdentifier`). Full exceptions logged server-side. Business exceptions (duplicate email, insufficient funds) return safe messages. Standardized error response format: `{ error: string, correlationId?: string }`. Fixed `TransferService.FailureReason` to not persist raw `ex.Message` in Cosmos DB.

**Key files:**
- `src/user-service/Controllers/AdminController.cs` — removed `[AllowAnonymous]`, cleaned up error format
- `src/user-service/Program.cs` — `Admin__BootstrapEmail` bootstrap logic
- `src/user-service/Services/InMemoryUserService.cs` — configurable demo password
- `Directory.Packages.props` — centralized NuGet versions
- `src/account-service/Controllers/AccountsController.cs` — correlationId error handling
- `src/user-service/Controllers/AuthController.cs` — catch-all + correlationId
- `src/transaction-service/Controllers/TransactionsController.cs` — safe InsufficientFunds response
- `src/transfer-service/Services/TransferService.cs` — generic FailureReason
- `src/prompt-eval-service/Controllers/EvaluationsController.cs` — generic errors + correlationId

**Pattern:** All error responses follow `{ error: string, correlationId?: string }`. Business exceptions (known, user-safe) return the business message. Unknown exceptions return "An internal error occurred" with correlationId for log correlation.

### 2026-05 — Input validation constraints across all services (#45)

**Problem:** Request DTOs across all services lacked input validation constraints, allowing unbounded strings, missing required fields, and predictable account number generation via `System.Random`.

**Fix:**
- **.NET services:** Added `[Required]`, `[StringLength]`, `[Range]`, `[EmailAddress]`, `[RegularExpression]` attributes to all request DTOs in user-service, account-service, and prompt-eval-service. Shared DTOs (`RegisterUserRequest`, `CreateAccountRequest`, `CreateTransactionRequest`, `CreateTransferRequest`) already had validation — no changes needed.
- **Python services:** Added `Field()` constraints (`min_length`, `max_length`, `pattern`, `gt`) to all Pydantic request models in ai-service, budget-service, chatbot-service, and account-opening-service.
- **Security fix:** Replaced `new Random()` with `System.Security.Cryptography.RandomNumberGenerator.GetInt32()` in `AccountService.GenerateAccountNumber()` to prevent predictable account number enumeration.
- All `[ApiController]` attributes were already present — automatic 400 on ModelState errors is active.

**Key files:**
- `src/user-service/Controllers/UsersController.cs` — ChangePasswordRequest, SetAvatarRequest, SetCategoryPreferencesRequest
- `src/user-service/Controllers/AdminController.cs` — PromoteRequest
- `src/user-service/Controllers/AuthController.cs` — LoginRequest
- `src/account-service/Controllers/AccountsController.cs` — UpdateBalanceRequest
- `src/account-service/Services/AccountService.cs` — RandomNumberGenerator fix
- `src/prompt-eval-service/Models/Dtos.cs` — all request DTOs
- `src/ai-service/app/main.py` — DetectRequest, ReviewRequest, EvalRequest
- `src/budget-service/app/main.py` — TransactionEvent
- `src/chatbot-service/app/main.py` — ChatRequest
- `src/account-opening-service/app/models.py` — Address, Employment, ApplicationCreate
- `src/account-opening-service/app/routes.py` — ReviewRequest

**Pattern:** Shared .NET DTOs in `src/shared/Contracts/Dtos/` already have DataAnnotations validation. Service-local DTOs (defined in Controllers/ or Models/) need validation added manually. Python services use Pydantic `Field()` for the same purpose.

### 2026-05 — Deep Code Quality Audit (All Backend Services)

**Scope:** user-service, account-service, transaction-service, transfer-service, prompt-eval-service, event-processor (Go)

**Total findings: 64** — 6 🔴 Critical, 39 🟡 Medium, 19 🟢 Low

**Critical findings:**
- transaction-service: Transaction persisted before balance update — partial failure causes data inconsistency (`Services/TransactionService.cs:58-68,220-239`)
- transaction-service: `UpdateAccountBalanceAsync` swallows exceptions — balance not updated but txn recorded
- transaction-service: No account ownership check on `GetAccountTransactions` — authorization bypass
- transfer-service: `Encoding.UTF8.GetBytes(config["Jwt:Key"])` crashes on missing config (`Program.cs:61-65`)
- transfer-service: Cosmos DB config used without null checks — startup crash (`Services/TransferService.cs:36-44`)
- prompt-eval-service: Fire-and-forget `Task.Run` loses exceptions silently (`Services/EvaluationService.cs:56-70`)

**Cross-cutting anti-patterns (all services):**
1. No repository/data-access abstraction — every service talks directly to Cosmos containers
2. Swallowed exceptions in Redis publish / event handlers
3. Static health endpoints — no dependency checks
4. Magic strings instead of enums/constants for status, event types, claims
5. InMemory services duplicate business logic from Cosmos-backed services
6. No input validation on DTOs/request bodies
7. Hardcoded config fallbacks

**Full report:** `.squad/decisions/inbox/basher-code-audit.md`
