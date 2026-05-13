# Chatbot Service

AI-powered financial advice chatbot with natural language query capabilities.

## Purpose

Provides conversational AI assistant for banking operations. Users can ask natural language questions about accounts, transactions, budgets, and transfers. Uses Azure AI Agent framework with custom tool integrations for account lookups, transaction queries, and budget insights.

## Technology Stack

- Python 3.11+
- FastAPI
- Azure AI Foundry / Azure AI Agents
- Azure OpenAI
- Azure Cosmos DB (chat history)
- OpenTelemetry
- JWT authentication

## API Endpoints

### Chat
- `POST /api/chat` — Send chat message and receive AI response
- `POST /api/chat/new` — Start new chat session
- `GET /api/chat/history/{user_id}` — Get chat history for user

### Admin
- `GET /api/chat/admin/foundry-status` — Check Azure AI Foundry connection status

### Health
- `GET /health` — Health check
- `GET /healthz` — Health check (Kubernetes-style)
- `GET /readyz` — Readiness check

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `FOUNDRY_PROJECT_ENDPOINT` / `AZURE_AI_AGENTS_ENDPOINT` | Azure AI Foundry/Agents endpoint | Yes |
| `FOUNDRY_MODEL` / `AZURE_OPENAI_MODEL` | AI model name | Yes |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint (fallback) | No |
| `BUDGET_SERVICE_URL` | Budget service base URL | Yes |
| `TRANSACTION_SERVICE_URL` | Transaction service base URL | Yes |
| `ACCOUNT_SERVICE_URL` | Account service base URL | Yes |
| `COSMOS_DB_ENDPOINT` | Cosmos DB endpoint for chat history | Yes |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry collector endpoint | No |
| `AZURE_TENANT_ID` | Azure Entra tenant ID for auth | Yes |
| `AZURE_CLIENT_ID` | Azure Entra client ID for auth | Yes |

## Local Development

### Prerequisites
- Python 3.11+
- Azure AI Foundry project or Azure AI Agents instance
- Azure Cosmos DB for chat history
- Running instances of account-service, transaction-service, budget-service

### Run Locally

```bash
cd src/chatbot-service
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Service will start on `http://localhost:8001`.

### Docker

```bash
docker build -t chatbot-service .
docker run -p 8001:8001 --env-file .env chatbot-service
```

## Testing

```bash
cd src/chatbot-service
pytest
```

## Agent Tools

The chatbot has access to these custom tools:

- **get_account_balance**: Retrieve account balance
- **get_transactions**: Fetch recent transactions
- **get_budget_insights**: Get spending analysis
- **transfer_funds**: Initiate transfers (with user confirmation)

## Example Queries

- "What's my account balance?"
- "Show me my last 5 transactions"
- "How much did I spend on dining last month?"
- "Transfer $100 from checking to savings"
- "Give me budget recommendations"

## Notes

- All endpoints require JWT authentication
- Chat sessions persist in Cosmos DB for history
- Agent uses function calling to interact with backend services
- OpenTelemetry traces all AI agent interactions
- Responses include conversational explanations of financial data
- Tool calls are logged and auditable
