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