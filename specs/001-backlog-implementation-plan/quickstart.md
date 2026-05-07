# Quickstart: Online Banking Demo

**Time to running**: ~15 minutes (local) | ~30 minutes (cloud)

## Prerequisites

- Docker Desktop (or Podman)
- Node.js 18+ (for UI development)
- .NET 8 SDK (for backend services)
- Go 1.22+ (for event-processor)
- Python 3.11+ (for AI services)
- Task (taskfile.dev) — `brew install go-task`
- kubectl + Azure CLI (for cloud deployment)

## Local Development (docker-compose)

```bash
# Clone and start all services
git clone https://github.com/briandenicola/online-banking-demo.git
cd online-banking-demo
cp .env.example .env

# Start all services (Redis, Cosmos emulator, all microservices)
docker-compose up -d

# Verify health
curl http://localhost:8080/api/users/health   # user-service
curl http://localhost:8080/api/accounts/health # account-service
curl http://localhost:3000                      # UI (React dev server)
```

**Note**: Local mode uses key-based auth (no Entra). The `AZURE_CLIENT_ID` env var is NOT set in docker-compose, triggering connection-string auth mode.

## Cloud Deployment (AKS)

```bash
# 1. Provision infrastructure
task -t Taskfile.cloud.yml up

# 2. Build and push containers
task -t Taskfile.cloud.yml build

# 3. Deploy cluster config (Istio, network policies)
task -t Taskfile.cloud.yml deploy:cluster-config

# 4. Deploy application
task -t Taskfile.cloud.yml deploy

# 5. Verify
kubectl get pods -n banking-demo  # All should show Running 2/2
```

## Running Tests

```bash
# .NET unit tests
dotnet test src/user-service.Tests/
dotnet test src/account-service.Tests/
dotnet test src/transfer-service.Tests/

# Python tests
cd src/anomaly-service && pytest
cd src/budget-service && pytest

# React tests
cd src/ui-app && CI=true npx react-scripts test --watchAll=false

# E2E tests (requires running services)
cd tests/e2e && npx playwright test
```

## Service Map

| Service | Port | Language | Role |
|---------|------|----------|------|
| user-service | 8080 | .NET 8 | Auth, user CRUD, roles |
| account-service | 8080 | .NET 8 | Account CRUD |
| transaction-service | 8080 | .NET 8 | Transaction history |
| transfer-service | 8080 | .NET 8 | Fund transfers |
| event-processor | 8080 | Go | Redis Streams consumer |
| chatbot-service | 8001 | Python | AI chatbot |
| anomaly-service | 8002 | Python | Anomaly detection |
| budget-service | 8003 | Python | Budget analysis |
| ui-app | 80 | React | Frontend SPA |
