# Online Banking Demo

A microservices-based online banking application demonstrating agentic AI capabilities with .NET 9, Python, Go, React, and cloud-native Azure services deployed on AKS with Istio service mesh.

## Quick Start

### Prerequisites
- Docker & Docker Compose
- [go-task](https://taskfile.dev/) (Taskfile runner)
- Git, Node.js 18+ (for UI development)
- 8GB RAM, 10GB disk space

### Running Locally

```bash
git clone https://github.com/briandenicola/online-banking-demo.git
cd online-banking-demo
cp .env.example .env

# Start all services
task local:up

# Seed demo data (optional)
./scripts/seed-data.sh
```

### Access Points

- **React UI**: http://localhost:3000/
- **API Gateway**: http://localhost/
- **Health Check**: http://localhost/health

## Documentation

- **[Documentation Hub](docs/README.md)** — Start here for all guides
- **[Local Development](docs/deployment-local.md)** — Docker Compose setup, environment variables, hot reload workflows
- **[Azure Cloud Deployment](docs/deployment-azure.md)** — Terraform provisioning, AKS + Istio, Taskfile-driven deployment
- **[System Architecture](docs/architecture.md)** — Service map, communication patterns, authentication, event pipeline
- **[Testing Guide](docs/testing.md)** — Playwright E2E test suite (4 phases, 195+ specs)

### Agentic Development

This project was built using AI-assisted development practices:

- **[ADRs](docs/adr/README.md)** — Architecture Decision Records capturing key technical choices
- **[Squad Guide](docs/squad-guide.md)** — How the AI team framework (Squad) was used with specialized agent roles
- **[Copilot Integration](docs/copilot-integration.md)** — GitHub Copilot CLI usage, speckit workflow, and lessons learned
- **[Future AI Capabilities](docs/future-ai-capabilities.md)** — Spike on multi-agent orchestration, MCP/A2A, Agent365, AI red teaming

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      External Users / Clients                    │
└───────────────────────┬──────────────────────────────────────────┘
                        │
            ┌───────────▼────────────────┐
            │   Istio Ingress Gateway    │
            │  (HTTP/HTTPS, envsubst)    │
            └───────────┬────────────────┘
                        │
       ┌────────────────┼────────────────┐
       │                │                │
  ┌────▼────┐     ┌─────▼─────┐    ┌────▼─────┐
  │ React   │     │  .NET 9   │    │  Python  │
  │ UI App  │     │ Services  │    │  Agents  │
  └─────────┘     └─────┬─────┘    └────┬─────┘
                        │               │
                        └───────┬───────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
     ┌────▼────┐          ┌────▼─────┐         ┌────▼─────┐
     │  Redis  │          │ Cosmos DB│         │  Azure   │
     │ Streams │          │ (Entra)  │         │ AI Foundry│
     └─────────┘          └──────────┘         └──────────┘
```

### Services (10+)

**Core .NET 9 Microservices** (REST/HTTP, JWT-authenticated):
- **User Service** — Authentication, JWT token generation, user profiles
- **Account Service** — Account lifecycle, balance tracking
- **Transaction Service** — Transaction history, event publishing to Redis Streams
- **Transfer Service** — Money transfer orchestration, inter-service calls with JWT forwarding

**Python Agent Services** (FastAPI, AI-powered via Azure AI Foundry):
- **Chatbot Service** — AI financial advisor with Agent Framework, Cosmos chat persistence, account/transaction tools
- **AI Service** — Risk scoring, transaction categorization via Foundry agents
- **Budget Service** — Spending analysis and financial health insights

**Infrastructure & Admin Services**:
- **Event Processor** (Go) — Redis Streams consumer, async event routing
- **Prompt Eval Service** (.NET) — AI prompt evaluation with admin UI
- **UI Application** (React 18 + MUI v9) — Web frontend with admin panel

### Key Features

- **Event-Driven**: Redis Streams (`banking-events`) for inter-service communication
- **JWT Authentication**: Tokens issued by User Service, validated across all services
- **Agentic AI**: Chatbot with real data tools, anomaly detection, budget analysis via Azure AI Foundry
- **Chat Persistence**: Cosmos DB-backed chat history with 30-day TTL
- **Cloud-Native**: AKS with Istio service mesh, Workload Identity, KeyVault CSI driver
- **Infrastructure as Code**: Terraform with AzureRM + AzAPI providers
- **Observability**: OpenTelemetry SDK + Application Insights

## Taskfile Commands

All operations are managed via [go-task](https://taskfile.dev/):

| Command | Description |
|---------|-------------|
| **Local Development** | |
| `task local:up` | Start all services with Docker Compose |
| `task local:down` | Stop all services |
| **Cloud Deployment** | |
| `task cloud:up` | Full Azure environment (Terraform + AKS config) |
| `task cloud:infra:config` | One-time AKS setup (creds, namespaces, secrets, CSI) |
| `task cloud:build` | Build all container images via ACR |
| `task cloud:deploy` | Deploy manifests to AKS (repeatable) |
| `task cloud:infra:tls` | Install cert-manager + configure TLS |
| `task cloud:infra:tls:status` | Check certificate status |
| `task cloud:down` | Destroy all Azure resources |
| **Testing** | |
| `task e2e:run` | Run all Playwright E2E tests |
| `task e2e:ui` | Interactive Playwright UI mode |

## Project Structure

```
online-banking-demo/
├── docs/                        # Documentation
│   ├── deployment-local.md      # Local Docker Compose guide
│   ├── deployment-azure.md      # Azure AKS deployment guide
│   ├── architecture.md          # System architecture
│   └── testing.md               # E2E testing guide
├── cluster-config/              # Kubernetes cluster configuration
│   ├── cert-manager/            # TLS certificates (ClusterIssuer, Certificate)
│   └── istio/gateway/           # Istio ingress gateway configuration
├── deploy/kustomize/            # Kubernetes manifests
│   ├── base/                    # Service deployments, ConfigMap, SecretProviderClass
│   └── observability/           # OTEL collector, monitoring
├── infra/cloud/                 # Terraform (AKS, Cosmos DB, Redis, AI Foundry, KeyVault)
├── src/
│   ├── user-service/            # .NET 9 — Authentication
│   ├── account-service/         # .NET 9 — Account management
│   ├── transaction-service/     # .NET 9 — Transaction history
│   ├── transfer-service/        # .NET 9 — Money transfers
│   ├── chatbot-service/         # Python — AI financial advisor (Agent Framework)
│   ├── ai-service/              # Python — Risk scoring, categorization
│   ├── budget-service/          # Python — Budget analysis
│   ├── event-processor/         # Go — Redis Streams consumer
│   ├── prompt-eval-service/     # .NET 9 — AI prompt evaluation
│   └── ui-app/                  # React 18 + MUI v9 — Web frontend
├── tests/e2e/                   # Playwright E2E test suite
├── Taskfile.yml                 # Root Taskfile (includes cloud, local, e2e)
├── Taskfile.cloud.yml           # Azure deployment tasks
├── Taskfile.local.yml           # Local development tasks
├── Taskfile.e2e.yml             # E2E testing tasks
├── docker-compose.yml           # Local services orchestration
└── .env.example                 # Environment variables template
```

## Azure Deployment

Deployed to Azure using Terraform and Taskfile:

| Resource | Purpose |
|----------|---------|
| **AKS** | Kubernetes with Istio service mesh |
| **Cosmos DB** | Primary database (Entra RBAC auth) |
| **Azure Managed Redis** | Cache + event streaming (Balanced B0, port 10000/TLS) |
| **Azure AI Foundry** | AI agents + OpenAI models |
| **Application Insights** | Observability (OTEL SDK) |
| **Key Vault** | Secrets (synced to K8s via CSI driver) |
| **Container Registry** | Image storage (ACR) |

```bash
# Full deployment workflow
task cloud:up           # Terraform + AKS configuration
task cloud:build        # Build all images to ACR
task cloud:deploy       # Deploy manifests to AKS

# Optional TLS
task cloud:infra:tls    # cert-manager + Let's Encrypt
```

See [docs/deployment-azure.md](docs/deployment-azure.md) for the complete guide.

## Development

### Prerequisites

- **.NET 9 SDK**: .NET services
- **Python 3.11+**: AI agent services
- **Go 1.22+**: Event processor
- **Node.js 18+**: React UI

### Hot Reload

```bash
# Keep infrastructure running
docker-compose up -d

# .NET service
cd src/user-service && dotnet watch run

# Python service
cd src/chatbot-service && uvicorn app.main:app --reload --port 8001

# React UI
cd src/ui-app && npm start
```

## Troubleshooting

- **Services won't start**: Increase Docker memory to 8GB+, check ports with `sudo lsof -i :80`
- **Redis errors**: `docker-compose down -v && docker-compose up -d redis`
- **JWT 401 errors**: Clear browser localStorage, re-login for fresh token
- **Azure 401s**: Verify Workload Identity annotation on service account, check Entra RBAC roles

See [docs/deployment-local.md](docs/deployment-local.md) for more troubleshooting.

## License

MIT License — see LICENSE file for details.

---

**Last Updated**: May 2026
**Repository**: https://github.com/briandenicola/online-banking-demo
