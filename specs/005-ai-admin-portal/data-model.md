# Data Model: AI Admin Portal

## Entity: PromptTemplate

Stores reusable AI prompt templates that admins can edit and evaluate.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string (UUID) | Yes | Unique identifier |
| name | string | Yes | Human-readable name (e.g., "Risk Scoring v2") |
| description | string | No | Purpose/notes about this template |
| target | string (enum) | Yes | `risk-scoring` or `categorization` |
| systemPrompt | string | Yes | The full system prompt text |
| version | int | Yes | Auto-incrementing version number |
| userId | string | Yes | Admin who created/owns this template |
| isActive | bool | Yes | Whether this is the currently deployed prompt |
| createdAt | DateTime | Yes | Creation timestamp |
| updatedAt | DateTime | Yes | Last modification timestamp |

**Partition key**: `/userId`
**Container**: `prompt-templates`

### Validation Rules
- `name`: 1–200 characters, unique per user
- `systemPrompt`: 1–10,000 characters
- `target`: must be `risk-scoring` or `categorization`
- `version`: starts at 1, auto-incremented on update

---

## Entity: EvaluationRun

Stores metadata and results for each evaluation execution.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string (UUID) | Yes | Unique identifier |
| templateId | string | Yes | Reference to PromptTemplate used |
| templateName | string | Yes | Denormalized template name |
| templateVersion | int | Yes | Version of template at time of eval |
| foundryEvalId | string | No | Azure AI Foundry evaluation ID |
| foundryRunId | string | No | Azure AI Foundry run ID |
| status | string (enum) | Yes | `pending`, `running`, `completed`, `failed` |
| transactionCount | int | Yes | Number of transactions evaluated |
| userId | string | Yes | Admin who initiated the run |
| qualityScores | QualityScores | No | Aggregated quality metrics |
| safetyScores | SafetyScores | No | Aggregated safety metrics |
| error | string | No | Error message if failed |
| createdAt | DateTime | Yes | When the run was initiated |
| completedAt | DateTime | No | When the run finished |

**Partition key**: `/userId`
**Container**: `evaluation-runs`

### State Transitions
```
pending → running → completed
                  → failed
```

---

## Value Object: QualityScores

| Field | Type | Description |
|-------|------|-------------|
| coherence | float | Average coherence score (1–5) |
| fluency | float | Average fluency score (1–5) |
| relevance | float | Average relevance score (1–5) |
| passRate | float | Percentage of items that passed all quality checks |

---

## Value Object: SafetyScores

| Field | Type | Description |
|-------|------|-------------|
| violence | SafetyResult | Violence evaluation result |
| hateUnfairness | SafetyResult | Hate/unfairness evaluation result |
| selfHarm | SafetyResult | Self-harm evaluation result |
| sexual | SafetyResult | Sexual content evaluation result |

---

## Value Object: SafetyResult

| Field | Type | Description |
|-------|------|-------------|
| passed | bool | Whether the safety check passed |
| averageScore | float | Average severity score (0–7, ≤3 = pass) |
| failedCount | int | Number of items that failed this check |

---

## Value Object: EvaluationOutputItem

Per-transaction result within an evaluation run.

| Field | Type | Description |
|-------|------|-------------|
| transactionId | string | Original transaction ID |
| query | string | Formatted transaction input sent to AI |
| response | string | AI's response text |
| coherenceScore | float | Individual coherence score (1–5) |
| fluencyScore | float | Individual fluency score (1–5) |
| relevanceScore | float | Individual relevance score (1–5) |
| safetyPassed | bool | Whether all safety checks passed |
| safetyDetails | map<string, float> | Per-evaluator safety scores |

---

## Relationships

```
PromptTemplate 1──* EvaluationRun
EvaluationRun 1──* EvaluationOutputItem (stored in Foundry, fetched on demand)
```
