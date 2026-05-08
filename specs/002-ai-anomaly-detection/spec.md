# 002: AI-Powered Anomaly Detection via Azure AI Foundry

## Problem Statement

The ai-service currently uses a local scikit-learn `IsolationForest` model for transaction risk scoring. This approach has critical limitations:

1. **Cold start** — requires 10+ in-memory transactions before scoring begins; pod restarts reset the model
2. **No AI integration** — `AZURE_OPENAI_ENDPOINT` is never configured; AI explanation generation is dead code
3. **No risk scores on all transactions** — the admin page only shows flagged transactions, not all transactions with their risk scores
4. **Uses wrong SDK** — uses `azure-ai-inference` instead of `agent-framework-foundry` (the project standard, used by chatbot-service)
5. **Simplistic feature extraction** — only considers amount and type length

## Goal

Replace the IsolationForest ML model with Azure AI Foundry (GPT-5.4-mini) for transaction risk assessment. Every transaction should receive a risk score (0.0–1.0) and AI-generated risk explanation. The admin dashboard should display ALL transactions with their risk scores, with flagged transactions linked to detailed views.

## Requirements

### R1: Foundry-Based Risk Scoring
- Replace `IsolationForest` + `azure-ai-inference` with `agent-framework-foundry` (`FoundryChatClient`)
- Use the same `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` (gpt-5.4-mini) env vars as chatbot-service
- Every transaction consumed from Redis Stream gets a risk score (0.0–1.0) and explanation
- Use structured output / JSON mode for consistent risk assessment responses
- Define a clear prompt template for the financial risk assessment persona

### R2: All Transactions with Risk Scores in Admin View
- Store risk score and AI explanation alongside every transaction (not just flagged ones)
- Admin dashboard shows ALL recent transactions in a table with risk score column
- Risk score rendered as color-coded chip (green/yellow/orange/red)
- Sortable/filterable by risk score, amount, date, account
- High-risk transactions (score > threshold) automatically flagged

### R3: Flagged Transaction Details
- Flagged transactions link to a detail view with full AI risk assessment
- Detail view shows: transaction data, risk score, AI explanation, review status, admin notes
- Admin can review/clear flagged transactions (existing functionality, keep working)

### R4: Remove scikit-learn Dependency
- Remove `IsolationForest`, `numpy`, `sklearn` from ai-service
- Remove in-memory `transaction_history` and feature extraction code
- Simplify to: consume event → call Foundry → store result → flag if high risk

### R5: K8s Configuration
- Add `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` env vars to ai-service K8s deployment (same pattern as chatbot-service)
- Remove `AZURE_OPENAI_ENDPOINT` references

## Architecture

```
Redis Stream (banking-events)
    │
    ▼
ai-service (consume_redis_stream)
    │
    ├── Call Foundry GPT-5.4-mini with transaction context
    │   └── Returns: { riskScore: 0.0-1.0, explanation: "...", flags: [...] }
    │
    ├── Store scored transaction in Redis (scored-tx:{id})
    │   └── ALL transactions stored, not just flagged
    │
    └── If riskScore > 0.7 → also store in flagged-transactions sorted set
        └── (existing admin review flow continues working)

Admin UI
    ├── /api/admin/transactions → ALL scored transactions with risk scores
    └── /api/admin/flagged-transactions → high-risk only (existing)
```

## Non-Goals
- Real-time streaming risk scores to the user-facing UI (admin only for now)
- Custom model training / fine-tuning
- Historical re-scoring of old transactions
- Changes to the transaction-service itself (it already publishes events)

## Existing Infrastructure
- **Foundry endpoint**: Terraform output `openai_endpoint` → already provisioned
- **Model**: `gpt-5.4-mini` already deployed (same as chatbot)
- **K8s secret**: `banking-secrets.openai-endpoint` already exists (chatbot uses it)
- **Workload Identity**: ai-service already uses `banking-workload-identity` SA with `Cognitive Services OpenAI User` role
- **Redis**: ai-service already connected and consuming from `banking-events` stream
- **Istio routing**: `/api/admin` already routes to ai-service
