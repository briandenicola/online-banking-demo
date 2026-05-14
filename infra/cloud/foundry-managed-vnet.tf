#############################################
# FOUNDRY MANAGED VIRTUAL NETWORK (preview) — issue #141
#
# Microsoft provisions and manages a dedicated VNet for Foundry agent egress.
# Outbound private endpoints to backing services (Storage, Cosmos, Search) are
# created INSIDE the Microsoft-managed VNet via outbound rules — not in our
# customer VNet.
#
# Cost note: zero FQDN outbound rules — no Azure Firewall is provisioned.
# Isolation mode is "AllowInternetOutbound" (no firewall, PE rules still create
# private connectivity to backing services).
#
# Provisioning is SLOW: 10m wait per backing-service PE before its outbound
# rule, plus 600s wait after all rules before the capability host can bind.
# Total clean provisioning: 30+ minutes.
#############################################

# Managed network child resource on the Foundry account
resource "azapi_resource" "managed_network" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks@2025-10-01-preview"
  name      = "default"
  parent_id = azapi_resource.this.id

  schema_validation_enabled = false

  body = {
    properties = {
      managedNetwork = {
        isolationMode       = "AllowInternetOutbound"
        managedNetworkKind  = "V2"
        provisionNetworkNow = true
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.foundry_network_connection_approver
  ]
}

#############################################
# 10-minute waits — backing services + their PEs must be fully provisioned
# before the managed network can create its own PE to them.
#############################################

resource "time_sleep" "wait_storage_outbound" {
  create_duration = "10m"

  depends_on = [
    azurerm_storage_account.main,
    azurerm_private_endpoint.storage,
  ]
}

resource "time_sleep" "wait_cosmos_outbound" {
  create_duration = "10m"

  depends_on = [
    azurerm_cosmosdb_account.main,
    azurerm_private_endpoint.cosmos,
  ]
}

resource "time_sleep" "wait_aisearch_outbound" {
  create_duration = "10m"

  depends_on = [
    azapi_resource.ai_search,
    azurerm_private_endpoint.search,
  ]
}

#############################################
# Outbound rules — managed PE per backing service
#############################################

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
    time_sleep.wait_storage_outbound,
    azurerm_role_assignment.foundry_network_connection_approver,
    azurerm_role_assignment.foundry_storage_blob_data_contributor,
  ]
}

resource "azapi_resource" "cosmos_outbound_rule" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2025-10-01-preview"
  name      = "cosmos-sql-rule"
  parent_id = azapi_resource.managed_network.id

  schema_validation_enabled = false

  body = {
    properties = {
      type = "PrivateEndpoint"
      destination = {
        serviceResourceId = azurerm_cosmosdb_account.main.id
        subresourceTarget = "Sql"
      }
      category = "UserDefined"
    }
  }

  depends_on = [
    time_sleep.wait_cosmos_outbound,
    azurerm_role_assignment.foundry_network_connection_approver,
    azurerm_role_assignment.foundry_cosmos_arm_contributor,
    azurerm_cosmosdb_sql_role_assignment.foundry_cosmos_contributor,
  ]
}

resource "azapi_resource" "aisearch_outbound_rule" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2025-10-01-preview"
  name      = "aisearch-rule"
  parent_id = azapi_resource.managed_network.id

  schema_validation_enabled = false

  body = {
    properties = {
      type = "PrivateEndpoint"
      destination = {
        serviceResourceId = azapi_resource.ai_search.id
        subresourceTarget = "searchService"
      }
      category = "UserDefined"
    }
  }

  depends_on = [
    time_sleep.wait_aisearch_outbound,
    azurerm_role_assignment.foundry_network_connection_approver,
    azurerm_role_assignment.foundry_search_index_data_contributor,
    azurerm_role_assignment.foundry_search_service_contributor,
  ]
}

# 600s wait — outbound rules need extra time to reach `Succeeded` state before
# the capability host can validate them. Per canonical sample.
resource "time_sleep" "wait_outbound_rules" {
  create_duration = "600s"

  depends_on = [
    azapi_resource.storage_outbound_rule,
    azapi_resource.cosmos_outbound_rule,
    azapi_resource.aisearch_outbound_rule,
  ]
}
