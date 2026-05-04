# Online Banking Demo

A microservices-based online banking application demonstrating agentic capabilities with .NET, Python, Go, and cloud-native Azure services.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    API Gateway (Nginx)                     │
│                      http://localhost                       │
└───────────────────────┬───────────────────────────────────┘
                        │
       ┌────────────────┴────────────────┐
       │                                 │
┌──────▼──────┐                  ┌───────▼───────┐
│  .NET 9     │                  │ Python 3.11   │
│ Microservices│                  │ Agent Services│
└─────────────┘                  └───────────────┘
```

### Services

| Service | Tech | Port | Description |
|---------|------|------|-------------|
| **User Service** | .NET 9 | 6001 | Authentication & User Management |
| **Account Service** | .NET 9 | 6002 | Account Operations |
| **Transaction Service** | .NET 9 | 6003 | Transaction History |
| **Transfer Service** | .NET 9 | 6004 | Money Transfers |
| **Chatbot Service** | Python | 8001 | AI Financial Assistant |
| **Anomaly Service** | Python | 8002 | Fraud Detection Agent |
| **Budget Service** | Python | 8003 | Budget Analysis Agent |
| **Event Processor** | Go | - | Real-time Event Processing |
| **UI Application** | React | 3000 | Web Frontend |
| **Redis** | - | 6380 | Cache & State Store |

## Getting Started

### Prerequisites
- Docker & Docker Compose
- .NET 9 SDK (for local development)
- Python 3.11+ (for agent services)
- Go 1.22+ (for event processor)

### Running Locally

```bash
# Clone the repository
git clone https://github.com/briandenicola/online-banking-demo.git
cd online-banking-demo

# Start all services
docker-compose up -d --build

# Check services are running
docker-compose ps
```

### Access Points

- **React UI**: http://localhost:3000/
- **API Gateway**: http://localhost/
- **Health Check**: http://localhost/health

### Demo Credentials
- Email: `demo@banking-demo.com`
- Password: `password123`

## API Documentation

Access Swagger documentation through the gateway:

- User Service: http://localhost/api/users/swagger/index.html
- Account Service: http://localhost/api/accounts/swagger/index.html
- Transaction Service: http://localhost/api/transactions/swagger/index.html
- Transfer Service: http://localhost/api/transfers/swagger/index.html
- Chatbot Docs: http://localhost/api/chat/docs

## Project Structure

```
online-banking-demo/
├── docker-compose.yml
├── nginx.conf                    # API Gateway configuration
├── src/
│   ├── user-service/            # .NET Authentication service
│   ├── account-service/         # .NET Account management
│   ├── transaction-service/     # .NET Transaction history
│   ├── transfer-service/        # .NET Money transfers
│   ├── chatbot-service/         # Python AI assistant
│   ├── anomaly-service/         # Python fraud detection
│   ├── budget-service/          # Python budget analysis
│   ├── event-processor/         # Go event processor
│   └── ui-app/                  # React frontend
└── README.md
```

## Agentic Capabilities

### AI Chatbot Assistant
The chatbot service provides:
- Financial advice and insights
- Transaction categorization
- Budget recommendations
- Natural language queries

### Anomaly Detection
Real-time fraud detection:
- Unusual transaction patterns
- Velocity analysis
- Geographic anomalies
- Merchant behavior analysis

### Budget Analysis
Automated budget insights:
- Spending categorization
- Budget variance tracking
- Savings recommendations
- Financial health scoring

## Azure Deployment

Designed for deployment to Azure cloud services:
- **AKS** - Container orchestration
- **Cosmos DB** - Database (currently using in-memory)
- **Event Hub** - Event streaming
- **Redis** - Caching
- **Azure OpenAI** - AI services
- **Application Insights** - Monitoring

## Development

### Running Individual Services

```bash
# .NET services
cd src/user-service && dotnet run

# Python services  
cd src/chatbot-service && python main.py

# React UI (development mode)
cd src/ui-app && npm start
```

### Environment Variables

Services use these key environment variables:

```bash
# Authentication
Jwt__Key=YourSuperSecretKeyForJWTTokenGeneration12345
Jwt__Issuer=user-service

# Database
UseInMemoryDatabase=true

# Azure (when deploying)
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_KEY=
EVENTHUB_CONNECTION_STRING=
APPLICATIONINSIGHTS_CONNECTION_STRING=
```

## License

MIT License - see LICENSE file for details.