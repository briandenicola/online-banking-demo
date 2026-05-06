# Online Banking Demo

A microservices-based online banking application demonstrating agentic capabilities with .NET, Python, Go, and cloud-native Azure services.

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

### Event-Driven Communication

- **Asynchronous**: Redis Streams (`banking-events`) for inter-service events
- **Synchronous**: Direct HTTP calls for immediate responses (Transfer → Account)
- **Event Types**: `transfer.completed`, `transaction.recorded`, `anomaly.detected`, etc.

### Authentication

- **JWT Tokens** issued by User Service
- **Shared Key** across all services for token validation
- **Default Credentials**: demo@banking-demo.com / password123 (after seed)

### Data Storage

- **In-Memory Store** (development) — Fast, ephemeral
- **Cosmos DB** (Azure production) — Managed NoSQL, multi-region replication
- **Redis Persistence** — RDB snapshots for cache durability

## Getting Started

### Prerequisites
- Docker & Docker Compose
- .NET 9 SDK (for local development)
- Python 3.11+ (for agent services)
- Go 1.22+ (for event processor)

### Running Locally

```bash
# Clone the repository
git clone https://github.com/briandenicola/online-banking-demo.git
cd online-banking-demo

# Start all services
docker-compose up -d --build

# Check services are running
docker-compose ps
```

### Access Points

- **React UI**: http://localhost:3000/
- **API Gateway**: http://localhost/
- **Health Check**: http://localhost/health

### Demo Credentials
- Email: `demo@banking-demo.com`
- Password: `password123`

## Documentation

Comprehensive guides for deployment and architecture:

- **[Local Development Deployment](docs/deployment-local.md)** — Quick start guide for Docker Compose setup, environment variables, service ports, and development workflows
- **[Azure Cloud Deployment](docs/deployment-azure.md)** — Production deployment guide with Terraform, AKS, Flux GitOps, secrets management, and CI/CD pipeline
- **[System Architecture](docs/architecture.md)** — Detailed architecture overview, service map, communication patterns, event pipeline, and scaling considerations

## API Documentation

Access Swagger documentation through the gateway:

- **User Service**: http://localhost/api/users/swagger/index.html
- **Account Service**: http://localhost/api/accounts/swagger/index.html
- **Transaction Service**: http://localhost/api/transactions/swagger/index.html
- **Transfer Service**: http://localhost/api/transfers/swagger/index.html
- **Chatbot Docs**: http://localhost/api/chat/docs
- **Anomaly Detection Docs**: http://localhost/api/anomaly/docs
- **Budget Analysis Docs**: http://localhost/api/budget/docs

## Project Structure

```
online-banking-demo/
├── docs/
│   ├── deployment-local.md      # Local Docker Compose deployment guide
│   ├── deployment-azure.md      # Azure AKS + Flux GitOps deployment guide
│   └── architecture.md           # Detailed system architecture documentation
├── deploy/
│   ├── flux/                     # GitOps configuration (Flux CD)
│   │   ├── kustomization.yaml   # Kustomization reconciliation config
│   │   └── repository.yaml      # Git source repository for Flux
│   └── kustomize/               # Kubernetes manifests (base + overlays)
│       └── base/
│           └── app.yaml         # Service deployments, ConfigMaps, Secrets
├── infra/
│   ├── cloud/                    # Azure infrastructure as code (Terraform)
│   │   ├── main.tf              # Resource definitions (AKS, Cosmos DB, etc.)
│   │   ├── variables.tf         # Input variables
│   │   └── outputs.tf           # Output values
│   └── local/                    # Local development infrastructure
├── src/
│   ├── user-service/            # .NET 9 Authentication service
│   ├── account-service/         # .NET 9 Account management
│   ├── transaction-service/     # .NET 9 Transaction history
│   ├── transfer-service/        # .NET 9 Money transfer service
│   ├── chatbot-service/         # Python AI financial advisor
│   ├── anomaly-service/         # Python fraud detection agent
│   ├── budget-service/          # Python budget analysis agent
│   ├── event-processor/         # Go event streaming processor
│   └── ui-app/                  # React web frontend
├── scripts/
│   └── seed-data.sh             # Demo data population script
├── nginx.conf                    # API Gateway configuration
├── docker-compose.yml           # Local services orchestration
├── .env.example                 # Environment variables template
├── README.md                    # This file
└── LICENSE                      # MIT License
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
- Geographic anomalies
- Merchant behavior analysis

### Budget Analysis
Automated budget insights:
- Spending categorization
- Budget variance tracking
- Savings recommendations
- Financial health scoring

## Azure Deployment

Designed for deployment to Azure cloud services:
- **AKS** - Container orchestration
- **Cosmos DB** - Database (currently using in-memory)
- **Event Hub** - Event streaming
- **Redis** - Caching
- **Azure OpenAI** - AI services
- **Application Insights** - Monitoring

## Development

### Running Individual Services

```bash
# .NET services
cd src/user-service && dotnet run

# Python services  
cd src/chatbot-service && python main.py

# React UI (development mode)
cd src/ui-app && npm start
```

### Environment Variables

Services use these key environment variables:

```bash
# Authentication
Jwt__Key=YourSuperSecretKeyForJWTTokenGeneration12345
Jwt__Issuer=user-service

# Database
UseInMemoryDatabase=true

# Azure (when deploying)
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_KEY=
EVENTHUB_CONNECTION_STRING=
APPLICATIONINSIGHTS_CONNECTION_STRING=
```

## License

MIT License - see LICENSE file for details.