# Online Banking Demo

A microservices-based online banking application demonstrating agentic capabilities with .NET, Python, Go, and cloud-native Azure services.

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Git, Node.js 18+ (for UI development)
- 8GB RAM, 10GB disk space

### Running Locally

```bash
# Clone the repository
git clone https://github.com/briandenicola/online-banking-demo.git
cd online-banking-demo

# Start all services
docker-compose up -d --build

# Check services are running
docker-compose ps

# Seed demo data (optional)
chmod +x scripts/seed-data.sh
./scripts/seed-data.sh
```

### Access Points

- **React UI**: http://localhost:3000/
- **API Gateway**: http://localhost/
- **Health Check**: http://localhost/health
- **Demo Credentials**: demo@banking-demo.com / password123 (after seed)

## Documentation

Comprehensive guides for local development and cloud deployment:

- **[Local Development Deployment](docs/deployment-local.md)** — Quick start guide for Docker Compose setup, environment variables, service ports, troubleshooting, and development workflows (hot reload)

- **[Azure Cloud Deployment](docs/deployment-azure.md)** — Production deployment guide with Terraform infrastructure provisioning, AKS setup, Flux GitOps, secrets management, CI/CD pipeline, and cost considerations

- **[System Architecture](docs/architecture.md)** — Detailed architecture documentation with service map, communication patterns, authentication flow, event pipeline, scaling considerations, security, and monitoring

## Architecture

The Online Banking Demo showcases a modern microservices architecture with cloud-native patterns and agentic AI capabilities.

```
┌──────────────────────────────────────────────────────────────┐
│                    External Users / Clients                  │
└───────────────────┬────────────────────────────────────────┘
                    │
        ┌───────────▼─────────────┐
        │   NGINX API Gateway     │
        │  (Port 80, Port 3000)   │
        └───────────┬─────────────┘
                    │
     ┌──────────────┼──────────────┐
     │              │              │
┌────▼────┐   ┌────▼────┐   ┌────▼────┐
│ React   │   │  .NET   │   │ Python  │
│   UI    │   │  Core   │   │ Agents  │
│ (3000)  │   │Services │   │Services │
└─────────┘   │(6001-   │   │(8001-  │
              │ 6004)   │   │ 8003)   │
              └────┬────┘   └────┬────┘
                   │            │
                   └────┬───────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
    ┌───▼───┐     ┌────▼────┐   ┌────▼────┐
    │ Redis │     │Cosmos DB│   │Event    │
    │Streams│     │  (SQL)  │   │Processor│
    │(6380) │     │         │   │         │
    └───────┘     └─────────┘   └─────────┘
```

### Services (9 Total)

**Core .NET Microservices** (REST/HTTP, JWT-authenticated):
- **User Service** (6001) — Authentication, JWT token generation, user profiles
- **Account Service** (6002) — Account lifecycle, balance queries
- **Transaction Service** (6003) — Transaction history, event publishing
- **Transfer Service** (6004) — Money transfer orchestration, inter-service calls

**Python Agent Services** (FastAPI, AI-powered):
- **Chatbot Service** (8001) — AI financial advisor powered by Azure OpenAI
- **Anomaly Service** (8002) — Real-time fraud detection and risk scoring
- **Budget Service** (8003) — Spending analysis and financial health insights

**Infrastructure Services**:
- **Event Processor** (Go) — Redis Streams consumer, async event routing
- **API Gateway** (NGINX, Port 80) — Request routing, load balancing
- **UI Application** (React, Port 3000) — Web interface
- **Redis** (Port 6380) — Cache, session store, event streaming (banking-events stream)

### Key Features

- **Event-Driven**: Redis Streams (`banking-events`) for inter-service communication
- **JWT Authentication**: Tokens issued by User Service, validated across services
- **Agentic AI**: Chatbot, anomaly detection, budget analysis powered by Azure OpenAI
- **Cloud-Ready**: Designed for Azure AKS with Flux GitOps and Terraform IaC
- **Microservices**: Clear separation of concerns with independent deployment

## API Documentation

Access Swagger/OpenAPI documentation:

- **User Service**: http://localhost/api/users/swagger/index.html
- **Account Service**: http://localhost/api/accounts/swagger/index.html
- **Transaction Service**: http://localhost/api/transactions/swagger/index.html
- **Transfer Service**: http://localhost/api/transfers/swagger/index.html
- **Chatbot Service**: http://localhost/api/chat/docs (FastAPI)
- **Anomaly Service**: http://localhost/api/anomaly/docs (FastAPI)
- **Budget Service**: http://localhost/api/budget/docs (FastAPI)

### API Authentication

All protected endpoints require a JWT token:

```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"password123"}' | jq -r '.token')

# Use token in requests
curl http://localhost/api/accounts/ \
  -H "Authorization: Bearer $TOKEN"
```

## Project Structure

```
online-banking-demo/
├── docs/
│   ├── deployment-local.md      # Local Docker Compose deployment guide
│   ├── deployment-azure.md      # Azure AKS + Flux GitOps deployment guide
│   └── architecture.md          # Detailed system architecture documentation
├── deploy/
│   ├── flux/                    # GitOps configuration (Flux CD)
│   │   ├── kustomization.yaml  # Kustomization reconciliation config
│   │   └── repository.yaml     # Git source repository for Flux
│   └── kustomize/              # Kubernetes manifests (base + overlays)
│       └── base/
│           └── app.yaml        # Service deployments, ConfigMaps, Secrets
├── infra/
│   ├── cloud/                   # Azure infrastructure as code (Terraform)
│   │   ├── main.tf             # Resource definitions (AKS, Cosmos DB, etc.)
│   │   ├── variables.tf        # Input variables
│   │   └── outputs.tf          # Output values
│   └── local/                   # Local development infrastructure
├── src/
│   ├── user-service/           # .NET 9 Authentication service
│   ├── account-service/        # .NET 9 Account management
│   ├── transaction-service/    # .NET 9 Transaction history
│   ├── transfer-service/       # .NET 9 Money transfer service
│   ├── chatbot-service/        # Python AI financial advisor
│   ├── anomaly-service/        # Python fraud detection agent
│   ├── budget-service/         # Python budget analysis agent
│   ├── event-processor/        # Go event streaming processor
│   └── ui-app/                 # React web frontend
├── scripts/
│   └── seed-data.sh            # Demo data population script
├── nginx.conf                   # API Gateway configuration
├── docker-compose.yml          # Local services orchestration
├── .env.example                # Environment variables template
└── README.md                   # This file
```

## Agentic Capabilities

### AI Chatbot Assistant
The chatbot service provides:
- Financial advice and insights
- Transaction categorization
- Budget recommendations
- Natural language queries

### Anomaly Detection
Real-time fraud detection:
- Unusual transaction patterns
- Velocity analysis
- Merchant behavior analysis

### Budget Analysis
Automated budget insights:
- Spending categorization
- Budget variance tracking
- Savings recommendations
- Financial health scoring

## Development

### Prerequisites for Local Development

- **.NET 9 SDK**: For building/running .NET services locally
- **Python 3.11+**: For running Python agent services
- **Go 1.22+**: For event processor
- **Node.js 18+**: For React UI development

### Running Individual Services (Hot Reload)

```bash
# Terminal 1: Keep Docker services running
docker-compose up -d

# Terminal 2: .NET service with hot reload
cd src/user-service
dotnet watch run

# Terminal 3: Python service with auto-reload
cd src/chatbot-service
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

# Terminal 4: React UI development server
cd src/ui-app
npm install
npm start
```

## Azure Deployment

Designed for deployment to Azure cloud services:
- **AKS** - Container orchestration
- **Cosmos DB** - Managed NoSQL database
- **Redis Cache** - Managed distributed caching
- **Azure OpenAI** - AI services
- **Application Insights** - Monitoring and logging
- **Key Vault** - Secrets management
- **Flux CD** - GitOps continuous deployment

See `docs/deployment-azure.md` for complete Azure deployment instructions.

## Environment Variables

Key variables for local development (see `.env.example` for full list):

```bash
# Authentication
Jwt__Key=YourSuperSecretKeyForJWTTokenGeneration12345
Jwt__Issuer=user-service

# Database (in-memory for local development)
UseInMemoryDatabase=true

# Azure Services (optional)
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_MODEL=gpt-4o-mini
AZURE_CLIENT_ID=
AZURE_TENANT_ID=
AZURE_CLIENT_SECRET=

# Redis
REDIS__CONNECTIONSTRING=redis:6379

# Inter-service Communication
Services__AccountService=http://account-service:8080
Services__TransactionService=http://transaction-service:8080
```

## Troubleshooting

### Services won't start
- Increase Docker Desktop memory to 8GB+
- Check port conflicts: `sudo lsof -i :80`
- View logs: `docker-compose logs -f`

### Redis connection failed
```bash
docker-compose ps redis  # Should show "healthy"
docker-compose down -v
docker-compose up -d redis
```

### JWT authentication errors
- Clear browser localStorage: DevTools → Application → Clear All
- Re-login to get fresh token
- Verify JWT key consistency across services

See `docs/deployment-local.md` for more troubleshooting steps.

## License

MIT License - see LICENSE file for details.

---

**Last Updated**: May 2024  
**Repository**: https://github.com/briandenicola/online-banking-demo
