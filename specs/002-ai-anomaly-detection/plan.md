# 002: AI-Powered Anomaly Detection — Implementation Plan

## Overview

Replace the anomaly-service's local IsolationForest ML model with Azure AI Foundry (GPT-5.4-mini) for risk scoring. Add an "All Transactions" admin view showing every transaction with its AI-generated risk score.

## Technical Context

- **AI SDK**: `agent-framework-foundry` (FoundryChatClient) — same as chatbot-service
- **Model**: `gpt-5.4-mini` via Azure AI Foundry (already deployed)
- **Foundry endpoint**: Already in Terraform outputs + K8s secret `banking-secrets.openai-endpoint`
- **Current anomaly-service**: Python/FastAPI, consumes Redis Stream `banking-events`, stores flagged txns in Redis
- **Admin UI**: React/MUI, fetches from `/api/admin/stats` and `/api/admin/flagged-transactions`
- **Istio routing**: `/api/admin` → anomaly-service (already configured)

## Phase 1: Anomaly Service Backend Rework

### T1: Replace IsolationForest with Foundry FoundryChatClient
**File**: `src/anomaly-service/app/main.py`
- Remove `sklearn`, `numpy` imports and `IsolationForest` model
- Remove `transaction_history`, `extract_features()`, in-memory ML training
- Add `agent-framework-foundry` import (same pattern as chatbot-service)
- Initialize `FoundryChatClient` using `FOUNDRY_PROJECT_ENDPOINT` env var
- Create `assess_transaction_risk()` function that:
  - Sends transaction context to GPT-5.4-mini with a risk assessment prompt
  - Uses JSON structured output to get: `{ riskScore: float, explanation: str, flags: list[str] }`
  - Returns `RiskAssessment` pydantic model

### T2: Define risk assessment prompt template
**File**: `src/anomaly-service/app/main.py`
- Create `RISK_ASSESSMENT_PROMPT` — financial security expert persona
- Include transaction fields: amount, type, description, category, account context
- Request structured JSON response with riskScore (0.0-1.0), explanation, and flags
- Include examples of low-risk vs high-risk patterns for few-shot guidance

### T3: Store ALL scored transactions in Redis
**File**: `src/anomaly-service/app/main.py`
- New Redis key pattern: `scored-tx:{transactionId}` for individual scored transactions
- New Redis sorted set: `scored-transactions` (scored by timestamp for ordering)
- Store full transaction data + risk score + AI explanation for EVERY transaction
- Keep existing `flagged-transactions` sorted set for high-risk items (riskScore > 0.7)
- Add TTL on scored-tx keys (e.g., 30 days) to prevent unbounded growth

### T4: Add new admin API endpoint for all scored transactions
**File**: `src/anomaly-service/app/main.py`
- `GET /api/admin/transactions` — returns all scored transactions with risk scores
- Support query params: `?sort=riskScore&order=desc&limit=100`
- Response model: list of `ScoredTransaction` (extends existing fields + riskScore + explanation)
- Update `GET /api/admin/stats` to include: totalScored, avgRiskScore, highRiskCount, aiCallsToday

### T5: Update anomaly-service requirements and Dockerfile
**Files**: `src/anomaly-service/requirements.txt`, `src/anomaly-service/Dockerfile`
- Remove: `scikit-learn`, `numpy`
- Add: `agent-framework`, `agent-framework-foundry`
- Keep: `azure-identity`, `redis`, `fastapi`, `structlog`, `opentelemetry-*`
- Remove `azure-ai-inference` if present

### T6: Update K8s deployment for anomaly-service
**File**: `deploy/kustomize/base/anomaly-service.yaml`
- Add `FOUNDRY_PROJECT_ENDPOINT` env var from `banking-secrets.openai-endpoint` (same as chatbot-service)
- Add `FOUNDRY_MODEL` env var (value: `gpt-5.4-mini`)
- Remove any `AZURE_OPENAI_ENDPOINT` references

## Phase 2: Admin UI Enhancement

### T7: Add "All Transactions" tab/view to AdminPage
**File**: `src/ui-app/src/pages/AdminPage.tsx`
- Add tab navigation: "Flagged Transactions" (existing) | "All Transactions" (new)
- "All Transactions" tab shows table with columns: Date, Account, Amount, Type, Risk Score, Description
- Risk score as color-coded MUI Chip (green ≤0.3, yellow ≤0.5, orange ≤0.7, red >0.7)
- Sortable by risk score (default: descending) and all other columns
- Click row to expand → shows AI explanation inline

### T8: Link flagged transactions to full details
**File**: `src/ui-app/src/pages/AdminPage.tsx`
- In flagged transactions table, clicking a row expands to show full AI risk assessment
- Display: AI explanation, risk flags list, transaction metadata
- Keep existing review/clear action buttons

### T9: Update admin stats cards
**File**: `src/ui-app/src/pages/AdminPage.tsx`
- Add "Total Scored" stat card (shows how many transactions have been AI-scored)
- Add "AI Calls Today" stat card (shows Foundry usage)
- Update "Avg Risk Score" to use new endpoint data

## Phase 3: Testing & Deployment

### T10: Update anomaly-service tests
**File**: `src/anomaly-service/tests/`
- Update `test_detection.py` to test Foundry-based risk assessment (mock FoundryChatClient)
- Test risk assessment prompt generates valid JSON
- Test threshold logic: score > 0.7 → flagged, score ≤ 0.7 → scored only
- Test Redis storage of scored and flagged transactions

### T11: Build and deploy
- Build anomaly-service container to ACR
- Build ui-app container to ACR
- Rollout restart both deployments
- Verify: create transaction → check admin page shows risk score → verify flagged if high risk

## Dependencies

```
T1 ──┐
T2 ──┤
T5 ──┴── T3 ── T4 ── T6 ── T11
T7 ── T8 ── T9 ── T11
T10 (parallel with T7-T9)
```

## Risk Mitigation

- **Foundry rate limits**: GPT-5.4-mini has 10 capacity units. At ~1 txn/sec this is fine. Add retry with backoff.
- **Foundry unavailable**: Graceful fallback — assign default risk score (0.5) with explanation "AI scoring unavailable"
- **Redis memory**: TTL on scored-tx keys (30 days) prevents unbounded growth
- **Cost**: GPT-5.4-mini is the cheapest model; each risk assessment is ~200 tokens in + ~100 tokens out
