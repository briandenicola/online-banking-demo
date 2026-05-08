# Local Development Deployment Guide

[← Architecture](architecture.md) | [Home](README.md) | [Next: Azure Deployment →](deployment-azure.md)

## Quick Start

### 1. Prerequisites

- Docker 20.10+ & Docker Compose 2.0+
- Git, Node.js 18+ (for UI dev)
- 8GB RAM minimum, 10GB disk space

### 2. Start Services

```bash
git clone https://github.com/briandenicola/online-banking-demo.git
cd online-banking-demo

# Start all 9 services
docker-compose up -d --build

# Verify services running
docker-compose ps
```

### 3. Access Application

- **UI Application**: http://localhost:3000/
- **API Gateway**: http://localhost/
- **Health Check**: http://localhost/health

### 4. Seed Demo Data (Optional)

```bash
chmod +x scripts/seed-data.sh
./scripts/seed-data.sh

# Demo Credentials: demo@banking-demo.com / password123
```

## Service Ports Mapping

| Service | Port | Purpose |
|---------|------|---------|
| **API Gateway (NGINX)** | 80 | Main entry point for all API requests |
| **User Service** | 6001 | Authentication, user management, JWT token generation |
| **Account Service** | 6002 | Account lifecycle, balance queries |
| **Transaction Service** | 6003 | Transaction history, event publishing |
| **Transfer Service** | 6004 | Money transfer orchestration |
| **Chatbot Service** | 8001 | AI financial assistant (FastAPI) |
| **Anomaly Service** | 8002 | Fraud detection (FastAPI) |
| **Budget Service** | 8003 | Budget analysis (FastAPI) |
| **Redis** | 6380 | Cache, session store, event streaming |
| **UI Application** | 3000 | React frontend |

## Environment Variables (.env) Setup

### Quick Start (Defaults for Local Dev)

For local development, most variables have sensible defaults. You can run immediately with:

```bash
cp .env.example .env
# File is ready to use; no edits needed for basic local development
```

### Complete Configuration for Local Development

If you want to enable AI features or customize settings:

```bash
cp .env.example .env

# Edit .env with your values:
```

#### Authentication & Security

```bash
# JWT Secret - Change from default for production, but default works for local dev
Jwt__Key=YourSuperSecretKeyForJWTTokenGeneration12345

# JWT Token Issuer
Jwt__Issuer=user-service
```

#### Database

```bash
# Use in-memory database (recommended for local dev - no setup needed)
UseInMemoryDatabase=true

# To use a real database instead, set to false and configure connection:
# UseInMemoryDatabase=false
# COSMOS_CONNECTION_STRING=DefaultEndpoint=https://...;AccountKey=...;
```

#### Redis (Event Bus & Caching)

```bash
# Local Redis - docker-compose runs Redis internally on port 6379
# Accessible from other containers as 'redis:6379'
# Externally exposed on 'localhost:6380'
REDIS__CONNECTIONSTRING=redis:6379
```

#### Service-to-Service URLs

```bash
# Inter-service communication within Docker network
Services__AccountService=http://account-service:8080
Services__TransactionService=http://transaction-service:8080
```

#### Azure Services (Optional for Local Dev)

If you want to test AI features locally using Azure services:

```bash
# Azure Identity - Required if using Azure AI services
AZURE_TENANT_ID=<your-tenant-id>
AZURE_CLIENT_ID=<your-client-id>
AZURE_CLIENT_SECRET=<your-client-secret>  # Only for service principal; use managed identity in production

# Azure OpenAI - For anomaly detection and budget analysis AI features
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_MODEL=gpt-4o-mini

# Azure AI Agents - For advanced chatbot features (optional)
AZURE_AI_AGENTS_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/

# Application Insights - Optional telemetry (leave blank for local dev)
APPLICATIONINSIGHTS_CONNECTION_STRING=
```

### Minimal `.env` for Local Development

If you just want to run the app without AI features:

```bash
# Only JWT secret is truly required; docker-compose provides defaults for everything else
Jwt__Key=YourSuperSecretKeyForJWTTokenGeneration12345
UseInMemoryDatabase=true
```

## Using Seed Script

The `scripts/seed-data.sh` populates demo data (idempotent):

```bash
./scripts/seed-data.sh

# Creates:
# - Demo users (john_doe, jane_smith, etc.)
# - Checking/savings accounts with initial balances
# - Sample transfers between accounts

# Expected credentials: demo@banking-demo.com / password123
```

## API Documentation

### Swagger UI

- User Service: http://localhost/api/users/swagger/index.html
- Account Service: http://localhost/api/accounts/swagger/index.html
- Transaction Service: http://localhost/api/transactions/swagger/index.html
- Transfer Service: http://localhost/api/transfers/swagger/index.html

### FastAPI Docs

- Chatbot: http://localhost/api/chat/docs
- Anomaly Detection: http://localhost/api/anomaly/docs
- Budget Analysis: http://localhost/api/budget/docs

### API Authentication

```bash
# Get JWT token
TOKEN=$(curl -s -X POST http://localhost/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"password123"}' | jq -r '.token')

# Use token in requests
curl http://localhost/api/accounts/ \
  -H "Authorization: Bearer $TOKEN"
```

## Development Workflow

### Hot Reload for .NET Services

```bash
# Terminal 1: Keep Docker services running
docker-compose up -d

# Terminal 2: Run service with hot reload
cd src/user-service
dotnet watch run
```

### Hot Reload for Python Services

```bash
# Terminal 1: Keep Docker services running
docker-compose up -d

# Terminal 2: Run with auto-reload
cd src/chatbot-service
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

### Hot Reload for React UI

```bash
# Terminal 1: Keep Docker services running (skip ui-app)
docker-compose up -d --no-build

# Terminal 2: Start React dev server
cd src/ui-app
npm install
npm start
```

## Troubleshooting

### Port Already in Use

```bash
# Find what's using the port (e.g., port 80)
sudo lsof -i :80

# Change NGINX port in docker-compose.yml or use override
docker-compose -f docker-compose.yml -f docker-compose.override.yml up
```

### Out of Memory

```bash
# Increase Docker resources:
# Docker Desktop → Preferences → Resources → Memory (8GB+)

# Or run fewer services
docker-compose up -d user-service account-service redis
```

### Redis Connection Failed

```bash
# Check Redis is running and healthy
docker-compose ps redis

# Reset Redis
docker-compose down -v
docker-compose up -d redis
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f user-service

# Last 100 lines
docker-compose logs --tail=100
```

## Cleanup

```bash
# Stop all services
docker-compose down

# Remove containers and volumes
docker-compose down -v

# Remove all images
docker rmi $(docker images | grep banking | awk '{print $3}')
```

## Next Steps

1. Explore APIs using Swagger documentation
2. Check `docs/architecture.md` for system design
3. See `docs/deployment-azure.md` for cloud deployment
4. Follow "Development Workflow" section for local code changes

---

**Last Updated**: May 2026  
**Tested On**: Docker 25+, Docker Compose 2.0+

---

[← Architecture](architecture.md) | [Home](README.md) | [Next: Azure Deployment →](deployment-azure.md)
