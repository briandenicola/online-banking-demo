#############################################
# NETWORKING — Virtual network and subnets
#############################################

resource "azurerm_virtual_network" "main" {
  name                = local.vnet_name
  address_space       = [local.vnet_cidr]
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_subnet" "aks" {
  name                 = "aks-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.nodes_subnet_cidr]
}

resource "azurerm_network_security_group" "aks" {
  name                = "${local.resource_name}-aks-nsg"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  security_rule {
    name                       = "AllowHTTP"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowHTTPS"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_subnet_network_security_group_association" "aks" {
  subnet_id                 = azurerm_subnet.aks.id
  network_security_group_id = azurerm_network_security_group.aks.id
}

resource "azurerm_network_security_group" "agents" {
  name                = "${local.resource_name}-agents-nsg"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_subnet" "agents" {
  name                 = "agents"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.agent_subnet_cidr]

  delegation {
    name = "agent-delegation"
    service_delegation {
      name = "Microsoft.App/environments"
    }
  }
}

resource "azurerm_subnet_network_security_group_association" "agents" {
  subnet_id                 = azurerm_subnet.agents.id
  network_security_group_id = azurerm_network_security_group.agents.id
}
