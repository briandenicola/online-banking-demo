#############################################
# KEY VAULT — Azure Key Vault for secrets
#############################################

resource "azurerm_key_vault" "main" {
  name                = local.keyvault_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"
  tags = {
    AppName = local.resource_name
  }
}
