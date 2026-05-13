# Budget Service

Budget insights and transaction categorization service.

## Purpose

Provides spending insights, budget analysis, and AI-powered transaction categorization for users. Uses Azure OpenAI embeddings and LLM inference to categorize transactions and generate personalized budget recommendations.

## Technology Stack

- Python 3.11+
- FastAPI
- Azure OpenAI
- OpenTelemetry

## API Endpoints

### Budget & Insights
- `GET /insights/{userId}` — Get spending insights and budget analysis for user
- `POST /categorize` — Categorize transaction by description (query param or JSON body)

### Health
- `GET /health` — Health check
- `GET /healthz` — Health check (Kubernetes-style)
- `GET /readyz` — Readiness check

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | Yes |
| `AZURE_OPENAI_EMBEDDING_MODEL` | Embedding model name | `text-embedding-ada-002` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry collector endpoint | No |

## Local Development

### Prerequisites
- Python 3.11+
- Azure OpenAI instance with embeddings deployment

### Run Locally

```bash
cd src/budget-service
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

Service will start on `http://localhost:8003`.

### Docker

```bash
docker build -t budget-service .
docker run -p 8003:8003 --env-file .env budget-service
```

## Testing

```bash
cd src/budget-service
pytest
```

## Features

- **Transaction Categorization**: Uses AI to categorize transactions into standard categories (Groceries, Dining, Entertainment, etc.)
- **Spending Insights**: Analyzes user transaction history to identify spending patterns
- **Budget Recommendations**: Provides personalized budget suggestions based on spending behavior
- **Embedding-based Matching**: Uses OpenAI embeddings for semantic transaction categorization

## Notes

- Endpoints do not require authentication (called by internal services and chatbot)
- Azure OpenAI used for all inference and embeddings
- OpenTelemetry traces all AI operations
- Category predictions cached for performance
- Supports both query parameter and JSON body for categorization
