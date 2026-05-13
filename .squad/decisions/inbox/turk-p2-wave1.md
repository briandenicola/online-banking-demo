# Turk P2 Wave 1 Decisions

## Env var naming (Issue #108)
- Python/FastAPI services standardized on SCREAMING_SNAKE_CASE env vars (JWT_KEY/JWT_ISSUER/JWT_AUDIENCE, REDIS_CONNECTION_STRING, COSMOS_DB_ENDPOINT).
- Kustomize now wires these names directly from existing secrets/configmap entries, and configmap includes COSMOS_DB_ENDPOINT for Cosmos DB routing.
- docker-compose/.env.example/docs updated to reflect the new names without changing .NET env var conventions.

## Layered architecture extraction (Issue #93)
- main.py now only wires app/middleware/routers/lifespan per service.
- Added per-service config.py (logging/telemetry), models/, services/, routes/ packages for separation of concerns.
- Service modules hold shared state (e.g., analyzer pipeline, agent sessions, in-memory stores) to preserve existing behavior.

## Go slog adoption (Issue #106)
- event-processor now uses stdlib slog with JSON handler and structured key/value logging.
- Replaced log.Printf/Println/Fatalf with slog equivalents to align with structured logging across services.
