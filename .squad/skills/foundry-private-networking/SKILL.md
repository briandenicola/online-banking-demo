# Skill: Azure AI Foundry Private Networking — Canonical Pattern

**When to use:** Any Azure AI Foundry deployment that requires private networking (VNet isolation, private endpoints, no public internet access).

**Background:** Azure AI Foundry (formerly Azure AI Studio) has a specific "standard setup" for private networking documented by Microsoft. This skill captures the canonical Terraform pattern based on Microsoft's reference architecture and our Phase 1 implementation of issue #138.

## Architecture Overview

Three areas of network isolation:

1. **Inbound to Foundry** — Private endpoint on Foundry account, `publicNetworkAccess = "Disabled"`
2. **Outbound from Foundry → backing PaaS** — Private endpoints to Storage, Search, Cosmos, Key Vault, ACR
3. **Outbound from Agent client → customer VNet** — VNet injection of agent runtime into delegated subnet

## Implementation Phases

The canonical pattern is implemented in 5 phases (3 Terraform, 2 validation):

### Phase 1: BYO Data Plane (Azure AI Search)

Add the missing BYO Azure AI Search resource with private endpoint.

**Files:**
- `infra/cloud/search.tf` — new file
- `infra/cloud/locals.tf` — add `search_service_name`
- `infra/cloud/private-endpoints.tf` — add `search` DNS zone + private endpoint
- `infra/cloud/identity.tf` — deployer role assignments

**Search Service Configuration:**
```hcl
resource "azapi_resource" "ai_search" {
  type                      = "Microsoft.Search/searchServices@2025-05-01"
  name                      = local.search_service_name
  parent_id                 = azurerm_resource_group.this.id
  location                  = azurerm_resource_group.this.location
  schema_validation_enabled = true

  body = {
    sku = { name = "standard" }  # Minimum for private endpoints
    identity = { type = "SystemAssigned" }
    properties = {
      replicaCount     = 1
      partitionCount   = 1
      hostingMode      = "Default"
      semanticSearch   = "disabled"
      disableLocalAuth = false
      authOptions = {
        aadOrApiKey = { aadAuthFailureMode = "http401WithBearerChallenge" }
      }
      publicNetworkAccess = "Disabled"
      networkRuleSet = { bypass = "None" }
    }
  }

  response_export_values = ["identity.principalId"]
}
```

## Critical Patterns

### 1. `time_sleep` for RBAC Propagation

**Always** add a 60-second sleep after role assignments, before creating `capabilityHost`. Entra ID role assignments are eventually consistent and can take 30-90 seconds to propagate.

### 2. Connection Flow

The correct flow is:
1. Create BYO resources (Storage, Search, Cosmos) with private endpoints
2. Grant Foundry MSI data-plane roles on those resources
3. **Wait 60 seconds** for RBAC propagation
4. Create project-scoped connections (AAD auth)
5. Create `capabilityHosts` sub-resource on project referencing those connections
6. Add `networkInjections` to Foundry account pointing at delegated subnet

### 3. `networkInjections` belongs on Foundry ACCOUNT, not project

**CRITICAL:** `networkInjections` must be added to `Microsoft.CognitiveServices/accounts`, NOT the project resource.

### 4. `capabilityHosts` is the binding mechanism

Project needs a `capabilityHosts` sub-resource that explicitly names the search/storage/cosmos connections. Connections alone are not sufficient.

## Common Pitfalls

1. **Putting `networkInjections` on the project instead of account** — Will not work. Reference clearly shows it on `Microsoft.CognitiveServices/accounts`.

2. **Skipping `time_sleep` after role assignments** — Will cause intermittent failures when creating `capabilityHost` due to RBAC propagation lag.

3. **Using API keys instead of AAD** — Defeats the purpose of private networking. All connections must use `authType = "AAD"`.

4. **Not creating `capabilityHosts` sub-resource** — Connections alone are not enough. The project needs a `capabilityHosts` resource that binds the connections together.

5. **Wrong Search SKU** — Must be `standard` or higher. `basic` does not support private endpoints.

## References

- [Microsoft docs: Configure Foundry private link](https://learn.microsoft.com/en-us/azure/foundry/how-to/configure-private-link)
- [Microsoft docs: Agent Service VNet injection](https://learn.microsoft.com/en-us/azure/ai-services/agents/how-to/virtual-networks)
- Issue #138 — full implementation plan
- PR #139 — Phase 1 reference implementation
- `infra/cloud/search.tf`, `infra/cloud/private-endpoints.tf`, `infra/cloud/identity.tf` — Phase 1 code
