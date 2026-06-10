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

# NOTE: Azure auto-creates managedNetworks/default when networkInjections is
# configured on the Foundry account. We reference it directly in outbound rules
# instead of creating it as a standalone resource to avoid conflicts.

#############################################
# 10-minute wait — Cosmos backing service + its PE must be fully provisioned
# before the managed network can create its own PE to it.
# NOTE: Storage and Search waits removed — their connections auto-create outbound rules.
#############################################

resource "time_sleep" "wait_cosmos_outbound" {
  create_duration = "10m"

  depends_on = [
    azurerm_cosmosdb_account.main,
    azurerm_private_endpoint.cosmos,
  ]
}

# NOTE: AI Search and AzureStorageAccount connections auto-create managed-VNet
# outbound rules. CognitiveSearch (aisearch_connection in ai-connections.tf) and
# AzureStorageAccount (storage_connection in ai-connections.tf) both auto-create
# outbound rules to their respective backing services. Attempting to create explicit
# rules results in HTTP 400 "There is already an outbound rule to the same destination".
# CosmosDb connections do NOT auto-create outbound rules, so an explicit rule is
# required for Cosmos. See: microsoft-foundry/foundry-samples issue discussions on
# managed VNet behavior.

#############################################
# Outbound rules — managed PE per backing service
#############################################

# Storage outbound rule removed — auto-created by storage_connection (category AzureStorageAccount).
# The explicit azapi_resource.storage_outbound_rule is no longer needed and causes conflicts.
# If migrating from an existing deployment, run:
#   terraform state rm azapi_resource.storage_outbound_rule
#   terraform state rm time_sleep.wait_storage_outbound
# before re-applying.

resource "azapi_resource" "cosmos_outbound_rule" {
  type      = "Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2025-10-01-preview"
  name      = "cosmos-sql-rule"
  parent_id = "${azapi_resource.this.id}/managedNetworks/default"

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

# 600s wait — outbound rules need extra time to reach `Succeeded` state before
# the capability host can validate them. Per canonical sample. The aisearch and
# storage connections auto-create their outbound rules, so we wait for the
# connections instead of explicit rules.
resource "time_sleep" "wait_outbound_rules" {
  create_duration = "600s"

  depends_on = [
    azapi_resource.cosmos_outbound_rule,
    azapi_resource.aisearch_connection, # aisearch connection auto-creates outbound rule
    azapi_resource.storage_connection,  # storage connection auto-creates outbound rule
  ]
}
