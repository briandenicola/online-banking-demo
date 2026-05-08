# Azure Deployment Guide

## Architecture Overview

The Online Banking Demo deploys to Azure Kubernetes Service (AKS) using Terraform for infrastructure and [go-task](https://taskfile.dev/) (Taskfile) for orchestrating build and deploy workflows. Ingress is handled by the Istio service mesh addon, secrets are synced from Azure Key Vault via the CSI driver, and container images are built directly in Azure Container Registry (ACR).

### High-Level Architecture

```
Azure Resource Group
├─ AKS Cluster (Kubernetes + Istio service mesh)
│  ├─ Namespace: banking-demo
│  │  ├─ Workloads (10 services):
│  │  │  ├─ user-service (.NET)        account-service (.NET)
│  │  │  ├─ transaction-service (.NET)  transfer-service (.NET)
│  │  │  ├─ chatbot-service (Python)    budget-service (Python)
│  │  │  ├─ ai-service (Python)         event-processor (Go)
│  │  │  ├─ prompt-eval-service (.NET)  ui-app (React)
│  │  │  └─ All services on port 8080
│  │  ├─ ConfigMap: banking-demo-config
│  │  ├─ Secret: banking-secrets (synced from Key Vault via CSI)
│  │  └─ ServiceAccount: banking-workload-identity
│  ├─ Namespace: aks-istio-ingress
│  │  └─ Istio Gateway + VirtualService (routing)
│  └─ Namespace: observability
│     └─ OpenTelemetry Collector
│
├─ Azure Container Registry (ACR) — image builds & storage
├─ Cosmos DB (database: BankingDemo, Entra RBAC auth)
├─ Azure Managed Redis (Balanced_B0, Entra ID auth)
├─ Azure AI Foundry (gpt-5.4-mini, agent framework)
├─ Key Vault (secrets → CSI driver → K8s Secrets)
├─ Application Insights + Log Analytics
└─ Storage Account
```

### Azure Resources

| Resource | Purpose | Configuration |
|----------|---------|---------------|
| **AKS** | Container orchestration | Auto-scaling, Istio mesh, OIDC + Workload Identity, Key Vault CSI |
| **Cosmos DB** | Primary database | Entra RBAC auth, 5 containers |
| **Azure Managed Redis** | Caching & events | Balanced_B0, port 10000/TLS, Entra ID auth |
| **Azure AI Foundry** | AI services | gpt-5.4-mini deployment, agent framework |
| **ACR** | Container registry | AKS has AcrPull role, `az acr build` |
| **Key Vault** | Secrets management | RBAC-protected, CSI driver syncs to K8s |
| **Application Insights** | Monitoring | Workspace-based, OTEL SDK integration |

### Cosmos DB Containers

| Container | Partition Key | Purpose |
|-----------|--------------|---------|
| Users | `/id` | User accounts |
| Accounts | `/id` | Bank accounts |
| Transactions | `/accountId` | Transaction records |
| Transfers | `/id` | Transfer records |
| ChatSessions | `/userId` | AI chat history |

### Authentication Model

All services use **Workload Identity** (not service principals or connection string keys):

- AKS has OIDC issuer + workload identity enabled
- Service account `banking-workload-identity` carries the `azure.workload.identity/client-id` annotation
- **Cosmos DB**: Entra RBAC auth (no connection string keys)
- **Redis**: Entra ID token auth (dual-mode — `AZURE_CLIENT_ID` env var triggers Entra path, absence falls back to password)
- **AI Foundry / OpenAI**: Entra identity via `Azure.Identity`
- Federated credentials configured in `infra/cloud/identity.tf`

## Prerequisites

### Required Tools

| Tool | Purpose | Install |
|------|---------|---------|
| **Azure CLI** | Azure resource management | [install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) |
| **kubectl** | Kubernetes CLI | [install](https://kubernetes.io/docs/tasks/tools/) |
| **Terraform** | Infrastructure as code (1.5+) | [install](https://www.terraform.io/downloads) |
| **go-task** | Task runner (Taskfile) | [install](https://taskfile.dev/installation/) |
| **Helm** | Kubernetes package manager | [install](https://helm.sh/docs/intro/install/) |
| **kustomize** | Kubernetes manifest management | [install](https://kubectl.docs.kubernetes.io/installation/kustomize/) |

### Azure Account

- Active subscription with billing enabled
- **Owner or Contributor** role on the subscription
- Permissions to create AKS, Cosmos DB, ACR, Key Vault, AI resources

### Environment Setup

Copy the environment template and fill in required values:

```bash
cp .env.example .env
# Edit .env with your values (CUSTOM_DOMAIN, etc.)
```

The `.env` file is loaded automatically by Taskfile via `dotenv: ['.env']`.

## Infrastructure Provisioning

All infrastructure is managed through Taskfile commands that wrap Terraform.

### Full Environment Creation

```bash
# Create everything: terraform init → apply → AKS config (15-25 min)
task cloud:up
```

This single command:
1. Initializes Terraform and selects/creates a workspace based on region
2. Runs `terraform apply` (you will be prompted to confirm)
3. Runs `infra:config` to configure AKS post-provisioning

### Terraform Only

```bash
# Apply just the Terraform infrastructure
task cloud:apply
```

### What Gets Created

Terraform provisions all Azure resources defined in `infra/cloud/`:

- AKS cluster with Istio service mesh, OIDC, workload identity, Key Vault CSI
- Cosmos DB account + `BankingDemo` database + 5 containers
- Azure Managed Redis (Balanced_B0)
- Azure AI Foundry project + gpt-5.4-mini deployment
- Key Vault with secrets (see `infra/cloud/keyvault-secrets.tf`)
- ACR with AcrPull role for AKS
- VNet, subnet, NSG (ports 80/443 inbound)
- Log Analytics + Application Insights
- User-assigned managed identity with federated credentials

### Tear Down

```bash
# Delete all Azure resources and clean Terraform state
task cloud:down
```

## AKS Configuration

After Terraform provisioning, `task cloud:infra:config` performs one-time AKS setup:

```bash
# Run standalone (also runs automatically as part of cloud:up)
task cloud:infra:config
```

This command:
1. Gets AKS credentials via `az aks get-credentials`
2. Creates namespaces (`banking-demo`, `observability`)
3. Creates the `banking-workload-identity` service account with workload identity annotation
4. Creates the observability namespace secret
5. Patches `secret-provider-class.yaml` with Key Vault name, tenant ID, and client ID from Terraform outputs
6. Patches `configmap.yaml` with the Cosmos DB endpoint
7. Reverts placeholder files after applying

## Building Container Images

Images are built directly in ACR using `az acr build` — no local Docker build or push required.

```bash
# Build all service images
task cloud:build
```

This builds the following groups:
- **`build:dotnet`** — user-service, account-service, transaction-service, transfer-service
- **`build:python`** — chatbot-service, budget-service, ai-service, event-processor
- **`build:ui`** — ui-app (React)

The ACR name is resolved from Terraform output automatically.

## Deploying to AKS

```bash
# Deploy all services (repeatable)
task cloud:deploy
```

This command:
1. Updates kustomize image references to point to the ACR registry
2. Applies the observability stack (`deploy/kustomize/observability/`)
3. Applies the base workloads (`deploy/kustomize/base/`)
4. Applies the Istio gateway configuration with `envsubst` for `CUSTOM_DOMAIN`

### Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n banking-demo

# Check services
kubectl get svc -n banking-demo

# Check the Istio gateway
kubectl get gateway -n aks-istio-ingress
```

### Ingress Routing (Istio)

The Istio VirtualService (`cluster-config/istio/gateway/default-ingress.yaml`) routes traffic:

| Path | Service |
|------|---------|
| `/api/auth`, `/api/users` | user-service |
| `/api/accounts` | account-service |
| `/api/transactions` | transaction-service |
| `/api/transfers` | transfer-service |
| `/api/chat` | chatbot-service |
| `/api/anomaly`, `/api/admin` | ai-service |
| `/api/budget` | budget-service |
| `/api/evaluations` | prompt-eval-service |
| `/` (default) | ui-app |

## TLS Configuration (Optional)

TLS is handled by cert-manager with Let's Encrypt. Requires `CUSTOM_DOMAIN` set in `.env`.

```bash
# Install cert-manager + apply ClusterIssuer and Certificate
task cloud:infra:tls

# Check certificate status
task cloud:infra:tls:status
```

This sets up:
- **cert-manager** installed via Helm
- **Let's Encrypt ClusterIssuer** with HTTP-01 challenge (Istio solver)
- **Certificate** in the `aks-istio-ingress` namespace (`banking-demo-tls`)
- The Istio Gateway references this cert via `credentialName: banking-demo-tls`

## Configuration Management

### Secrets — Key Vault CSI Driver

Secrets are managed in Terraform (`infra/cloud/keyvault-secrets.tf`) and synced to Kubernetes automatically via the Azure Key Vault CSI driver. No manual secret creation is needed.

**How it works:**
1. Terraform creates secrets in Key Vault: `jwt-key`, `openai-endpoint`, `redis-connection-string`, `appinsights-connection-string`
2. `deploy/kustomize/base/secret-provider-class.yaml` defines a `SecretProviderClass` that maps Key Vault secrets to a K8s Secret named `banking-secrets`
3. The CSI driver uses workload identity (`useVMkubeletIdentity: "true"`) to authenticate
4. `task cloud:infra:config` patches the placeholder values (Key Vault name, tenant ID, client ID) in the SecretProviderClass

Pods mount the CSI volume and reference `banking-secrets` for environment variables.

### ConfigMap

Non-sensitive configuration is stored in `deploy/kustomize/base/configmap.yaml`:

- Inter-service URLs (`Services__AccountService`, `Services__TransactionService`)
- Cosmos DB endpoint (`CosmosDb__Endpoint`)
- OTEL collector endpoint
- `task cloud:infra:config` patches the Cosmos DB endpoint from Terraform output

### Environment Variables

The `.env` file at the repo root is loaded by Taskfile (`dotenv: ['.env']`). Key variables:

| Variable | Purpose |
|----------|---------|
| `CUSTOM_DOMAIN` | Domain for TLS certificate and Istio gateway |

See `.env.example` for the full template.

## Monitoring & Observability

### OpenTelemetry

Services are instrumented with the OTEL SDK. An OpenTelemetry Collector runs in the `observability` namespace (`deploy/kustomize/observability/`) and forwards telemetry to Application Insights.

### Application Insights

```bash
# Query logs in Azure Portal → Application Insights → Logs
# KQL examples:
# traces | where timestamp > ago(1h) | summarize count() by severityLevel
# requests | where duration > 5000 | summarize count() by name
```

### Kubernetes Monitoring

```bash
# Check cluster health
kubectl get nodes

# View pod metrics
kubectl top nodes
kubectl top pods -n banking-demo

# Stream pod logs
kubectl logs -f -l app=user-service -n banking-demo

# View logs from crashed pod
kubectl logs <pod-name> --previous -n banking-demo
```

## Cost Considerations

### Estimated Monthly Costs

| Resource | SKU | Est. Cost |
|----------|-----|-----------|
| AKS | 3 nodes (Standard_DS2_v2) | $400–500 |
| Cosmos DB | 400 RU/s provisioned | $200–300 |
| Azure Managed Redis | Balanced_B0 | $50–100 |
| Application Insights | 1 GB ingestion | $50–100 |
| Azure AI Foundry | gpt-5.4-mini usage | $50–100 |
| ACR | Basic tier | $5 |
| **Total** | | **~$755–1,105** |

### Optimization Tips

- Use Dev/Test pricing with lower-cost SKUs
- Enable AKS auto-scaling based on CPU/memory
- Use Reserved Instances for 30–40% discount
- Reduce Application Insights retention to 30 days
- Shut down AKS cluster during off-hours (dev environments)
- Use `task cloud:down` to tear down unused environments

## Troubleshooting

### Pods Not Starting

```bash
# Check pod events
kubectl describe pod <pod-name> -n banking-demo

# Check node resources
kubectl top nodes

# Check image pull issues (ACR auth)
kubectl describe pod <pod-name> -n banking-demo | grep -A5 "Events"
```

### Secret Sync Issues (CSI Driver)

```bash
# Verify SecretProviderClass exists
kubectl get secretproviderclass -n banking-demo

# Check CSI driver pods
kubectl get pods -n kube-system -l app=secrets-store-csi-driver

# Verify the K8s secret was created
kubectl get secret banking-secrets -n banking-demo

# Check Key Vault access from the pod
kubectl describe pod <pod-name> -n banking-demo | grep -A10 "Volumes"
```

### Istio Gateway Issues

```bash
# Check gateway resource
kubectl get gateway -n aks-istio-ingress

# Check VirtualService
kubectl get virtualservice -n banking-demo

# Verify Istio ingress pods
kubectl get pods -n aks-istio-ingress

# Get external IP
kubectl get svc -n aks-istio-ingress
```

### Service Connectivity Issues

```bash
# Test DNS resolution
kubectl run -it --rm debug --image=busybox:1.28 --restart=Never \
  -- nslookup user-service.banking-demo

# Test inter-service connectivity
kubectl exec -it <pod-name> -n banking-demo -- curl http://account-service:8080/health

# Check service endpoints
kubectl get endpoints -n banking-demo
```

### TLS Certificate Issues

```bash
# Check certificate status
task cloud:infra:tls:status

# Manual check
kubectl get certificate -n aks-istio-ingress
kubectl get certificaterequest -n aks-istio-ingress
kubectl describe certificate banking-demo-tls -n aks-istio-ingress
```

## Quick Reference — Taskfile Commands

| Command | Description |
|---------|-------------|
| `task cloud:up` | Full environment creation (init + apply + config) |
| `task cloud:apply` | Terraform apply only |
| `task cloud:infra:config` | One-time AKS post-provisioning setup |
| `task cloud:build` | Build all container images in ACR |
| `task cloud:deploy` | Deploy all services to AKS (repeatable) |
| `task cloud:infra:tls` | Install cert-manager + TLS certificate |
| `task cloud:infra:tls:status` | Check TLS certificate status |
| `task cloud:down` | Tear down all Azure resources |

---

**Last Updated**: May 2026
**Architecture**: AKS + Istio + Key Vault CSI + ACR + Workload Identity
**Tested On**: Azure CLI 2.50+, kubectl 1.28+, Terraform 1.5+, go-task 3.x
