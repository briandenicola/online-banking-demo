#############################################
# REDIS — Azure Managed Redis (Entra ID auth only)
#############################################

resource "azurerm_managed_redis" "main" {
  name                = local.redis_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku_name            = "Balanced_B0"
  default_database {
    access_keys_authentication_enabled = false
  }
  # Public access is disabled; traffic flows through private endpoint only
  public_network_access = "Disabled"
  tags = {
    AppName = local.resource_name
  }
}
