# AI Service

AI-powered transaction anomaly detection and risk scoring service.

## Purpose

Provides real-time anomaly detection for transactions using AI/ML models. Scores transactions for fraud risk, maintains flagged transaction history, and offers admin evaluation/prompt management tools. Uses Azure AI Foundry for inference and Redis for result caching.

## Technology Stack

- Python 3.11+
- FastAPI
- Azure AI Foundry
- Azure OpenAI
- Azure Cosmos DB
- Redis (for caching and DLQ)
- OpenTelemetry
- JWT authentication

## API Endpoints

### Detection
- `POST /detect` — Detect anomalies in transaction (returns risk score and explanation)

### Health
- `GET /health` — Health check
- `GET /healthz` — Health check (Kubernetes-style)
- `GET /readyz` — Readiness check

### Admin Operations
- `GET /api/admin/foundry-status` — Check Azure AI Foundry connection status
- `GET /api/admin/stats` — Get anomaly detection statistics
- `GET /api/admin/transactions` — List all scored transactions
- `GET /api/admin/flagged-transactions` — List flagged transactions (high-risk)
- `GET /api/admin/flagged-transactions/{tx_id}` — Get flagged transaction details
- `GET /api/admin/scored-transactions/{tx_id}` — Get scored transaction details
- `POST /api/admin/scored-transactions/{tx_id}/rescore` — Re-run anomaly detection
- `PUT /api/admin/flagged-transactions/{tx_id}/review` — Review and update flagged transaction
- `GET /api/admin/prompts` — List prompt templates
- `POST /api/admin/evaluate` — Run evaluation on prompt templates

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `REDIS_CONNECTION_STRING` | Redis connection string | Yes |
| `AZURE_CLIENT_ID` | Azure Entra client ID for auth | Yes |
| `DLQ_MAX_RETRIES` | Dead letter queue retry limit | `3` |
| `FOUNDRY_PROJECT_ENDPOINT` | Azure AI Foundry project endpoint | Yes |
| `FOUNDRY_MODEL` | Azure AI model name | Yes |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint (fallback) | No |
| `USER_SERVICE_URL` | User service base URL | Yes |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry collector endpoint | No |

## Local Development

### Prerequisites
- Python 3.11+
- Azure AI Foundry project or Azure OpenAI instance
- Redis instance
- Azure Cosmos DB (for prompt/eval storage)

### Run Locally

```bash
cd src/ai-service
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

Service will start on `http://localhost:8002`.

### Docker

```bash
docker build -t ai-service .
docker run -p 8002:8002 --env-file .env ai-service
```

## Testing

```bash
cd src/ai-service
pytest
```

## Detection Algorithm

1. Transaction received at `/detect` endpoint
2. Redis cache checked for recent score
3. If cache miss, AI model analyzes transaction features:
   - Amount relative to account history
   - Transaction type and category risk
   - Description keywords
   - Velocity patterns
4. AI returns risk score (0-100) and explanation
5. Results cached in Redis (TTL: 5 minutes)
6. High-risk scores (>70) automatically flagged for review

## Notes

- `/detect` endpoint does not require authentication (called by internal services)
- Admin endpoints require JWT with admin role
- Redis used for caching scores and DLQ for failed detections
- Cosmos DB stores flagged transactions and prompt templates
- OpenTelemetry traces all AI inference calls
- Evaluation framework supports A/B testing of prompts
