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


