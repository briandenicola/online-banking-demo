# Prompt Evaluation Service

Prompt template management and evaluation service for AI models.

## Purpose

Manages prompt templates for AI services and orchestrates evaluation runs. Enables A/B testing of prompts, stores evaluation results, and provides comparison analytics. Used by ai-service for prompt experimentation.

## Technology Stack

- .NET 9.0 (C#)
- ASP.NET Core Web API
- Entity Framework Core
- Azure Cosmos DB
- JWT authentication

## API Endpoints

### Prompt Management
- `GET /api/evaluations/prompts` — List all prompt templates
- `GET /api/evaluations/prompts/{id}` — Get prompt by ID
- `POST /api/evaluations/prompts` — Create new prompt template
- `PUT /api/evaluations/prompts/{id}` — Update prompt template
- `DELETE /api/evaluations/prompts/{id}` — Delete prompt template

### Evaluation Runs
- `POST /api/evaluations/run` — Start new evaluation run
- `GET /api/evaluations` — List all evaluation runs
- `GET /api/evaluations/{id}` — Get evaluation run details
- `GET /api/evaluations/compare` — Compare multiple evaluation runs

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
| `AI_SERVICE_URL` | AI service base URL for evaluation runs | (required) |
| `CosmosDb__Endpoint` | Cosmos DB endpoint | (required) |
| `CosmosDb__ConnectionString` | Cosmos DB connection string | (required) |
| `CosmosDb__DatabaseName` | Database name | `BankingDemo` |
| `CosmosDb__PromptTemplatesContainer` | Prompt templates container | `prompt-templates` |
| `CosmosDb__EvaluationRunsContainer` | Evaluation runs container | `evaluation-runs` |

### appsettings.json

See `appsettings.json` for full configuration schema.

## Local Development

### Prerequisites
- .NET 9.0 SDK
- Azure Cosmos DB instance

### Run Locally

```bash
cd src/prompt-eval-service
dotnet restore
dotnet run
```

Service will start on `http://localhost:5280`.

### Docker

```bash
docker build -t prompt-eval-service .
docker run -p 5280:8080 --env-file .env prompt-eval-service
```

## Testing

```bash
cd src/prompt-eval-service.Tests
dotnet test
```

See `../prompt-eval-service.Tests/` for unit and integration tests.

## Evaluation Workflow

1. Create prompt templates via `POST /api/evaluations/prompts`
2. Define test dataset (transaction samples)
3. Run evaluation via `POST /api/evaluations/run` with prompt IDs
4. Service calls ai-service with each prompt variant
5. Results stored in Cosmos DB with metrics (accuracy, latency, cost)
6. Compare runs via `GET /api/evaluations/compare`

## Notes

- All endpoints require JWT authentication with admin role
- Prompt templates support variables (e.g., `{{transaction.amount}}`)
- Evaluation runs are async and may take several minutes
- Cosmos DB partition key is `templateId` for prompts, `runId` for evaluations
- Used for A/B testing and prompt optimization in production
