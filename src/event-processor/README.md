# Event Processor

Background event consumer for banking event streams and audit logging.

## Purpose

Consumes banking events from Redis Streams, emits a structured audit record per recognised event
type, and handles a dead letter queue for failed events. Runs as a standalone background worker.

## Technology Stack

- Go 1.22+
- Redis Streams
- OpenTelemetry
- Entra ID authentication

## Audit durability — read this before relying on it

**This service does not persist audit records to a database.** It has no Cosmos DB dependency;
`go.mod` carries Redis, OpenTelemetry and `azidentity` only.

Each recognised event is emitted as a structured `slog` record to stdout (see `processMessage`),
plus an OpenTelemetry span. Durability is therefore whatever the surrounding platform provides —
container log retention, and Application Insights when
`APPLICATIONINSIGHTS_CONNECTION_STRING` is configured. Nothing here is queryable as a system of
record, and an unrecognised event type falls through to the default branch and is acknowledged
without an audit line.

This is a deliberate scope boundary for the demo, not an oversight, and it is recorded here so the
gap is visible rather than assumed closed. Two consequences worth stating plainly:

- **Do not cite this service as the audit system of record.** The authority/approval chain keeps
  its own durable trail; this stream is observability, not evidence.
- **Log retention is the retention policy.** If audit records must outlive the pod's logs, that
  requires a persistence layer this service does not currently have.

Related: #335 (event types published but unaudited).

## API Endpoints

### Health (internal HTTP server)
- `GET /healthz` — Health check
- `GET /readyz` — Readiness check

*Note: This is a background worker; health endpoints are for Kubernetes liveness/readiness probes only.*

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS__CONNECTIONSTRING` | Redis connection string | (required) |
| `DLQ_MAX_RETRIES` | Dead letter queue retry limit | `3` |
| `AZURE_CLIENT_ID` | Azure Entra client ID for auth | (required) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights connection string | (optional) |
| `APPINSIGHTS_INSTRUMENTATIONKEY` | App Insights key | (optional) |

## Local Development

### Prerequisites
- Go 1.22+
- Redis instance with Streams enabled

### Run Locally

```bash
cd src/event-processor
go mod download
go run main.go
```

Service will start and consume events from Redis Streams. Health server runs on port `8080`.

### Docker

```bash
docker build -t event-processor .
docker run --env-file .env event-processor
```

## Event Processing

1. Listens to Redis Stream: `banking-events`
2. Processes event types:
   - User registration
   - Login/logout
   - Account creation
   - Transaction creation
   - Transfer initiation
   - Admin actions
3. Emits a structured `slog` audit record per recognised event type (see "Audit durability" above —
   these go to stdout, not to a database)
4. Failed events retry with exponential backoff
5. After max retries, moves to dead letter queue: `banking-events:dlq`

## Notes

- Runs as a long-lived background process
- No authentication required (internal service)
- Uses Redis consumer groups for at-least-once delivery
- OpenTelemetry traces all event processing
- Audit records are structured logs, not database rows — there is no partition key and nothing to
  query. See "Audit durability" above.
- DLQ events require manual intervention to reprocess
