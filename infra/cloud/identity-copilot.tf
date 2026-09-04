#############################################
# BANKER-COPILOT-SERVICE WORKLOAD IDENTITY (issue #336, epic #332 Phase 2)
#
# This file is the two-service split of epic §2.1 written in IAM.
#
# The invariant is "agents never approve", and the enforcement mechanism is that
# `banker-copilot-service` registers ZERO write tools — its only write affordance
# is `propose_action`, which is an HTTP call to `authority-service`. That is a
# statement about application code, and application code can be changed by a
# pull request. The role assignments below are what makes the same statement
# true at the platform layer, where changing it requires a Terraform diff that
# shows up as an infrastructure change rather than a refactor:
#
#   - Cosmos Data CONTRIBUTOR is scoped to the three HARNESS containers only
#     (copilot-sessions, copilot-artifacts, copilot-traces). The harness owns its
#     own conversation, artifact and trace state and nothing else.
#   - Cosmos Data READER — not Contributor — on `copilot-approvals`. The harness
#     must render the approval card and watch the approval's status change, so it
#     needs to read the document. It must never write one. A harness that could
#     write to `copilot-approvals` could set `status: signed` on its own proposal,
#     which is precisely the invariant this epic exists to defend, and no amount
#     of application-level tool-manifest discipline would stop it.
#   - NOTHING on Accounts, Transactions, Transfers, Users, account-applications
#     or authority-policy — not even read. The harness reads banking state
#     through the six read tools of epic §3.3, which are HTTP calls to the owning
#     services carrying the banker's own bearer token. Granting it direct Cosmos
#     reads "because it needs the data anyway" would bypass those services'
#     authorization checks entirely and make the tool manifest decorative.
#
# What it deliberately does NOT get, and why — the omissions are the design:
#
#   - NO Redis data access. `authority-service` owns audit publishing (§5.7) and
#     the harness has no audit responsibility. Redis access here would be write
#     access to the `banking-events` stream, i.e. the ability to FORGE an audit
#     event — including an `ApprovalSigned` — for the one service in the system
#     whose defining property is that it cannot act. Granting the shared
#     `banking-events` stream to the component we are containing would undo the
#     containment through the audit trail rather than through the data plane.
#     If the harness ever genuinely needs a stream (e.g. multi-replica SSE
#     fan-out in Phase 3), it gets its OWN stream with its own access policy,
#     never the audit bus.
#   - NO Storage Blob, NO AI Search. It touches neither.
#   - `Azure AI User`, not `Azure AI Project Manager`. The shared identity holds
#     Project Manager because ai-service and chatbot-service provision agents;
#     the harness only needs to RUN one. Project Manager additionally permits
#     creating and deleting projects and connections, which is a control-plane
#     capability with no place in a request-path service.
#
# The one uncomfortable grant is Key Vault Secrets User. See the comment on that
# resource — it is required, and #334 makes it more powerful than it looks.
#############################################

resource "azurerm_user_assigned_identity" "banker_copilot_service" {
  name                = "${local.resource_name}-copilot-mi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = {
    AppName = local.resource_name
    Service = "banker-copilot-service"
  }
}

# Federated credential — bound to its OWN Kubernetes service account, distinct
# from BOTH banking-workload-identity and authority-workload-identity. If the
# harness could assume authority-service's identity the split would be cosmetic,
# so the two service accounts are the boundary and this is where it is drawn.
#
# NOTE: no `resource_group_name` argument. azurerm ~> 4 removed it from this
# resource; adding it (a habit from 3.x) fails `terraform validate`. Matches
# the existing credentials in identity.tf and identity-authority.tf.
resource "azurerm_federated_identity_credential" "aks_banker_copilot_workload_identity" {
  name                      = "aks-banker-copilot-workload-identity"
  user_assigned_identity_id = azurerm_user_assigned_identity.banker_copilot_service.id
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "system:serviceaccount:${var.kubernetes_namespace}:${var.banker_copilot_service_account}"
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
}

#############################################
# Cosmos data plane — WRITE, scoped to the three harness containers
#############################################

resource "azurerm_cosmosdb_sql_role_assignment" "copilot_cosmos_sessions" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.banker_copilot_service.principal_id
  scope               = "${azurerm_cosmosdb_account.main.id}/dbs/${azurerm_cosmosdb_sql_database.banking.name}/colls/${azurerm_cosmosdb_sql_container.copilot_sessions.name}"
}

resource "azurerm_cosmosdb_sql_role_assignment" "copilot_cosmos_artifacts" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.banker_copilot_service.principal_id
  scope               = "${azurerm_cosmosdb_account.main.id}/dbs/${azurerm_cosmosdb_sql_database.banking.name}/colls/${azurerm_cosmosdb_sql_container.copilot_artifacts.name}"
}

resource "azurerm_cosmosdb_sql_role_assignment" "copilot_cosmos_traces" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.banker_copilot_service.principal_id
  scope               = "${azurerm_cosmosdb_account.main.id}/dbs/${azurerm_cosmosdb_sql_database.banking.name}/colls/${azurerm_cosmosdb_sql_container.copilot_traces.name}"
}

#############################################
# Cosmos data plane — READ ONLY on the approval store
#
# 00000000-0000-0000-0000-000000000001 is Cosmos DB Built-in Data READER.
# The single character that differs from the Contributor assignments above
# (…0001 vs …0002) is load-bearing for the core invariant of this epic, which is
# why it is called out here rather than left to be noticed in a diff.
#############################################

resource "azurerm_cosmosdb_sql_role_assignment" "copilot_cosmos_approvals_read" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001"
  principal_id        = azurerm_user_assigned_identity.banker_copilot_service.principal_id
  scope               = "${azurerm_cosmosdb_account.main.id}/dbs/${azurerm_cosmosdb_sql_database.banking.name}/colls/${azurerm_cosmosdb_sql_container.copilot_approvals.name}"
}

#############################################
# Model access — the harness IS the agent loop, so this is its core dependency
#############################################

resource "azurerm_role_assignment" "copilot_cognitive_services_openai_user" {
  scope                = azapi_resource.this.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.banker_copilot_service.principal_id
}

# Azure AI User (53ca6127-db72-4b80-b1b0-d745d6d5456d) — run agents, threads and
# runs in the Foundry project. Deliberately narrower than the Azure AI Project
# Manager role the shared identity holds: the harness consumes the Agents API,
# it does not provision projects or connections.
resource "azurerm_role_assignment" "copilot_ai_user" {
  scope              = azapi_resource.ai_foundry_project.id
  role_definition_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
  principal_id       = azurerm_user_assigned_identity.banker_copilot_service.principal_id
}

#############################################
# Key Vault — required, and honestly annotated
#
# The harness authenticates the banker's bearer token on every request, so it
# must read the JWT signing key. Under #334 that key is a SYMMETRIC HMAC secret
# shared by every service, which means the ability to VERIFY a token is
# indistinguishable from the ability to MINT one. So this grant, which reads as
# "let the harness check who is calling it", in fact also confers "let the
# harness forge a token for any identity, including a supervisor" — and a forged
# supervisor token calling authority-service directly would satisfy an L2
# signature slot with no human involved.
#
# Everything else in this file narrows the harness. This one grant is the hole,
# and it is not closable here: it closes when #334 gives authority-service an
# asymmetric key and a mediator-only audience, so that a service holding the
# verification material cannot produce signing material. Recording it plainly
# rather than quietly granting it, because a least-privilege boundary with an
# undocumented exception is worse than no boundary — it invites the belief that
# the boundary holds.
#############################################

resource "azurerm_role_assignment" "copilot_keyvault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.banker_copilot_service.principal_id
}
