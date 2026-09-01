output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "aks_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "storage_account_name" {
  value = azurerm_storage_account.main.name
}

output "cosmos_db_endpoint" {
  value = azurerm_cosmosdb_account.main.endpoint
}

output "redis_host" {
  value = azurerm_managed_redis.main.hostname
}

output "redis_connection_string" {
  value = "${azurerm_managed_redis.main.hostname}:10000,ssl=True,abortConnect=False"
}

output "banking_services_client_id" {
  value = azurerm_user_assigned_identity.banking_services.client_id
}

output "application_insights_key" {
  value     = azurerm_application_insights.main.instrumentation_key
  sensitive = true
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "key_vault_uri" {
  value = azurerm_key_vault.main.vault_uri
}

output "openai_endpoint" {
  value     = "https://${local.openai_name}.services.ai.azure.com/api/projects/${local.project_name}"
  sensitive = false
}

output "key_vault_name" {
  value = azurerm_key_vault.main.name
}

output "acr_name" {
  value = azurerm_container_registry.main.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "app_name" {
  description = "Base name every resource is derived from. Pass this to scripts/setup-keyvault-secrets.sh."
  value       = local.resource_name
}

output "jwt_key" {
  description = "JWT signing key held in state. Export as JWT_KEY before running scripts/setup-keyvault-secrets.sh to reuse it instead of generating a new one."
  value       = random_password.jwt_key.result
  sensitive   = true
}

output "jumpbox_name" {
  value = azurerm_linux_virtual_machine.jumpbox.name
}

output "jumpbox_id" {
  value = azurerm_linux_virtual_machine.jumpbox.id
}

output "bastion_name" {
  value = azurerm_bastion_host.jumpbox.name
}

# Key Vault secrets are not managed by Terraform (see keyvault.tf). Connect to
# the in-VNet jumpbox and run the bootstrap script from there.
#
# Bastion Developer SKU does not support native-client connections
# (`az network bastion ssh` requires Standard or higher), so connect from the
# Azure Portal: Virtual machines -> ${local.jumpbox_name} -> Connect -> Bastion.
output "keyvault_bootstrap_instructions" {
  value = <<-EOT
    Bastion Developer SKU is browser-only. In the Azure Portal, open:

      Virtual machines -> ${local.jumpbox_name} -> Connect -> Bastion

    Authenticate as "${var.jumpbox_admin_username}" with the private key matching
    ${var.jumpbox_ssh_public_key_path}, then run on the jumpbox:

      setup-keyvault-secrets.sh ${local.resource_name}

    Direct portal link:
      https://portal.azure.com/#@/resource${azurerm_linux_virtual_machine.jumpbox.id}/bastionHost
  EOT
}