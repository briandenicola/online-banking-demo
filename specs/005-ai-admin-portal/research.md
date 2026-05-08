# Research: AI Admin Portal (US5)

## R1: Azure AI Evaluation SDK for C#/.NET

### Decision: Use `Azure.AI.Projects` NuGet package (prerelease)

**Rationale**: The C# evaluation API is available through `Azure.AI.Projects` NuGet package. It provides `EvaluationClient` via `AIProjectClient.GetEvaluationClient()`. This is the same package family used across the project for Azure AI Foundry integration.

**Key findings**:
- Evaluation API uses **protocol methods** (`BinaryData`/`BinaryContent`) — not fully typed models yet
- Red teaming has strongly-typed models (`RedTeam`, `AttackStrategy`, `RiskCategory`)
- `#pragma warning disable AAIP001` required for experimental features
- All evaluation runs are **server-side** (cloud-hosted in Foundry) — no local execution

**Alternatives considered**:
- `azure-ai-evaluation` Python SDK — local execution, but Python-only. User explicitly wants C#.
- Custom LLM-as-judge — more control but reinvents what Foundry provides built-in

### API Pattern (C#)

```csharp
var projectClient = new AIProjectClient(endpoint, new DefaultAzureCredential());
var evalClient = projectClient.GetEvaluationClient();

// 1. Create Evaluation (schema + testing criteria)
var evalData = BinaryData.FromObjectAsJson(new {
    name = "Risk Scoring Prompt Eval",
    data_source_config = new { type = "custom", ... },
    testing_criteria = new[] {
        new { type = "azure_ai_evaluator", evaluator_name = "builtin.coherence", ... },
        new { type = "azure_ai_evaluator", evaluator_name = "builtin.violence", ... }
    }
});
var eval = await evalClient.CreateEvaluationAsync(BinaryContent.Create(evalData));

// 2. Create Run (execute with data)
var runData = BinaryData.FromObjectAsJson(new { eval_id = evalId, data_source = ... });
var run = await evalClient.CreateEvaluationRunAsync(evalId, BinaryContent.Create(runData));

// 3. Poll for completion
// 4. Get output items
var results = await evalClient.GetEvaluationRunOutputItemsAsync(evalId, runId, ...);
```

## R2: Available Evaluators

### Quality evaluators (require `deployment_name` for judge model):
| Evaluator | `evaluator_name` | Score | Inputs |
|-----------|------------------|-------|--------|
| Coherence | `builtin.coherence` | 1–5 Likert | query, response |
| Fluency | `builtin.fluency` | 1–5 Likert | response |
| Relevance | `builtin.relevance` | 1–5 Likert | query, response |
| Groundedness | `builtin.groundedness` | 1–5 Likert | response, context |

### Safety evaluators (use Microsoft-hosted models — NO deployment_name):
| Evaluator | `evaluator_name` | Scale | Inputs |
|-----------|------------------|-------|--------|
| Violence | `builtin.violence` | 0–7 (≤3 pass) | query, response |
| Hate & Unfairness | `builtin.hate_unfairness` | 0–7 | query, response |
| Self Harm | `builtin.self_harm` | 0–7 | query, response |
| Sexual | `builtin.sexual` | 0–7 | query, response |

### For this feature, use:
- **Quality**: coherence, fluency, relevance (groundedness skipped — no RAG context)
- **Safety**: violence, hate_unfairness, self_harm, sexual

## R3: Storage Design

### Decision: Cosmos DB — new container `prompt-templates`

**Rationale**: Consistent with existing services. All other services use the same Cosmos DB instance. Convention over configuration — reuse existing connection patterns.

**Partition key**: `/userId` (admin who created the template)

**Alternatives considered**:
- Redis — ephemeral, not suitable for versioned prompt storage
- Separate database — unnecessary complexity, violates convention principle

## R4: Evaluation Data Flow

### Decision: Fetch scored transactions from ai-service, transform to eval format

**Flow**:
1. Admin selects transactions from UI (IDs from existing scored-transactions list)
2. prompt-eval-service fetches full transaction data from ai-service
3. Transforms to JSONL-style items: `{ query: "<formatted transaction>", expected: "<current AI response>" }`
4. Creates Foundry Evaluation with selected prompt template as the system prompt
5. Runs evaluation → polls → returns results

**Key insight**: We're evaluating "given this prompt + transaction data, how good is the AI response?" — this maps to quality evaluators (coherence, fluency, relevance) where:
- `query` = the formatted transaction context
- `response` = the AI's risk assessment / categorization output

## R5: Service-to-Service Communication

### Decision: prompt-eval-service calls ai-service directly via K8s service DNS

**Pattern**: `http://ai-service:80/api/admin/transactions` — same as other service-to-service calls. No JWT forwarding needed since ai-service admin endpoints accept cluster-internal traffic.

**Note**: Need to verify if ai-service admin endpoints require JWT or are open internally. If JWT required, forward the admin's JWT from the request.
