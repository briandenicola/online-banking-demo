# Transfer Service

Peer-to-peer and account transfer service with transfer record management.

## Purpose

Initiates fund transfers between accounts, validates transfer eligibility, and maintains transfer records. Coordinates with transaction-service for actual fund movements.

## Technology Stack

- .NET 9.0 (C#)
- ASP.NET Core Web API
- Entity Framework Core
- Azure Cosmos DB (or in-memory for local dev)
- Redis (for distributed caching)
- JWT authentication

## API Endpoints

### Transfers
- `POST /api/transfers` — Initiate new transfer
- `GET /api/transfers/{id}` — Get transfer by ID

### Health
- `GET /healthz` — Health check
- `GET /readyz` — Readiness check
- `GET /swagger` — Swagger/OpenAPI UI

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `Jwt__Key` | JWT signing key (must match user-service) | (required) |
| `Jwt__Issuer` | JWT issuer | `user-service` |
| `Jwt__Audience` | JWT audience | `banking-demo` |
| `Redis__ConnectionString` | Redis connection string | (required) |
| `UseInMemoryDatabase` | Use in-memory DB instead of Cosmos | `false` |
| `CosmosDb__Endpoint` | Cosmos DB endpoint | (required if not in-memory) |
| `CosmosDb__ConnectionString` | Cosmos DB connection string | (required if not in-memory) |
| `CosmosDb__DatabaseName` | Database name | `BankingDemo` |
| `CosmosDb__ContainerName` | Container name | `Transfers` |

### appsettings.json

See `appsettings.json` and `appsettings.Development.json` for full configuration schema.

## Local Development

### Prerequisites
- .NET 9.0 SDK
- Azure Cosmos DB Emulator (or use `UseInMemoryDatabase=true`)
- Redis instance

### Run Locally

```bash
cd src/transfer-service
dotnet restore
dotnet run
```

Service will start on `http://localhost:6004`.

### Docker

```bash
docker build -t transfer-service .
docker run -p 6004:8080 -e Jwt__Key=<your-key> transfer-service
```

## Testing

```bash
cd src/transfer-service.Tests
dotnet test
```

See `../transfer-service.Tests/` for unit and integration tests.

## Notes

- All endpoints require JWT authentication
- Transfer validation includes source account balance checks
- Redis used for caching transfer data
- Cosmos DB partition key is `transferId`
- Transfers are atomic operations coordinated with transaction-service
