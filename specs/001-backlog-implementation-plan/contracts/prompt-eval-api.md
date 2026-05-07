# API Contracts: Prompt Evaluation Service

**Base URL**: `/api/evaluations`
**Auth**: Bearer JWT with `role: "Admin"` claim required

## Endpoints

### POST /api/evaluations

Submit a prompt for evaluation against a target AI service.

**Request**:
```json
{
  "targetService": "chatbot-service",
  "prompt": "What is my account balance?",
  "templateId": "template-uuid"  // optional
}
```

**Response** (202 Accepted):
```json
{
  "id": "eval-uuid",
  "status": "pending",
  "createdAt": "2026-05-07T12:00:00Z"
}
```

### GET /api/evaluations/:id

Get evaluation results.

**Response** (200 OK):
```json
{
  "id": "eval-uuid",
  "targetService": "chatbot-service",
  "prompt": "What is my account balance?",
  "response": "Your current balance is $1,234.56",
  "status": "completed",
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
  "createdAt": "2026-05-07T12:00:00Z",
  "completedAt": "2026-05-07T12:00:05Z"
}
```

### GET /api/evaluations

List evaluations (paginated).

**Query params**: `?page=1&pageSize=20&targetService=chatbot-service`

**Response** (200 OK):
```json
{
  "items": [...],
  "total": 42,
  "page": 1,
  "pageSize": 20
}
```

### POST /api/evaluations/batch

Run a template's prompts as a batch evaluation.

**Request**:
```json
{
  "templateId": "template-uuid",
  "targetService": "chatbot-service"
}
```

**Response** (202 Accepted):
```json
{
  "batchId": "batch-uuid",
  "evaluationIds": ["eval-1", "eval-2", "eval-3"],
  "status": "pending"
}
```

---

## Prompt Templates API

**Base URL**: `/api/templates`

### POST /api/templates

```json
{
  "name": "Balance Inquiry Test",
  "description": "Tests chatbot responses to balance questions",
  "prompts": ["What is my balance?", "How much money do I have?"],
  "targetService": "chatbot-service"
}
```

### GET /api/templates
### GET /api/templates/:id
### PUT /api/templates/:id
### DELETE /api/templates/:id

---

## User Roles API Extension

**Added to existing user-service**:

### PATCH /api/users/:id/role

Admin-only: Change a user's role.

**Request**:
```json
{
  "role": "Admin"
}
```

**Response** (200 OK):
```json
{
  "id": "user-uuid",
  "email": "user@example.com",
  "role": "Admin"
}
```

### GET /api/users/me

Returns current user including role.

**Response** (200 OK):
```json
{
  "id": "user-uuid",
  "email": "brian@example.com",
  "firstName": "Brian",
  "lastName": "DeNicola",
  "role": "Admin"
}
```
