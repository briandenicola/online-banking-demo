# Quickstart: AI Admin Portal (US5)

## Prerequisites
- .NET 9 SDK
- Access to Azure AI Foundry endpoint (or `FOUNDRY_PROJECT_ENDPOINT` env var)
- Running Cosmos DB instance (or emulator)
- Existing admin user account (role = "Admin")

## Local Development

```bash
# 1. Start dependencies
docker-compose up -d redis cosmos-db

# 2. Run the prompt-eval-service
cd src/prompt-eval-service
dotnet run

# Service starts on http://localhost:5280
# Swagger UI: http://localhost:5280/swagger
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `FOUNDRY_PROJECT_ENDPOINT` | Azure AI Foundry endpoint | `https://xxx.services.ai.azure.com` |
| `FOUNDRY_MODEL` | Model deployment name | `gpt-5.4-mini` |
| `CosmosDb__Endpoint` | Cosmos DB endpoint | `https://xxx.documents.azure.com:443/` |
| `CosmosDb__DatabaseId` | Cosmos DB database name | `banking-demo` |
| `JWT__SecretKey` | JWT signing key (local dev) | `your-secret-key` |
| `AI_SERVICE_URL` | ai-service base URL | `http://ai-service:80` |

## Key Workflows

### 1. Create a Prompt Template
```bash
curl -X POST http://localhost:5280/api/evaluations/prompts \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Risk Scoring Test","target":"risk-scoring","systemPrompt":"You are a financial security expert..."}'
```

### 2. Run an Evaluation
```bash
curl -X POST http://localhost:5280/api/evaluations/run \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"templateId":"<template-id>","transactionIds":["tx1","tx2","tx3"]}'
```

### 3. Check Results
```bash
curl http://localhost:5280/api/evaluations/<run-id> \
  -H "Authorization: Bearer <admin-jwt>"
```

## Cloud Deployment

```bash
# Build and push to ACR
az acr build --registry $ACR_NAME --image prompt-eval-service:latest -f ./src/prompt-eval-service/Dockerfile .

# Apply K8s manifests
kubectl apply -f deploy/kustomize/base/prompt-eval-service.yaml
```
