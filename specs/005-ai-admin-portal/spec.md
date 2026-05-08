# 005: AI Admin Portal — Prompt Evaluation & Tuning

## Problem Statement

The admin dashboard currently shows risk-scored and categorized transactions, but admins have no way to evaluate or improve the AI prompts used for scoring and categorization. There's no visibility into prompt quality, no A/B testing, and no safety validation. Admins need the ability to see current prompts, adjust them, test changes against real transactions, and compare results.

## Goal

Build a new `prompt-eval-service` (C#/.NET 9) that uses Azure AI Foundry's Evaluation SDK (`Azure.AI.Projects`) to let admins evaluate and tune AI prompts. Add a new "AI Evaluation" tab to the existing Admin page where admins can:

1. View and edit the risk scoring and categorization prompts used by ai-service
2. Run evaluations against existing scored transactions to test prompt quality
3. See quality scores (coherence, relevance, fluency) and safety results (violence, hate, self-harm)
4. Compare evaluation runs to track improvement over time

## Requirements

### R1: Prompt Eval Service (C#/.NET 9)
- New ASP.NET Core Web API service at `src/prompt-eval-service/`
- Uses `Azure.AI.Projects` NuGet package for Foundry evaluation APIs
- Authenticated via JWT (admin role required on all endpoints)
- Workload Identity for Azure AI Foundry access
- Endpoints per contracts/prompt-eval-api.md

### R2: Prompt Management
- Store prompt templates (system prompts for risk scoring, categorization)
- CRUD operations on templates
- Each template has: name, system prompt text, target (risk-scoring | categorization), version history
- Templates stored in Cosmos DB (same database, new container)

### R3: Evaluation Execution
- Admin selects a prompt template and a set of existing transactions
- Service creates an Azure AI Foundry Evaluation with testing criteria
- Runs the evaluation against the selected transactions using the prompt
- Returns quality scores: coherence, fluency, relevance
- Returns safety scores: violence, hate_unfairness, self_harm, sexual

### R4: Evaluation Results & History
- List all past evaluation runs with summary scores
- Drill into individual run results (per-transaction scores)
- Compare two runs side-by-side to see improvement/regression

### R5: Admin UI — New Tab in AdminPage
- New "AI Evaluation" tab in existing AdminPage.tsx (alongside Flagged/All Transactions)
- Prompt editor with syntax highlighting (or monospace textarea)
- Transaction selector (pick from recent scored transactions)
- Run evaluation button → shows progress → displays results
- Results table with quality + safety scores per transaction
- Historical runs list with comparison feature

## Architecture

```
Admin UI (AdminPage.tsx — "AI Evaluation" tab)
    │
    ▼
prompt-eval-service (C#/.NET 9)
    │
    ├── GET/PUT /api/evaluations/prompts — manage prompt templates (Cosmos DB)
    ├── POST /api/evaluations/run — execute evaluation
    │     └── Uses Azure.AI.Projects EvaluationClient
    │           ├── Creates Evaluation with testing criteria
    │           ├── Creates EvaluationRun with transaction data
    │           └── Polls for results
    ├── GET /api/evaluations — list past runs
    ├── GET /api/evaluations/{id} — get run details with per-item scores
    └── GET /api/evaluations/compare — compare two runs
    
    Fetches transactions from:
    └── ai-service GET /api/admin/transactions (existing)
```

## Non-Goals
- Automated prompt deployment (admins manually copy improved prompts to ai-service config)
- Real-time continuous evaluation (can be added later via Foundry's ContinuousEvaluationRules)
- Red teaming automation (Phase 2 — start with quality + safety evaluators)

## Existing Infrastructure
- **Foundry endpoint**: `FOUNDRY_PROJECT_ENDPOINT` — already provisioned
- **Model**: `gpt-5.4-mini` — already deployed
- **Workload Identity**: `banking-workload-identity` SA with `Cognitive Services OpenAI User` role
- **Cosmos DB**: `leading-terrier-26956-cosmos` — add new container for templates
- **Istio routing**: Add `/api/evaluations` route to prompt-eval-service
- **Admin role**: Already implemented in JWT (ClaimTypes.Role = "Admin")
