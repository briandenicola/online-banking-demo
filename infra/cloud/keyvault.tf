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
  # Public access stays enabled but locked down to the deployer's IP so that
  # `terraform apply` can write secrets. The Private Endpoint is the path
  # workloads use at runtime; the public surface is gated by network_acls.
  public_network_access_enabled = true

  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
    ip_rules       = ["${chomp(data.http.myip.response_body)}/32"]
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
