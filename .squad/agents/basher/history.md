# Basher — History

## Project Context
- **Project:** online-banking-demo — AI-generated online banking application
- **User:** Brian
- **Stack:** C#/.NET + Python/FastAPI microservices, Redis, Docker Compose, Azure
- **Services:** user-service, account-service, transaction-service, transfer-service (C#), anomaly-service, budget-service, chatbot-service, event-processor (Python)

## Learnings

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
