#############################################
# AI CONNECTIONS — AI Foundry project connections to backing services
#############################################

resource "azapi_resource" "application_insights_connection" {
  depends_on = [
    azapi_resource.ai_foundry_project,
    azurerm_application_insights.main
  ]
  type                      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01"
  name                      = azurerm_application_insights.main.name
  parent_id                 = azapi_resource.ai_foundry_project.id
  schema_validation_enabled = false

  body = {
    name = azurerm_application_insights.main.name
    properties = {
      category      = "AppInsights"
      authType      = "ApiKey"
      isSharedToAll = false
      metadata = {
        ApiType    = "Azure"
        ResourceId = azurerm_application_insights.main.id
        location   = azurerm_resource_group.this.location
      }
      target = azurerm_application_insights.main.id
      credentials = {
        key = azurerm_application_insights.main.connection_string
      }
    }
  }
}

# BYO AI Search connection (AAD auth) — schema matches Microsoft sample
# https://github.com/microsoft-foundry/foundry-samples/tree/main/infrastructure/infrastructure-setup-terraform/18-managed-virtual-network
resource "azapi_resource" "aisearch_connection" {
  depends_on = [
    azapi_resource.ai_foundry_project,
    azapi_resource.ai_search
  ]
  type                      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview"
  name                      = azapi_resource.ai_search.name
  parent_id                 = azapi_resource.ai_foundry_project.id
  schema_validation_enabled = false

  body = {
    properties = {
      category = "CognitiveSearch"
      target   = "https://${azapi_resource.ai_search.name}.search.windows.net"
      authType = "AAD"
      metadata = {
        ApiType    = "Azure"
        ResourceId = azapi_resource.ai_search.id
        location   = azurerm_resource_group.this.location
      }
    }
  }
}

# BYO Cosmos DB connection (AAD auth) — schema matches Microsoft sample
resource "azapi_resource" "cosmosdb_connection" {
  depends_on = [
    azapi_resource.ai_foundry_project,
    azurerm_cosmosdb_account.main,
    azapi_resource.aisearch_connection
  ]
  type                      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview"
  name                      = azurerm_cosmosdb_account.main.name
  parent_id                 = azapi_resource.ai_foundry_project.id
  schema_validation_enabled = false

  body = {
    properties = {
      category = "CosmosDb"
      target   = azurerm_cosmosdb_account.main.endpoint
      authType = "AAD"
      metadata = {
        ApiType    = "Azure"
        ResourceId = azurerm_cosmosdb_account.main.id
        location   = azurerm_cosmosdb_account.main.location
      }
    }
  }
}

# BYO Storage connection (AAD auth) — schema matches Microsoft sample
resource "azapi_resource" "storage_connection" {
  depends_on = [
    azapi_resource.ai_foundry_project,
    azurerm_storage_account.main,
    azapi_resource.cosmosdb_connection
  ]
  type                      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview"
  name                      = azurerm_storage_account.main.name
  parent_id                 = azapi_resource.ai_foundry_project.id
  schema_validation_enabled = false

  body = {
    properties = {
      category = "AzureStorageAccount"
      target   = azurerm_storage_account.main.primary_blob_endpoint
      authType = "AAD"
      metadata = {
        ApiType    = "Azure"
        ResourceId = azurerm_storage_account.main.id
        location   = azurerm_storage_account.main.location
      }
    }
  }
}

#############################################
# RBAC PROPAGATION WAIT — Entra ID role assignments are eventually consistent
#############################################

resource "time_sleep" "wait_foundry_rbac" {
  depends_on = [
    azurerm_role_assignment.foundry_storage_blob_data_contributor,
    azurerm_cosmosdb_sql_role_assignment.foundry_cosmos_contributor,
    azurerm_role_assignment.foundry_search_index_data_contributor,
    azurerm_role_assignment.foundry_search_service_contributor
  ]
  create_duration = "60s"
}

#############################################
# CAPABILITY HOST — Binds BYO connections to Foundry project for agent runtime
#############################################

resource "azapi_resource" "ai_foundry_project_capability_host" {
  depends_on = [
    azapi_resource.aisearch_connection,
    azapi_resource.cosmosdb_connection,
    azapi_resource.storage_connection,
    time_sleep.wait_foundry_rbac,
    # Managed VNet outbound rules must be Succeeded before the capability host
    # binds the project to the agent runtime. See foundry-managed-vnet.tf.
    azapi_resource.storage_outbound_rule,
    azapi_resource.cosmos_outbound_rule,
    azapi_resource.aisearch_outbound_rule,
    time_sleep.wait_outbound_rules
  ]
  type                      = "Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-10-01-preview"
  name                      = "agents-capability-host"
  parent_id                 = azapi_resource.ai_foundry_project.id
  schema_validation_enabled = false

  body = {
    properties = {
      capabilityHostKind = "Agents"
      vectorStoreConnections = [
        azapi_resource.ai_search.name
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


