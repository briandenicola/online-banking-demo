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

output "jwt_private_key" {
  description = "RSA private key that signs every JWT. Only user-service ever receives it. Export as JWT_PRIVATE_KEY_PEM before running scripts/setup-keyvault-secrets.sh to reuse it instead of generating a new one."
  value       = tls_private_key.jwt_signing.private_key_pem
  sensitive   = true
}

output "jwt_public_key" {
  description = "Public half of the JWT signing key. Published by user-service at /.well-known/jwks.json; no service needs it as configuration."
  value       = tls_private_key.jwt_signing.public_key_pem
}

output "mediator_client_secret_authority" {
  description = "Broker client credential for authority-service, the only mediator client. Export as MEDIATOR_CLIENT_SECRET_AUTHORITY before running scripts/setup-keyvault-secrets.sh."
  value       = random_password.mediator_client_secret_authority.result
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
#############################################
# BANKER COPILOT — authority-service platform wiring (epic #332, Phase 1)
#############################################

output "authority_service_client_id" {
  description = "Client ID of the dedicated authority-service workload identity (#336). Annotated onto the authority-workload-identity Kubernetes service account."
  value       = azurerm_user_assigned_identity.authority_service.client_id
}

output "authority_service_service_account" {
  description = "Kubernetes service account bound to the authority-service workload identity."
  value       = var.authority_service_service_account
}

output "bootstrap_supervisor_email" {
  description = "Seeded bootstrap supervisor identity — supplied to user-service as Authority__BootstrapSupervisorEmail."
  value       = var.bootstrap_supervisor_email
}

output "bootstrap_banker_email" {
  description = "Seeded bootstrap banker identity — supplied to user-service as Authority__BootstrapBankerEmail."
  value       = var.bootstrap_banker_email
}

#############################################
# BANKER COPILOT — harness platform wiring (epic #332, Phase 2)
#############################################

output "banker_copilot_service_client_id" {
  description = "Client ID of the dedicated banker-copilot-service workload identity (#336). Annotated onto the banker-copilot-workload-identity Kubernetes service account. Distinct from authority_service_client_id by design — the harness must not be able to assume the executor's identity."
  value       = azurerm_user_assigned_identity.banker_copilot_service.client_id
}

output "banker_copilot_service_account" {
  description = "Kubernetes service account bound to the banker-copilot-service workload identity."
  value       = var.banker_copilot_service_account
}

output "copilot_container_names" {
  description = "Cosmos container names the harness reads and writes. Emitted so the deployment task can populate the ConfigMap from Terraform rather than from a second hand-maintained list — the container name is one value with one home, and the scoped role assignments in identity-copilot.tf reference the same resources."
  value = {
    sessions  = azurerm_cosmosdb_sql_container.copilot_sessions.name
    artifacts = azurerm_cosmosdb_sql_container.copilot_artifacts.name
    traces    = azurerm_cosmosdb_sql_container.copilot_traces.name
    approvals = azurerm_cosmosdb_sql_container.copilot_approvals.name
    database  = azurerm_cosmosdb_sql_database.banking.name
  }
}
