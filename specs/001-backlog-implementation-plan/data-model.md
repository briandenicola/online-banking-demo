# Data Model: Backlog Implementation Plan

**Date**: 2026-05-07
**Scope**: User Roles (P1) + Prompt Evaluation (P3)

## User Roles (Track C — Phase 1)

### Entity: UserRole

Added to existing `User` document in Cosmos DB (user-service).

```json
{
  "id": "user-uuid",
  "partitionKey": "user-uuid",
  "email": "admin@example.com",
  "passwordHash": "...",
  "firstName": "Brian",
  "lastName": "DeNicola",
  "role": "Admin",
  "createdAt": "2026-05-07T00:00:00Z",
  "updatedAt": "2026-05-07T00:00:00Z"
}
```

**Fields**:
| Field | Type | Validation | Default |
|-------|------|-----------|---------|
| role | string | enum: `"Admin"`, `"User"` | `"User"` |

**Constraints**:
- Role is immutable by the user themselves (only Admin can change another user's role)
- First registered user MAY be auto-promoted to Admin (seed data decision)
- Role is embedded in JWT `role` claim on login

### JWT Token Structure (updated)

```json
{
  "sub": "user-uuid",
  "email": "admin@example.com",
  "role": "Admin",
  "iat": 1715040000,
  "exp": 1715126400
}
```

### State Transitions

```
[New User] → role: "User" (default)
[Admin promotes] → role: "Admin"
[Admin demotes] → role: "User"
```

---

## Prompt Evaluation (Phase 3)

### Entity: PromptEvaluation

Stored in Cosmos DB (prompt-eval-service container).

```json
{
  "id": "eval-uuid",
  "partitionKey": "admin-user-uuid",
  "userId": "admin-user-uuid",
  "targetService": "chatbot-service",
  "prompt": "What is my account balance?",
  "response": "Your current balance is $1,234.56",
  "evaluationResults": {
    "groundedness": 4.2,
    "relevance": 4.8,
    "coherence": 4.5,
    "fluency": 4.7
  },
  "redTeamResults": {
    "jailbreak": { "passed": true, "score": 0.1 },
    "hateSpeech": { "passed": true, "score": 0.0 },
    "selfHarm": { "passed": true, "score": 0.0 },
    "violence": { "passed": true, "score": 0.0 }
  },
  "status": "completed",
  "createdAt": "2026-05-07T12:00:00Z",
  "completedAt": "2026-05-07T12:00:05Z"
}
```

**Fields**:
| Field | Type | Validation |
|-------|------|-----------|
| userId | string | Must be Admin role |
| targetService | string | enum: `"chatbot-service"`, `"budget-service"`, `"ai-service"` |
| prompt | string | max 4000 chars |
| status | string | enum: `"pending"`, `"running"`, `"completed"`, `"failed"` |
| evaluationResults | object | Quality metrics (1-5 scale) |
| redTeamResults | object | Safety metrics (0-1 score, lower = safer) |

### Entity: PromptTemplate

```json
{
  "id": "template-uuid",
  "partitionKey": "template",
  "name": "Balance Inquiry Test",
  "description": "Tests chatbot response to balance questions",
  "prompts": [
    "What is my account balance?",
    "How much money do I have?",
    "Show me my balance"
  ],
  "targetService": "chatbot-service",
  "createdBy": "admin-user-uuid",
  "createdAt": "2026-05-07T00:00:00Z"
}
```

### Relationships

```
User (1) ──── creates ────▶ (N) PromptEvaluation
User (1) ──── creates ────▶ (N) PromptTemplate
PromptTemplate (1) ── runs as ──▶ (N) PromptEvaluation
```

---

## Private Endpoints Infrastructure (US10)

**Date**: 2026-05-09
**Scope**: 6 private endpoints, 6 DNS zones, 1 PE subnet

### Entity: Private Endpoint Subnet

**Resource**: `azurerm_subnet.private_endpoints` in `networking.tf`

| Field | Value |
|-------|-------|
| `name` | `"private-endpoints"` |
| `address_prefixes` | `[local.pe_subnet_cidr]` — `/24` at offset 4 |

### Entity: Private DNS Zones (×6)

**Resource**: `azurerm_private_dns_zone.<service>` in `private-dns.tf`

| Instance | Zone Name |
|----------|-----------|
| `keyvault` | `privatelink.vaultcore.azure.net` |
| `cosmos` | `privatelink.documents.azure.com` |
| `redis` | `privatelink.redisenterprise.cache.azure.net` |
| `acr` | `privatelink.azurecr.io` |
| `ai` | `privatelink.cognitiveservices.azure.com` |
| `storage` | `privatelink.blob.core.windows.net` |

Each zone has one VNet link (`azurerm_private_dns_zone_virtual_network_link`).

### Entity: Private Endpoints (×6)

**Resource**: `azurerm_private_endpoint.<service>` in `private-endpoints.tf`

| Instance | Target Resource | Sub-resource |
|----------|----------------|--------------|
| `keyvault` | `azurerm_key_vault.main.id` | `vault` |
| `cosmos` | `azurerm_cosmosdb_account.main.id` | `Sql` |
| `redis` | `azurerm_managed_redis.main.id` | `redisEnterprise` |
| `acr` | `azurerm_container_registry.main.id` | `registry` |
| `ai` | `azapi_resource.this.id` | `account` |
| `storage` | `azurerm_storage_account.main.id` | `blob` |

Each PE includes a `private_dns_zone_group` linking to its corresponding DNS zone.

### Dependency Graph

```
VNet → PE Subnet → Private Endpoints (×6) → Target Resources
                                          → DNS Zone Groups → DNS Zones → VNet Links
```

### Existing Resources — No Modifications Required

All 6 services already have correct public access settings. No changes to existing `.tf` files needed.
