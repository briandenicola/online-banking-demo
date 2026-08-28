# Chatbot Service

AI-powered financial advice chatbot with natural language query capabilities.

## Purpose

Provides conversational AI assistant for banking operations. Users can ask natural language questions about accounts, transactions, budgets, and transfers. Uses Azure AI Agent framework with custom tool integrations for account lookups, transaction queries, and budget insights.

## Technology Stack

- Python 3.11+
- FastAPI
- Azure AI Foundry / Azure AI Agents
- Azure OpenAI
- Azure Cosmos DB (chat history and optional agent memory)
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
| `CHAT_MEMORY_ENABLED` | Enables Agent Memory Toolkit retrieval and derived memory writes | No, default `false` |
| `CHAT_MEMORY_REQUIRED` | Fail startup if memory cannot initialize when enabled | No, default `false` |
| `CHAT_MEMORY_DATABASE` | Cosmos DB database for agent memory | No, default `BankingDemo` |
| `CHAT_MEMORY_CONTAINER` | Toolkit memories container for facts/procedural/episodic records | No, default `AgentMemories` |
| `CHAT_MEMORY_TURNS_CONTAINER` | Toolkit turns container | No, default `AgentMemoryTurns` |
| `CHAT_MEMORY_SUMMARIES_CONTAINER` | Toolkit summaries container | No, default `AgentMemorySummaries` |
| `CHAT_MEMORY_COUNTER_CONTAINER` | Toolkit processing cadence counter container | No, default `AgentMemoryCounters` |
| `CHAT_MEMORY_LEASE_CONTAINER` | Toolkit lease container for change-feed/processing support | No, default `AgentMemoryLeases` |
| `CHAT_MEMORY_MAX_CONTEXT_TURNS` | Recent turns to inject into a chat prompt | No, default `8` |
| `CHAT_MEMORY_MAX_FACTS` | Relevant derived memories to inject into a chat prompt | No, default `5` |
| `CHAT_MEMORY_MAX_PROMPT_CHARS` | Max characters of memory context injected into the prompt | No, default `4000` |
| `CHAT_MEMORY_MIN_CONFIDENCE` | Minimum toolkit confidence for retrieved facts | No, default `0.7` |
| `CHAT_MEMORY_PROCESS_EVERY_N_TURNS` | In-process derived memory cadence; `0` disables processing | No, default `2` |
| `CHAT_MEMORY_RECONCILE_EVERY_N_TURNS` | Contradiction reconciliation cadence; `0` disables reconciliation | No, default `8` |
| `CHAT_MEMORY_EMBEDDING_DEPLOYMENT` | Foundry embedding deployment used by toolkit semantic search | No, default `text-embedding-ada-002` |
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

### Agent Memory Toolkit MVP

Memory is disabled by default. To roll out the MVP, keep `CHAT_MEMORY_REQUIRED=false`, provision or point at a Foundry embedding deployment, then use the deployment tasks:

```bash
task local:memory:enable
task cloud:memory:enable
```

Use `task local:memory:disable` or `task cloud:memory:disable` to roll back without changing the rest of the application. See [Azure Deployment](../../docs/deployment-azure.md#chatbot-agent-memory-mvp) for the rollout checklist and [MVP vs. Production Quality Gaps](../../docs/deployment-azure.md#mvp-vs-production-quality-gaps) before promoting this beyond a demo.

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
- Agent Memory Toolkit integration is feature-flagged with `CHAT_MEMORY_ENABLED`
- When enabled, the toolkit creates `AgentMemoryTurns`, `AgentMemories`, `AgentMemorySummaries`, `AgentMemoryCounters`, and `AgentMemoryLeases` with its required policies
- Memory context is retrieved only for the authenticated JWT user and injected as untrusted background context
- The service redacts common sensitive values before writing turns to agent memory
- Agent uses function calling to interact with backend services
- OpenTelemetry traces all AI agent interactions
- Responses include conversational explanations of financial data
- Tool calls are logged and auditable
