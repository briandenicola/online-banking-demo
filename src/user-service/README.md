# User Service

Authentication and user profile management service for the Online Banking Demo.

## Purpose

Handles user registration, authentication (JWT-based), profile management, and admin operations. Provides bootstrap admin promotion and audit logging for security-critical operations.

## Technology Stack

- .NET 9.0 (C#)
- ASP.NET Core Web API
- Entity Framework Core
- Azure Cosmos DB (or in-memory for local dev)
- Redis (for distributed caching)
- JWT authentication

## API Endpoints

### Authentication
- `POST /api/auth/register` — Register new user
- `POST /api/auth/login` — Login and receive JWT token

### User Self-Service
- `POST /api/users/register` — Alternative registration endpoint
- `GET /api/users/me` — Get current user profile
- `PUT /api/users/me/password` — Update own password
- `GET /api/users/{id}` — Get user by ID (authenticated)

### Admin Operations
- `POST /api/admin/promote` — Promote bootstrap admin
- `GET /api/admin/users` — List all users
- `PUT /api/admin/users/{id}/lock` — Lock user account
- `PUT /api/admin/users/{id}/unlock` — Unlock user account
- `PUT /api/admin/users/{id}/reset-password` — Reset user password
- `DELETE /api/admin/users/{id}` — Delete user
- `GET /api/admin/login-audits` — View login audit logs

### Health
- `GET /healthz` — Health check
- `GET /readyz` — Readiness check
- `GET /swagger` — Swagger/OpenAPI UI

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `Jwt__Key` | JWT signing key | (required) |
| `Jwt__Issuer` | JWT issuer | `user-service` |
| `Jwt__Audience` | JWT audience | `banking-demo` |
| `Jwt__ExpiresInMinutes` | Token expiration time | `60` |
| `ACCOUNT_SERVICE_URL` | Account service base URL | (required) |
| `UseInMemoryDatabase` | Use in-memory DB instead of Cosmos | `false` |
| `Admin__BootstrapEmail` | Bootstrap admin email | (optional) |
| `CosmosDb__Endpoint` | Cosmos DB endpoint | (required if not in-memory) |
| `CosmosDb__ConnectionString` | Cosmos DB connection string | (required if not in-memory) |
| `CosmosDb__DatabaseName` | Database name | `BankingDemo` |
| `CosmosDb__ContainerName` | Container name | `Users` |
| `Redis__ConnectionString` | Redis connection string | (required) |

### appsettings.json

See `appsettings.json` and `appsettings.Development.json` for full configuration schema.

## Local Development

### Prerequisites
- .NET 9.0 SDK
- Azure Cosmos DB Emulator (or use `UseInMemoryDatabase=true`)
- Redis instance

### Run Locally

```bash
cd src/user-service
dotnet restore
dotnet run
```

Service will start on `http://localhost:6001`.

### Docker

```bash
docker build -t user-service .
docker run -p 6001:8080 -e Jwt__Key=<your-key> user-service
```

## Testing

```bash
cd src/user-service.Tests
dotnet test
```

See `../user-service.Tests/` for unit and integration tests.

## Notes

- First user registered via `/api/admin/promote` with bootstrap email becomes admin
- All endpoints except `/auth/register` and `/auth/login` require JWT authentication
- Redis used for caching user data and rate limiting
- Cosmos DB stores user records with partition key on `userId`
