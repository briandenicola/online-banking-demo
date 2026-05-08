# API Contracts: Prompt Evaluation Service

**Base URL**: `/api/evaluations`
**Auth**: Bearer JWT with `role: "Admin"` claim required on all endpoints

---

## Prompt Template Endpoints

### GET /api/evaluations/prompts

List all prompt templates for the current admin.

**Response** (200 OK):
```json
[
  {
    "id": "uuid",
    "name": "Risk Scoring v2",
    "description": "Improved risk scoring with category context",
    "target": "risk-scoring",
    "systemPrompt": "You are a financial security expert...",
    "version": 3,
    "isActive": false,
    "createdAt": "2026-05-08T12:00:00Z",
    "updatedAt": "2026-05-08T14:30:00Z"
  }
]
```

### GET /api/evaluations/prompts/{id}

Get a single prompt template.

**Response** (200 OK): Same as list item above.

### POST /api/evaluations/prompts

Create a new prompt template.

**Request**:
```json
{
  "name": "Risk Scoring v2",
  "description": "Improved risk scoring with category context",
  "target": "risk-scoring",
  "systemPrompt": "You are a financial security expert at a major bank..."
}
```

**Response** (201 Created): Full template object with generated `id`, `version: 1`.

### PUT /api/evaluations/prompts/{id}

Update a prompt template. Increments version automatically.

**Request**:
```json
{
  "name": "Risk Scoring v2",
  "description": "Updated description",
  "systemPrompt": "Updated prompt text..."
}
```

**Response** (200 OK): Updated template with incremented version.

### DELETE /api/evaluations/prompts/{id}

Delete a prompt template and all associated evaluation runs.

**Response** (204 No Content)

---

## Evaluation Run Endpoints

### POST /api/evaluations/run

Execute an evaluation against selected transactions using a prompt template.

**Request**:
```json
{
  "templateId": "uuid",
  "transactionIds": ["tx-uuid-1", "tx-uuid-2", "tx-uuid-3"]
}
```

**Response** (202 Accepted):
```json
{
  "id": "eval-run-uuid",
  "status": "pending",
  "transactionCount": 3,
  "createdAt": "2026-05-08T15:00:00Z"
}
```

### GET /api/evaluations

List evaluation runs (most recent first).

**Query params**: `?page=1&pageSize=20&templateId=uuid`

**Response** (200 OK):
```json
{
  "items": [
    {
      "id": "eval-run-uuid",
      "templateId": "uuid",
      "templateName": "Risk Scoring v2",
      "templateVersion": 3,
      "status": "completed",
      "transactionCount": 5,
      "qualityScores": {
        "coherence": 4.2,
        "fluency": 4.5,
        "relevance": 4.1,
        "passRate": 0.80
      },
      "safetyScores": {
        "violence": { "passed": true, "averageScore": 0.2, "failedCount": 0 },
        "hateUnfairness": { "passed": true, "averageScore": 0.0, "failedCount": 0 },
        "selfHarm": { "passed": true, "averageScore": 0.0, "failedCount": 0 },
        "sexual": { "passed": true, "averageScore": 0.0, "failedCount": 0 }
      },
      "createdAt": "2026-05-08T15:00:00Z",
      "completedAt": "2026-05-08T15:00:45Z"
    }
  ],
  "total": 12,
  "page": 1,
  "pageSize": 20
}
```

### GET /api/evaluations/{id}

Get evaluation run details including per-transaction results.

**Response** (200 OK):
```json
{
  "id": "eval-run-uuid",
  "templateId": "uuid",
  "templateName": "Risk Scoring v2",
  "templateVersion": 3,
  "status": "completed",
  "transactionCount": 3,
  "qualityScores": { ... },
  "safetyScores": { ... },
  "outputItems": [
    {
      "transactionId": "tx-uuid-1",
      "query": "Assess this transaction: Amount: $150.00, Type: purchase...",
      "response": "{\"riskScore\": 0.15, \"explanation\": \"Routine purchase\", ...}",
      "coherenceScore": 4.5,
      "fluencyScore": 4.8,
      "relevanceScore": 4.2,
      "safetyPassed": true,
      "safetyDetails": {
        "violence": 0.0,
        "hateUnfairness": 0.0,
        "selfHarm": 0.0,
        "sexual": 0.0
      }
    }
  ],
  "createdAt": "2026-05-08T15:00:00Z",
  "completedAt": "2026-05-08T15:00:45Z"
}
```

### GET /api/evaluations/compare?runId1={id1}&runId2={id2}

Compare two evaluation runs side-by-side.

**Response** (200 OK):
```json
{
  "run1": { "id": "...", "templateName": "v1", "qualityScores": {...}, "safetyScores": {...} },
  "run2": { "id": "...", "templateName": "v2", "qualityScores": {...}, "safetyScores": {...} },
  "deltas": {
    "coherence": +0.5,
    "fluency": +0.2,
    "relevance": -0.1,
    "passRate": +0.10
  }
}
```

---

## Health Endpoints

### GET /healthz
**Response** (200 OK): `{ "status": "healthy" }`

### GET /readyz
**Response** (200 OK): `{ "status": "ready" }`
