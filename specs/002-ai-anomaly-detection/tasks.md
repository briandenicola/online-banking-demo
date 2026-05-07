# 002: AI-Powered Anomaly Detection — Tasks

## Phase 1: Anomaly Service Backend Rework

- [ ] T1 Replace IsolationForest with FoundryChatClient — remove sklearn/numpy, add agent-framework-foundry, init FoundryChatClient with FOUNDRY_PROJECT_ENDPOINT, create assess_transaction_risk() that calls GPT-5.4-mini and returns structured JSON {riskScore, explanation, flags}
- [ ] T2 Define risk assessment prompt template — financial security expert persona, include transaction amount/type/description/category, request JSON structured output, add few-shot examples of low-risk vs high-risk patterns
- [ ] T3 Store ALL scored transactions in Redis — new key pattern scored-tx:{id} with TTL 30d, new sorted set scored-transactions by timestamp, keep existing flagged-transactions set for riskScore > 0.7
- [ ] T4 Add GET /api/admin/transactions endpoint — returns all scored transactions with risk scores, support sort/order/limit query params, update GET /api/admin/stats to include totalScored and aiCallsToday
- [ ] T5 Update requirements.txt and Dockerfile — remove scikit-learn/numpy/azure-ai-inference, add agent-framework + agent-framework-foundry
- [ ] T6 Update anomaly-service K8s deployment — add FOUNDRY_PROJECT_ENDPOINT from banking-secrets.openai-endpoint, add FOUNDRY_MODEL=gpt-5.4-mini, remove AZURE_OPENAI_ENDPOINT refs

## Phase 2: Admin UI Enhancement

- [ ] T7 Add "All Transactions" tab to AdminPage — tab nav between Flagged and All, table with Date/Account/Amount/Type/Risk Score/Description, color-coded risk Chip (green≤0.3, yellow≤0.5, orange≤0.7, red>0.7), sortable by risk score descending
- [ ] T8 Link flagged transactions to full AI details — expand row shows AI explanation, risk flags list, full transaction metadata, keep existing review/clear buttons
- [ ] T9 Update admin stats cards — add Total Scored and AI Calls Today cards, update Avg Risk Score from new endpoint

## Phase 3: Testing & Deployment

- [ ] T10 Update anomaly-service tests — mock FoundryChatClient, test risk prompt JSON output, test threshold flagging logic, test Redis scored/flagged storage
- [ ] T11 Build and deploy — ACR build anomaly-service + ui-app, rollout restart, smoke test: create transaction → verify risk score appears in admin
