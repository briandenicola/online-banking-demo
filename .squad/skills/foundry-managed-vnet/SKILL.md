# Skill: Azure AI Foundry Managed Virtual Network — Canonical Pattern

**When to use:** Deploying Azure AI Foundry with Microsoft-managed egress network isolation (no BYO subnet for agents).

**Background:** The Managed Virtual Network feature lets Microsoft provision and manage a dedicated VNet for Foundry agent outbound traffic. Private endpoints to backing services (Storage, Cosmos, Search) are created *inside* the managed VNet — no customer subnet/delegation needed.

## Architecture Overview

1. **Inbound to Foundry** — BYO private endpoint in customer VNet (unchanged — AKS pods access Foundry via PE)
2. **Agent Outbound** — Microsoft-managed VNet with managed private endpoints to backing services
3. **Outbound Control** — Isolation modes: `AllowInternetOutbound` (default) or `AllowOnlyApprovedOutbound` (adds Azure Firewall)

## Key Resources (AzAPI)

### 1. Foundry Account with Managed Network Injection

```hcl
resource "azapi_resource" "cognitive_account" {
  type = "Microsoft.CognitiveServices/accounts@2025-10-01-preview"
  # ...
  body = {
    kind = "AIServices"
    properties = {
      allowProjectManagement = true
      customSubDomainName    = local.foundry_name
      disableLocalAuth       = true
      publicNetworkAccess    = "Disabled"
      networkAcls = {
        defaultAction       = "Deny"
        virtualNetworkRules = []
        ipRules             = []
      }
      networkInjections = [
        {
          scenario                   = "agent"
          subnetArmId                = ""           # Empty — no BYO subnet
          useMicrosoftManagedNetwork = true         # Key flag
        }
      ]
      # Optional declarative references
      userOwnedStorage  = [{ resourceId = azurerm_storage_account.main.id }]
      userOwnedCosmosDB = [{ resourceId = azurerm_cosmosdb_account.main.id }]
      userOwnedSearch   = [{ resourceId = azapi_resource.ai_search.id }]
    }
  }
}
```

### 2. Managed Network Child Resource

```hcl
resource "azapi_resource" "managed_network" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks@2025-10-01-preview"
  name      = "default"
  parent_id = azapi_resource.cognitive_account.id

  schema_validation_enabled = false

  body = {
    properties = {
      managedNetwork = {
        isolationMode       = "AllowInternetOutbound"  # or "AllowOnlyApprovedOutbound"
        managedNetworkKind  = "V2"
        provisionNetworkNow = true
      }
    }
  }
}
```

### 3. Outbound Rules (Managed PEs)

```hcl
resource "azapi_resource" "storage_outbound_rule" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2025-10-01-preview"
  name      = "storage-blob-rule"
  parent_id = azapi_resource.managed_network.id

  schema_validation_enabled = false

  body = {
    properties = {
      type = "PrivateEndpoint"
      destination = {
        serviceResourceId = azurerm_storage_account.main.id
        subresourceTarget = "blob"
      }
      category = "UserDefined"
    }
  }

  depends_on = [
    time_sleep.wait_storage,                          # 10m after target resource + PE
    azurerm_role_assignment.foundry_network_connection_approver
  ]
}
```

### 4. Network Connection Approver Role

```hcl
resource "azurerm_role_assignment" "foundry_network_connection_approver" {
  scope                = azurerm_resource_group.main.id
  role_definition_name = "Azure AI Enterprise Network Connection Approver"
  principal_id         = azapi_resource.cognitive_account.identity[0].principal_id
}
```

Role ID: `b556d68e-0be0-4f35-a333-ad7ee1ce17ea`

### 5. capabilityHost (same as BYO pattern, but depends on outbound rules)

```hcl
resource "azapi_resource" "project_capability_host" {
  type      = "Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-04-01-preview"
  name      = "caphostproj"
  parent_id = azapi_resource.ai_foundry_project.id

  schema_validation_enabled = false

  body = {
    properties = {
      capabilityHostKind       = "Agents"
      vectorStoreConnections   = [azapi_resource.ai_search.name]
      storageConnections       = [azurerm_storage_account.main.name]
      threadStorageConnections = [azurerm_cosmosdb_account.main.name]
    }
  }

  depends_on = [
    azapi_resource.storage_outbound_rule,
    azapi_resource.cosmos_outbound_rule,
    azapi_resource.aisearch_outbound_rule,
    time_sleep.wait_outbound_rules,          # 600s after all rules
    time_sleep.wait_project_rbac             # 90s after project RBAC
  ]
}
```

## Critical Patterns

### 1. `networkInjections` Must Be Set at Creation Time

Per docs: `customSubDomainName`, `allowProjectManagement`, and `networkInjections` cannot be added after account creation. Changing `useMicrosoftManagedNetwork` from `false` → `true` likely requires account recreate.

### 1a. **Project Connections Require `useWorkspaceManagedIdentity: true`** (CRITICAL)

When the Foundry account uses Microsoft-managed VNet (`useMicrosoftManagedNetwork: true`), **all project connections** (type `Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01`) with `authType: "AAD"` **MUST** include `useWorkspaceManagedIdentity: true` in the properties block.

Without this flag, the API returns HTTP 400 "unable to deserialize request body". This is a schema enforcement specific to the managed VNet scenario.

**Required connection schema for managed VNet:**
```hcl
resource "azapi_resource" "storage_connection" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01"
  name      = azurerm_storage_account.main.name
  parent_id = azapi_resource.ai_foundry_project.id

  body = {
    name = azurerm_storage_account.main.name
    properties = {
      category                     = "AzureStorage"  # or "AzureCosmosDB", "CognitiveSearch"
      authType                     = "AAD"
      isSharedToAll                = false
      useWorkspaceManagedIdentity  = true            # REQUIRED for managed VNet + AAD auth
      metadata = {
        ApiType    = "Azure"
        ResourceId = azurerm_storage_account.main.id
      }
      target = azurerm_storage_account.main.id
    }
  }
}
```

**Why:** The managed VNet delegates all egress to Microsoft's network. The workspace's system-assigned MSI is granted PE auto-approve rights and data-plane RBAC. Connections must explicitly opt into using that MSI rather than default AAD flows.

**Applies to:** Storage (AzureStorage), Cosmos DB (AzureCosmosDB), AI Search (CognitiveSearch) connections. Not needed for AppInsights (uses ApiKey auth).

### 2. Outbound Rule Provisioning is SLOW

- 10-minute wait after target resource creation before creating outbound rule
- 600-second (10-minute) wait after all outbound rules before creating capabilityHost
- Total managed VNet provisioning: 30+ minutes from clean state

### 3. Isolation Mode is One-Way

- `AllowInternetOutbound` → cannot downgrade to `Disabled`
- `AllowOnlyApprovedOutbound` → cannot upgrade to `AllowInternetOutbound`
- Choose carefully at creation time

### 4. Azure Firewall Cost Trigger

FQDN outbound rules in `AllowOnlyApprovedOutbound` mode trigger Azure Firewall provisioning:
- Standard SKU: ~$1.25/hr (~$912/month)
- Basic SKU: ~$0.395/hr (~$288/month)
- One firewall per Foundry account — cannot be shared

### 5. Supported Regions (as of 2026-05)

East US, East US2, Japan East, France Central, UAE North, Brazil South, Spain Central, Germany West Central, Italy North, South Central US, Australia East, Sweden Central, Canada East, South Africa North, West US, West US 3, South India, UK South.

### 6. Required Outbound Rules per Scenario

**Agents (always needed):**
- PE to Storage (blob)
- PE to Cosmos DB (Sql)
- PE to AI Search (searchService)

**Evaluations & Traces (if using App Insights):**
- FQDN: `settings.sdk.monitor.azure.com`, `*.livediagnostics.monitor.azure.com`, `*.in.applicationinsights.azure.com`

**Automatically created (in AllowOnlyApprovedOutbound):**
- ServiceTag: AzureActiveDirectory
- ServiceTag: AzureMachineLearning

## Differences from BYO VNet Pattern

| Aspect | BYO VNet | Managed VNet |
|--------|----------|--------------|
| Agent subnet | Customer-owned, delegated to `Microsoft.App/environments` | Microsoft-managed (invisible) |
| `networkInjections.useMicrosoftManagedNetwork` | `false` | `true` |
| `networkInjections.subnetArmId` | Customer subnet ID | `""` (empty) |
| Outbound PEs to backing services | Customer creates in PE subnet | Microsoft creates inside managed VNet via outbound rules |
| NSG management | Customer-owned NSG on agents subnet | Not applicable |
| Minimum subnet size | /27 | Not applicable |
| Firewall | Optional, customer-owned | Managed (provisioned if FQDN rules used in approved-only mode) |
| `managedNetworks` child resource | Not used | Required |
| `outboundRules` child resources | Not used | Required (one per PE destination) |

## References

- [Microsoft Docs: Managed Virtual Network](https://learn.microsoft.com/en-us/azure/foundry/how-to/managed-virtual-network?tabs=azure-cli)
- [Microsoft Foundry Samples: 18-managed-virtual-network (TF)](https://github.com/microsoft-foundry/foundry-samples/tree/main/infrastructure/infrastructure-setup-terraform/18-managed-virtual-network)
- Issue #141 — Migration plan
- Issue #138 — Original BYO VNet implementation
