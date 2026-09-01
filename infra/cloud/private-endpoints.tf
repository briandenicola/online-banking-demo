#############################################
# PRIVATE ENDPOINTS — Subnet, DNS zones, VNet links, endpoints
#############################################

# --- Subnet for Private Endpoints ---

resource "azurerm_subnet" "private_endpoints" {
  name                 = "pe-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.pe_subnet_cidr]
}

# --- Private DNS Zones ---

locals {
  private_dns_zones = {
    keyvault    = "privatelink.vaultcore.azure.net"
    cosmos      = "privatelink.documents.azure.com"
    redis       = "privatelink.redis.azure.net"
    acr         = "privatelink.azurecr.io"
    cogservices = "privatelink.cognitiveservices.azure.com"
    openai      = "privatelink.openai.azure.com"
    services_ai = "privatelink.services.ai.azure.com"
    search      = "privatelink.search.windows.net"
    blob        = "privatelink.blob.core.windows.net"
    queue       = "privatelink.queue.core.windows.net"
    table       = "privatelink.table.core.windows.net"
    file        = "privatelink.file.core.windows.net"
  }
}

resource "azurerm_private_dns_zone" "zones" {
  for_each            = local.private_dns_zones
  name                = each.value
  resource_group_name = azurerm_resource_group.this.name
  tags = {
    AppName = local.resource_name
  }
}

# --- VNet Links (one per DNS zone) ---

resource "azurerm_private_dns_zone_virtual_network_link" "links" {
  for_each              = local.private_dns_zones
  name                  = "${each.key}-vnet-link"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.zones[each.key].name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags = {
    AppName = local.resource_name
  }
}

# --- Private Endpoints ---

# 1. Key Vault
resource "azurerm_private_endpoint" "keyvault" {
  name                = "${local.resource_name}-kv-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-kv-psc"
    private_connection_resource_id = azurerm_key_vault.main.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "keyvault-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["keyvault"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 2. Cosmos DB
resource "azurerm_private_endpoint" "cosmos" {
  name                = "${local.resource_name}-cosmos-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-cosmos-psc"
    private_connection_resource_id = azurerm_cosmosdb_account.main.id
    subresource_names              = ["Sql"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "cosmos-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["cosmos"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 3. Azure Managed Redis
resource "azurerm_private_endpoint" "redis" {
  name                = "${local.resource_name}-redis-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-redis-psc"
    private_connection_resource_id = azurerm_managed_redis.main.id
    subresource_names              = ["redisEnterprise"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "redis-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["redis"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 4. ACR (public access kept enabled; PE added for in-VNet pulls)
resource "azurerm_private_endpoint" "acr" {
  name                = "${local.resource_name}-acr-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-acr-psc"
    private_connection_resource_id = azurerm_container_registry.main.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "acr-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["acr"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 5. AI Services / Cognitive Services (two DNS zones: cognitiveservices + openai)
resource "azurerm_private_endpoint" "ai" {
  name                = "${local.resource_name}-ai-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  depends_on = [
    azapi_resource.ai_foundry_project,
    azapi_resource.gpt54_mini,
    azapi_resource.text_embedding,
  ]

  private_service_connection {
    name                           = "${local.resource_name}-ai-psc"
    private_connection_resource_id = azapi_resource.this.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name = "ai-dns"
    private_dns_zone_ids = [
      azurerm_private_dns_zone.zones["cogservices"].id,
      azurerm_private_dns_zone.zones["openai"].id,
      azurerm_private_dns_zone.zones["services_ai"].id,
    ]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 6. Content Understanding Service (cross-region AI Services)
resource "azurerm_private_endpoint" "content_understanding" {
  name                = "${local.resource_name}-cus-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  depends_on = [
    azapi_resource.content_understanding,
    time_sleep.wait_cus_provisioning
  ]

  private_service_connection {
    name                           = "${local.resource_name}-cus-psc"
    private_connection_resource_id = data.azurerm_cognitive_account.content_understanding.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name = "cus-dns"
    private_dns_zone_ids = [
      azurerm_private_dns_zone.zones["cogservices"].id,
      azurerm_private_dns_zone.zones["openai"].id,
      azurerm_private_dns_zone.zones["services_ai"].id,
    ]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 7. Storage Account (blob)
resource "azurerm_private_endpoint" "storage" {
  name                = "${local.resource_name}-storage-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-storage-psc"
    private_connection_resource_id = azurerm_storage_account.main.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "storage-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["blob"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 8. Storage Account (queue)
resource "azurerm_private_endpoint" "storage_queue" {
  name                = "${local.resource_name}-storage-queue-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-storage-queue-psc"
    private_connection_resource_id = azurerm_storage_account.main.id
    subresource_names              = ["queue"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "storage-queue-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["queue"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 9. Storage Account (table)
resource "azurerm_private_endpoint" "storage_table" {
  name                = "${local.resource_name}-storage-table-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-storage-table-psc"
    private_connection_resource_id = azurerm_storage_account.main.id
    subresource_names              = ["table"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "storage-table-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["table"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 10. Storage Account (file)
resource "azurerm_private_endpoint" "storage_file" {
  name                = "${local.resource_name}-storage-file-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-storage-file-psc"
    private_connection_resource_id = azurerm_storage_account.main.id
    subresource_names              = ["file"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "storage-file-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["file"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}

# 11. Azure AI Search
resource "azurerm_private_endpoint" "search" {
  name                = "${local.resource_name}-search-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  depends_on = [azapi_resource.ai_search]

  private_service_connection {
    name                           = "${local.resource_name}-search-psc"
    private_connection_resource_id = azapi_resource.ai_search.id
    subresource_names              = ["searchService"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "search-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["search"].id]
  }

  tags = {
    AppName = local.resource_name
  }
}
