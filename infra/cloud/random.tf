#############################################
# LOCALS — Random resources
#############################################

resource "random_pet" "this" {}

resource "random_id" "this" {
  byte_length = 2
}

resource "random_uuid" "guid" {}

resource "random_integer" "vnet_cidr" {
  min = 10
  max = 250
}

resource "random_integer" "services_cidr" {
  min = 64
  max = 99
}

resource "random_integer" "pod_cidr" {
  min = 100
  max = 127
}

# JWT signing key for the banking services. Held in state so the value is stable
# across applies. Terraform does NOT write it to Key Vault (see keyvault.tf);
# surface it with `terraform output -raw jwt_key` and pass it to
# scripts/setup-keyvault-secrets.sh, or let that script generate its own.
resource "random_password" "jwt_key" {
  length  = 32
  special = false
}