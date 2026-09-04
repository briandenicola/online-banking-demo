#############################################
# KEY VAULT — Azure Key Vault for secrets
#############################################

resource "azurerm_key_vault" "main" {
  name                       = local.keyvault_name
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  # Public access stays enabled but the firewall stays locked to specific IPs so
  # that `terraform apply` can write secrets. The Private Endpoint is the path
  # workloads use at runtime.
  #
  # SECURITY: default_action MUST remain "Deny". Access is restricted to the
  # detected deployer IP plus any explicit CIDRs in var.keyvault_allowed_ip_rules.
  # If the deployer egress is NAT'd across multiple SNAT IPs, add those CIDRs to
  # var.keyvault_allowed_ip_rules — do NOT relax default_action to "Allow".
  public_network_access_enabled = true

  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
    ip_rules       = concat(["${chomp(data.http.myip.response_body)}/32"], var.keyvault_allowed_ip_rules)
  }

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_role_assignment" "deployer_keyvault_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# RBAC — CSI driver (kubelet identity) needs Key Vault read access
resource "azurerm_role_assignment" "csi_keyvault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_kubernetes_cluster.main.key_vault_secrets_provider[0].secret_identity[0].object_id
}

#############################################
# SECRETS ARE NOT MANAGED BY TERRAFORM
#
# Writing a secret is a Key Vault *data-plane* call. This vault's data plane is
# reachable only over its Private Endpoint (public surface is gated by the
# network_acls above), so `azurerm_key_vault_secret` writes race the Private
# Endpoint / firewall converging and fail with:
#
#   Error: checking for presence of existing Secret ... Status=403
#   Code="Forbidden" ... InnerError={"code":"ForbiddenByConnection"}
#
# Instead, populate the vault from the in-VNet jumpbox (see jumpbox.tf). The
# Bastion is a Developer SKU, which is browser-only — native-client SSH
# (`az network bastion ssh`) requires Standard or higher. Connect from the
# Azure Portal (Virtual machines -> <app>-jump -> Connect -> Bastion) and run:
#
#   setup-keyvault-secrets.sh <app-name>
#
# The script derives every value from the app name via the Azure control plane.
# Secrets created: jwt-private-key, mediator-client-secret-authority,
# openai-endpoint, content-understanding-endpoint,
# redis-connection-string, appinsights-connection-string.
#############################################
