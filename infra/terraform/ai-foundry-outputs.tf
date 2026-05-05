# AI Foundry Outputs
output "ai_hub_name" {
  value = azurerm_ai_foundry.banking_hub.name
}

output "ai_project_name" {
  value = azurerm_ai_foundry_project.banking_project.name
}

output "ai_hub_id" {
  value = azurerm_ai_foundry.banking_hub.id
}

output "openai_endpoint" {
  value     = azurerm_ai_services.openai.endpoint
  sensitive = true
}

output "openai_key" {
  value     = azurerm_ai_services.openai.primary_access_key
  sensitive = true
}

output "app_insights_connection_string" {
  value     = azurerm_application_insights.banking_ai.connection_string
  sensitive = true
}