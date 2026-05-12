# Online Banking Demo — Documentation

> A microservices banking platform showcasing cloud-native patterns, agentic AI, and secure Azure deployment.

## 🗺️ Learning Path

Follow these guides in order for the best experience:

| # | Guide | Description |
|---|-------|-------------|
| 1 | [Architecture](architecture.md) | System overview, service map, data flows, and technology choices |
| 2 | [Local Development](deployment-local.md) | Run the full platform locally with Docker Compose |
| 3 | [Azure Deployment](deployment-azure.md) | Deploy to AKS with Terraform, Istio, and KeyVault CSI |
| 4 | [Azure Authentication](azure-auth.md) | How Entra ID workload identity and DefaultAzureCredential work |
| 5 | [Testing](testing.md) | E2E testing with Playwright — setup, running, and writing tests |

## 🏗️ Architecture at a Glance

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│   Browser    │────▶│  Istio Ingress Gateway (TLS / Let's Encrypt) │
└─────────────┘     └──────────────┬───────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │         VirtualService        │
                    │   /api/users    → user-service │
                    │   /api/accounts → account-svc  │
                    │   /api/txn      → txn-service   │
                    │   /api/transfers→ transfer-svc  │
                    │   /api/chat     → chatbot-svc   │
                    │   /api/budget   → budget-svc    │
                    │   /api/applications → acct-opening │
                    │   /api/anomalies→ ai-service    │
                    │   /api/eval     → prompt-eval   │
                    │   /*            → ui-app        │
                    └──────────────┬───────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
   ┌────▼─────┐  ┌────────▼────────┐  ┌──────▼───────┐
   │ Cosmos DB │  │  Redis Streams   │  │ AI Foundry   │
   │ (Entra)   │  │  (Event Bus)     │  │ (GPT-5.4)    │
   └──────────┘  └────────┬────────┘  └──────────────┘
                          │
              ┌───────────┼───────────┐
              │                       │
        ┌─────▼──────┐        ┌──────▼────────┐
        │ ai-service  │        │event-processor│
        │ (consumer)  │        │  (consumer)   │
        └────────────┘        └───────────────┘
```

## 🛠️ Quick Commands

```bash
# Local development
docker-compose up -d              # Start all services
docker-compose logs -f ai-service # Follow specific service

# Cloud deployment
task -t Taskfile.cloud.yml up     # Provision Azure infra
task -t Taskfile.cloud.yml cloud:build   # Build all containers
task -t Taskfile.cloud.yml cloud:deploy  # Deploy to AKS

# Testing
task e2e:run                      # Run Playwright E2E tests
```

## 📂 Repository Structure

```
online-banking-demo/
├── .devcontainer/          # DevContainer for Codespaces / VS Code
├── cluster-config/         # Istio, cert-manager, network policies
├── deploy/kustomize/       # Kubernetes manifests (base + overlays)
├── docs/                   # This documentation
├── infra/cloud/            # Terraform for Azure resources
├── src/
│   ├── account-service/    # .NET — Account management
│   ├── ai-service/         # Python — Risk scoring & categorization
│   ├── budget-service/     # Python — Budget tracking
│   ├── account-opening-service/ # Python — AI account opening pipeline
│   ├── chatbot-service/    # Python — AI chatbot (Foundry agents)
│   ├── event-processor/    # Go — Redis Stream audit consumer
│   ├── prompt-eval-service/# .NET — AI prompt evaluation (admin)
│   ├── transaction-service/# .NET — Transaction processing
│   ├── transfer-service/   # .NET — Inter-account transfers
│   ├── ui-app/             # React 18 + MUI v9
│   └── user-service/       # .NET — Authentication & user management
├── tests/e2e/              # Playwright E2E tests
├── Taskfile.yml            # Local task orchestration
└── Taskfile.cloud.yml      # Cloud build/deploy orchestration
```

## 🔐 Security Model

- **Zero secrets in Kubernetes** — all via Azure KeyVault CSI driver
- **Entra ID everywhere** — Cosmos DB, Redis, AI Foundry (no keys)
- **Private endpoints** — all PaaS services accessed via private endpoints (9 endpoints, public access disabled except ACR)
- **Private DNS zones** — 10 zones for private endpoint name resolution within the VNet
- **Istio mTLS** — service-to-service encryption
- **JWT authentication** — HS256 tokens with role claims (User/Admin)

## 📚 Additional References

- [Architecture Decision Records](adr/README.md) — Key technical decisions with rationale
- [Squad Guide](squad-guide.md) — How the AI team framework was used during development
- [Copilot Integration](copilot-integration.md) — GitHub Copilot CLI and speckit workflow
