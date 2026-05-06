# Secure Deployment Plan — Online Banking Demo

> **Approach:** Layer-cake — build, deploy, and test one layer at a time. Each layer must pass verification before starting the next.

## Current State

| Component | Resource | Location |
|-----------|----------|----------|
| AKS | `${resource_name}-aks` (Cilium CNI + overlay, KEDA, Azure Policy) | `infra/cloud/main.tf` |
| Cosmos DB | `${resource_name}-cosmos` (Serverless) | `infra/cloud/main.tf` |
| Azure Managed Redis | `${resource_name}-redis` (Balanced B0) | `infra/cloud/main.tf` |
| Azure OpenAI (AI Services) | `${resource_name}-foundry` | `infra/cloud/main.tf` |
| ACR | `${resource_name}acr` (Basic SKU) | `infra/cloud/main.tf` |
| Key Vault | `${resource_name}-kv` | `infra/cloud/main.tf` |
| VNet | `${resource_name}-vnet` with single `aks-subnet` | `infra/cloud/main.tf` |
| K8s manifests | Kustomize base with nginx ingress | `deploy/kustomize/base/` |
| Namespace | `banking-demo` | `deploy/kustomize/base/namespace.yaml` |
| Services | user, account, transaction, transfer, chatbot, budget, anomaly, event-processor, ui-app | `deploy/kustomize/base/*.yaml` |
| Deployment | Taskfile tasks: `up`, `build`, `deploy` | `Taskfile.cloud.yml` |

---

## Layer 1: Kubernetes Hardening

**Dependencies:** None — builds on existing AKS cluster.

### What Changes

#### Terraform (`infra/cloud/main.tf`)

1. **Enable Istio service mesh addon on AKS:**

   ```hcl
   resource "azurerm_kubernetes_cluster" "main" {
     # Add to existing cluster resource
     service_mesh_profile {
       mode                             = "Istio"
       internal_ingress_gateway_enabled = true
       external_ingress_gateway_enabled = true
     }
   }
   ```

   > **Pattern from:** [eShopOnAKS/cluster-config/istio](https://github.com/briandenicola/eShopOnAKS/tree/main/cluster-config/istio) — Brian uses the AKS-managed Istio addon (not standalone Istio), configured via `aks-istio-system` namespace with custom ConfigMaps.

2. **No new Terraform variables needed** — convention over configuration. The mesh mode is always `Istio` for this project.

#### Kustomize Manifests

3. **Create `deploy/cluster-config/` directory** (following eShopOnAKS pattern):

   ```
   deploy/cluster-config/
   ├── kustomization.yaml
   ├── istio/
   │   ├── kustomization.yaml
   │   ├── configuration/
   │   │   ├── kustomization.yaml
   │   │   ├── istio-configuration.yaml     # mesh access logging, tracing
   │   │   └── istio-cluster-roles.yaml     # VirtualService RBAC
   │   └── gateway/
   │       ├── kustomization.yaml
   │       └── banking-ingress.yaml          # Istio Gateway + VirtualService
   ├── cert-manager/
   │   ├── kustomization.yaml
   │   └── cert-manager.yaml                 # HelmRelease via Flux or direct install
   └── network-policies/
       ├── kustomization.yaml
       ├── default-deny.yaml
       └── banking-demo-policies.yaml
   ```

4. **Istio configuration** (`deploy/cluster-config/istio/configuration/istio-configuration.yaml`):

   Following Brian's [eShopOnAKS istio-configuration.yaml](https://github.com/briandenicola/eShopOnAKS/blob/main/cluster-config/istio/configuration/istio-configuration.yaml) pattern:

   ```yaml
   kind: ConfigMap
   apiVersion: v1
   metadata:
     name: istio-shared-configmap-asm-1-24
     namespace: aks-istio-system
   data:
     mesh: |-
       accessLogFile: /dev/stdout
       accessLogEncoding: JSON
       enableTracing: true
       defaultConfig:
         tracing:
           zipkin:
             address: otel-collector.observability.svc.cluster.local:9411
     meshNetworks: 'networks: {}'
   ```

5. **Istio ingress gateway** (`deploy/cluster-config/istio/gateway/banking-ingress.yaml`):

   Replaces the current nginx ingress (`deploy/kustomize/base/ingress.yaml`). Following the [eShopOnAKS default-ingress.yaml](https://github.com/briandenicola/eShopOnAKS/blob/main/cluster-config/istio/gateway/default-ingress.yaml) pattern:

   ```yaml
   apiVersion: networking.istio.io/v1
   kind: Gateway
   metadata:
     name: banking-demo-gateway
     namespace: banking-demo
   spec:
     selector:
       istio: aks-istio-ingressgateway-external
     servers:
     - port:
         number: 443
         name: https
         protocol: HTTPS
       tls:
         mode: SIMPLE
         credentialName: banking-demo-tls
       hosts:
       - "banking-demo.${DOMAIN}"
   ---
   apiVersion: networking.istio.io/v1
   kind: VirtualService
   metadata:
     name: banking-demo-vs
     namespace: banking-demo
   spec:
     hosts:
     - "banking-demo.${DOMAIN}"
     gateways:
     - banking-demo-gateway
     http:
     - match:
       - uri:
           prefix: /api/users
       route:
       - destination:
           host: user-service
           port:
             number: 80
     - match:
       - uri:
           prefix: /api/accounts
       route:
       - destination:
           host: account-service
           port:
             number: 80
     - match:
       - uri:
           prefix: /api/transactions
       route:
       - destination:
           host: transaction-service
           port:
             number: 80
     - match:
       - uri:
           prefix: /api/transfers
       route:
       - destination:
           host: transfer-service
           port:
             number: 80
     - match:
       - uri:
           prefix: /api/chat
       route:
       - destination:
           host: chatbot-service
           port:
             number: 80
     - match:
       - uri:
           prefix: /
       route:
       - destination:
           host: ui-app
           port:
             number: 80
   ```

6. **cert-manager** (`deploy/cluster-config/cert-manager/cert-manager.yaml`):

   Following Brian's [eShopOnAKS cert-manager.yaml](https://github.com/briandenicola/eShopOnAKS/blob/main/cluster-config/cert-manager/cert-manager.yaml) HelmRelease pattern:

   ```yaml
   apiVersion: v1
   kind: Namespace
   metadata:
     name: cert-manager
   ---
   # Install via helm: helm install cert-manager jetstack/cert-manager --namespace cert-manager --set installCRDs=true
   # Then create a ClusterIssuer for Let's Encrypt or self-signed certs
   apiVersion: cert-manager.io/v1
   kind: ClusterIssuer
   metadata:
     name: letsencrypt-prod
   spec:
     acme:
       server: https://acme-v02.api.letsencrypt.org/directory
       email: admin@${DOMAIN}
       privateKeySecretRef:
         name: letsencrypt-prod
       solvers:
       - http01:
           ingress:
             class: istio
   ```

7. **Cilium network policies** (`deploy/cluster-config/network-policies/`):

   The AKS cluster already uses Cilium CNI with `network_policy = "cilium"` (see `infra/cloud/main.tf` line 171). Leverage native Cilium policies:

   ```yaml
   # default-deny.yaml — deny all ingress to banking-demo namespace
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: default-deny-ingress
     namespace: banking-demo
   spec:
     podSelector: {}
     policyTypes:
     - Ingress
   ---
   # banking-demo-policies.yaml — allow traffic from Istio ingress gateway
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: allow-istio-ingress
     namespace: banking-demo
   spec:
     podSelector: {}
     policyTypes:
     - Ingress
     ingress:
     - from:
       - namespaceSelector:
           matchLabels:
             kubernetes.io/metadata.name: aks-istio-ingress
   ---
   # Allow inter-service communication within banking-demo
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: allow-intra-namespace
     namespace: banking-demo
   spec:
     podSelector: {}
     policyTypes:
     - Ingress
     ingress:
     - from:
       - podSelector: {}
   ```

8. **Enable Istio sidecar injection** on `banking-demo` namespace:

   Update `deploy/kustomize/base/namespace.yaml`:

   ```yaml
   apiVersion: v1
   kind: Namespace
   metadata:
     name: banking-demo
     labels:
       app.kubernetes.io/part-of: banking-demo
       istio.io/rev: asm-1-24
   ```

#### Taskfile (`Taskfile.cloud.yml`)

9. **Add `deploy:cluster-config` task** before `deploy`:

   ```yaml
   deploy:cluster-config:
     desc: Deploy cluster configuration (Istio, cert-manager, network policies)
     cmds:
       - kubectl apply -k deploy/cluster-config/
   ```

10. **Update `deploy` task** to remove nginx ingress dependency and call `deploy:cluster-config` first.

### Deploy Steps

```bash
# 1. Apply Terraform to enable Istio addon
task -t Taskfile.cloud.yml apply

# 2. Verify Istio control plane is running
kubectl get pods -n aks-istio-system

# 3. Deploy cluster config (Istio config, cert-manager, network policies)
task -t Taskfile.cloud.yml deploy:cluster-config

# 4. Restart banking-demo pods to inject Istio sidecars
kubectl rollout restart deployment -n banking-demo

# 5. Deploy application with updated ingress
task -t Taskfile.cloud.yml deploy
```

### Verification Criteria

- [ ] `kubectl get pods -n aks-istio-system` — Istiod and ingress gateway pods are `Running`
- [ ] `kubectl get pods -n banking-demo` — all pods show `2/2` containers (sidecar injected)
- [ ] `kubectl get gateway -n banking-demo` — `banking-demo-gateway` exists
- [ ] `kubectl get vs -n banking-demo` — `banking-demo-vs` exists
- [ ] `kubectl get networkpolicy -n banking-demo` — default-deny + allow policies exist
- [ ] `curl -k https://<ISTIO_INGRESS_IP>/api/users` — returns 200 through Istio gateway
- [ ] `kubectl logs -n banking-demo <pod> -c istio-proxy` — access logs showing JSON output
- [ ] `kubectl exec -n default -- curl http://user-service.banking-demo:80` — blocked by NetworkPolicy (should timeout/refuse)

---

## Layer 2: Private Endpoints & DNS

**Dependencies:** Layer 1 complete (VNet and subnets in place).

### What Changes

#### Terraform (`infra/cloud/main.tf`)

1. **Add subnets for private endpoints** (following [ai-application-architectures/infrastructure/agent-service/network.tf](https://github.com/briandenicola/ai-application-architectures/blob/main/infrastructure/agent-service/network.tf) pattern):

   ```hcl
   locals {
     # Add to existing locals
     pe_subnet_cidr = cidrsubnet(local.vnet_cidr, 8, 4)
   }

   resource "azurerm_subnet" "private_endpoints" {
     name                 = "private-endpoints"
     resource_group_name  = azurerm_resource_group.this.name
     virtual_network_name = azurerm_virtual_network.main.name
     address_prefixes     = [local.pe_subnet_cidr]
   }

   resource "azurerm_network_security_group" "pe" {
     name                = "${local.resource_name}-pe-nsg"
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
   }

   resource "azurerm_subnet_network_security_group_association" "pe" {
     subnet_id                 = azurerm_subnet.private_endpoints.id
     network_security_group_id = azurerm_network_security_group.pe.id
   }
   ```

   > **Pattern from:** Brian's agent-service uses a dedicated `private-endpoints` subnet with NSG association. No custom NSG rules needed initially — the default deny-all-inbound plus private endpoint traffic is sufficient.

2. **Private endpoint for Cosmos DB:**

   ```hcl
   resource "azurerm_private_endpoint" "cosmos" {
     name                = "${local.resource_name}-cosmos-pe"
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
     subnet_id           = azurerm_subnet.private_endpoints.id

     private_service_connection {
       name                           = "${local.resource_name}-cosmos-psc"
       private_connection_resource_id = azurerm_cosmosdb_account.main.id
       subresource_names              = ["Sql"]
       is_manual_connection           = false
     }

     private_dns_zone_group {
       name                 = "cosmos-dns-group"
       private_dns_zone_ids = [azurerm_private_dns_zone.cosmos.id]
     }
   }

   resource "azurerm_private_dns_zone" "cosmos" {
     name                = "privatelink.documents.azure.com"
     resource_group_name = azurerm_resource_group.this.name
   }

   resource "azurerm_private_dns_zone_virtual_network_link" "cosmos" {
     name                  = "cosmos-dns-link"
     resource_group_name   = azurerm_resource_group.this.name
     private_dns_zone_name = azurerm_private_dns_zone.cosmos.name
     virtual_network_id    = azurerm_virtual_network.main.id
   }
   ```

3. **Private endpoint for Azure Managed Redis:**

   ```hcl
   resource "azurerm_private_endpoint" "redis" {
     name                = "${local.resource_name}-redis-pe"
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
     subnet_id           = azurerm_subnet.private_endpoints.id

     private_service_connection {
       name                           = "${local.resource_name}-redis-psc"
       private_connection_resource_id = azurerm_managed_redis.main.id
       subresource_names              = ["redisEnterprise"]
       is_manual_connection           = false
     }

     private_dns_zone_group {
       name                 = "redis-dns-group"
       private_dns_zone_ids = [azurerm_private_dns_zone.redis.id]
     }
   }

   resource "azurerm_private_dns_zone" "redis" {
     name                = "privatelink.redisenterprise.cache.azure.net"
     resource_group_name = azurerm_resource_group.this.name
   }

   resource "azurerm_private_dns_zone_virtual_network_link" "redis" {
     name                  = "redis-dns-link"
     resource_group_name   = azurerm_resource_group.this.name
     private_dns_zone_name = azurerm_private_dns_zone.redis.name
     virtual_network_id    = azurerm_virtual_network.main.id
   }
   ```

4. **Private endpoint for ACR** (upgrade to Premium SKU — required for private endpoints):

   ```hcl
   resource "azurerm_container_registry" "main" {
     # Change existing SKU
     sku = "Premium"
     public_network_access_enabled = false
   }

   resource "azurerm_private_endpoint" "acr" {
     name                = "${local.resource_name}-acr-pe"
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
     subnet_id           = azurerm_subnet.private_endpoints.id

     private_service_connection {
       name                           = "${local.resource_name}-acr-psc"
       private_connection_resource_id = azurerm_container_registry.main.id
       subresource_names              = ["registry"]
       is_manual_connection           = false
     }

     private_dns_zone_group {
       name                 = "acr-dns-group"
       private_dns_zone_ids = [azurerm_private_dns_zone.acr.id]
     }
   }

   resource "azurerm_private_dns_zone" "acr" {
     name                = "privatelink.azurecr.io"
     resource_group_name = azurerm_resource_group.this.name
   }

   resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
     name                  = "acr-dns-link"
     resource_group_name   = azurerm_resource_group.this.name
     private_dns_zone_name = azurerm_private_dns_zone.acr.name
     virtual_network_id    = azurerm_virtual_network.main.id
   }
   ```

5. **Private endpoint for Azure OpenAI (AI Services):**

   ```hcl
   resource "azurerm_private_endpoint" "openai" {
     name                = "${local.resource_name}-openai-pe"
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
     subnet_id           = azurerm_subnet.private_endpoints.id

     private_service_connection {
       name                           = "${local.resource_name}-openai-psc"
       private_connection_resource_id = azapi_resource.this.id
       subresource_names              = ["account"]
       is_manual_connection           = false
     }

     private_dns_zone_group {
       name                 = "openai-dns-group"
       private_dns_zone_ids = [azurerm_private_dns_zone.openai.id]
     }
   }

   resource "azurerm_private_dns_zone" "openai" {
     name                = "privatelink.cognitiveservices.azure.com"
     resource_group_name = azurerm_resource_group.this.name
   }

   resource "azurerm_private_dns_zone_virtual_network_link" "openai" {
     name                  = "openai-dns-link"
     resource_group_name   = azurerm_resource_group.this.name
     private_dns_zone_name = azurerm_private_dns_zone.openai.name
     virtual_network_id    = azurerm_virtual_network.main.id
   }
   ```

6. **Disable public access on backing services:**

   ```hcl
   resource "azurerm_cosmosdb_account" "main" {
     # Add to existing
     public_network_access_enabled = false
   }

   # Azure Managed Redis — public access disabled via network rules
   # ACR — already set public_network_access_enabled = false above
   # OpenAI — add to azapi_resource body:
   #   properties.networkAcls.defaultAction = "Deny"
   ```

7. **Private endpoint for Key Vault:**

   ```hcl
   resource "azurerm_key_vault" "main" {
     # Add to existing
     network_acls {
       default_action = "Deny"
       bypass         = "AzureServices"
     }
   }

   resource "azurerm_private_endpoint" "keyvault" {
     name                = "${local.resource_name}-kv-pe"
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
     subnet_id           = azurerm_subnet.private_endpoints.id

     private_service_connection {
       name                           = "${local.resource_name}-kv-psc"
       private_connection_resource_id = azurerm_key_vault.main.id
       subresource_names              = ["vault"]
       is_manual_connection           = false
     }

     private_dns_zone_group {
       name                 = "kv-dns-group"
       private_dns_zone_ids = [azurerm_private_dns_zone.keyvault.id]
     }
   }

   resource "azurerm_private_dns_zone" "keyvault" {
     name                = "privatelink.vaultcore.azure.net"
     resource_group_name = azurerm_resource_group.this.name
   }

   resource "azurerm_private_dns_zone_virtual_network_link" "keyvault" {
     name                  = "kv-dns-link"
     resource_group_name   = azurerm_resource_group.this.name
     private_dns_zone_name = azurerm_private_dns_zone.keyvault.name
     virtual_network_id    = azurerm_virtual_network.main.id
   }
   ```

#### No K8s manifest changes needed — DNS resolution is handled by Azure Private DNS zones linked to the VNet.

### Deploy Steps

```bash
# 1. Apply Terraform (creates PE subnet, private endpoints, DNS zones)
task -t Taskfile.cloud.yml apply

# 2. Verify private endpoints are provisioned
az network private-endpoint list -g $(terraform -chdir=infra/cloud output -raw resource_group_name) -o table

# 3. Verify DNS resolution from within AKS
kubectl run dns-test --rm -it --image=busybox --restart=Never -- nslookup <cosmos-account>.documents.azure.com

# 4. Restart pods to pick up new DNS resolution
kubectl rollout restart deployment -n banking-demo

# 5. Run e2e tests to verify services still connect to backing stores
task -t Taskfile.e2e.yml test
```

### Verification Criteria

- [ ] `az network private-endpoint list -g <RG>` — shows 5 private endpoints (Cosmos, Redis, ACR, OpenAI, Key Vault) all in `Succeeded` state
- [ ] `az network private-dns zone list -g <RG>` — shows all `privatelink.*` DNS zones
- [ ] `kubectl run dns-test --rm -it --image=busybox -- nslookup <cosmos>.documents.azure.com` — resolves to private IP (10.x.x.x), not public
- [ ] Services can connect to Cosmos DB — `kubectl logs -n banking-demo <account-service-pod>` shows no connection errors
- [ ] Services can connect to Redis — `kubectl logs -n banking-demo <transaction-service-pod>` shows no Redis errors
- [ ] `az acr build` still works (note: ACR builds run in Azure, not from your machine — you may need to allow-list your client IP or use `az acr build` with `--no-wait`)
- [ ] Public access to Cosmos DB endpoint is blocked — `curl https://<cosmos>.documents.azure.com` from outside VNet returns connection refused

---

## Layer 3: API Management

**Dependencies:** Layer 1 (Istio ingress) + Layer 2 (VNet with subnets) complete.

### What Changes

#### Terraform (`infra/cloud/main.tf`)

1. **Add APIM subnet** (APIM requires its own dedicated subnet):

   ```hcl
   locals {
     # Add to existing locals
     apim_subnet_cidr = cidrsubnet(local.vnet_cidr, 8, 5)
     apim_name        = "${local.resource_name}-apim"
   }

   resource "azurerm_subnet" "apim" {
     name                 = "apim-subnet"
     resource_group_name  = azurerm_resource_group.this.name
     virtual_network_name = azurerm_virtual_network.main.name
     address_prefixes     = [local.apim_subnet_cidr]
   }
   ```

2. **Create APIM instance** (following [azure-multi-region-proof-of-concept/infrastructure/apim](https://github.com/briandenicola/azure-multi-region-proof-of-concept/tree/main/infrastructure/apim) pattern — single region, VNet-integrated):

   ```hcl
   resource "azurerm_api_management" "main" {
     name                = local.apim_name
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
     publisher_name      = "Online Banking Demo"
     publisher_email     = "admin@bankingdemo.local"
     sku_name            = "Developer_1"

     virtual_network_type = "Internal"
     virtual_network_configuration {
       subnet_id = azurerm_subnet.apim.id
     }

     identity {
       type = "SystemAssigned"
     }

     tags = {
       AppName = local.resource_name
     }
   }
   ```

   > **Note:** `Developer_1` SKU for dev/test. For production, use `Premium_1`. Brian's multi-region PoC uses Standard/Premium. Convention: start simple.

3. **APIM Private DNS zone** (for internal VNet resolution):

   ```hcl
   resource "azurerm_private_dns_zone" "apim" {
     name                = "azure-api.net"
     resource_group_name = azurerm_resource_group.this.name
   }

   resource "azurerm_private_dns_zone_virtual_network_link" "apim" {
     name                  = "apim-dns-link"
     resource_group_name   = azurerm_resource_group.this.name
     private_dns_zone_name = azurerm_private_dns_zone.apim.name
     virtual_network_id    = azurerm_virtual_network.main.id
   }

   resource "azurerm_private_dns_a_record" "apim_gateway" {
     name                = local.apim_name
     zone_name           = azurerm_private_dns_zone.apim.name
     resource_group_name = azurerm_resource_group.this.name
     ttl                 = 300
     records             = [azurerm_api_management.main.private_ip_addresses[0]]
   }
   ```

4. **APIM APIs — one API per banking service:**

   ```hcl
   resource "azurerm_api_management_api" "banking" {
     name                = "banking-api"
     resource_group_name = azurerm_resource_group.this.name
     api_management_name = azurerm_api_management.main.name
     revision            = "1"
     display_name        = "Banking API"
     path                = "api"
     protocols           = ["https"]

     service_url = "http://${azurerm_kubernetes_cluster.main.fqdn}"
   }
   ```

5. **APIM policies** — rate limiting and security headers:

   ```hcl
   resource "azurerm_api_management_api_policy" "banking" {
     api_name            = azurerm_api_management_api.banking.name
     api_management_name = azurerm_api_management.main.name
     resource_group_name = azurerm_resource_group.this.name

     xml_content = <<XML
     <policies>
       <inbound>
         <base />
         <rate-limit calls="100" renewal-period="60" />
         <set-header name="X-Forwarded-By" exists-action="override">
           <value>APIM</value>
         </set-header>
         <cors>
           <allowed-origins>
             <origin>*</origin>
           </allowed-origins>
         </cors>
       </inbound>
       <backend>
         <base />
       </backend>
       <outbound>
         <base />
         <set-header name="X-Powered-By" exists-action="delete" />
         <set-header name="X-AspNet-Version" exists-action="delete" />
       </outbound>
       <on-error>
         <base />
       </on-error>
     </policies>
     XML
   }
   ```

6. **Add Terraform outputs:**

   ```hcl
   output "apim_gateway_url" {
     value = azurerm_api_management.main.gateway_url
   }

   output "apim_private_ip" {
     value = azurerm_api_management.main.private_ip_addresses[0]
   }
   ```

### Deploy Steps

```bash
# 1. Apply Terraform (APIM takes 30-45 minutes to provision)
task -t Taskfile.cloud.yml apply

# 2. Verify APIM is provisioned
az apim show -n $(terraform -chdir=infra/cloud output -raw apim_name) -g $(terraform -chdir=infra/cloud output -raw resource_group_name) --query "provisioningState"

# 3. Test API endpoint from within VNet
kubectl run api-test --rm -it --image=curlimages/curl --restart=Never -- \
  curl -v https://<apim-name>.azure-api.net/api/users

# 4. Verify rate limiting
for i in $(seq 1 110); do curl -s -o /dev/null -w "%{http_code}\n" https://<apim-gateway>/api/users; done
# Should see 429 after 100 requests
```

### Verification Criteria

- [ ] `az apim show` — APIM in `Succeeded` provisioning state
- [ ] APIM is VNet-integrated — `virtualNetworkType` is `Internal`
- [ ] DNS resolves — `nslookup <apim-name>.azure-api.net` from within AKS returns private IP
- [ ] API calls through APIM reach AKS services — `/api/users` returns 200
- [ ] Rate limiting works — 101st request within 60s returns HTTP 429
- [ ] Security headers stripped — response does not contain `X-Powered-By` or `X-AspNet-Version`

---

## Layer 4: Application Gateway (Stretch Goal)

**Dependencies:** Layer 3 (APIM with internal VNet) complete.

### What Changes

#### Terraform (`infra/cloud/main.tf`)

1. **Add Application Gateway subnet** (requires its own dedicated subnet, min /24):

   ```hcl
   locals {
     # Add to existing locals
     appgw_subnet_cidr = cidrsubnet(local.vnet_cidr, 8, 6)
     appgw_name        = "${local.resource_name}-appgw"
     appgw_pip_name    = "${local.resource_name}-appgw-pip"
   }

   resource "azurerm_subnet" "appgw" {
     name                 = "appgw-subnet"
     resource_group_name  = azurerm_resource_group.this.name
     virtual_network_name = azurerm_virtual_network.main.name
     address_prefixes     = [local.appgw_subnet_cidr]
   }
   ```

2. **Public IP for Application Gateway:**

   ```hcl
   resource "azurerm_public_ip" "appgw" {
     name                = local.appgw_pip_name
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
     allocation_method   = "Static"
     sku                 = "Standard"
     tags = {
       AppName = local.resource_name
     }
   }
   ```

3. **Application Gateway with WAF v2** (following [azure-multi-region-proof-of-concept/infrastructure/gateway](https://github.com/briandenicola/azure-multi-region-proof-of-concept/tree/main/infrastructure/gateway) pattern):

   ```hcl
   resource "azurerm_web_application_firewall_policy" "main" {
     name                = "${local.resource_name}-waf-policy"
     resource_group_name = azurerm_resource_group.this.name
     location            = azurerm_resource_group.this.location

     policy_settings {
       enabled                     = true
       mode                        = "Prevention"
       request_body_check          = true
       max_request_body_size_in_kb = 128
     }

     managed_rules {
       managed_rule_set {
         type    = "OWASP"
         version = "3.2"
       }
     }
   }

   resource "azurerm_application_gateway" "main" {
     name                = local.appgw_name
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
     firewall_policy_id  = azurerm_web_application_firewall_policy.main.id

     sku {
       name     = "WAF_v2"
       tier     = "WAF_v2"
       capacity = 2
     }

     gateway_ip_configuration {
       name      = "appgw-ip-config"
       subnet_id = azurerm_subnet.appgw.id
     }

     frontend_port {
       name = "https-port"
       port = 443
     }

     frontend_port {
       name = "http-port"
       port = 80
     }

     frontend_ip_configuration {
       name                 = "appgw-frontend-ip"
       public_ip_address_id = azurerm_public_ip.appgw.id
     }

     # Backend pool points to APIM private IP
     backend_address_pool {
       name  = "apim-backend"
       fqdns = ["${local.apim_name}.azure-api.net"]
     }

     backend_http_settings {
       name                  = "apim-https-settings"
       cookie_based_affinity = "Disabled"
       port                  = 443
       protocol              = "Https"
       request_timeout       = 30
       probe_name            = "apim-health-probe"

       pick_host_name_from_backend_address = true
     }

     http_listener {
       name                           = "https-listener"
       frontend_ip_configuration_name = "appgw-frontend-ip"
       frontend_port_name             = "https-port"
       protocol                       = "Https"
       ssl_certificate_name           = "appgw-ssl-cert"
     }

     http_listener {
       name                           = "http-listener"
       frontend_ip_configuration_name = "appgw-frontend-ip"
       frontend_port_name             = "http-port"
       protocol                       = "Http"
     }

     # HTTP to HTTPS redirect
     redirect_configuration {
       name                 = "http-to-https"
       redirect_type        = "Permanent"
       target_listener_name = "https-listener"
       include_path         = true
       include_query_string = true
     }

     request_routing_rule {
       name                        = "apim-routing-rule"
       priority                    = 100
       rule_type                   = "Basic"
       http_listener_name          = "https-listener"
       backend_address_pool_name   = "apim-backend"
       backend_http_settings_name  = "apim-https-settings"
     }

     request_routing_rule {
       name                       = "http-redirect-rule"
       priority                   = 200
       rule_type                  = "Basic"
       http_listener_name         = "http-listener"
       redirect_configuration_name = "http-to-https"
     }

     probe {
       name                = "apim-health-probe"
       protocol            = "Https"
       path                = "/status-0123456789abcdef"
       interval            = 30
       timeout             = 30
       unhealthy_threshold = 3
       pick_host_name_from_backend_http_settings = true
     }

     ssl_certificate {
       name                = "appgw-ssl-cert"
       key_vault_secret_id = azurerm_key_vault_certificate.appgw.secret_id
     }

     identity {
       type         = "UserAssigned"
       identity_ids = [azurerm_user_assigned_identity.appgw.id]
     }

     tags = {
       AppName = local.resource_name
     }
   }
   ```

4. **Managed identity for App Gateway to access Key Vault certs:**

   ```hcl
   resource "azurerm_user_assigned_identity" "appgw" {
     name                = "${local.resource_name}-appgw-mi"
     location            = azurerm_resource_group.this.location
     resource_group_name = azurerm_resource_group.this.name
   }

   resource "azurerm_role_assignment" "appgw_kv_secrets" {
     scope                = azurerm_key_vault.main.id
     role_definition_name = "Key Vault Secrets User"
     principal_id         = azurerm_user_assigned_identity.appgw.principal_id
   }
   ```

5. **Add Terraform outputs:**

   ```hcl
   output "appgw_public_ip" {
     value = azurerm_public_ip.appgw.ip_address
   }
   ```

### Deploy Steps

```bash
# 1. Upload TLS cert to Key Vault (if not using self-signed)
az keyvault certificate create --vault-name <kv-name> --name appgw-ssl-cert --policy "$(az keyvault certificate get-default-policy)"

# 2. Apply Terraform
task -t Taskfile.cloud.yml apply

# 3. Get public IP
terraform -chdir=infra/cloud output appgw_public_ip

# 4. Test from internet
curl -v https://<appgw-public-ip>/api/users -H "Host: banking-demo.example.com"
```

### Verification Criteria

- [ ] App Gateway is `Running` — `az network application-gateway show`
- [ ] WAF policy is in `Prevention` mode
- [ ] HTTP → HTTPS redirect works — `curl -I http://<public-ip>` returns 301 to HTTPS
- [ ] Traffic flows: Internet → App Gateway → APIM → Istio → Service
- [ ] WAF blocks SQL injection — `curl "https://<public-ip>/api/users?id=1' OR 1=1--"` returns 403
- [ ] WAF blocks XSS — `curl "https://<public-ip>/api/users?name=<script>alert(1)</script>"` returns 403
- [ ] Health probe succeeds — App Gateway backend health shows APIM as `Healthy`

---

## Architecture Summary

```
Internet
   │
   ▼
┌──────────────────────────┐
│  Application Gateway     │  Layer 4 (stretch)
│  WAF v2 + SSL            │  appgw-subnet
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  API Management          │  Layer 3
│  Rate limiting, policies │  apim-subnet (Internal VNet)
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  AKS Cluster             │  Layer 1
│  Istio mesh + gateway    │  aks-subnet
│  Cilium network policies │
│  cert-manager TLS        │
│  ┌────────────────────┐  │
│  │ banking-demo ns    │  │
│  │ (sidecar injected) │  │
│  │ user-service       │  │
│  │ account-service    │  │
│  │ transaction-svc    │  │
│  │ transfer-service   │  │
│  │ chatbot-service    │  │
│  │ budget-service     │  │
│  │ anomaly-service    │  │
│  │ event-processor    │  │
│  │ ui-app             │  │
│  └────────────────────┘  │
└──────────────────────────┘
           │
           ▼ (private endpoints)
┌──────────────────────────┐
│  Azure PaaS Services     │  Layer 2
│  private-endpoints subnet│
│  ┌──────┐ ┌──────┐      │
│  │Cosmos│ │Redis │      │
│  └──────┘ └──────┘      │
│  ┌──────┐ ┌──────┐      │
│  │ ACR  │ │OpenAI│      │
│  └──────┘ └──────┘      │
│  ┌──────┐               │
│  │  KV  │               │
│  └──────┘               │
└──────────────────────────┘
```

## Subnet Layout

All CIDRs derived from `local.vnet_cidr` using `cidrsubnet()` — no manual IP math needed.

| Subnet | CIDR | Purpose |
|--------|------|---------|
| `aks-subnet` | `cidrsubnet(vnet_cidr, 8, 3)` | AKS node pool (existing) |
| `private-endpoints` | `cidrsubnet(vnet_cidr, 8, 4)` | Private endpoints for PaaS |
| `apim-subnet` | `cidrsubnet(vnet_cidr, 8, 5)` | API Management (internal) |
| `appgw-subnet` | `cidrsubnet(vnet_cidr, 8, 6)` | Application Gateway + WAF |

## Reference Patterns Used

| Pattern | Source Repo | Applied In |
|---------|-------------|-----------|
| VNet + PE subnet + NSG association | [ai-application-architectures/agent-service/network.tf](https://github.com/briandenicola/ai-application-architectures/blob/main/infrastructure/agent-service/network.tf) | Layer 2 |
| `cidrsubnet()` for all CIDR derivation | [ai-application-architectures/agent-service/main.tf](https://github.com/briandenicola/ai-application-architectures/blob/main/infrastructure/agent-service/main.tf) | All layers |
| Naming: `${resource_name}-<suffix>` | [ai-application-architectures/agent-service/main.tf](https://github.com/briandenicola/ai-application-architectures/blob/main/infrastructure/agent-service/main.tf) | All layers |
| Istio mesh addon + ConfigMap config | [eShopOnAKS/cluster-config/istio/configuration](https://github.com/briandenicola/eShopOnAKS/tree/main/cluster-config/istio/configuration) | Layer 1 |
| Istio ingress gateway + VirtualService | [eShopOnAKS/cluster-config/istio/gateway](https://github.com/briandenicola/eShopOnAKS/tree/main/cluster-config/istio/gateway) | Layer 1 |
| cert-manager HelmRelease | [eShopOnAKS/cluster-config/cert-manager](https://github.com/briandenicola/eShopOnAKS/tree/main/cluster-config/cert-manager) | Layer 1 |
| APIM internal VNet + APIs | [azure-multi-region-proof-of-concept/infrastructure/apim](https://github.com/briandenicola/azure-multi-region-proof-of-concept/tree/main/infrastructure/apim) | Layer 3 |
| App Gateway WAF v2 + backend pool | [azure-multi-region-proof-of-concept/infrastructure/gateway](https://github.com/briandenicola/azure-multi-region-proof-of-concept/tree/main/infrastructure/gateway) | Layer 4 |
| Convention over variables (`max_count = node_count * 2`) | Current repo `infra/cloud/main.tf:149` | All layers |
