output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "openai_endpoint" {
  value     = "https://${local.project_name}.services.ai.azure.com/api/projects/${local.project_name}"
  sensitive = false
}

output "managed_identity_client_id" {
  value = azurerm_user_assigned_identity.openai_managed_identity.client_id
}

# Chatbot Service Principal outputs for local Docker authentication
output "chatbot_spn_tenant_id" {
  value     = data.azurerm_client_config.current.tenant_id
  sensitive = false
}

output "chatbot_spn_client_id" {
  value     = azuread_application.chatbot_local.client_id
  sensitive = false
}

output "chatbot_spn_client_secret" {
  value     = azuread_application_password.chatbot_local.value
  sensitive = true
}