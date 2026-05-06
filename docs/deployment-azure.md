# Azure Deployment Guide

## Architecture Overview

The Online Banking Demo is designed for cloud-native deployment on Azure using modern DevOps practices and GitOps principles.

### High-Level Architecture

```
Azure Resource Group
├─ AKS Cluster (Kubernetes)
│  ├─ Namespace: banking-demo
│  ├─ Deployments (2 replicas each):
│  │  ├─ user-service, account-service
│  │  ├─ transaction-service, transfer-service
│  │  └─ chatbot-service, anomaly-service, budget-service
│  ├─ Services (ClusterIP, LoadBalancer for gateway)
│  ├─ ConfigMaps & Secrets (banking-secrets)
│
├─ Cosmos DB (managed database)
├─ Azure Cache for Redis (managed Redis)
├─ Container Registry (ghcr.io)
├─ Azure OpenAI (AI endpoint)
├─ Application Insights (logging & monitoring)
├─ Key Vault (secrets management)
└─ Log Analytics Workspace (diagnostics)
```

### Azure Resources

| Resource | Purpose | Configuration |
|----------|---------|----------------|
| **AKS** | Container orchestration | 3-5 nodes, auto-scaling |
| **Cosmos DB** | Primary database | Multi-region, SSD storage |
| **Azure Cache Redis** | Distributed caching, events | Premium tier |
| **Azure OpenAI** | AI services | gpt-4o-mini deployment |
| **Application Insights** | Logging & monitoring | Workspace-based |
| **Key Vault** | Secrets management | RBAC-protected |
| **Container Registry** | Image storage | ghcr.io (GitHub) |

## Prerequisites

### Required Tools

- **Azure CLI**: Version 2.50+ ([install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli))
- **kubectl**: Kubernetes CLI ([install](https://kubernetes.io/docs/tasks/tools/))
- **Flux CLI**: GitOps management ([install](https://fluxcd.io/docs/installation/))
- **Terraform**: Version 1.5+ ([install](https://www.terraform.io/downloads))

### Azure Account

- **Active subscription** with billing enabled
- **Owner or Contributor** role in subscription
- **Permissions** for AKS, Cosmos DB, managed services

## Infrastructure Provisioning with Terraform

### 1. Initialize Infrastructure

```bash
cd infra/cloud

# Initialize Terraform
terraform init

# Validate configuration
terraform validate
```

### 2. Plan Deployment

```bash
# Generate execution plan
terraform plan -out=tfplan

# Review resources to be created
```

### 3. Apply Infrastructure

```bash
# Create infrastructure (15-25 minutes)
terraform apply tfplan

# Note the outputs:
# - aks_cluster_name
# - cosmos_endpoint
# - redis_host
```

### 4. Get Kubernetes Credentials

```bash
# Configure kubectl
CLUSTER_NAME=$(terraform output -raw aks_cluster_name)
RESOURCE_GROUP=$(terraform output -raw resource_group_name)

az aks get-credentials \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --overwrite-existing

# Verify connectivity
kubectl get nodes
```

### 5. Collect Resource Connection Details

Before configuring secrets, gather connection strings and endpoints from the Azure resources provisioned by Terraform:

```bash
# Set variables for easy access
CLUSTER_NAME=$(terraform output -raw aks_cluster_name)
RESOURCE_GROUP=$(terraform output -raw resource_group_name)
KEYVAULT_NAME=$(terraform output -raw keyvault_name)
COSMOS_ACCOUNT=$(terraform output -raw cosmos_account_name)
REDIS_NAME=$(terraform output -raw redis_name)
OPENAI_RESOURCE=$(terraform output -raw openai_resource_name)
AI_RESOURCE=$(terraform output -raw ai_resource_name)

# Get AKS Managed Identity
IDENTITY_PRINCIPAL_ID=$(az aks show -g $RESOURCE_GROUP -n $CLUSTER_NAME --query "identity.principalId" -o tsv)

# Cosmos DB Connection String
COSMOS_CONNECTION_STRING=$(az cosmosdb keys list \
  --name $COSMOS_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --type connection-strings \
  --query "connectionStrings[0].connectionString" -o tsv)
echo "COSMOS_CONNECTION_STRING: $COSMOS_CONNECTION_STRING"

# Redis Connection String
REDIS_HOSTNAME=$(az redis show -g $RESOURCE_GROUP -n $REDIS_NAME --query "hostName" -o tsv)
REDIS_KEY=$(az redis list-keys -g $RESOURCE_GROUP -n $REDIS_NAME --query "primaryKey" -o tsv)
REDIS_CONNECTION_STRING="${REDIS_HOSTNAME}:6380,password=${REDIS_KEY},ssl=True"
echo "REDIS_CONNECTION_STRING: $REDIS_CONNECTION_STRING"

# Azure OpenAI Endpoint & Keys
AZURE_OPENAI_ENDPOINT=$(az cognitiveservices account show \
  -n $OPENAI_RESOURCE \
  -g $RESOURCE_GROUP \
  --query "properties.endpoint" -o tsv)
echo "AZURE_OPENAI_ENDPOINT: $AZURE_OPENAI_ENDPOINT"

# Azure AI Services Endpoint
AZURE_AI_ENDPOINT=$(az cognitiveservices account show \
  -n $AI_RESOURCE \
  -g $RESOURCE_GROUP \
  --query "properties.endpoint" -o tsv)
echo "AZURE_AI_AGENTS_ENDPOINT: $AZURE_AI_ENDPOINT"

# Application Insights Connection String
APPINSIGHTS_NAME="${CLUSTER_NAME}-insights"
APPINSIGHTS_CONNECTION=$(az monitor app-insights component show \
  -g $RESOURCE_GROUP \
  -a $APPINSIGHTS_NAME \
  --query "connectionString" -o tsv)
echo "APPLICATIONINSIGHTS_CONNECTION_STRING: $APPINSIGHTS_CONNECTION"

# Generate JWT Secret (one-time)
JWT_KEY=$(openssl rand -base64 32)
echo "Jwt__Key: $JWT_KEY"

# Azure Tenant & Client ID (for managed identity)
AZURE_TENANT_ID=$(az account show --query "tenantId" -o tsv)
AZURE_CLIENT_ID=$(az aks show -g $RESOURCE_GROUP -n $CLUSTER_NAME --query "identity.userAssignedIdentities" -o tsv | grep -oE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | head -1)
echo "AZURE_TENANT_ID: $AZURE_TENANT_ID"
echo "AZURE_CLIENT_ID: $AZURE_CLIENT_ID"

# Save to file for later use (keep this secure!)
cat > azure-credentials.env << EOF
Jwt__Key=$JWT_KEY
COSMOS_CONNECTION_STRING=$COSMOS_CONNECTION_STRING
REDIS__CONNECTIONSTRING=$REDIS_CONNECTION_STRING
AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_MODEL=gpt-4o-mini
AZURE_AI_AGENTS_ENDPOINT=$AZURE_AI_ENDPOINT
APPLICATIONINSIGHTS_CONNECTION_STRING=$APPINSIGHTS_CONNECTION
AZURE_TENANT_ID=$AZURE_TENANT_ID
AZURE_CLIENT_ID=$AZURE_CLIENT_ID
UseInMemoryDatabase=false
Jwt__Issuer=user-service
ASPNETCORE_ENVIRONMENT=Production
EOF

# IMPORTANT: Keep azure-credentials.env secret
# Add to .gitignore if not already there
echo "azure-credentials.env" >> .gitignore
```

## Flux GitOps Setup

### 1. Install Flux on Cluster

```bash
# Install Flux components
flux install

# Verify installation
kubectl get pods -n flux-system
```

### 2. Create GitHub Authentication

```bash
# Create secret for GitHub access
flux create secret git github-pat \
  --namespace=flux-system \
  --url=https://github.com \
  --username=git \
  --password=$GITHUB_PAT
```

### 3. Apply Git Repository Source

```bash
# Apply Git source configuration
kubectl apply -f deploy/flux/repository.yaml

# Verify source
kubectl get gitrepository -n flux-system

# Monitor sync
flux get source git banking-demo --watch
```

### 4. Apply Kustomization

```bash
# Apply Kustomization config
kubectl apply -f deploy/flux/kustomization.yaml

# Monitor reconciliation
flux get kustomization banking-demo --watch
```

### 5. Verify Deployments

```bash
# Check deployments in banking-demo namespace
kubectl get deployments -n banking-demo

# View running pods
kubectl get pods -n banking-demo

# Check pod status (should be Running)
kubectl describe pod -n banking-demo user-service-xxx-yyy
```

## Environment & Secrets Configuration

### 1. Prepare Environment Variables

Azure deployment requires all secrets to be stored in Azure Key Vault (not committed to git). Create an `.env` file locally for the deploy process, or set them directly in Key Vault.

#### Required Variables for Azure Deployment

All of the following must be set before deploying to Azure:

| Variable | Required | Purpose | Example |
|----------|----------|---------|---------|
| **Jwt__Key** | ✓ | JWT token signing secret | Generated with `openssl rand -base64 32` |
| **Jwt__Issuer** | ✓ | JWT token issuer claim | `user-service` |
| **UseInMemoryDatabase** | ✓ | Must be `false` for production | `false` |
| **COSMOS_CONNECTION_STRING** | ✓ | Cosmos DB connection string | `DefaultEndpoint=https://...;AccountKey=...;` |
| **REDIS__CONNECTIONSTRING** | ✓ | Azure Cache for Redis connection | `<cache-name>.redis.cache.windows.net:6380` |
| **AZURE_TENANT_ID** | ✓ | Azure AD tenant ID | `12345678-1234-1234-1234-123456789012` |
| **AZURE_CLIENT_ID** | ✓ | Managed Identity or Service Principal client ID | `12345678-1234-1234-1234-123456789012` |
| **AZURE_CLIENT_SECRET** | ✗ (optional) | Service Principal secret (use managed identity instead) | - |
| **AZURE_OPENAI_ENDPOINT** | ✓ | Azure OpenAI service endpoint | `https://<resource>.openai.azure.com/` |
| **AZURE_OPENAI_MODEL** | ✓ | Deployment name for GPT model | `gpt-4o-mini` |
| **AZURE_AI_AGENTS_ENDPOINT** | ✓ | Azure AI Services endpoint | `https://<resource>.cognitiveservices.azure.com/` |
| **APPLICATIONINSIGHTS_CONNECTION_STRING** | ✓ | Application Insights ingestion endpoint | `InstrumentationKey=...;` |

#### Optional Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| **Services__AccountService** | Account service URL | `https://account-service.banking-demo.svc.cluster.local` |
| **Services__TransactionService** | Transaction service URL | `https://transaction-service.banking-demo.svc.cluster.local` |
| **CORS_ALLOWED_ORIGINS** | Allowed CORS origins | `https://banking-demo.azurewebsites.net` |
| **ASPNETCORE_ENVIRONMENT** | ASP.NET Core environment | `Production` |

### 2. Azure Key Vault Setup

Store all secrets in Azure Key Vault for secure, centralized management:

```bash
# Create Key Vault (if not already created by Terraform)
KEYVAULT_NAME="banking-demo-kv"
az keyvault create \
  --name $KEYVAULT_NAME \
  --resource-group $RESOURCE_GROUP

# Set secrets in Key Vault
az keyvault secret set --vault-name $KEYVAULT_NAME \
  --name "JwtKey" \
  --value "$(openssl rand -base64 32)"

az keyvault secret set --vault-name $KEYVAULT_NAME \
  --name "CosmosConnectionString" \
  --value "DefaultEndpoint=https://<account>.documents.azure.com:443/;AccountKey=<key>;"

az keyvault secret set --vault-name $KEYVAULT_NAME \
  --name "RedisConnectionString" \
  --value "<cache-name>.redis.cache.windows.net:6380,password=<key>,ssl=True"

az keyvault secret set --vault-name $KEYVAULT_NAME \
  --name "AzureOpenAiEndpoint" \
  --value "https://<resource>.openai.azure.com/"

az keyvault secret set --vault-name $KEYVAULT_NAME \
  --name "AzureAiAgentsEndpoint" \
  --value "https://<resource>.cognitiveservices.azure.com/"

az keyvault secret set --vault-name $KEYVAULT_NAME \
  --name "ApplicationInsightsConnectionString" \
  --value "InstrumentationKey=<key>;IngestionEndpoint=https://..."

# Grant AKS managed identity access to Key Vault
IDENTITY_PRINCIPAL_ID=$(az aks show -g $RESOURCE_GROUP -n $CLUSTER_NAME --query "identity.principalId" -o tsv)
az keyvault set-policy --name $KEYVAULT_NAME \
  --object-id $IDENTITY_PRINCIPAL_ID \
  --secret-permissions get list

# Verify secrets are set
az keyvault secret list --vault-name $KEYVAULT_NAME --query "[].[name]" -o tsv
```

### 3. Create Kubernetes Secrets from Key Vault

Option A: **Automated (Using External Secrets Operator)**

```bash
# Install External Secrets Operator (Helm)
helm repo add external-secrets https://charts.external-secrets.io
helm repo update
helm install external-secrets \
  external-secrets/external-secrets \
  -n external-secrets-system \
  --create-namespace

# Create SecretStore resource pointing to Key Vault
kubectl apply -f - <<EOF
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: azure-keyvault
  namespace: banking-demo
spec:
  provider:
    azure:
      authType: managedIdentity
      vaultUrl: https://${KEYVAULT_NAME}.vault.azure.net
      identityID: ${AZURE_CLIENT_ID}
EOF

# Create ExternalSecret to sync secrets into K8s
kubectl apply -f - <<EOF
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: banking-secrets
  namespace: banking-demo
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: azure-keyvault
    kind: SecretStore
  target:
    name: banking-secrets
    creationPolicy: Owner
  data:
    - secretKey: jwt-key
      remoteRef:
        key: JwtKey
    - secretKey: cosmos-connection-string
      remoteRef:
        key: CosmosConnectionString
    - secretKey: redis-connection-string
      remoteRef:
        key: RedisConnectionString
    - secretKey: azure-openai-endpoint
      remoteRef:
        key: AzureOpenAiEndpoint
    - secretKey: azure-ai-agents-endpoint
      remoteRef:
        key: AzureAiAgentsEndpoint
    - secretKey: appinsights-connection-string
      remoteRef:
        key: ApplicationInsightsConnectionString
EOF
```

Option B: **Manual Kubernetes Secret Creation**

```bash
# Get secrets from Key Vault
JWT_KEY=$(az keyvault secret show --vault-name $KEYVAULT_NAME --name "JwtKey" -o tsv --query "value")
COSMOS_CS=$(az keyvault secret show --vault-name $KEYVAULT_NAME --name "CosmosConnectionString" -o tsv --query "value")
REDIS_CS=$(az keyvault secret show --vault-name $KEYVAULT_NAME --name "RedisConnectionString" -o tsv --query "value")
OPENAI_EP=$(az keyvault secret show --vault-name $KEYVAULT_NAME --name "AzureOpenAiEndpoint" -o tsv --query "value")
AI_AGENTS_EP=$(az keyvault secret show --vault-name $KEYVAULT_NAME --name "AzureAiAgentsEndpoint" -o tsv --query "value")
APPINSIGHTS_CS=$(az keyvault secret show --vault-name $KEYVAULT_NAME --name "ApplicationInsightsConnectionString" -o tsv --query "value")

# Create Kubernetes secret
kubectl create secret generic banking-secrets \
  --namespace=banking-demo \
  --from-literal=jwt-key="$JWT_KEY" \
  --from-literal=cosmos-connection-string="$COSMOS_CS" \
  --from-literal=redis-connection-string="$REDIS_CS" \
  --from-literal=azure-openai-endpoint="$OPENAI_EP" \
  --from-literal=azure-ai-agents-endpoint="$AI_AGENTS_EP" \
  --from-literal=appinsights-connection-string="$APPINSIGHTS_CS"

# Verify secret was created
kubectl describe secret banking-secrets -n banking-demo
```

### 4. Create ConfigMap for Non-Sensitive Configuration

```bash
# Create ConfigMap with environment variables and service URLs
kubectl create configmap banking-config \
  --namespace=banking-demo \
  --from-literal=UseInMemoryDatabase="false" \
  --from-literal=Jwt__Issuer="user-service" \
  --from-literal=AZURE_OPENAI_MODEL="gpt-4o-mini" \
  --from-literal=ASPNETCORE_ENVIRONMENT="Production" \
  --from-literal=Services__AccountService="http://account-service:8080" \
  --from-literal=Services__TransactionService="http://transaction-service:8080"

# Verify ConfigMap
kubectl describe configmap banking-config -n banking-demo
```

### 5. Mount Secrets in Deployment Specs

Reference these secrets/configs in your Kubernetes deployment files:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-service
spec:
  template:
    spec:
      containers:
      - name: user-service
        image: ghcr.io/your-org/banking-demo/user-service:latest
        env:
          # From Secrets
          - name: Jwt__Key
            valueFrom:
              secretKeyRef:
                name: banking-secrets
                key: jwt-key
          - name: APPLICATIONINSIGHTS_CONNECTION_STRING
            valueFrom:
              secretKeyRef:
                name: banking-secrets
                key: appinsights-connection-string
          # From ConfigMap
          - name: Jwt__Issuer
            valueFrom:
              configMapKeyRef:
                name: banking-config
                key: Jwt__Issuer
          - name: UseInMemoryDatabase
            valueFrom:
              configMapKeyRef:
                name: banking-config
                key: UseInMemoryDatabase
```

## Container Registry & CI/CD

### Build & Push Images

```bash
# Login to GitHub Container Registry
echo $GITHUB_PAT | docker login ghcr.io -u your-username --password-stdin

# Build image
docker build -t ghcr.io/your-username/banking-demo/user-service:latest src/user-service/

# Push to registry
docker push ghcr.io/your-username/banking-demo/user-service:latest

# Tag with version
docker tag ghcr.io/your-username/banking-demo/user-service:latest \
           ghcr.io/your-username/banking-demo/user-service:v1.0.0
docker push ghcr.io/your-username/banking-demo/user-service:v1.0.0
```

### GitHub Actions CI/CD Pipeline

CI/CD automatically:
1. Builds images on GitHub
2. Pushes to ghcr.io
3. Triggers Flux to reconcile
4. Flux applies new deployments to AKS

See `.github/workflows/` for configuration.

## Monitoring & Observability

### Application Insights

```bash
# Get connection string
APPINSIGHTS_CONNECTION=$(terraform output -raw appinsights_connection_string)

# Query logs in Azure Portal → Application Insights → Logs
# KQL examples:
# traces | where timestamp > ago(1h) | summarize count() by severityLevel
# requests | where duration > 5000 | summarize count() by name
```

### Kubernetes Monitoring

```bash
# Check cluster health
kubectl get nodes
kubectl get componentstatuses

# View pod metrics
kubectl top nodes
kubectl top pods -n banking-demo

# Check persistent volumes
kubectl get pvc -n banking-demo
```

### Log Aggregation

```bash
# Stream pod logs
kubectl logs -f -l app=user-service -n banking-demo

# View logs from crashed pod
kubectl logs <pod-name> --previous -n banking-demo

# Export logs
kubectl logs -l app=user-service -n banking-demo > user-logs.txt
```

## Cost Considerations

### Estimated Monthly Costs

| Resource | SKU | Cost |
|----------|-----|------|
| AKS | 3 nodes (Standard_DS2_v2) | $400-500 |
| Cosmos DB | 400 RU/s provisioned | $200-300 |
| Azure Cache Redis | Premium, 2GB | $100-150 |
| Application Insights | 1GB ingestion | $50-100 |
| Azure OpenAI | ~1000 tokens/day | $50-100 |
| **Total** | | **~$850-1200** |

### Optimization Tips

- Use Dev/Test environments with lower-cost SKUs
- Enable auto-scaling based on CPU/memory
- Use Reserved Instances for 30-40% discount
- Use Azure Spot VMs (up to 90% discount) for non-critical workloads
- Reduce Application Insights retention to 30 days
- Shut down AKS cluster during off-hours (dev environments)

## Troubleshooting

### Flux Not Reconciling

```bash
# Check reconciliation status
flux get kustomization banking-demo

# Force reconciliation
flux reconcile kustomization banking-demo --with-source

# View controller logs
kubectl logs -n flux-system -l app=kustomize-controller -f
```

### Pods Stuck in Pending

```bash
# Check pod events
kubectl describe pod <pod-name> -n banking-demo

# Check node resources
kubectl top nodes

# Check image pull issues
kubectl describe pod -n banking-demo | grep ImagePull
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

---

**Last Updated**: May 2024  
**Tested On**: Azure CLI 2.50+, kubectl 1.28+, Terraform 1.5+, Flux 2.1+
