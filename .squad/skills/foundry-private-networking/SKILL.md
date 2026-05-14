# Skill: Azure AI Foundry Private Networking — Canonical Pattern

**When to use:** Any Azure AI Foundry deployment that requires private networking (VNet isolation, private endpoints, no public internet access).

**Background:** Azure AI Foundry (formerly Azure AI Studio) has a specific "standard setup" for private networking documented by Microsoft. This skill captures the canonical Terraform pattern based on Microsoft's reference architecture and our Phase 1 implementation of issue #138.

## Architecture Overview

Three areas of network isolation:

1. **Inbound to Foundry** — Private endpoint on Foundry account, `publicNetworkAccess = "Disabled"`
2. **Outbound from Foundry → backing PaaS** — Private endpoints to Storage, Search, Cosmos, Key Vault, ACR
3. **Outbound from Agent client → customer VNet** — VNet injection of agent runtime into delegated subnet

## Implementation Phases

The canonical pattern is implemented in 3 phases (all Terraform):

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

### Phase 2: BYO Connections + Foundry MSI RBAC + capabilityHost

Add project-scoped connections to Storage, Cosmos, Search with AAD auth. Grant Foundry account MSI data-plane access. Create capabilityHost binding.

**Files:**
- `infra/cloud/ai.tf` — bump API version to `2025-10-01-preview` (all Foundry resources)
- `infra/cloud/ai-connections.tf` — add three BYO connections + time_sleep + capabilityHost
- `infra/cloud/identity.tf` — Foundry MSI role assignments

**API Version:**
All Foundry resources (account, project, deployments) must use `2025-10-01-preview` or later for `networkInjections` support (Phase 3).

**BYO Connections (AAD auth, no keys):**
```hcl
resource "azapi_resource" "storage_connection" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01"
  name      = azurerm_storage_account.main.name
  parent_id = azapi_resource.ai_foundry_project.id

  body = {
    properties = {
      category      = "AzureStorage"
      authType      = "AAD"
      isSharedToAll = false
      metadata = {
        ApiType    = "Azure"
        ResourceId = azurerm_storage_account.main.id
      }
      target = azurerm_storage_account.main.id
    }
  }
}

resource "azapi_resource" "cosmosdb_connection" {
  # Similar structure, category = "AzureCosmosDB"
}

resource "azapi_resource" "aisearch_connection" {
  # Similar structure, category = "CognitiveSearch"
}
```

**Foundry MSI Data-Plane Roles:**
```hcl
# Storage Blob Data Contributor (Foundry → Storage)
resource "azurerm_role_assignment" "foundry_storage_blob_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azapi_resource.this.output.identity.principalId
}

# Cosmos DB Built-in Data Contributor (SQL role, not ARM RBAC)
resource "azurerm_cosmosdb_sql_role_assignment" "foundry_cosmos_contributor" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azapi_resource.this.output.identity.principalId
  scope               = azurerm_cosmosdb_account.main.id
}

# Search Index Data Contributor + Search Service Contributor
resource "azurerm_role_assignment" "foundry_search_index_data_contributor" {
  scope                = azapi_resource.ai_search.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = azapi_resource.this.output.identity.principalId
}

resource "azurerm_role_assignment" "foundry_search_service_contributor" {
  scope                = azapi_resource.ai_search.id
  role_definition_name = "Search Service Contributor"
  principal_id         = azapi_resource.this.output.identity.principalId
}
```

**RBAC Propagation Wait:**
```hcl
resource "time_sleep" "wait_foundry_rbac" {
  depends_on = [
    azurerm_role_assignment.foundry_storage_blob_data_contributor,
    azurerm_cosmosdb_sql_role_assignment.foundry_cosmos_contributor,
    azurerm_role_assignment.foundry_search_index_data_contributor,
    azurerm_role_assignment.foundry_search_service_contributor
  ]
  create_duration = "60s"
}
```

**capabilityHost (Binding Mechanism):**
```hcl
resource "azapi_resource" "ai_foundry_project_capability_host" {
  depends_on = [
    azapi_resource.aisearch_connection,
    azapi_resource.cosmosdb_connection,
    azapi_resource.storage_connection,
    time_sleep.wait_foundry_rbac
  ]
  type                      = "Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-10-01-preview"
  name                      = "agents-capability-host"
  parent_id                 = azapi_resource.ai_foundry_project.id
  schema_validation_enabled = false

  body = {
    properties = {
      capabilityHostKind = "Agents"
      vectorStoreConnections = [
        azapi_resource.ai_search.name  # Use .name, not .id
      ]
      storageConnections = [
        azurerm_storage_account.main.name
      ]
      threadStorageConnections = [
        azurerm_cosmosdb_account.main.name
      ]
    }
  }
}
```

### Phase 3: networkInjections on Foundry Account + Agents Subnet NSG Split

Add VNet injection configuration to Foundry account. Create dedicated NSG for agents subnet.

**Files:**
- `infra/cloud/ai.tf` — add `networkInjections` to Foundry account
- `infra/cloud/networking.tf` — create agents NSG, update association

**networkInjections (on ACCOUNT, not project):**
```hcl
resource "azapi_resource" "this" {
  type = "Microsoft.CognitiveServices/accounts@2025-10-01-preview"
  # ... existing config ...

  body = {
    kind = "AIServices"
    # ... existing properties ...
    properties = {
      # ... existing properties ...
      networkInjections = [
        {
          scenario                   = "agent"
          useMicrosoftManagedNetwork = false
          subnetArmId                = azurerm_subnet.agents.id
        }
      ]
    }
  }
}
```

**Agents Subnet NSG:**
```hcl
resource "azurerm_network_security_group" "agents" {
  name                = "${local.resource_name}-agents-nsg"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  # Default rules (no explicit rules yet — Foundry agent traffic flows by default)
}

resource "azurerm_subnet_network_security_group_association" "agents" {
  subnet_id                 = azurerm_subnet.agents.id
  network_security_group_id = azurerm_network_security_group.agents.id
}
```

## Critical Patterns

### 1. API Version Requirement

**CRITICAL:** Use `2025-10-01-preview` or later for all Foundry resources (account, project, deployments). Earlier versions (`2025-04-01-preview`) don't support `networkInjections` schema.

### 2. `time_sleep` for RBAC Propagation

**Always** add a 60-second sleep after role assignments, before creating `capabilityHost`. Entra ID role assignments are eventually consistent and can take 30-90 seconds to propagate.

### 3. Connection Flow

The correct flow is:
1. Create BYO resources (Storage, Search, Cosmos) with private endpoints
2. Grant Foundry **account** MSI data-plane roles on those resources (not project MSI)
3. **Wait 60 seconds** for RBAC propagation
4. Create project-scoped connections (AAD auth, no keys)
5. Create `capabilityHosts` sub-resource on project referencing those connections
6. Add `networkInjections` to Foundry **account** pointing at delegated subnet

### 4. `networkInjections` belongs on Foundry ACCOUNT, not project

**CRITICAL:** `networkInjections` must be added to `Microsoft.CognitiveServices/accounts` (the Foundry account resource), NOT the project resource. Schema validation will fail if placed on project.

### 5. `capabilityHosts` is the binding mechanism

Project needs a `capabilityHosts` sub-resource that explicitly names the search/storage/cosmos connections. Connections alone are not sufficient.

### 6. capabilityHost Uses Resource Names, Not IDs

**CRITICAL:** The `vectorStoreConnections`, `storageConnections`, and `threadStorageConnections` arrays must contain the **simple name strings** (e.g., `azapi_resource.ai_search.name`), NOT the full Azure resource IDs. The API expects connection names, not ARMIDs.

### 7. Foundry MSI vs. Project MSI

**CRITICAL:** Data-plane role assignments must use the **Foundry account MSI** (`azapi_resource.this.output.identity.principalId`), NOT the project MSI. Agent runtime executes under the account-level system-assigned identity.

### 8. Cosmos DB SQL Role Assignment Syntax

Use `azurerm_cosmosdb_sql_role_assignment` (not `azurerm_role_assignment`) for Cosmos DB data-plane access:
```hcl
resource "azurerm_cosmosdb_sql_role_assignment" "foundry_cosmos_contributor" {
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azapi_resource.this.output.identity.principalId
  scope               = azurerm_cosmosdb_account.main.id
}
```
The role GUID `00000000-0000-0000-0000-000000000002` is Cosmos DB Built-in Data Contributor (read/write).


## Common Pitfalls

1. **Putting `networkInjections` on the project instead of account** — Will not work. Schema validation fails. Reference clearly shows it on `Microsoft.CognitiveServices/accounts`.

2. **Skipping `time_sleep` after role assignments** — Will cause intermittent failures when creating `capabilityHost` due to RBAC propagation lag.

3. **Using API keys instead of AAD** — Defeats the purpose of private networking. All BYO connections must use `authType = "AAD"`.

4. **Not creating `capabilityHosts` sub-resource** — Connections alone are not enough. The project needs a `capabilityHosts` resource that binds the connections together.

5. **Wrong Search SKU** — Must be `standard` or higher. `basic` does not support private endpoints.

6. **Using wrong API version** — `2025-04-01-preview` doesn't support `networkInjections`. Must use `2025-10-01-preview` or later.

7. **Using connection IDs instead of names in capabilityHost** — `vectorStoreConnections` expects `["search-name"]`, not `["/subscriptions/.../search-id"]`. Use `.name`, not `.id`.

8. **Granting roles to project MSI instead of account MSI** — Agent runtime uses account-level system-assigned identity. Use `azapi_resource.this.output.identity.principalId`, not `azapi_resource.ai_foundry_project.output.identity.principalId`.

9. **Using `azurerm_role_assignment` for Cosmos DB data-plane** — Must use `azurerm_cosmosdb_sql_role_assignment` with SQL role GUID. ARM RBAC doesn't cover Cosmos DB data-plane.


## References

- [Microsoft docs: Configure Foundry private link](https://learn.microsoft.com/en-us/azure/foundry/how-to/configure-private-link)
- [Microsoft docs: Agent Service VNet injection](https://learn.microsoft.com/en-us/azure/ai-services/agents/how-to/virtual-networks)
- Issue #138 — full implementation plan (3 phases)
- PR #139 — Phase 1 reference implementation (Search + PE + deployer roles)
- `infra/cloud/search.tf`, `infra/cloud/private-endpoints.tf`, `infra/cloud/identity.tf` — Phase 1 code
- `infra/cloud/ai.tf`, `infra/cloud/ai-connections.tf`, `infra/cloud/networking.tf` — Phase 2+3 code
- Brian's reference repo: https://github.com/briandenicola/ai-application-architectures (agent-service/ pattern)

## Implementation History

- **2026-05-13 (Phase 1):** Azure AI Search + private endpoint + deployer roles (PR #139 merged to main)
- **2026-05-13 (Phase 2+3):** BYO connections + Foundry MSI RBAC + capabilityHost + networkInjections + agents NSG split (commits d5fa18b, 1a888c6 on branch `138-foundry-troubleshooting`)

