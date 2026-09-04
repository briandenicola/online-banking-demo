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

# JWT signing key for the banking services (issue #334).
#
# ASYMMETRIC ON PURPOSE. This used to be a 32-character shared secret: every one of the
# eleven services held it, and with HS256 holding it meant being able to MINT tokens, not
# merely verify them. Any service could therefore forge a `supervisor` claim. Now only
# `user-service` receives the private half (Key Vault secret `jwt-private-key`); everyone
# else fetches the public half from its JWKS endpoint at runtime, so no consumer holds
# anything that can sign.
#
# Held in state so the value is stable across applies. Terraform does NOT write it to Key
# Vault (see keyvault.tf); surface it with `terraform output -raw jwt_private_key` and pass
# it to scripts/setup-keyvault-secrets.sh, or let that script generate its own.
resource "tls_private_key" "jwt_signing" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

# Client credential for the ONE mediator client, `authority-service`. It buys a broker token
# from `user-service` and nothing else — it is not signing material, and it is deliberately
# not granted to `banker-copilot-service`, which must remain unable to act as the broker.
resource "random_password" "mediator_client_secret_authority" {
  length  = 48
  special = false
}
