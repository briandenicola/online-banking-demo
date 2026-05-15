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

### Eval Debug Pod (AKS)

A dedicated `eval-debug` Deployment runs in `banking-demo` with the
`ai-service` Python code, the Azure CLI, and network diagnostic tools
(`curl`, `jq`, `dig`, `openssl`, `ping`). It uses the same workload
identity as the rest of the services so token acquisition works against
the Foundry project endpoint from inside the Managed VNet.

The REPL imports the **same** judge helpers (`_build_judge_instructions`,
`_build_judge_user_prompt`, `_parse_judge_scores`) that production
`/api/admin/evaluate` uses, so debugger output is faithful to prod
behavior. See [ADR-006](../../docs/adr/006-llm-as-judge-evaluation.md)
for the LLM-as-judge architecture.

Build + deploy:

```bash
task cloud:build:eval-debug
task cloud:deploy
kubectl rollout status -n banking-demo deploy/eval-debug
```

Exec in:

```bash
kubectl exec -it -n banking-demo deploy/eval-debug -- bash
# or jump straight into the REPL:
kubectl exec -it -n banking-demo deploy/eval-debug -- python -m app.eval_debug
```

#### REPL commands

| Command | What it does |
|---|---|
| `show` | Print current endpoint, model, prompt, transaction, evaluators, timeouts |
| `prompt` / `tx` / `evals` / `name` | Edit the corresponding field |
| `timeouts` | Inspect or update eval / agent timeouts |
| `payload` | Dump the exact JSONL payload that would be sent to Foundry |
| `run` | Execute one Foundry eval and dump the **live** run state from the control plane (status, error, result_counts, per_testing_criteria_results) |
| `list-evals` | List recent evals from the project endpoint |
| `list-runs [eval_id]` | List runs for an eval (default: last eval from this session) |
| `eval [eval_id]` | Dump raw eval definition |
| `inspect [eval_id run_id]` | Dump raw run + output_items |
| `watch [eval_id run_id]` | Poll a run continuously, log every status change with timestamps |
| `last` | Print the last `eval_id` / `run_id` captured this session |
| `help` / `quit` | Self-explanatory |

`run` always captures the run on timeout — the SDK gives up after
~180s by default, but the run usually keeps going server-side. Use
`watch` (or `inspect`) to follow it.

One-shot mode for CI/iteration:

```bash
kubectl exec -it -n banking-demo deploy/eval-debug -- \
  python -m app.eval_debug --once \
  --agent-run-timeout-seconds 45 \
  --eval-timeout-seconds 120 \
  --hard-timeout-seconds 180
```

#### Hitting Foundry directly with `az`

The pod has the workload identity client ID in `AGENT_ID_AGENT_IDENTITY`
and the federated token mounted at `AZURE_FEDERATED_TOKEN_FILE`. To
log in and call the Foundry control plane:

```bash
# Inside the pod
az login --federated-token "$(cat $AZURE_FEDERATED_TOKEN_FILE)" \
         --service-principal -u "$AZURE_CLIENT_ID" -t "$AZURE_TENANT_ID"

# What does Foundry think this principal can do?
az cognitiveservices account show \
  --name <foundry-account-name> --resource-group <rg-name>

# Read the project's eval list via the OpenAI-compatible REST shim
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
curl -sS -H "Authorization: Bearer $TOKEN" \
  "${FOUNDRY_PROJECT_ENDPOINT}/openai/v1/evals?limit=5" | jq

# Drill into a specific run
curl -sS -H "Authorization: Bearer $TOKEN" \
  "${FOUNDRY_PROJECT_ENDPOINT}/openai/v1/evals/<eval_id>/runs/<run_id>" | jq
```

> **Historical note (issue #145):** the `list-evals` / `inspect` /
> `watch` REPL commands and the `az` recipes above were added to
> diagnose Foundry's hosted `raisvc` evaluation backend, which is
> non-functional inside Managed VNets due to a service-side bug
> writing inline JSONL datasets to private-endpoint-only blob
> storage. Production evaluations no longer depend on `raisvc` —
> they use the LLM-as-judge path described in
> [ADR-006](../../docs/adr/006-llm-as-judge-evaluation.md). The
> Foundry control-plane tooling is retained because it is still
> useful when debugging unrelated Foundry issues (RBAC, capability
> hosts, agent definitions, model deployments).

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
