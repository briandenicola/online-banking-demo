#############################################
# COSMOS DB — NoSQL database for banking data
#############################################

resource "azurerm_cosmosdb_account" "main" {
  name                          = local.cosmos_name
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  offer_type                    = "Standard"
  kind                          = "GlobalDocumentDB"
  public_network_access_enabled = false

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.this.location
    failover_priority = 0
  }

  capabilities {
    name = "EnableServerless"
  }

  # Required by the Agent Memory Toolkit: it creates the AgentMemory* containers
  # with vector and full-text index policies, which the account rejects unless
  # these capabilities are enabled ("A Container Vector Policy has been
  # provided, but the capability has not been enabled on your account").
  # Harmless when chatbot memory is disabled.
  capabilities {
    name = "EnableNoSQLVectorSearch"
  }

  capabilities {
    name = "EnableNoSQLFullTextSearch"
  }

  tags = {
    AppName = local.resource_name
  }
}

resource "azurerm_cosmosdb_sql_database" "banking" {
  name                = "BankingDemo"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
}

resource "azurerm_cosmosdb_sql_container" "users" {
  name                = "Users"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}

resource "azurerm_cosmosdb_sql_container" "accounts" {
  name                = "Accounts"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}

resource "azurerm_cosmosdb_sql_container" "transactions" {
  name                = "Transactions"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/accountId"]
}

resource "azurerm_cosmosdb_sql_container" "transfers" {
  name                = "Transfers"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}

resource "azurerm_cosmosdb_sql_container" "login_audits" {
  name                = "login-audits"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}

resource "azurerm_cosmosdb_sql_container" "chat_sessions" {
  name                = "ChatSessions"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/userId"]

  default_ttl = 2592000 # 30 days
}

resource "azurerm_cosmosdb_sql_container" "account_applications" {
  name                = "account-applications"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}

#############################################
# BANKER COPILOT — authority / approval store (epic #332, Phase 1)
#
# Contract of record: docs/design/banker-copilot-policy-engine.md §5.2/§5.5 and
# docs/epics/banker-copilot.md §5.2. Written by authority-service (.NET), read by
# banker-copilot-service (Python). Field paths below are camelCase and are a
# cross-service contract — see .squad/skills/cosmos-casing-audit.
#############################################

# Approval requests. PK /requesterId: the dominant read is "what is waiting for
# the banker currently looking at the screen", which this keeps single-partition.
#
# default_ttl = -1 means TTL is ENABLED but NOT DEFAULTED: live approvals carry
# ttl = null and are immortal, and a per-item ttl is stamped only once the
# approval reaches a terminal state (retention purge). Expiry-as-denial is driven
# by the authority-service sweeper, never by Cosmos deleting the document —
# a vanished approval is indistinguishable from one that never existed.
resource "azurerm_cosmosdb_sql_container" "copilot_approvals" {
  name                = "copilot-approvals"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/requesterId"]

  default_ttl = -1

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    # Large and never filtered on — indexing them is pure RU waste on write.
    excluded_path {
      path = "/payload/*"
    }

    excluded_path {
      path = "/evidence/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }

    # Q2 — "my pending approvals", newest first, within one requester partition.
    composite_index {
      index {
        path  = "/status"
        order = "ascending"
      }
      index {
        path  = "/createdAt"
        order = "descending"
      }
    }

    # Q4 — expiry sweep: pending approvals whose deadline has passed.
    composite_index {
      index {
        path  = "/status"
        order = "ascending"
      }
      index {
        path  = "/expiresAtEpoch"
        order = "ascending"
      }
    }

    # Q3 — "awaiting a supervisor co-signature". Inherently cross-partition
    # (separation of duties guarantees the co-signer is not the requester), so it
    # is bounded by this index plus a page size.
    composite_index {
      index {
        path  = "/status"
        order = "ascending"
      }
      index {
        path  = "/awaitingSeniority"
        order = "ascending"
      }
      index {
        path  = "/createdAt"
        order = "ascending"
      }
    }

    # Q4b / Q4c — "what expired?" and "what did a policy change void?".
    # REQUIRED, not an optimisation. Collapsing `expired` into
    # `denied` + terminalReason turned a single-field status filter into two
    # predicates plus a sort on a third field. Cosmos will not use a composite
    # index unless every filter and ORDER BY path appears in it, in order, so
    # without this the query degrades to a cross-partition scan of every denied
    # approval — cheap at demo volume, quietly expensive later.
    composite_index {
      index {
        path  = "/status"
        order = "ascending"
      }
      index {
        path  = "/terminalReason"
        order = "ascending"
      }
      index {
        path  = "/terminalAt"
        order = "descending"
      }
    }
  }
}

# Resolved authority policy: doc id `active` plus immutable versioned history
# docs keyed by policyVersion, so a decision can always be re-explained under the
# policy that was in force at the time rather than today's policy.
resource "azurerm_cosmosdb_sql_container" "authority_policy" {
  name                = "authority-policy"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/id"]
}
