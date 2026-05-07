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
| targetService | string | enum: `"chatbot-service"`, `"budget-service"`, `"anomaly-service"` |
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
