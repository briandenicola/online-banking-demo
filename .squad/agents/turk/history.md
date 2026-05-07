# Turk — History

## Project Context
- **Project:** online-banking-demo
- **User:** Brian
- **Stack:** C#/.NET (user-service, account-service, transaction-service, transfer-service), Python/FastAPI (anomaly-service, budget-service, chatbot-service), Go (event-processor), React/TypeScript (ui-app), Redis, Docker Compose, Azure AKS
- **Joined:** 2026-05-07
- **Focus:** Python service config fixes and cross-service consistency

## Learnings
- Azure Managed Redis (Balanced B0) uses port 10000 with TLS, not standard 6379
- Redis auth is dual-mode: AZURE_CLIENT_ID presence triggers Entra ID token auth (cloud/AKS), absence uses connection string password (local docker-compose)
- Go event-processor (src/event-processor/main.go) has the reference implementation for dual-mode Redis connection parsing
- .NET services use REDIS__CONNECTIONSTRING env var with format: host:10000,ssl=True,abortConnect=False
- Python services need to parse this .NET-style connection string into host/port/ssl components
- ConfigMap is at deploy/kustomize/base/configmap.yaml
- Brian's directive: all fixes must maintain docker-compose local development compatibility
