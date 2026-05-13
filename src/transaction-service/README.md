# Transaction Service

Transaction recording and retrieval service with balance validation.

## Purpose

Records financial transactions, validates balances, prevents insufficient funds, and provides transaction history queries. Integrates with Redis for caching.

## Technology Stack

- .NET 9.0 (C#)
- ASP.NET Core Web API
- Entity Framework Core
- Azure Cosmos DB (or in-memory for local dev)
- Redis (for distributed caching)
- JWT authentication

## API Endpoints

### Transactions
- `POST /api/transactions` — Create new transaction
- `GET /api/transactions/{id}` — Get transaction by ID
- `GET /api/transactions` — List all transactions (admin)
- `GET /api/transactions/my` — List transactions for authenticated user
- `GET /api/transactions/account/{accountId}` — List transactions for specific account

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
| `CosmosDb__ContainerName` | Container name | `Transactions` |

### appsettings.json

See `appsettings.json` and `appsettings.Development.json` for full configuration schema.

## Local Development

### Prerequisites
- .NET 9.0 SDK
- Azure Cosmos DB Emulator (or use `UseInMemoryDatabase=true`)
- Redis instance

### Run Locally

```bash
cd src/transaction-service
dotnet restore
dotnet run
```

Service will start on `http://localhost:6003`.

### Docker

```bash
docker build -t transaction-service .
docker run -p 6003:8080 -e Jwt__Key=<your-key> transaction-service
```

## Testing

```bash
cd src/transaction-service.Tests
dotnet test
```

See `../transaction-service.Tests/` for unit and integration tests.

## Notes

- All endpoints require JWT authentication
- Transaction validation includes balance checks
- Redis used for caching transaction data
- Cosmos DB partition key is `accountId` for efficient queries
- Insufficient funds are rejected with appropriate error codes
