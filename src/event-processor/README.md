# Event Processor

Background event consumer for banking event streams and audit logging.

## Purpose

Consumes banking events from Redis Streams, processes them for audit logging and analytics, and handles dead letter queue for failed events. Runs as a standalone background worker.

## Technology Stack

- Go 1.22+
- Redis Streams
- Azure Cosmos DB (audit log storage)
- OpenTelemetry
- Entra ID authentication

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
- Azure Cosmos DB for audit logs

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
3. Writes audit records to Cosmos DB
4. Failed events retry with exponential backoff
5. After max retries, moves to dead letter queue: `banking-events:dlq`

## Notes

- Runs as a long-lived background process
- No authentication required (internal service)
- Uses Redis consumer groups for at-least-once delivery
- OpenTelemetry traces all event processing
- Cosmos DB partition key is `eventType` for efficient queries
- DLQ events require manual intervention to reprocess
