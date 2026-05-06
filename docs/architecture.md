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
   └─> User Service validates credentials
   
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
User calls /api/transfers/execute

Transfer Service:
  ├─ Validates request (JWT token)
  ├─ Calls Account Service (get details, lock)
  ├─ Calls Transaction Service (record)
  ├─ Publishes event to banking-events stream
  │   {"event_type": "transfer.completed", ...}
  └─ Returns transfer ID and status

Event Processor (subscribes to banking-events):
  ├─ Routes to audit logger, anomaly detector
  └─ Updates consumer group offset

Anomaly Service:
  ├─ Analyzes transaction patterns
  ├─ Publishes anomaly.detected if suspicious
  └─ Returns risk score

Budget Service:
  ├─ Categorizes spending
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

- 4 .NET services (user, account, transaction, transfer)
- 3 Python services (chatbot, anomaly, budget)
- 1 Go service (event-processor)
- 1 React UI
- 1 NGINX gateway
- 1 Redis instance

**Network**: Docker bridge network (compose auto-networking)
**Storage**: Redis persistence to `redis-data` volume
**Ports**: All services exposed on localhost

### Cloud Deployment (Azure AKS)

```
Azure Resource Group
├─ AKS Cluster (Kubernetes)
│  ├─ Namespace: banking-demo
│  ├─ Deployments (2 replicas each)
│  ├─ Services (ClusterIP, LoadBalancer)
│  ├─ ConfigMaps & Secrets (banking-secrets)
│
├─ Cosmos DB (managed database)
├─ Azure Cache for Redis (managed Redis)
├─ Container Registry (ghcr.io)
├─ Azure OpenAI (AI endpoint)
├─ Application Insights (logging)
├─ Key Vault (secrets)
└─ Log Analytics Workspace (diagnostics)
```

**GitOps**: Flux CD watches GitHub repo (`deploy/flux/` and `deploy/kustomize/`)

## Scaling Considerations

### Horizontal Scaling

- **Stateless services**: Scale replicas in K8s based on CPU/memory metrics
- **Redis**: Switch to Azure Cache for Redis in production
- **Database**: Cosmos DB handles scaling automatically

### Optimization

1. **API Gateway** - NGINX can handle ~1000 req/s; use K8s HPA to scale
2. **Transaction Service** - Cache frequently accessed transactions in Redis
3. **Event Processing** - Use consumer groups for parallel processing
4. **Authentication** - Cache JWT validation results in-memory

## Security Architecture

### Network Security

- **Services isolated** within K8s network namespace in production
- **NGINX Gateway** validates all external requests
- **Service-to-service** calls use internal service names

### Data Security

- **In-transit**: TLS/SSL for all external communication
- **At-rest**: Cosmos DB encryption, Redis TLS in production
- **Secrets**: K8s Secrets (backed by Azure Key Vault in production)

### Identity & Access

- **JWT tokens** for API authentication
- **Service accounts** for pod-to-pod communication
- **RBAC**: Namespace isolation (banking-demo separate from system)

## Monitoring & Observability

### Logging

- **Application Insights**: Instrumented via `APPLICATIONINSIGHTS_CONNECTION_STRING`
- **Local dev**: Logs to stdout/stderr (captured by Docker)

### Metrics

- **Request metrics**: Count, latency, error rate per endpoint
- **System metrics**: CPU, memory, disk I/O
- **Business metrics**: Transaction volume, anomaly rate

### Tracing

- **Distributed tracing**: Trace IDs across service calls
- **Service dependency map**: Generated from trace data
- **Error tracking**: Exceptions logged with full context

## Resilience Patterns

### Retry Logic

- **Transient failures**: Exponential backoff (2s, 4s, 8s, etc.)
- **Circuit breaker**: Break circuit after 5 failures in 30s

### Fallback

- **Account Service unavailable**: Return HTTP 503
- **Redis unavailable**: Continue but disable event publishing

### Health Checks

- **Liveness probe**: Kubernetes restarts unhealthy pods
- **Readiness probe**: Removes unhealthy pods from load balancer
- **Startup probe**: Grace period for initialization (30s)

---

**Last Updated**: May 2024  
**Architecture Version**: 2.0
