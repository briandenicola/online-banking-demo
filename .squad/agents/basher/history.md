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
