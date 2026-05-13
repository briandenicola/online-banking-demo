# Account Opening Service

Account opening workflow service with document processing and AI-powered review.

## Purpose

Manages the complete account opening lifecycle: application submission, identity document upload, AI-assisted review, and background account provisioning. Uses Azure AI Foundry for document analysis and agent-based provisioning.

## Technology Stack

- Python 3.11+
- FastAPI
- Azure AI Foundry
- Azure Cosmos DB
- Azure Blob Storage
- Redis (for distributed caching)
- OpenTelemetry
- JWT authentication
- Background worker (Celery-style)

## API Endpoints

### Account Opening
- `POST /api/account-opening/applications` — Submit new account application
- `POST /api/account-opening/applications/{application_id}/documents` — Upload identity documents
- `GET /api/account-opening/applications/{application_id}` — Get application status
- `GET /api/account-opening/applications` — List user's applications
- `PATCH /api/account-opening/applications/{application_id}/review` — Review/approve application (admin)

### Health
- `GET /health` — Health check
- `GET /healthz` — Health check (Kubernetes-style)
- `GET /readyz` — Readiness check

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `FOUNDRY_PROJECT_ENDPOINT` | Azure AI Foundry project endpoint | Yes |
| `FOUNDRY_MODEL` | Azure AI model name | Yes |
| `CUS_ENDPOINT` | Custom understanding service endpoint | No |
| `COSMOS_DB_ENDPOINT` | Cosmos DB endpoint | Yes |
| `AZURE_STORAGE_ACCOUNT_NAME` | Blob storage account for documents | Yes |
| `REDIS_CONNECTION_STRING` | Redis connection string | Yes |
| `JWT_KEY` | JWT signing key (must match user-service) | Yes |
| `JWT_ISSUER` | JWT issuer | `user-service` |
| `JWT_AUDIENCE` | JWT audience | `banking-demo` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry collector endpoint | No |
| `DLQ_MAX_RETRIES` | Dead letter queue retry limit | `3` |

## Local Development

### Prerequisites
- Python 3.11+
- Azure AI Foundry project
- Azure Cosmos DB instance
- Azure Blob Storage account
- Redis instance

### Run Locally

```bash
cd src/account-opening-service
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload
```

Service will start on `http://localhost:8004`.

### Run Worker

The background provisioning worker must run separately:

```bash
python -m app.worker
```

### Docker

```bash
docker build -t account-opening-service .
docker run -p 8004:8004 --env-file .env account-opening-service
```

## Testing

```bash
cd src/account-opening-service
pytest
```

## Workflow

1. User submits application via `POST /applications`
2. User uploads ID documents via `POST /applications/{id}/documents`
3. AI agent extracts and validates document info
4. Admin reviews and approves via `PATCH /applications/{id}/review`
5. Background worker provisions account in account-service
6. Application status updated to `provisioned`

## Notes

- All endpoints require JWT authentication
- Document storage uses Azure Blob Storage with secure signed URLs
- AI Foundry integration provides document OCR and validation
- Background provisioning uses agent-based workflow
- Redis used for task queue and caching
- OpenTelemetry traces all operations
