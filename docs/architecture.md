# Online Banking Demo - Architecture

## Overview

This is a demo online banking application showcasing agentic capabilities using a microservices architecture deployed to Azure.

## Microservices

### Core Services (.NET)

| Service | Purpose | Language | Port |
|---------|---------|----------|------|
| `user-service` | Authentication & User Management | C# (.NET 9) | 6001 |
| `account-service` | Account CRUD & Balance Management | C# (.NET 9) | 6002 |
| `transaction-service` | Transaction History & Records | C# (.NET 9) | 6003 |
| `transfer-service` | Money Transfer Processing | C# (.NET 9) | 6004 |

### Agent Services

| Service | Purpose | Language | Port |
|---------|---------|----------|------|
| `chatbot-service` | AI-powered Financial Advice | Python | 8001 |
| `anomaly-service` | Suspicious Transaction Detection | Python | 8002 |
| `budget-service` | Spending Analysis & Budget Insights | Python | 8003 |
| `event-processor` | Event Hub Consumer for Events | Go | 9001 |

## Data Stores

| Store | Purpose | Service |
|-------|---------|---------|
| Cosmos DB | Primary data store (accounts, users, transactions) | All .NET services |
| Redis | Session cache, rate limiting | API Gateway |
| Event Hub | Event streaming between services | All services |

## Communication

- **Async**: Event Hub for all inter-service communication
- **Sync**: REST/gRPC for direct API calls when needed

## Agentic Workflows

### 1. Transaction Anomaly Detection
1. Transaction occurs → Event published to Event Hub
2. `anomaly-service` consumes event
3. AI model analyzes transaction patterns
4. If anomalous → Alert published to Event Hub
5. `notification-service` (future) sends alert

### 2. Financial Advice Chatbot
1. User sends message to `chatbot-service`
2. Service enriches context with user account/transaction data
3. Azure OpenAI generates response
4. Response returned to user

### 3. Budget Analysis
1. Scheduled trigger (daily/weekly)
2. `budget-service` analyzes transaction history
3. Categories spending patterns
4. Generates insights via Event Hub

## Azure Resources

| Resource | Purpose |
|----------|---------|
| AKS | Container orchestration |
| Cosmos DB (SQL API) | Primary database |
| Event Hub | Event streaming |
| Redis Cache | Session storage |
| Azure OpenAI | AI services |
| Application Insights | Monitoring |
| Key Vault | Secrets management |

## Security

- OAuth2 with JWT tokens
- Encryption at rest (Cosmos DB, Redis)
- Managed Identity for Azure service access
- Key Vault for secrets

## Deployment

- **IaC**: Terraform
- **GitOps**: Flux CD
- **CI/CD**: GitHub Actions
- **Observability**: OpenTelemetry + Azure Monitor

## Directory Structure

```
src/
├── user-service/          # .NET Auth service
├── account-service/       # .NET Account management
├── transaction-service/   # .NET Transaction history
├── transfer-service/      # .NET Transfer processing
├── chatbot-service/       # Python AI chatbot
├── anomaly-service/       # Python anomaly detection
├── budget-service/        # Python budget analysis
├── event-processor/       # Go event processor
└── shared/                # Shared DTOs/contracts
infra/
└── terraform/             # Terraform IaC
deploy/
├── flux/                  # GitOps manifests
└── helm/                  # Helm charts
docs/
└── architecture.md        # This file
```