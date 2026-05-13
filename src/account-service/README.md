# Account Service

Account management service handling CRUD operations and balance management for bank accounts.

## Purpose

Manages bank accounts for authenticated users. Provides account creation, retrieval, balance updates, and account number lookups.

## Technology Stack

- .NET 9.0 (C#)
- ASP.NET Core Web API
- Entity Framework Core
- Azure Cosmos DB (or in-memory for local dev)
- JWT authentication

## API Endpoints

### Accounts
- `POST /api/accounts` — Create new account
- `GET /api/accounts` — List accounts for authenticated user
- `GET /api/accounts/{id}` — Get account by ID
- `GET /api/accounts/number/{accountNumber}` — Get account by account number
- `POST /api/accounts/{id}/balance` — Update account balance

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
| `UseInMemoryDatabase` | Use in-memory DB instead of Cosmos | `false` |
| `CosmosDb__Endpoint` | Cosmos DB endpoint | (required if not in-memory) |
| `CosmosDb__ConnectionString` | Cosmos DB connection string | (required if not in-memory) |
| `CosmosDb__DatabaseName` | Database name | `BankingDemo` |
| `CosmosDb__ContainerName` | Container name | `Accounts` |

### appsettings.json

See `appsettings.json` and `appsettings.Development.json` for full configuration schema.

## Local Development

### Prerequisites
- .NET 9.0 SDK
- Azure Cosmos DB Emulator (or use `UseInMemoryDatabase=true`)

### Run Locally

```bash
cd src/account-service
dotnet restore
dotnet run
```

Service will start on `http://localhost:6002`.

### Docker

```bash
docker build -t account-service .
docker run -p 6002:8080 -e Jwt__Key=<your-key> account-service
```

## Testing

```bash
cd src/account-service.Tests
dotnet test
```

See `../account-service.Tests/` for unit and integration tests.

## Notes

- All endpoints require JWT authentication from user-service
- Account numbers are auto-generated
- Cosmos DB partition key is `accountId`
- Balance updates are atomic operations
