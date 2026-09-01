#############################################
# JUMPBOX — Linux VM inside the VNet, reached via Azure Bastion (Developer SKU)
#
# Terraform cannot write Key Vault secrets: the vault data plane is only
# reachable over its Private Endpoint, so data-plane writes from the deployer's
# workstation race the endpoint/firewall and fail with ForbiddenByConnection.
#
# This jumpbox lives in the same VNet and therefore resolves every
# privatelink.* zone. Connect through Bastion and run
# `setup-keyvault-secrets.sh <app-name>` to populate the vault.
#############################################

resource "azurerm_subnet" "jumpbox" {
  name                 = "jumpbox-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.jumpbox_subnet_cidr]
}

# Explicit egress. Default outbound access is retired for new subnets, so the
# jumpbox needs a NAT gateway to reach ARM / the Azure CLI package feeds.
resource "azurerm_public_ip" "jumpbox_nat" {
  name                = "${local.jumpbox_name}-nat-pip"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_nat_gateway" "jumpbox" {
  name                = "${local.jumpbox_name}-nat"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku_name            = "Standard"

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_nat_gateway_public_ip_association" "jumpbox" {
  nat_gateway_id       = azurerm_nat_gateway.jumpbox.id
  public_ip_address_id = azurerm_public_ip.jumpbox_nat.id
}

resource "azurerm_subnet_nat_gateway_association" "jumpbox" {
  subnet_id      = azurerm_subnet.jumpbox.id
  nat_gateway_id = azurerm_nat_gateway.jumpbox.id
}

resource "azurerm_network_interface" "jumpbox" {
  name                = "${local.jumpbox_name}-nic"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.jumpbox.id
    private_ip_address_allocation = "Dynamic"
  }

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_user_assigned_identity" "jumpbox" {
  name                = "${local.jumpbox_name}-mi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = {
    AppName = local.resource_name
  }
}

# Write access to the vault data plane — this is the identity that actually
# creates the secrets.
resource "azurerm_role_assignment" "jumpbox_keyvault_secrets_officer" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = azurerm_user_assigned_identity.jumpbox.principal_id
}

# Read access to the resource group so the bootstrap script can derive secret
# values (Redis hostname, App Insights connection string, CUS endpoint) from
# the app name via the Azure control plane.
resource "azurerm_role_assignment" "jumpbox_rg_reader" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.jumpbox.principal_id
}

# Same Reader grant for the VM's system-assigned identity, so `az login
# --identity` with no client ID can also read the resource group.
resource "azurerm_role_assignment" "jumpbox_system_identity_rg_reader" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Reader"
  principal_id         = azurerm_linux_virtual_machine.jumpbox.identity[0].principal_id
}

# The system-assigned identity is the ergonomic one to use on the box — plain
# `az login --identity` picks it with no client ID — so it gets the same
# data-plane write access to the vault as the user-assigned identity.
resource "azurerm_role_assignment" "jumpbox_system_identity_keyvault_secrets_officer" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = azurerm_linux_virtual_machine.jumpbox.identity[0].principal_id
}

resource "azurerm_linux_virtual_machine" "jumpbox" {
  name                  = local.jumpbox_name
  location              = azurerm_resource_group.this.location
  resource_group_name   = azurerm_resource_group.this.name
  size                  = var.jumpbox_vm_size
  admin_username        = var.jumpbox_admin_username
  provision_vm_agent    = true
  patch_assessment_mode = "AutomaticByPlatform"
  patch_mode            = "AutomaticByPlatform"
  reboot_setting        = "IfRequired"
  network_interface_ids = [azurerm_network_interface.jumpbox.id]

  admin_ssh_key {
    username   = var.jumpbox_admin_username
    public_key = file(pathexpand(var.jumpbox_ssh_public_key_path))
  }

  os_disk {
    name                 = "${local.jumpbox_name}-osdisk"
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
  }

  identity {
    # System-assigned is enabled alongside the user-assigned identity so tooling
    # that calls `az login --identity` with no client ID still works. The
    # user-assigned identity remains the one that holds Key Vault Secrets
    # Officer (see azurerm_role_assignment.jumpbox_keyvault_secrets_officer).
    type         = "SystemAssigned, UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.jumpbox.id]
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }

  # Installs the Azure CLI and drops the bootstrap script at
  # /usr/local/bin/setup-keyvault-secrets.sh.
  custom_data = base64encode(templatefile("${path.module}/cloud-init/jumpbox.yaml.tftpl", {
    setup_script = file("${path.module}/../../scripts/setup-keyvault-secrets.sh")
    app_name     = local.resource_name
  }))

  tags = {
    AppName = local.resource_name
  }
}

# Developer SKU: free, no AzureBastionSubnet and no public IP required. It is
# browser-only — native-client connections (`az network bastion ssh`) need
# Standard or higher. Connect from the Azure Portal:
#   Virtual machines -> <app>-jump -> Connect -> Bastion
resource "azurerm_bastion_host" "jumpbox" {
  name                = local.bastion_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Developer"
  virtual_network_id  = azurerm_virtual_network.main.id

  depends_on = [azurerm_linux_virtual_machine.jumpbox]

  tags = {
    AppName = local.resource_name
  }
}
