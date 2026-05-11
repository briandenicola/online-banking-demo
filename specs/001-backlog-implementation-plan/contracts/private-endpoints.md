# Terraform Interface Contract: Private Endpoints

**Date**: 2026-05-09
**Scope**: New files `private-dns.tf` and `private-endpoints.tf` in `infra/cloud/`

## Input Dependencies (consumed from existing resources)

| Input | Source | Type |
|-------|--------|------|
| `azurerm_resource_group.this.name` | `locals.tf` | Resource group for all resources |
| `azurerm_resource_group.this.location` | `locals.tf` | Azure region |
| `local.resource_name` | `locals.tf` | Name prefix for all PE resources |
| `local.pe_subnet_cidr` | `locals.tf` | `/24` CIDR at VNet offset 4 |
| `azurerm_virtual_network.main` | `networking.tf` | VNet for subnet + DNS links |
| `azurerm_key_vault.main.id` | `keyvault.tf` | PE target |
| `azurerm_cosmosdb_account.main.id` | `cosmos.tf` | PE target |
| `azurerm_managed_redis.main.id` | `redis.tf` | PE target |
| `azurerm_container_registry.main.id` | `acr.tf` | PE target |
| `azapi_resource.this.id` | `ai.tf` | PE target (AI Services) |
| `azurerm_storage_account.main.id` | `storage.tf` | PE target |

## Output Contracts (produced by new files)

### `networking.tf` — New Subnet

```hcl
# New resource added to networking.tf
resource "azurerm_subnet" "private_endpoints" {
  name                 = "private-endpoints"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.pe_subnet_cidr]
}
```

### `private-dns.tf` — DNS Zones + VNet Links

6 DNS zones, each following this pattern:

```hcl
resource "azurerm_private_dns_zone" "<service>" {
  name                = "<canonical-zone-name>"
  resource_group_name = azurerm_resource_group.this.name
  tags = { AppName = local.resource_name }
}

resource "azurerm_private_dns_zone_virtual_network_link" "<service>" {
  name                  = "<service>-vnet-link"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.<service>.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags = { AppName = local.resource_name }
}
```

### `private-endpoints.tf` — Private Endpoints

6 endpoints, each following this pattern:

```hcl
resource "azurerm_private_endpoint" "<service>" {
  name                = "${local.resource_name}-<abbrev>-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-<abbrev>-psc"
    private_connection_resource_id = <target_resource>.id
    subresource_names              = ["<sub-resource>"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.<service>.id]
  }

  tags = { AppName = local.resource_name }
}
```

## Naming Convention

| Service | PE Name Suffix | PSC Name Suffix |
|---------|---------------|-----------------|
| Key Vault | `-kv-pe` | `-kv-psc` |
| Cosmos DB | `-cosmos-pe` | `-cosmos-psc` |
| Redis | `-redis-pe` | `-redis-psc` |
| ACR | `-acr-pe` | `-acr-psc` |
| AI Services | `-ai-pe` | `-ai-psc` |
| Storage | `-sa-pe` | `-sa-psc` |

## Constraints

1. All PEs must use `is_manual_connection = false` (auto-approved)
2. All DNS zone groups must be named `"default"`
3. VNet links must have `registration_enabled = false` (not auto-registering VMs)
4. No new Terraform outputs required (services are accessed by DNS name, unchanged)
5. No changes to existing resource public access settings (already correctly configured)
