# Decision: Repository/Data-Access Abstraction (Issue #89)

**Date:** 2026-05-12
**Author:** Basher (backend specialist)
**Status:** Implemented

## Context

All 5 .NET services (user, account, transaction, transfer, prompt-eval) directly used `CosmosClient`, `Container`, and `IConnectionMultiplexer` in their service classes. This tight coupling meant:

- No seam for unit testing without infrastructure
- Business logic intertwined with data-access concerns
- No abstraction for caching, retry policies, or future storage migration

## Decision

Extract repository interfaces and implementations for each service:

| Service | Interfaces Created | Implementations |
|---------|-------------------|-----------------|
| user-service | `IUserRepository`, `ILoginAuditRepository`, `IEventPublisher` | `CosmosUserRepository`, `CosmosLoginAuditRepository`, `RedisEventPublisher` |
| account-service | `IAccountRepository` | `CosmosAccountRepository` |
| transaction-service | `ITransactionRepository`, `IAccountBalanceRepository`, `IEventPublisher` | `CosmosTransactionRepository`, `CosmosAccountBalanceRepository`, `RedisEventPublisher` |
| transfer-service | `ITransferRepository`, `IEventPublisher` | `CosmosTransferRepository`, `RedisEventPublisher` |
| prompt-eval-service | `IPromptTemplateRepository`, `IEvaluationRunRepository` | `CosmosPromptTemplateRepository`, `CosmosEvaluationRunRepository` |

## Design Principles

1. **Repository owns data access only** — no business logic in repositories. Queries, reads, writes, deletes.
2. **Service owns business logic** — validation, password hashing, event composition, error handling stay in the service layer.
3. **Event publishing abstracted** — `IEventPublisher` decouples Redis Stream details from service logic.
4. **Separate repositories for separate containers** — transaction-service has `ITransactionRepository` (transactions container) and `IAccountBalanceRepository` (accounts container), keeping concerns distinct.
5. **DI registrations mirror existing patterns** — repositories registered as `Scoped` (matching service lifetime), except `IEventPublisher` which is `Singleton` (matching `IConnectionMultiplexer`).

## Files Changed

- `src/*/Repositories/` — new interface + implementation files (6 services × 1-3 repos each)
- `src/*/Services/*Service.cs` — updated constructors to accept repository interfaces
- `src/*/Program.cs` — added DI registrations for repositories
- `src/prompt-eval-service/Services/EvaluationBackgroundService.cs` — replaced direct `CosmosClient` with `IEvaluationRunRepository`

## What Was NOT Changed

- **InMemory*Service implementations** — these are already separate implementations of the service interfaces and don't use Cosmos/Redis directly in the same way
- **Program.cs startup logic** (e.g., user-service bootstrap admin promotion) — this remains direct CosmosClient usage as it runs outside the DI-managed request scope
- **No behavior changes** — this is a pure structural refactoring

## Risks

- None significant. All changes are additive (new files) or structural (constructor injection). No behavioral changes.
