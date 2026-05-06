# Azure Deployment Guide

## Architecture Overview

The Online Banking Demo is designed for cloud-native deployment on Azure using modern DevOps practices. This guide covers the complete infrastructure provisioning and deployment pipeline.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      AZURE CLOUD PLATFORM                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              KUBERNETES (AKS)                                │  │
│  │  ┌────────────────────────────────────────────────────────┐  │  │
│  │  │  banking-demo Namespace                               │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌─────────────────────┐   │  │  │
│  │  │  │user-svc  │ │acct-svc  │ │ Ingress Controller │   │  │  │
│  │  │  │(2 pods)  │ │(2 pods)  │ │ (Public IP/TLS)    │   │  │  │
│  │  │  └──────────┘ └──────────┘ └─────────────────────┘   │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌─────────────────────┐   │  │  │
│  │  │  │txn-svc   │ │xfer-svc  │ │  ConfigMaps &      │   │  │  │
│  │  │  │(2 pods)  │ │(2 pods)  │ │  Secrets           │   │  │  │
│  │  │  └──────────┘ └──────────┘ └─────────────────────┘   │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐  │  │  │
│  │  │  │chatbot   │ │anomaly   │ │  event-processor   │  │  │  │
│  │  │  │(1 pod)   │ │(1 pod)   │ │  (1 pod)           │  │  │  │
│  │  │  └──────────┘ └──────────┘ └──────────────────────┘  │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              DATA LAYER                                  │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │  │
│  │  │ Cosmos DB    │  │ Redis Cache  │  │ Event Hub    │   │  │
│  │  │ (SQL API)    │  │ (Managed)    │  │ (Streaming)  │   │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              AI & MONITORING                             │  │
│  │  ┌──────────────────┐  ┌─────────────────────────────┐   │  │
│  │  │ Azure OpenAI     │  │ Application Insights (Logs) │   │  │
│  │  └──────────────────┘  │ Key Vault (Secrets)         │   │  │
│  │                        └─────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└─────────────────────────────────────────────────────────────────────┘

External Access:
┌──────────────┐
│ Users/GitHub │ ──┐
│  CI/CD       │   │
└──────────────┘   │
                   ├──> Application Ingress (TLS) ──> AKS Public IP
                   │
┌──────────────┐   │
│Container     │   │
│Registry      │ ──┘
│(ghcr.io)     │
└──────────────┘
```

### Azure Resources Summary

| Resource | Purpose | Configuration |
|----------|---------|----------------|
| **Azure Kubernetes Service (AKS)** | Container orchestration, manages pod lifecycle | 3-5 nodes, auto-scaling enabled |
| **Cosmos DB (SQL API)** | Primary data store for users, accounts, transactions | Multi-region replication, SSD storage |
| **Azure Cache for Redis** | Distributed caching, session management, event streaming | Premium tier, clustering enabled |
| **Azure OpenAI** | AI services for chatbot, anomaly detection, budget analysis | Deployment: gpt-4o-mini model |
| **Container Registry (ghcr.io)** | Docker image storage and distribution | GitHub Container Registry |
| **Application Insights** | Centralized logging, monitoring, distributed tracing | Workspace-based, 2-year retention |
| **Key Vault** | Centralized secrets management | RBAC-protected, audit logging |
| **Event Hub** | High-scale event ingestion (optional, uses Redis Streams by default) | 20+ throughput units |
| **Log Analytics Workspace** | Query and analyze logs, metrics | 5GB/day ingestion, 90-day retention |

## Prerequisites

### Azure Account Setup

1. **Azure Subscription**: Active subscription with billing enabled
2. **Azure CLI**: Version 2.50+ ([install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli))
3. **kubectl**: Kubernetes command-line tool ([install](https://kubernetes.io/docs/tasks/tools/))
4. **Flux CLI**: GitOps management ([install](https://fluxcd.io/docs/installation/))
5. **Terraform**: Version 1.5+ ([install](https://www.terraform.io/downloads))

### Verification Commands

```bash
# Verify Azure CLI
az --version
# Output: azure-cli 2.50.0

# Verify kubectl
kubectl version --client
# Output: Client Version: v1.28.0

# Verify Flux CLI
flux --version
# Output: flux version 2.1.0

# Verify Terraform
terraform --version
# Output: Terraform v1.5.0
```

### Azure Service Requirements

1. **Owner or Contributor** role in target subscription
2. **Permissions for**:
   - Creating resource groups
   - Managing AKS clusters
   - Creating Cosmos DB instances
   - Provisioning managed services (Redis, OpenAI, etc.)
   - Managing Azure Container Registry

### GitHub Integration

1. **Repository Settings**: Ensure `Settings > Actions` allows GitHub Actions
2. **GitHub Token**: Personal access token (PAT) with `repo`, `write:packages`, `read:packages` scopes
3. **Container Registry**: Credentials configured in GitHub Secrets for `ghcr.io`

## Infrastructure Provisioning with Terraform

### 1. Prepare Terraform Configuration

```bash
# Navigate to infrastructure directory
cd infra/cloud

# Examine main.tf for resources to be created
cat main.tf | head -50

# Check variables
cat variables.tf

# View outputs (what will be returned after provisioning)
cat outputs.tf
```

### 2. Initialize Terraform

```bash
# Download required providers
terraform init

# Output: Successfully configured the backend "local"!

# Verify backend is ready
terraform validate
# Output: Success! The configuration is valid.
```

### 3. Plan Infrastructure

```bash
# Generate execution plan (review before applying)
terraform plan -out=tfplan

# Output shows:
# Plan: X to add, 0 to change, 0 to destroy.
# - Resource Group
# - AKS Cluster
# - Cosmos DB
# - Redis Cache
# - Application Insights
# - Key Vault
# etc.
```

### 4. Apply Infrastructure

```bash
# Create infrastructure (this takes 15-25 minutes)
terraform apply tfplan

# Monitor progress
# Watch AKS cluster creation, may show:
# "Still creating... [2m30s elapsed]"
# "Still creating... [10m15s elapsed]"

# Once complete, Terraform outputs:
# Outputs:
# aks_cluster_name = "..."
# cosmos_endpoint = "https://..."
# redis_host = "..."
```

### 5. Save Outputs

```bash
# Export important values for next steps
terraform output -json > cluster-config.json

# Extract specific values
CLUSTER_NAME=$(terraform output -raw aks_cluster_name)
RESOURCE_GROUP=$(terraform output -raw resource_group_name)
COSMOS_ENDPOINT=$(terraform output -raw cosmos_db_endpoint)
REDIS_HOST=$(terraform output -raw redis_host)

echo "Cluster: $CLUSTER_NAME"
echo "Resource Group: $RESOURCE_GROUP"
```

### 6. Get Kubernetes Credentials

```bash
# Configure kubectl to access your AKS cluster
CLUSTER_NAME=$(terraform output -raw aks_cluster_name)
RESOURCE_GROUP=$(terraform output -raw resource_group_name)

az aks get-credentials \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --overwrite-existing

# Verify connectivity
kubectl get nodes

# Output:
# NAME                                STATUS   ROLES   AGE
# aks-default-12345678-vmss000000     Ready    agent   5m
# aks-default-12345678-vmss000001     Ready    agent   5m
# aks-default-12345678-vmss000002     Ready    agent   5m
```

## Flux GitOps Setup

### 1. Install Flux on the Cluster

```bash
# Check if Flux is already installed
flux check --pre

# Install Flux components
flux install

# Verify installation
kubectl get pods -n flux-system
# Output: source-controller, kustomize-controller, etc. all Running
```

### 2. Create Git Repository Secret

```bash
# Create secret for GitHub authentication (Flux needs to pull from private repo)
flux create secret git github-pat \
  --namespace=flux-system \
  --url=https://github.com \
  --username=git \
  --password=$GITHUB_PAT

# Verify secret created
kubectl get secrets -n flux-system github-pat
```

### 3. Create Git Repository Source

Flux needs to know where to pull manifests from:

```bash
# Check existing source (deploy/flux/repository.yaml)
cat deploy/flux/repository.yaml

# Apply Git source to cluster
kubectl apply -f deploy/flux/repository.yaml

# Verify source is created
kubectl get gitrepository -n flux-system

# Monitor sync status
flux get source git banking-demo --watch
# Output:
# banking-demo    	  True  	Fetched revision... (ready)
```

### 4. Apply Kustomization

Flux uses Kustomize to render and deploy manifests:

```bash
# Check Kustomization config (deploy/flux/kustomization.yaml)
cat deploy/flux/kustomization.yaml

# Apply Kustomization to cluster
kubectl apply -f deploy/flux/kustomization.yaml

# Verify Kustomization is created
kubectl get kustomization -n flux-system

# Monitor reconciliation
flux get kustomization banking-demo --watch
# Output:
# banking-demo    	  True  	Applied revision...
```

### 5. Verify Deployments

```bash
# Check namespace was created
kubectl get namespaces | grep banking-demo

# List all deployments in banking-demo namespace
kubectl get deployments -n banking-demo

# View running pods
kubectl get pods -n banking-demo
# Output: user-service, account-service, transaction-service, transfer-service, etc.

# Check pod status (should be Running)
kubectl describe pod -n banking-demo user-service-xxx-yyy
```

## Configuration Management

### 1. Create Banking Secrets

Store sensitive data in K8s Secrets:

```bash
# Create secret with connection strings and API keys
kubectl create secret generic banking-secrets \
  --namespace=banking-demo \
  --from-literal=cosmos-connection-string="DefaultEndpoint=https://...;AccountKey=..." \
  --from-literal=redis-connection-string="redis-host.redis.cache.windows.net:6380,ssl=True,password=..." \
  --from-literal=appinsights-connection-string="InstrumentationKey=...;IngestionEndpoint=..." \
  --from-literal=openai-endpoint="https://your-openai.openai.azure.com/" \
  --from-literal=openai-api-key="..." \
  --from-literal=jwt-key="YourSuperSecretKeyForJWTTokenGeneration12345"

# Verify secret created
kubectl get secrets -n banking-demo banking-secrets -o yaml

# Update if needed
kubectl patch secret banking-secrets \
  --namespace=banking-demo \
  -p '{"data":{"jwt-key":"...'
```

### 2. Update ConfigMap

Application configuration (non-sensitive):

```bash
# Check existing ConfigMap (deploy/kustomize/base/app.yaml)
kubectl get configmap -n banking-demo banking-demo-config -o yaml

# Update ConfigMap if needed
kubectl patch configmap banking-demo-config \
  --namespace=banking-demo \
  -p '{"data":{"REGISTRY":"ghcr.io","ASPNETCORE_ENVIRONMENT":"Production"}}'
```

### 3. Configure Image Registry

For container image pulls:

```bash
# Create image pull secret for ghcr.io
kubectl create secret docker-registry ghcr-secret \
  --namespace=banking-demo \
  --docker-server=ghcr.io \
  --docker-username=your-github-username \
  --docker-password=$GITHUB_PAT \
  --docker-email=your-email@example.com

# Link secret to service account
kubectl patch serviceaccount default \
  --namespace=banking-demo \
  -p '{"imagePullSecrets":[{"name":"ghcr-secret"}]}'
```

## Container Registry Setup

### 1. Build and Push Images

```bash
# Login to GitHub Container Registry
echo $GITHUB_PAT | docker login ghcr.io -u your-github-username --password-stdin

# Build images (locally or in CI/CD)
docker build -t ghcr.io/your-username/banking-demo/user-service:latest src/user-service/

# Push to registry
docker push ghcr.io/your-username/banking-demo/user-service:latest

# Tag with version
docker tag ghcr.io/your-username/banking-demo/user-service:latest \
           ghcr.io/your-username/banking-demo/user-service:v1.0.0
docker push ghcr.io/your-username/banking-demo/user-service:v1.0.0
```

### 2. Configure GitHub Actions CI/CD

```bash
# CI/CD pipeline automatically:
# 1. Builds images on GitHub
# 2. Pushes to ghcr.io
# 3. Triggers Flux to reconcile with new images
# 4. Flux applies new deployments to AKS

# See .github/workflows/ for pipeline configuration
cat .github/workflows/build-and-push.yml
```

## Secrets Management

### 1. Azure Key Vault Integration

Store secrets securely in Key Vault:

```bash
# Get Key Vault name from Terraform output
KEY_VAULT=$(terraform output -raw key_vault_name)

# Store secret
az keyvault secret set \
  --vault-name $KEY_VAULT \
  --name jwt-key \
  --value "YourSuperSecretKeyForJWTTokenGeneration12345"

# Retrieve secret
az keyvault secret show \
  --vault-name $KEY_VAULT \
  --name jwt-key --query value -o tsv
```

### 2. Sync Secrets to Kubernetes

Use Azure Key Vault Provider for Secrets Store CSI Driver:

```bash
# Install CSI driver for Key Vault integration
helm repo add csi-secrets-store-provider-azure https://raw.githubusercontent.com/Azure/secrets-store-csi-driver-provider-azure/master/charts
helm install csi-secrets-store-provider-azure/csi-secrets-store-provider-azure \
  --namespace kube-system

# Create SecretProviderClass that references Key Vault
kubectl apply -f - <<EOF
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: banking-secrets-provider
  namespace: banking-demo
spec:
  provider: azure
  parameters:
    usePodIdentity: "true"
    keyvaultName: $KEY_VAULT
    tenantId: $(az account show --query tenantId -o tsv)
    objects: |
      array:
        - |
          objectName: jwt-key
          objectType: secret
EOF

# Verify provider class
kubectl get secretproviderclass -n banking-demo
```

## CI/CD Pipeline Overview

### GitHub Actions Workflow

The repository includes automated CI/CD:

```
┌─────────────────────────────────────────────────────────┐
│  Developer Pushes to Main Branch                        │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────▼─────────────┐
        │ GitHub Actions Triggered │
        └────────────┬─────────────┘
                     │
     ┌───────────────┼───────────────┐
     │               │               │
     ▼               ▼               ▼
┌────────┐    ┌──────────┐    ┌──────────┐
│ Lint   │    │  Test    │    │  Build   │
│ Code   │    │  Unit    │    │  Docker  │
└────────┘    │  Tests   │    │ Images   │
              └──────────┘    └──────────┘
                     │               │
                     └───────┬───────┘
                            │
                    ┌───────▼────────┐
                    │ Push to        │
                    │ ghcr.io        │
                    │ Registry       │
                    └───────┬────────┘
                            │
                  ┌─────────▼──────────┐
                  │ Update Kustomize  │
                  │ Image Tags         │
                  │ in deploy/kustomize│
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │ Commit & Push     │
                  │ Updated Manifests │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │ Flux Detects      │
                  │ Changes in Git    │
                  │ Repository        │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │ Flux Reconciles   │
                  │ Deploys New       │
                  │ Service Versions  │
                  └───────────────────┘
```

### Manual Deployment Trigger

If automatic deployment doesn't trigger:

```bash
# Manually reconcile Flux
flux reconcile kustomization banking-demo --with-source

# Check reconciliation status
kubectl get kustomization -n flux-system -o wide

# View Flux events for debugging
kubectl get events -n flux-system --sort-by='.lastTimestamp' | tail -20
```

## Monitoring and Observability

### Application Insights

```bash
# Get Application Insights connection string
APPINSIGHTS_CONNECTION=$(terraform output -raw appinsights_connection_string)

# Query logs in Azure Portal
# Navigate to: Resource Group > Application Insights > Logs
# Run KQL:
# traces | where timestamp > ago(1h) | summarize count() by severityLevel
# requests | where duration > 5000 | summarize count() by name
```

### Kubernetes Monitoring

```bash
# Check cluster health
kubectl get nodes
kubectl get componentstatuses

# View pod metrics (requires metrics-server)
kubectl top nodes
kubectl top pods -n banking-demo

# Check persistent volumes
kubectl get pvc -n banking-demo

# View service mesh (if Istio installed)
kubectl get virtualservices -n banking-demo
```

### Log Aggregation

```bash
# Stream logs from all pods
kubectl logs -f -l app=user-service -n banking-demo

# View logs from crashed pod
kubectl logs <pod-name> --previous -n banking-demo

# Export logs for analysis
kubectl logs -l app=user-service -n banking-demo > user-service-logs.txt
```

## Cost Considerations

### Azure Resource Costs (Estimated Monthly)

| Resource | SKU | Estimated Cost | Notes |
|----------|-----|---|---|
| AKS | 3 nodes (Standard_DS2_v2) | $400-500 | Auto-scaling can increase |
| Cosmos DB | 400 RU/s (provisioned) | $200-300 | Pay-per-request cheaper for low traffic |
| Azure Cache Redis | Premium, 2GB | $100-150 | Managed Redis |
| Application Insights | 1GB ingestion | $50-100 | Log ingestion costs |
| Azure OpenAI | ~1000 tokens/day | $50-100 | Per token pricing |
| Managed Identity, Key Vault | Pay-per-operation | <$10 | Minimal cost |
| **Total Estimated** | | **~$850-1200** | Can be optimized |

### Cost Optimization Tips

1. **Use Dev/Test Environments**: Lower-cost SKUs for non-production
2. **Auto-scaling**: Set appropriate CPU/memory thresholds to avoid over-provisioning
3. **Reserved Instances**: Commit 1-3 years for 30-40% discount on compute
4. **Spot VMs**: Use Azure Spot for non-critical workloads (up to 90% discount)
5. **Log Retention**: Reduce Application Insights retention to 30 days if not needed
6. **Redis**: Switch from Premium to Standard for dev environments
7. **Cosmos DB**: Use shared throughput for multiple containers
8. **Shutdown**: Stop AKS cluster during off-hours (dev environments only)

## Troubleshooting Deployment

### Common Issues

#### Flux Not Reconciling

```bash
# Check Flux reconciliation status
flux get kustomization banking-demo

# Force reconciliation
flux reconcile kustomization banking-demo --with-source

# View Flux controller logs
kubectl logs -n flux-system -l app=kustomize-controller -f
```

#### Pods Stuck in Pending

```bash
# Check pod events
kubectl describe pod <pod-name> -n banking-demo

# Common causes:
# - Insufficient resources: kubectl top nodes
# - Image pull issues: kubectl describe pod -n banking-demo | grep ImagePull
# - Node affinity/tolerations: kubectl get nodes --show-labels
```

#### Service Connectivity Issues

```bash
# Check service DNS resolution
kubectl run -it --rm debug --image=busybox:1.28 --restart=Never -- nslookup user-service.banking-demo

# Test inter-service connectivity
kubectl exec -it <pod-name> -n banking-demo -- curl http://account-service:8080/health

# Check service endpoints
kubectl get endpoints -n banking-demo
```

#### Secret Not Found

```bash
# Verify secret exists
kubectl get secrets -n banking-demo banking-secrets

# Verify pod mounts secret
kubectl describe pod <pod-name> -n banking-demo | grep banking-secrets

# Check secret data
kubectl get secret banking-secrets -n banking-demo -o yaml
```

---

**Last Updated**: May 2024  
**Tested On**: Azure CLI 2.50+, kubectl 1.28+, Terraform 1.5+, Flux 2.1+
