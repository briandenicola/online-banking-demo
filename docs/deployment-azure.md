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

## Configuration Management

### 1. Create Banking Secrets

```bash
# Create K8s secret with sensitive data
kubectl create secret generic banking-secrets \
  --namespace=banking-demo \
  --from-literal=cosmos-connection-string="DefaultEndpoint=https://...;AccountKey=..." \
  --from-literal=redis-connection-string="..." \
  --from-literal=appinsights-connection-string="..." \
  --from-literal=openai-endpoint="https://..." \
  --from-literal=openai-api-key="..." \
  --from-literal=jwt-key="YourSuperSecretKeyForJWTTokenGeneration12345"

# Verify secret
kubectl get secrets -n banking-demo banking-secrets -o yaml
```

### 2. Configure Image Registry

```bash
# Create image pull secret for ghcr.io
kubectl create secret docker-registry ghcr-secret \
  --namespace=banking-demo \
  --docker-server=ghcr.io \
  --docker-username=your-github-username \
  --docker-password=$GITHUB_PAT \
  --docker-email=your-email@example.com

# Link to service account
kubectl patch serviceaccount default \
  --namespace=banking-demo \
  -p '{"imagePullSecrets":[{"name":"ghcr-secret"}]}'
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
