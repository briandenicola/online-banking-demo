# System Architecture

## Overview

The Online Banking Demo is a microservices-based banking platform built on .NET, Python, and Go, designed to showcase modern cloud-native patterns with agentic AI capabilities. The system follows a distributed architecture with clear separation of concerns, event-driven communication, and cloud-optimized deployment strategies.

## Service Map

### Core .NET Microservices

| Service | Port | Responsibility | Communication | Dependencies |
|---------|------|-----------------|----------------|--------------|
| **User Service** | 6001 | Authentication (JWT tokens), user registration, profile management | REST/HTTP | Redis (health check) |
| **Account Service** | 6002 | Account lifecycle management, balance tracking | REST/HTTP | Redis (health check) |
| **Transaction Service** | 6003 | Transaction history, query, logging | REST/HTTP | Redis (event streaming), Account Service |
| **Transfer Service** | 6004 | Money transfer orchestration, cross-account operations | REST/HTTP | Account Service, Transaction Service, Redis |

### Python Agent Services

| Service | Port | Responsibility | Communication | Dependencies |
|---------|------|-----------------|----------------|--------------|
| **Chatbot Service** | 8001 | AI financial assistant, natural language queries, financial advice | REST/HTTP (FastAPI) | Azure OpenAI API, User Service |
| **Anomaly Service** | 8002 | Real-time fraud detection, transaction anomalies, risk scoring | REST/HTTP (FastAPI) | Azure OpenAI Endpoint, Redis (event streaming) |
| **Budget Service** | 8003 | Budget analysis, spending insights, financial health scoring | REST/HTTP (FastAPI) | Transaction Service, Azure OpenAI Endpoint |

### Infrastructure Services

| Service | Port | Responsibility | Communication | Usage |
|---------|------|-----------------|----------------|-------|
| **Event Processor** | - | Redis Streams consumer, audit routing, event fan-out | Redis Streams, gRPC | Subscribes to banking-events stream |
| **API Gateway (NGINX)** | 80 | Request routing, load balancing, protocol translation | HTTP, REST proxy | Routes all external requests to services |
| **UI Application** | 3000 | React frontend, user interface, API client | HTTP, REST | Consumes gateway (port 80) |
| **Redis** | 6380 | Cache, session store, event streaming (Redis Streams) | Redis protocol | Shared by Transaction, Transfer, Anomaly services |

## Communication Patterns

### Synchronous (Request-Response)

- **External clients** → API Gateway (port 80) → Service via nginx routing
- **Frontend** → API Gateway → Services
- **Service-to-service**: Direct internal HTTP calls (e.g., Transfer → Account, Transfer → Transaction)
- **Swagger documentation**: Accessible through gateway at `/api/{service}/swagger/index.html`

### Asynchronous (Event-Driven)

- **Redis Streams**: Primary event bus using `banking-events` stream
- **Event publishers**: Transaction Service, Transfer Service, Anomaly Service publish events
- **Event Processor**: Go service that consumes events via consumer groups and routes to downstream processors
- **Consumer groups**: Multiple consumer group patterns for different event handling strategies

## Authentication & Authorization

### JWT Token Flow

```
1. User POST /api/auth/login (email + password)
   └─> User Service validates credentials against in-memory store
   
2. User Service returns JWT token:
   - Issuer: "user-service"
   - Key: Environment variable (Jwt__Key)
   - Contains: user_id, email, roles
   
3. Client includes Bearer token in Authorization header:
   Authorization: Bearer <JWT_TOKEN>
   
4. API Gateway passes Authorization header to services
   
5. Each service validates JWT signature using shared key
```

### Protected Endpoints

- `/api/users/*` - User management (requires login)
- `/api/accounts/*` - Account operations (requires login)
- `/api/transactions/*` - Transaction queries (requires login)
- `/api/transfers/*` - Transfer operations (requires login)
- `/api/chat/*` - Chatbot queries (requires login)

## Data Flow & Event Pipeline

### Transaction Flow Example

```
User calls /api/transfers/execute with from_account, to_account, amount

Transfer Service:
  ├─ Validates request (requires JWT token)
  ├─ Calls Account Service (get_account_details, lock for transfer)
  ├─ Calls Transaction Service (record_transaction)
  ├─ Publishes event to banking-events Redis Stream:
  │   {
  │     "event_type": "transfer.completed",
  │     "from_account_id": "...",
  │     "to_account_id": "...",
  │     "amount": 150.00,
  │     "timestamp": "2024-01-15T10:30:00Z"
  │   }
  └─ Returns transfer ID and status

Event Processor (subscribes to banking-events):
  ├─ Receives transfer.completed event
  ├─ Routes to:
  │   ├─ Audit logger (for compliance)
  │   ├─ Anomaly detection consumer (fraud check)
  │   └─ Budget tracker (for spending categorization)
  └─ Updates consumer group offset

Anomaly Service (if subscribed):
  ├─ Receives event
  ├─ Analyzes: velocity, patterns, merchant risk
  ├─ If anomalous: publishes to anomaly.detected event
  └─ Returns risk score

Budget Service (if subscribed):
  ├─ Receives event
  ├─ Categorizes transaction
  ├─ Updates budget tracking
  └─ Scores financial health
```

### Event Types (banking-events stream)

- **transfer.initiated** - Transfer request received
- **transfer.completed** - Transfer successfully executed
- **transaction.recorded** - Transaction logged in ledger
- **account.locked** - Account locked for processing
- **account.unlocked** - Account released
- **anomaly.detected** - Suspicious activity flagged
- **budget.updated** - Budget changed

## Deployment Architecture

### Local Development (Docker Compose)

```
docker-compose.yml defines:
  - 4 .NET services (user, account, transaction, transfer)
  - 3 Python services (chatbot, anomaly, budget)
  - 1 Go service (event-processor)
  - 1 React UI
  - 1 NGINX gateway
  - 1 Redis instance
```

**Network**: Docker bridge network (compose auto-networking)
**Storage**: Redis persistence to `redis-data` volume
**Ports**: All services exposed on localhost

### Cloud Deployment (Azure AKS)

```
Azure Resource Group
├─ AKS Cluster (Kubernetes)
│  ├─ Namespace: banking-demo
│  ├─ Deployments (2 replicas each):
│  │  ├─ user-service
│  │  ├─ account-service
│  │  ├─ transaction-service
│  │  ├─ transfer-service
│  │  ├─ chatbot-service
│  │  ├─ anomaly-service
│  │  └─ budget-service
│  ├─ Services (ClusterIP, LoadBalancer for gateway)
│  ├─ ConfigMaps (app configuration)
│  └─ Secrets (banking-secrets: DB, API keys)
│
├─ Cosmos DB (managed database)
│  └─ Connection string in banking-secrets K8s Secret
│
├─ Azure Cache for Redis (managed Redis)
│  └─ Used for distributed sessions and event streaming
│
├─ Container Registry (ghcr.io)
│  └─ Hosts all service images: ghcr.io/banking-demo/{service}:latest
│
├─ Azure OpenAI (AI endpoint)
│  └─ Used by chatbot, anomaly, budget services
│
├─ Application Insights
│  └─ Centralized logging, metrics, tracing
│
├─ Key Vault
│  └─ Centralized secrets management
│
└─ Log Analytics Workspace
   └─ Application logs and diagnostics
```

**GitOps**: Flux CD watches GitHub repo (`deploy/flux/` and `deploy/kustomize/`)

## Scaling Considerations

### Horizontal Scaling

- **Stateless services** (.NET & Python services): Scale replicas in K8s based on CPU/memory metrics
- **Redis**: Switch to Azure Cache for Redis (managed) in production
- **Database**: Cosmos DB handles scaling automatically

### Bottlenecks & Optimization

1. **API Gateway** - NGINX can handle ~1000 req/s on single instance; use K8s HPA to scale ingress controller
2. **Transaction Service** - Heavy read/write; cache frequently accessed transactions in Redis
3. **Event Processing** - Redis Streams can handle millions of events/sec; use consumer groups for parallel processing
4. **Authentication** - Cache JWT validation results in-memory to reduce User Service calls

## Security Architecture

### Network Security

- **Services isolated** within K8s network namespace in production
- **NGINX Gateway** validates all external requests
- **Service-to-service** calls use internal service names (no external exposure)

### Data Security

- **In-transit**: TLS/SSL for all external communication (enforced by HTTPS ingress)
- **At-rest**: Cosmos DB encryption, Redis TLS in production
- **Secrets**: K8s Secrets (backed by Azure Key Vault in production)

### Identity & Access

- **JWT tokens** for API authentication (bearer tokens)
- **Service accounts** for pod-to-pod communication (K8s service account tokens)
- **RBAC**: Namespace isolation (banking-demo namespace separate from system namespaces)

## Monitoring & Observability

### Logging

- **Application Insights**: Instrumented via `APPLICATIONINSIGHTS_CONNECTION_STRING`
- **Log destination**: Application Insights workspace (trace, dependency tracking)
- **Local dev**: Logs to stdout/stderr (captured by Docker)

### Metrics

- **Request metrics**: Request count, latency, error rate per endpoint
- **System metrics**: CPU, memory, disk I/O
- **Business metrics**: Transaction volume, anomaly detection rate, user activity

### Tracing

- **Distributed tracing**: Trace IDs propagated across service calls via X-Trace-Id header
- **Service dependency map**: Automatically generated from trace data
- **Error tracking**: Exceptions logged with full context

## Resilience Patterns

### Retry Logic

- **Transient failures**: Services implement exponential backoff (2s, 4s, 8s, etc.)
- **Circuit breaker**: Transfer Service breaks circuit to Account Service if >5 failures in 30s

### Fallback

- **Account Service unavailable**: Transfer Service returns HTTP 503 (Service Unavailable)
- **Redis unavailable**: Transaction Service continues but disables event publishing

### Health Checks

- **Liveness probe**: Kubernetes restarts unhealthy pods
- **Readiness probe**: Kubernetes removes unhealthy pods from load balancer
- **Startup probe**: Grace period for services to initialize (30s)

---

**Last Updated**: May 2024  
**Architecture Version**: 2.0