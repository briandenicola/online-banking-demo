# Decision: .NET Exception Handling Patterns (#88, #90, #91)

**Date:** 2026-05-12
**Author:** Basher (Backend Dev)
**Priority:** P1
**Status:** Implemented

## Context

Three related issues identified across .NET services:
1. Broad `catch (Exception)` blocks swallowing failures in Redis publish and transfer flows
2. No global exception-handling middleware — raw 500s with stack traces in production
3. Cosmos DB init in account-opening-service silently falling back to in-memory on any error

## Decisions

### 1. Shared GlobalExceptionHandlerMiddleware (Issue #90)

All .NET services now use `UseGlobalExceptionHandler()` from `Banking.Observability`. This establishes a **single, standardized error response shape** across all services:

```json
{
  "error": "InternalError",
  "message": "An unexpected error occurred. Please try again later.",
  "statusCode": 500
}
```

**Exception-to-status mapping:**
| Exception Type | HTTP Status | Error Code |
|---|---|---|
| ArgumentException / ArgumentNullException | 400 | ValidationError |
| UnauthorizedAccessException | 401 | Unauthorized |
| InvalidOperationException | 422 | OperationFailed |
| KeyNotFoundException | 404 | NotFound |
| OperationCanceledException | 503 | RequestCancelled |
| Everything else | 500 | InternalError |

**Pipeline placement:** After `UseCorrelationId()`, before `UseCors()`. This ensures correlation IDs are available for error logging.

**Stack trace policy:** Full exception messages shown in Development; generic message in production to prevent info leakage.

### 2. Specific Exception Catches (Issue #88)

**Pattern for fire-and-forget Redis publishes:** Catch `RedisConnectionException` and `RedisException` only. Let unexpected exceptions propagate to the global handler. This is intentional — event publishing should not break the main operation (transaction/transfer), but serialization errors or null refs should surface.

**Pattern for business-critical operations (transfers):** Catch `HttpRequestException`, `InvalidOperationException`, `CosmosException` separately with distinct failure reasons. Inner persist-failure catches narrowed to `CosmosException` only.

### 3. Production-Fail-Fast for Cosmos Init (Issue #91)

**Rule:** When `AZURE_CLIENT_ID` is set (production/Azure), Cosmos init failures must abort startup. Silent degradation to in-memory is only acceptable in local/dev mode.

**Specific exceptions caught:** `CosmosHttpResponseError`, `ConnectionError`/`OSError`, then `Exception` as final fallback — all with the production-vs-dev branching.

**Verification:** .NET services do NOT have this anti-pattern — they use an explicit `UseInMemoryDatabase` configuration toggle, not exception-based fallback.

## Convention Going Forward

- **New services** must register `UseGlobalExceptionHandler()` in their pipeline
- **Catch blocks** should target the most specific exception type; use the global handler as the safety net for unexpected failures
- **Error response shape** `{ error, message, statusCode }` is the standard for all .NET services — do not deviate
- **Production startup:** Infrastructure dependencies (Cosmos, Redis) must fail-fast in production; silent fallbacks are dev-only
