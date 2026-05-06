# Local Development Deployment Guide

## Prerequisites

Before you begin, ensure you have the following tools installed on your machine:

### Required Software

- **Docker**: Version 20.10+ ([download](https://www.docker.com/products/docker-desktop))
- **Docker Compose**: Version 2.0+ (included with Docker Desktop)
- **Git**: For cloning and managing the repository
- **Node.js**: Version 18+ (for UI development in watch mode)
- **npm**: Version 8+ (comes with Node.js)

### System Requirements

- **RAM**: Minimum 8GB recommended (Docker containers require ~4-6GB)
- **Disk Space**: Minimum 10GB free space (for Docker images and volumes)
- **Internet Connection**: Required for downloading Docker images and dependencies

### Verification

```bash
# Verify Docker and Docker Compose
docker --version
# Output: Docker version 20.10+

docker-compose --version
# Output: Docker Compose version 2.0+

# Verify Git
git --version
# Output: git version 2.30+

# Verify Node.js (optional, for UI development)
node --version
# Output: v18.0.0+
npm --version
# Output: 8.0.0+
```

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/briandenicola/online-banking-demo.git
cd online-banking-demo
```

### 2. Start All Services

```bash
# Start all services in background mode with fresh builds
docker-compose up -d --build

# Or, to view logs in real-time (Ctrl+C to stop viewing, services keep running)
docker-compose up --build
```

This command will:
- Build Docker images for all services
- Create a shared network for inter-service communication
- Start all 9 services and dependencies
- Initialize Redis with persistence
- Set up health checks for startup verification

### 3. Verify Services Are Running

```bash
# Check service status
docker-compose ps

# Expected output (all services RUNNING):
# NAME                      STATUS
# banking-ui-app           Up 2 minutes
# banking-gateway          Up 2 minutes
# banking-user-service     Up 2 minutes (healthy)
# banking-account-service  Up 2 minutes (healthy)
# banking-transaction-service Up 2 minutes (healthy)
# banking-transfer-service Up 2 minutes (healthy)
# banking-chatbot-service  Up 2 minutes
# banking-anomaly-service  Up 2 minutes
# banking-budget-service   Up 2 minutes
# banking-event-processor  Up 2 minutes
# banking-redis            Up 2 minutes (healthy)

# View full logs for debugging
docker-compose logs -f

# View logs for a specific service
docker-compose logs -f user-service
```

### 4. Access the Application

Once all services are running:

- **UI Application**: http://localhost:3000/
- **API Gateway**: http://localhost/
- **API Documentation**: http://localhost/ (landing page with Swagger links)

### 5. Seed Demo Data (Optional)

Populate the system with demo users, accounts, and transactions:

```bash
# From the repository root
chmod +x scripts/seed-data.sh
./scripts/seed-data.sh

# Expected output:
# ℹ Starting seed data population...
# ✔ Registered user: john_doe (john@example.com)
# ✔ Registered user: jane_smith (jane@example.com)
# ✔ Created checking account for john_doe: $5,000.00
# ✔ Created savings account for jane_smith: $10,000.00
# ... (more demo data created)
# ✔ Seed data population completed successfully!
```

**Demo Credentials** (after seeding):
- **Email**: `demo@banking-demo.com`
- **Password**: `password123`

## Service Ports Mapping

All services are exposed on `localhost` with dedicated ports:

| Service | Port | URL | Purpose |
|---------|------|-----|---------|
| **API Gateway (NGINX)** | 80 | http://localhost | Main entry point for all API requests |
| **User Service** | 6001 | http://localhost:6001 | Authentication, user management, JWT token generation |
| **Account Service** | 6002 | http://localhost:6002 | Account lifecycle, balance queries |
| **Transaction Service** | 6003 | http://localhost:6003 | Transaction history, recording |
| **Transfer Service** | 6004 | http://localhost:6004 | Money transfer orchestration |
| **Chatbot Service** | 8001 | http://localhost:8001 | AI financial assistant (FastAPI) |
| **Anomaly Service** | 8002 | http://localhost:8002 | Fraud detection (FastAPI) |
| **Budget Service** | 8003 | http://localhost:8003 | Budget analysis (FastAPI) |
| **Redis** | 6380 | redis://localhost:6380 | Cache, session store, event streaming |
| **UI Application** | 3000 | http://localhost:3000 | React frontend |

### Accessing Service APIs Directly

While you can access individual services on their ports, it's recommended to use the **API Gateway** (port 80) for consistency:

```bash
# Through API Gateway (recommended)
curl http://localhost/api/users/swagger/index.html

# Direct service access (for debugging)
curl http://localhost:6001/api/users/swagger/index.html
```

## Environment Variables Setup

The system uses a `.env` file for local configuration. A template is provided:

### 1. Create `.env` File

```bash
# Copy the example environment file
cp .env.example .env
```

### 2. Configure `.env` for Local Development

```bash
# .env file configuration (default values are suitable for local dev)

# ===== Authentication =====
# JWT signing key (keep consistent across all services)
Jwt__Key=YourSuperSecretKeyForJWTTokenGeneration12345
Jwt__Issuer=user-service

# ===== Database =====
# Use in-memory database for local development
UseInMemoryDatabase=true

# ===== Azure Services (Optional - leave empty for basic demo) =====
# Azure OpenAI endpoint (required only if using chatbot/anomaly/budget services)
AZURE_OPENAI_ENDPOINT=https://your-openai-instance.openai.azure.com/
AZURE_OPENAI_MODEL=gpt-4o-mini

# Azure authentication (for AI services)
AZURE_CLIENT_ID=
AZURE_TENANT_ID=
AZURE_CLIENT_SECRET=

# Application Insights connection string (optional monitoring)
APPLICATIONINSIGHTS_CONNECTION_STRING=

# ===== Redis =====
# Internal container name (resolved by Docker Compose networking)
REDIS__CONNECTIONSTRING=redis:6379

# ===== Service URLs (for inter-service communication) =====
Services__AccountService=http://account-service:8080
Services__TransactionService=http://transaction-service:8080
```

### 3. Verify Environment Loading

```bash
# Check that services are using env vars correctly
docker-compose logs user-service | grep -i "jwt\|environment"

# Services should print configuration on startup
```

## Accessing the UI

### Login Flow

1. **Navigate to UI**: http://localhost:3000/
2. **Demo Credentials** (if seed data was run):
   - Email: `demo@banking-demo.com`
   - Password: `password123`
3. **Or Register New User**: Create an account through the signup form
4. **Verify Login**: JWT token should be stored in browser localStorage under key `auth_token`

### Available Features

- **Dashboard**: Overview of accounts and recent transactions
- **Accounts**: View, create, and manage bank accounts
- **Transactions**: View transaction history
- **Transfers**: Execute money transfers between accounts
- **Chat**: Financial advice via AI chatbot (if Azure OpenAI configured)
- **Analytics**: Budget insights and spending analysis

## Using the Seed Script

The `scripts/seed-data.sh` script populates demo data into local services.

### Script Behavior

```bash
./scripts/seed-data.sh

# The script will:
# 1. Register demo users (idempotent — skips already-registered users)
# 2. Login each user and capture JWT tokens
# 3. Create checking/savings accounts with initial balances
# 4. Execute sample transfers
# 5. Verify all operations succeeded
# 6. Report any errors clearly
```

### Troubleshooting Seed Script

```bash
# If script fails, verify services are running
docker-compose ps

# If services aren't healthy, check logs
docker-compose logs user-service

# Manual seed (advanced users)
# Edit script directly or POST manually via curl
curl -X POST http://localhost/api/users/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","email":"test@example.com","password":"Pass123!","firstName":"Test","lastName":"User"}'
```

## API Documentation

### Accessing Swagger UI

All .NET services expose Swagger documentation:

- **User Service**: http://localhost/api/users/swagger/index.html
- **Account Service**: http://localhost/api/accounts/swagger/index.html
- **Transaction Service**: http://localhost/api/transactions/swagger/index.html
- **Transfer Service**: http://localhost/api/transfers/swagger/index.html

### Accessing FastAPI Docs

Python services use FastAPI with OpenAPI documentation:

- **Chatbot Service**: http://localhost/api/chat/docs
- **Anomaly Service**: http://localhost/api/anomaly/docs
- **Budget Service**: http://localhost/api/budget/docs

### API Authentication

All protected endpoints require a JWT token:

```bash
# 1. Login to get token
TOKEN=$(curl -s -X POST http://localhost/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"password123"}' | jq -r '.token')

# 2. Use token in Authorization header
curl http://localhost/api/accounts/ \
  -H "Authorization: Bearer $TOKEN"
```

## Development Workflow

### Hot Reload / Watch Mode

#### For .NET Services

```bash
# Terminal 1: Keep Docker services running
docker-compose up -d

# Terminal 2: Run individual .NET service with hot reload
cd src/user-service
dotnet watch run

# Or with environment variables
ASPNETCORE_ENVIRONMENT=Development dotnet watch run
```

#### For Python Services

```bash
# Terminal 1: Keep Docker services running
docker-compose up -d

# Terminal 2: Run Python service with auto-reload
cd src/chatbot-service
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

#### For UI (React)

```bash
# Terminal 1: Keep Docker services running (skip ui-app container)
docker-compose up -d --no-build

# Terminal 2: Start React dev server
cd src/ui-app
npm install
npm start

# Browser will open at http://localhost:3000 with hot reload enabled
```

### Rebuilding Individual Services

```bash
# Rebuild and restart a specific service
docker-compose build --no-cache user-service
docker-compose up -d user-service

# View build logs
docker-compose logs user-service
```

### Stopping Services

```bash
# Stop all services (containers remain, volumes persist)
docker-compose stop

# Resume services
docker-compose start

# Remove all containers (volumes persist)
docker-compose down

# Remove everything including volumes
docker-compose down -v
```

## Troubleshooting

### Common Issues & Solutions

#### 1. Port Already in Use

```bash
# Error: "Cannot assign requested address: bind"

# Find what's using the port (e.g., port 80)
sudo lsof -i :80

# Kill the process or change NGINX port in docker-compose.yml
# Alternative: Use docker-compose override
docker-compose -f docker-compose.yml -f docker-compose.override.yml up
```

#### 2. Services Won't Start (Out of Memory)

```bash
# Error: "docker daemon failed"

# Increase Docker Desktop memory allocation:
# macOS/Windows: Docker Desktop → Preferences → Resources → Memory (increase to 8GB+)
# Linux: Adjust system swap

# Or reduce service count
docker-compose up -d user-service account-service
```

#### 3. Redis Connection Failed

```bash
# Error: "Connection refused" or "Unable to connect to redis"

# Check Redis is running and healthy
docker-compose ps redis
# Should show: "Up X minutes (healthy)"

# Reset Redis
docker-compose down -v
docker-compose up -d redis
```

#### 4. JWT Token Validation Errors

```bash
# Error: "Unauthorized" or "Invalid token"

# Verify JWT key consistency across services
docker-compose logs | grep "Jwt__Key"

# Token is expired (default expiry ~1 hour)
# Re-login to get fresh token

# Clear browser localStorage if needed
# Browser DevTools → Application → LocalStorage → Clear All
```

#### 5. Service Dependency Issues

```bash
# Error: "Service A cannot reach Service B"

# Services use Docker internal DNS (service name as hostname)
# e.g., http://account-service:8080 (NOT localhost)

# Verify network connectivity
docker-compose exec transfer-service bash
curl http://account-service:8080/health

# If failing, check service dependencies in docker-compose.yml
# and ensure dependent services started first
```

### Viewing Logs

```bash
# All services, last 100 lines
docker-compose logs --tail=100

# Follow logs in real-time (Ctrl+C to stop)
docker-compose logs -f

# Specific service
docker-compose logs -f transfer-service

# Filter by timestamp
docker-compose logs --since 2024-01-15T10:00:00

# Colorized output (default on most systems)
docker-compose logs --colors
```

### Health Checks

```bash
# Check overall system health
curl http://localhost/health

# Check individual service health
docker-compose exec user-service curl http://localhost:8080/health

# View health status in docker ps
docker-compose ps
# STATUS column shows "(healthy)" for services with passing checks
```

## Performance Tuning

### Optimize Docker Desktop

**macOS/Windows**:
- Docker Desktop Preferences → Resources
- Increase CPUs: 4+ cores recommended
- Increase Memory: 8GB+ recommended
- Increase Disk Image Size: 100GB+ for large volumes

**Linux**:
- Native Docker (best performance)
- Adjust ulimits: `ulimit -n 65536` (increase open files)

### Redis Optimization

```bash
# Monitor Redis memory usage
docker-compose exec redis redis-cli INFO memory

# Clear expired data
docker-compose exec redis redis-cli BGSAVE
```

### Database Optimization

The demo uses in-memory SQLite. For production-like performance testing:
- Consider switching to a local PostgreSQL container
- Update `docker-compose.yml` to include postgres service
- Adjust service env vars to use postgres connection strings

## Cleanup

```bash
# Stop all services
docker-compose down

# Remove all containers and volumes (WARNING: deletes data)
docker-compose down -v

# Remove all Docker images (will rebuild on next docker-compose up)
docker rmi $(docker images | grep banking | awk '{print $3}')

# Full cleanup (use with caution)
docker system prune -a
```

## Next Steps

After local deployment:

1. **Explore APIs**: Use Swagger documentation to test endpoints
2. **Check Architecture**: See `docs/architecture.md` for system design
3. **Deploy to Cloud**: See `docs/deployment-azure.md` for Azure deployment
4. **Development**: Follow "Development Workflow" section for local code changes
5. **Testing**: Run tests with `./test.sh` or service-specific test commands

---

**Last Updated**: May 2024  
**Tested On**: Docker 25+, Docker Compose 2.0+, macOS 13+, Ubuntu 22.04+, Windows 11+
