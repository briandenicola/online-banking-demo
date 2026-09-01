# Azure Deployment Guide

[← Local Development](deployment-local.md) | [Home](README.md) | [Next: Azure Auth →](azure-auth.md)

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
│  │  │  ├─ account-opening-service (Python) + worker + init container
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
| **Cosmos DB** | Primary database and chatbot memory store | Entra RBAC auth; Terraform creates application containers, Agent Memory Toolkit creates memory containers when enabled |
| **Azure Managed Redis** | Caching & events | Balanced_B0, port 10000/TLS, Entra ID auth |
| **Azure AI Foundry** | AI services | gpt-5.4-mini deployment, agent framework |
| **ACR** | Container registry | Premium SKU (required for PE), AKS has AcrPull role, `az acr build` |
| **Key Vault** | Secrets management | RBAC-protected, CSI driver syncs to K8s |
| **Application Insights** | Monitoring | Workspace-based, OTEL SDK integration |
| **Private Endpoints** | Network isolation | 9 endpoints for all PaaS services (public access disabled except ACR) |
| **Private DNS Zones** | Name resolution | 10 zones linked to VNet for private endpoint resolution |

### Cosmos DB Containers

| Container | Partition Key | Purpose |
|-----------|--------------|---------|
| Users | `/id` | User accounts |
| Accounts | `/id` | Bank accounts |
| Transactions | `/accountId` | Transaction records |
| Transfers | `/id` | Transfer records |
| ChatSessions | `/userId` | AI chat history |
| AgentMemoryTurns | `/user_id`, `/thread_id` | Agent Memory Toolkit raw chatbot turns; created by toolkit when `CHAT_MEMORY_ENABLED=true` |
| AgentMemories | `/user_id`, `/thread_id` | Agent Memory Toolkit facts, procedural memories, and episodic memories; created by toolkit when `CHAT_MEMORY_ENABLED=true` |
| AgentMemorySummaries | `/user_id`, `/thread_id` | Agent Memory Toolkit thread and user summaries; created by toolkit when `CHAT_MEMORY_ENABLED=true` |
| AgentMemoryCounters | `/user_id`, `/thread_id` | Agent Memory Toolkit processing cadence counters; created by toolkit when `CHAT_MEMORY_ENABLED=true` |
| AgentMemoryLeases | `/id` | Agent Memory Toolkit lease support; created by toolkit when `CHAT_MEMORY_ENABLED=true` |
| account-applications | `/id` | Account opening application state |

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
- Cosmos DB account + `BankingDemo` database + application containers; Agent Memory Toolkit creates memory containers at startup when enabled
- Azure Managed Redis (Balanced_B0)
- Azure AI Foundry project + gpt-5.4-mini deployment
- Key Vault (secrets are **not** Terraform-managed — see [Secrets](#secrets--key-vault-csi-driver))
- ACR with AcrPull role for AKS (Premium SKU for private endpoint support)
- VNet (/16) with 3 subnets: AKS (/24, offset 3), Private Endpoints (/24, offset 4), Jumpbox (/24, offset 6)
- Jumpbox VM (Ubuntu 22.04) + Azure Bastion (Developer SKU) + NAT gateway for in-VNet data-plane access
- NSG (ports 80/443 inbound)
- 9 private endpoints (Key Vault, Cosmos DB, Redis, ACR, AI Services, Storage blob/queue/table/file)
- 10 private DNS zones for endpoint name resolution
- Deployer IP auto-detected via `data "http" "myip"` (checkip.amazonaws.com) for Key Vault network ACLs
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
- **`build:python`** — chatbot-service, budget-service, ai-service, event-processor, account-opening-service
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
3. Streams Terraform output and `.env` values into `deploy/kustomize/base/configmap.yaml`
4. Applies the base workloads (`deploy/kustomize/base/`)
5. Applies the Istio gateway configuration with `envsubst` for `CUSTOM_DOMAIN`

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
| `/api/applications` | account-opening-service |
| `/api/evaluations` | prompt-eval-service |
| `/` (default) | ui-app |

## Chatbot Agent Memory MVP

The chatbot Agent Memory Toolkit integration is deployed with safe defaults:

- `CHAT_MEMORY_ENABLED=false` by default
- `CHAT_MEMORY_REQUIRED=false` so memory initialization failures do not block chatbot startup
- Existing `ChatSessions` writes remain enabled as the fallback history store
- The toolkit creates its own vector/full-text enabled Cosmos containers when memory is first enabled; Terraform intentionally does not pre-create these containers

### Prerequisites

Before enabling memory in AKS, confirm the environment has:

- The current `chatbot-service` image, built from Python 3.11+ with `azure-cosmos-agent-memory`
- Cosmos DB Entra RBAC access for the `banking-workload-identity` managed identity
- Azure AI Foundry chat deployment for normal chatbot responses
- Azure AI Foundry embedding deployment matching `CHAT_MEMORY_EMBEDDING_DEPLOYMENT` (`text-embedding-ada-002` by default)

If the embedding deployment was not provisioned previously, recreate or update infrastructure before enabling memory. `DEPLOY_EMBEDDING_MODEL` defaults to `true`, so a normal apply is enough:

```bash
task cloud:apply
task cloud:infra:config
```

### Deploy With Memory Disabled

Ship the application first with memory disabled. This confirms the new package and ConfigMap defaults do not affect normal chat behavior:

```bash
task cloud:build:chatbot-service
task cloud:deploy
kubectl rollout status deployment/chatbot-service -n banking-demo --timeout=180s
```

### Enable Memory

Enable the MVP only after the disabled deployment is healthy:

```bash
task cloud:memory:enable
```

This reapplies `banking-demo-config` with `CHAT_MEMORY_ENABLED=true`, restarts only `deployment/chatbot-service`, waits for rollout, and prints current memory settings plus recent memory-related logs.

To use a different embedding deployment name:

```bash
CHAT_MEMORY_EMBEDDING_DEPLOYMENT=<embedding-deployment-name> task cloud:memory:enable
```

### Verify Memory

After a successful rollout, send a few authenticated chat messages, then inspect the chatbot logs and Cosmos containers:

```bash
task local:memory:test
task cloud:memory:status
kubectl get pods -n banking-demo -l app=chatbot-service
az cosmosdb sql container list \
  --account-name <cosmos-account-name> \
  --resource-group <resource-group-name> \
  --database-name BankingDemo \
  --query "[?starts_with(name, 'AgentMemory')].name" -o table
```

Expected containers are `AgentMemoryTurns`, `AgentMemories`, `AgentMemorySummaries`, `AgentMemoryCounters`, and `AgentMemoryLeases`.

### Phase 2.5 Lightweight Memory Evals

Phase 2.5 adds deterministic chatbot memory evals without introducing live Azure dependencies or a hosted eval pipeline. These tests use curated fixtures plus fake agent/memory services to verify the demo-critical behavior before or after enabling the MVP in a deployed environment.

```bash
task local:memory:test
```

The scenario fixture lives at `src/chatbot-service/tests/fixtures/memory_eval_scenarios.json` and currently covers:

| Category | What it proves |
|----------|----------------|
| Memory recall | Relevant user preferences can influence the prompt and response |
| Cross-session continuity | User-level memory can carry useful goals into a new chat thread |
| User isolation | Memory lookup uses the authenticated JWT user, not a spoofable request body user ID |
| Prompt-injection resistance | Stored memory remains background context and cannot override banking guardrails |
| PII redaction | SSNs, card/account-like numbers, emails, phone numbers, and secrets are redacted before memory writes |
| Relevance/noise control | Irrelevant memories do not leak into unrelated banking answers |
| Contradiction handling | Newer stated preferences can be favored over stale ones in curated scenarios |

Keep these evals small and deterministic for the demo. If memory becomes production-bound, extend this into offline/online quality evaluation with realistic conversations, LLM-as-judge scoring, drift tracking, and regression thresholds.

### Roll Back

Memory can be disabled without redeploying the whole application:

```bash
task cloud:memory:disable
```

Existing memory containers and documents remain in Cosmos DB, but the chatbot stops retrieving memory context and stops writing new toolkit turns. Existing `ChatSessions` history continues to work.

### Troubleshooting

| Symptom | Likely Cause | Check/Fix |
|---------|--------------|-----------|
| Chatbot starts but memory logs show initialization failure | `CHAT_MEMORY_REQUIRED=false` allows fallback | Run `task cloud:memory:status` and inspect the first error in chatbot logs |
| Toolkit cannot create containers | Managed identity lacks Cosmos DB data-plane permissions | Confirm the workload identity has Cosmos DB data contributor access |
| Semantic search or `process_now` fails | Missing or mismatched embedding deployment | Set `CHAT_MEMORY_EMBEDDING_DEPLOYMENT` to the actual Foundry deployment or run `task cloud:apply` |
| Import/package error in chatbot container | Old image still running or build did not include the new dependency | Re-run `task cloud:build:chatbot-service`, then `task cloud:deploy` |
| Container policy error | Memory containers were manually created without toolkit-required vector/full-text policies | Delete/recreate only the affected empty AgentMemory containers, then restart chatbot |
| `A Container Vector Policy has been provided, but the capability has not been enabled on your account` | The Cosmos `EnableNoSQLVectorSearch` capability takes ~10-15 minutes to reach the data plane after ARM reports `Succeeded` | Confirm capabilities with `az resource show --ids <cosmos-id> --api-version 2024-11-15 --query properties.capabilities[].name`, wait, then restart chatbot |

### MVP vs. Production Quality Gaps

Phase 3 is intentionally deferred for this demo application. The current implementation is appropriate for showcasing user-scoped chatbot memory because it is feature-flagged, bounded, redacts common sensitive values, keeps the original `ChatSessions` history fallback, and can be rolled back by disabling `CHAT_MEMORY_ENABLED`.

For production, the largest gap is operational hardening rather than basic functionality. The demo performs lightweight memory processing in the chatbot process; a production system should move derived-memory processing, reconciliation, retries, and lag monitoring into a dedicated background worker.

| Area | Current MVP | Production-quality gap |
|------|-------------|------------------------|
| Processing model | Chatbot writes sanitized turns and periodically calls toolkit processing/reconciliation in-process | Use a dedicated processor, such as Cosmos DB change feed plus Azure Functions or Durable Functions, so chat latency and memory extraction are isolated |
| Reliability | Memory failures are logged and non-blocking because `CHAT_MEMORY_REQUIRED=false` | Add retry policy, checkpointing, poison-message handling, replay procedures, and alerting for failed memory extraction |
| Observability | `task cloud:memory:status` surfaces ConfigMap values and recent logs | Add dashboards and alerts for processing lag, failure rate, RU consumption, embedding failures, and memory container growth |
| Data governance | Basic regex redaction before memory writes | Add formal retention policy, user deletion/export workflow, audit trail, and domain-reviewed PII/financial-data classification |
| Memory quality | Toolkit summaries/facts are bounded by confidence and prompt-size settings | Add offline evaluation for memory relevance, contradiction handling, hallucinated-memory rate, and regression tests with realistic customer conversations |
| Scaling | Sufficient for low-volume demo traffic | Validate RU/s, partition distribution, concurrency, and embedding throughput under expected user load |
| Security controls | Memory is keyed by authenticated JWT user ID and injected as untrusted background context | Add threat modeling for prompt injection via stored memories, stricter content filters, access reviews, and tenant/customer isolation requirements if the app becomes multi-tenant |
| Operations | Manual enable/disable tasks and rollback via ConfigMap flag | Add release gates, runbooks, SLOs, backup/restore procedures, and scripted cleanup for retired memory containers |
| Dependency maturity | Uses preview Agent Memory Toolkit package pinned in the chatbot dependency set | Track SDK breaking changes, pin upgrade tests, and require production supportability review before relying on preview APIs |

These gaps do not block the demo. They should be treated as the checklist to revisit if chatbot memory becomes a production feature rather than a showcase capability.

### Account Opening Service Deployment

The Account Opening Service has a unique deployment model with multiple containers defined in `deploy/kustomize/base/account-opening-service.yaml`:

- **Init container** (`provision-agents`) — Runs `python -m app.agents.init_agents` to provision Foundry agents (identity-verifier, compliance-assessor, account-provisioner) before the worker starts
- **API container** (`account-opening-service`) — FastAPI REST API serving application endpoints
- **Worker container** (`account-opening-worker`) — Background processor running 4 Redis Stream consumer agents
- **Entra Agent ID sidecar** (`entra-agent-id`) — Authentication sidecar on the worker pod that handles Foundry auth via Microsoft Entra Agent ID

Both the API and worker use the `banking-workload-identity` service account. The worker's sidecar authenticates with Foundry using the `AGENT_ID_SIDECAR_URL` (http://localhost:5000) and the workload identity client ID set via `AGENT_ID_AGENT_IDENTITY`.

### Eval Debug Pod (optional)

A separate `eval-debug` Pod can be deployed for in-cluster Foundry / eval debugging. It carries the `ai-service` Python code plus the Azure CLI and network diagnostics tools (`curl`, `jq`, `dig`, `openssl`) and runs under the same workload identity as the rest of the platform.

```bash
task cloud:build:eval-debug      # builds the dedicated image in ACR
task cloud:deploy                # ships the Pod manifest
kubectl exec -it -n banking-demo deploy/eval-debug -- python -m app.eval_debug
```

The REPL imports the production LLM-as-judge helpers from `ai-service`, so behavior matches `/api/admin/evaluate` exactly. See `src/ai-service/README.md` for command reference and [ADR-006](adr/006-llm-as-judge-evaluation.md) for the eval architecture.

## TLS Configuration (Optional)

TLS is handled by cert-manager with Let's Encrypt. Requires `CUSTOM_DOMAIN` set in `.env`. The setup is idempotent — safe to re-run if needed.

```bash
# Install cert-manager + apply ClusterIssuer and Certificate
task cloud:tls:enable

# Check certificate status
task cloud:tls:status
```

This sets up:
- **cert-manager** installed via Helm
- **Let's Encrypt ClusterIssuer** with HTTP-01 challenge (Istio solver)
- **Certificate** in the `aks-istio-ingress` namespace (`banking-demo-tls`)
- The Istio Gateway references this cert via `credentialName: banking-demo-tls`

## Configuration Management

### Secrets — Key Vault CSI Driver

Key Vault secrets are **not** managed by Terraform. Writing a secret is a Key Vault *data-plane* call, and the vault's data plane is reachable only over its private endpoint. A `terraform apply` from outside the VNet always races the private endpoint / firewall converging and fails with:

```text
Status=403 Code="Forbidden" ... InnerError={"code":"ForbiddenByConnection"}
```

Instead, secrets are created once from the in-VNet jumpbox (`infra/cloud/jumpbox.tf`), which has private DNS line of sight to the vault. The Bastion is a **Developer SKU**, which is browser-only — native-client SSH (`az network bastion ssh`) requires Standard or higher — so connect from the Azure Portal:

```bash
# Print the portal link and the exact bootstrap command for this deployment
task cloud:keyvault:secrets
```

Then in the Azure Portal, open **Virtual machines → `<app-name>-jump` → Connect → Bastion**, authenticate as `manager` with the private key matching `~/.ssh/id_rsa.pub`, and run:

```bash
# Every value is derived from the app name
setup-keyvault-secrets.sh <app-name> [--force] [--dry-run]
```

`scripts/setup-keyvault-secrets.sh` is staged onto the VM by cloud-init. It takes the app name (`terraform output -raw app_name`) and derives the resource group, vault, Redis, App Insights, Foundry, and Content Understanding names from it, reading the values it needs from the Azure control plane. The jumpbox's managed identity holds **Key Vault Secrets Officer** on the vault and **Reader** on the resource group. Existing secrets are skipped unless `--force` is passed.

To reuse the JWT key Terraform holds in state rather than generating a new one, export it first:

```bash
JWT_KEY="$(terraform -chdir=infra/cloud output -raw jwt_key)" setup-keyvault-secrets.sh <app-name>
```

**How it works:**
1. The bootstrap script creates the secrets in Key Vault: `jwt-key`, `openai-endpoint`, `content-understanding-endpoint`, `redis-connection-string`, `appinsights-connection-string`
2. `deploy/kustomize/base/secret-provider-class.yaml` defines a `SecretProviderClass` that maps Key Vault secrets to a K8s Secret named `banking-secrets`
3. The CSI driver uses workload identity (`useVMkubeletIdentity: "true"`) to authenticate
4. `task cloud:infra:config` patches the placeholder values (Key Vault name, tenant ID, client ID) in the SecretProviderClass

Pods mount the CSI volume and reference `banking-secrets` for environment variables.

### ConfigMap

Non-sensitive configuration is stored in `deploy/kustomize/base/configmap.yaml`:

- Inter-service URLs (`Services__AccountService`, `Services__TransactionService`)
- Cosmos DB endpoint (`COSMOS_DB_ENDPOINT`)
- Chatbot memory MVP settings (`CHAT_MEMORY_*`)
- OTEL collector endpoint
- `task cloud:infra:config` patches the Cosmos DB endpoint, workload identity values, and memory rollout settings from Terraform output and `.env`

### Environment Variables

The `.env` file at the repo root is loaded by Taskfile (`dotenv: ['.env']`). Key variables:

| Variable | Purpose |
|----------|---------|
| `CUSTOM_DOMAIN` | Domain for TLS certificate and Istio gateway |
| `DEPLOY_EMBEDDING_MODEL` | Provisions the default `text-embedding-ada-002` deployment for chatbot memory. Defaults to `true`; set to `false` only in regions where the model is unavailable |
| `CHAT_MEMORY_ENABLED` | Set to `true` only when explicitly rolling out the Agent Memory Toolkit MVP |
| `CHAT_MEMORY_EMBEDDING_DEPLOYMENT` | Foundry embedding deployment used by memory semantic search |

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
| ACR | Premium | $50 |
| Private Endpoints | 9 × ~$7.30/month | ~$66 |
| **Total** | | **~$821–1,171** |

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
task cloud:tls:status

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
| `task cloud:tls:enable` | Install cert-manager + TLS certificate (idempotent) |
| `task cloud:tls:status` | Check TLS certificate status |
| `task cloud:down` | Tear down all Azure resources |

---

**Last Updated**: May 2026
**Architecture**: AKS + Istio + Key Vault CSI + ACR + Workload Identity
**Tested On**: Azure CLI 2.50+, kubectl 1.28+, Terraform 1.5+, go-task 3.x

---

[← Local Development](deployment-local.md) | [Home](README.md) | [Next: Azure Auth →](azure-auth.md)
