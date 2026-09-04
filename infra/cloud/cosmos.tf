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

#############################################
# BANKER COPILOT — harness stores (epic #332, Phase 2)
#
# Written by banker-copilot-service (Python/FastAPI). These three containers are
# the ONLY containers that service may write: its dedicated identity in
# infra/cloud/identity-copilot.tf holds Cosmos Data Contributor scoped to these
# names and nothing else, plus Data READER on copilot-approvals. That is the
# two-service split of epic §2.1 expressed in IAM rather than in convention —
# the harness physically cannot write banking state or mint an approval.
#
# Container identity and partition keys are fixed by epic §2.4 and §8.0. Field
# paths below are the CopilotEventEnvelope of
# docs/design/banker-copilot-ui.md §4.2, which epic §8.0 ratified as the single
# trace schema for both the live UI stream and #333 eval replay. Paths are
# camelCase and are a cross-service contract — see .squad/skills/cosmos-casing-audit.
#############################################

# A banker's Copilot conversation, plus the runs inside it (epic §0.1: a session
# contains many runs). Two document types discriminated by `docType`, one
# container.
#
# PK /sessionId, NOT /id — a deliberate deviation from epic §2.4, filed as
# .squad/decisions/inbox/rusty-copilot-container-keys.md.
#
# §2.4 says `/id`, and that was right when the container held only sessions.
# banker-copilot-service stores RUN documents here too, whose `id` is the run id.
# Under `/id` every run would land in its own logical partition, so "load this
# session and its runs" — the only reason to co-locate them in one container —
# would fan out across as many partitions as the banker has ever executed. Under
# `/sessionId` a session and all of its runs share one partition, which is what
# the co-location was for.
#
# Nothing regresses for session documents: `Session.to_document()` sets
# `sessionId = id`, so a session's partition key and its id are the same value
# and the point read `read_item(item=sessionId, partition_key=sessionId)` behaves
# exactly as it would have under `/id`.
resource "azurerm_cosmosdb_sql_container" "copilot_sessions" {
  name                = "copilot-sessions"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/sessionId"]

  default_ttl = var.copilot_session_retention_seconds

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    # Foundry thread state and the conversation transcript: large, and never a
    # query predicate. Indexing them is pure RU cost on every write.
    excluded_path {
      path = "/threadState/*"
    }

    excluded_path {
      path = "/messages/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }

    # "My sessions, most recently active first" — the session list in the left
    # pane. Cross-partition by construction (PK is the session id), so it is
    # bounded by this index plus a page size.
    composite_index {
      index {
        path  = "/bankerId"
        order = "ascending"
      }
      index {
        path  = "/updatedAt"
        order = "descending"
      }
    }
  }
}

# Decision memos, payloads, comparisons and evidence bundles produced by a run.
# PK /sessionId: artifacts are always read in the context of the session that is
# on screen, which keeps the dominant read single-partition.
resource "azurerm_cosmosdb_sql_container" "copilot_artifacts" {
  name                = "copilot-artifacts"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/sessionId"]

  default_ttl = var.copilot_artifact_retention_seconds

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    # The artifact body itself. Rendered, never filtered on.
    excluded_path {
      path = "/content/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }

    # "The revisions of each artifact this run produced" — the right-hand
    # artifact pane. Filter on runId, sort on revision: both paths must appear,
    # in that order, or Cosmos ignores the index entirely.
    #
    # BOTH directions are declared on purpose. A composite index serves an
    # ORDER BY only when the directions match exactly, or are exactly reversed
    # for every path — so (runId ASC, revision DESC) does NOT serve
    # `WHERE runId = @r ORDER BY revision ASC`, which is the query the service
    # actually issues. Declaring one direction and assuming the other works is
    # the same silent degradation as a wrong field path: the query still returns
    # correct rows, just by scanning. Ascending serves "replay the revisions in
    # order", descending serves "show me the latest".
    composite_index {
      index {
        path  = "/runId"
        order = "ascending"
      }
      index {
        path  = "/revision"
        order = "ascending"
      }
    }

    composite_index {
      index {
        path  = "/runId"
        order = "ascending"
      }
      index {
        path  = "/revision"
        order = "descending"
      }
    }

    # "Show me the decision memos in this session" — filter by kind, newest
    # first, within the session partition.
    composite_index {
      index {
        path  = "/kind"
        order = "ascending"
      }
      index {
        path  = "/createdAt"
        order = "descending"
      }
    }
  }
}

# CopilotEventEnvelope frames (epic §8.0). This container has TWO consumers with
# different access shapes and it must serve both, because #333 replay cannot be
# retrofitted from a stream shaped only for live rendering:
#
#   (1) LIVE UI — SSE resume after a reconnect:
#       WHERE runId = @runId AND seq > @lastSeq ORDER BY seq ASC
#       Single-partition; served by the range index on /seq.
#
#   (2) EVAL REPLAY (#333) — replay an entire session's trajectory offline:
#       WHERE sessionId = @sessionId ORDER BY runId ASC, seq ASC
#       Cross-partition, because one session spans many runs and the PK is the
#       run. `seq` is monotonic and gapless PER RUN, never per session, so
#       ordering a whole session by seq alone would interleave runs and produce
#       a trajectory the agent never took. Ordering by (runId, seq) is the
#       deterministic reconstruction.
#
# PK /runId is fixed by epic §8.0 and is right for (1), which is the hot path.
# (2) pays a cross-partition fan-out, which is correct: it is an offline batch
# read, not a request-path query.
#
# default_ttl is a configured retention, not -1. A trace is the eval input for
# #333, so deleting it destroys eval history — but keeping every frame forever
# in a demo account is not honest either. The retention window is therefore
# configuration (var.copilot_trace_retention_seconds), so an environment that
# needs a longer eval corpus raises it without a code change.
resource "azurerm_cosmosdb_sql_container" "copilot_traces" {
  name                = "copilot-traces"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.banking.name
  partition_key_paths = ["/runId"]

  default_ttl = var.copilot_trace_retention_seconds

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    # The per-kind payload union (§4.2). Large, highly variable in shape, and
    # carries the redacted tool arguments and results — it is rendered and
    # replayed, never used as a predicate. Excluding it also means an unforeseen
    # payload shape can never blow up the index.
    excluded_path {
      path = "/payload/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }

    # (2) Eval replay of a whole session, in the order the agent actually acted.
    # All three paths are present and ordered because Cosmos will not use a
    # composite index unless every filter AND every ORDER BY path appears in it,
    # in order — the lesson that made the (status, terminalReason, terminalAt)
    # index above mandatory rather than optional.
    composite_index {
      index {
        path  = "/sessionId"
        order = "ascending"
      }
      index {
        path  = "/runId"
        order = "ascending"
      }
      index {
        path  = "/seq"
        order = "ascending"
      }
    }

    # Time-ordered read across a session — latency and timeout analysis (§8.0
    # requires the server clock `ts` precisely so this is answerable). Distinct
    # from the index above: `ts` is comparable across runs, `seq` is not.
    composite_index {
      index {
        path  = "/sessionId"
        order = "ascending"
      }
      index {
        path  = "/ts"
        order = "ascending"
      }
    }

    # "Every approval frame in this run", "every tool call in this run" — the
    # eval questions of §8.0 are asked per kind. Filter on kind, order by seq,
    # inside the run partition.
    composite_index {
      index {
        path  = "/kind"
        order = "ascending"
      }
      index {
        path  = "/seq"
        order = "ascending"
      }
    }

    # Cross-run reconstruction of a subagent fan-out tree (§8.0 `parentRunId`).
    # Phase 3 lights this up; the index lands with the schema so that a Phase 3
    # query does not silently degrade to a full scan on a container that by then
    # holds every frame of every run.
    composite_index {
      index {
        path  = "/parentRunId"
        order = "ascending"
      }
      index {
        path  = "/ts"
        order = "ascending"
      }
    }
  }
}
