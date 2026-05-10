#############################################
# Storage
#############################################

resource "azurerm_storage_account" "main" {
  name                          = local.storage_name
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  account_tier                  = "Standard"
  account_replication_type      = "LRS"
  shared_access_key_enabled     = false
  public_network_access_enabled = false
}