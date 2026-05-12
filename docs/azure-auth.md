# Azure Authentication

[← Azure Deployment](deployment-azure.md) | [Home](README.md) | [Next: Testing →](testing.md)

This document covers how services authenticate with Azure — both locally (Docker) and in production (AKS). The platform uses two credential patterns:

1. **DefaultAzureCredential** — Standard Azure Identity SDK credential chain (all services)
2. **Entra Agent ID Sidecar** — Microsoft Entra Agent ID auth-sidecar for Foundry agent workloads (account-opening-worker)

---

## DefaultAzureCredential

The Python services (ai-service, budget-service, chatbot-service, account-opening-service) and .NET services use `DefaultAzureCredential` from the Azure Identity SDK to authenticate with Azure resources (Cosmos DB, Blob Storage, Redis, AI Foundry).

### How DefaultAzureCredential Works

`DefaultAzureCredential` tries multiple credential sources in order:

1. Environment variables (service principal)
2. Workload Identity (Kubernetes — federated token file)
3. Managed Identity (Azure VMs, App Service)
4. Azure CLI credentials (`~/.azure` token cache)
5. Azure PowerShell
6. Azure Developer CLI

| Environment | Credential Used |
|-------------|----------------|
| Local Docker | Azure CLI volume mount (`~/.azure`) |
| AKS (production) | Workload Identity (federated token via service account) |
| CI/CD | Service principal environment variables |

---

## Method A: Development Mode — Azure CLI Volume Mount

For local development, mount your host's Azure CLI credentials into the container.

### Prerequisites

```bash
# Login on your host machine
az login
```

### How It Works

The `docker-compose.yml` mounts `~/.azure` (read-only) into each Python service container at `/home/appuser/.azure`. `DefaultAzureCredential` finds the cached token and uses it.

```yaml
volumes:
  - ${HOME}/.azure:/home/appuser/.azure:ro
```

### Advantages

- Zero configuration beyond `az login`
- Uses your existing Azure identity and RBAC permissions
- No secrets in `.env` files

### Limitations

- Tokens expire (re-run `az login` if you see 401 errors)
- Only works for the user who ran `az login`
- Not suitable for CI/CD or production

---

## Method B: Production — Service Principal Environment Variables

For CI/CD and production, use a service principal (app registration) with client credentials.

### Prerequisites

1. Create an Azure AD app registration / service principal
2. Assign it the required RBAC roles:
   - **Cognitive Services OpenAI User** on your Azure OpenAI resource
   - **Azure AI Developer** on your Azure AI Foundry project (for chatbot-service)

### Configuration

Add these to your `.env` file:

```env
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
```

The `docker-compose.yml` passes these as environment variables to the containers. `DefaultAzureCredential` picks them up via `EnvironmentCredential` (first in the chain).

### Advantages

- No host filesystem dependency
- Works in any environment (CI, Kubernetes, cloud VMs)
- Explicit, auditable identity

### Limitations

- Secret rotation required
- Must manage `.env` file securely (never commit to git)

---

## Verifying Credential Availability

Each service exposes a `/readyz` endpoint that verifies Azure credential access by attempting to acquire a token:

```bash
# Check ai-service
curl http://localhost:8002/readyz

# Check budget-service
curl http://localhost:8003/readyz

# Check chatbot-service
curl http://localhost:8001/readyz
```

Response when credentials are working:

```json
{
  "status": "ready",
  "checks": {
    "azure_credential": true
  }
}
```

Response when credentials are missing or invalid:

```json
{
  "status": "degraded",
  "checks": {
    "azure_credential": false
  }
}
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `azure_credential: false` in /readyz | No valid credential found | Run `az login` or set env vars |
| `CredentialUnavailableError` in logs | Token expired | Re-run `az login` on host |
| `AADSTS700016` error | Wrong client ID | Verify `AZURE_CLIENT_ID` in `.env` |
| `Permission denied` on volume | File permissions | Ensure `~/.azure` is readable |

---

## Security Notes

- The `~/.azure` volume is mounted **read-only** (`:ro`) — containers cannot modify your local credentials.
- Never commit `.env` files containing `AZURE_CLIENT_SECRET` to source control.
- In production Kubernetes deployments, use Workload Identity (no secrets needed).
- The Entra Agent ID sidecar uses federated credentials — no client secrets.

---

## Entra Agent ID Sidecar (Account Opening Worker)

The Account Opening Worker uses a **dual credential pattern**: DefaultAzureCredential for infrastructure services (Cosmos DB, Blob Storage) and a dedicated **Entra Agent ID auth-sidecar** for Azure AI Foundry agent communication.

### Why a Sidecar?

Azure AI Foundry's Agent Framework requires scoped tokens with specific audiences. The Entra Agent ID sidecar (from `mcr.microsoft.com/entra-sdk/auth-sidecar`) handles token acquisition, caching, and refresh — isolating the complexity from application code.

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  account-opening-worker Pod                         │
│                                                     │
│  ┌─────────────┐     ┌──────────────────────────┐  │
│  │   Worker     │────▶│  Entra Agent ID Sidecar  │  │
│  │  (Python)    │     │  (ASP.NET, port 5000)    │  │
│  │             │     │                          │  │
│  │ DAC → Cosmos│     │ Workload Identity Fed    │  │
│  │ DAC → Blob  │     │ Token → Foundry Agents   │  │
│  │ Sidecar →   │     │                          │  │
│  │   Foundry   │     │ GET /AuthorizationHeader  │  │
│  └─────────────┘     │     Unauthenticated/     │  │
│                       │     {api_name}           │  │
│                       └──────────────────────────┘  │
│                                                     │
│  ┌─────────────┐                                    │
│  │ Istio Proxy │  (mTLS mesh traffic)               │
│  └─────────────┘                                    │
└─────────────────────────────────────────────────────┘
```

### How It Works

1. The AKS Workload Identity webhook injects `AZURE_FEDERATED_TOKEN_FILE` and `AZURE_CLIENT_ID` into all pod containers.
2. The sidecar uses `SignedAssertionFilePath` credential type to exchange the federated token for Azure AD tokens.
3. The worker's `SidecarTokenCredential` calls the sidecar's HTTP endpoint to get bearer tokens for Foundry.
4. Tokens are cached by the sidecar and refreshed automatically.

### Sidecar API

```
GET http://localhost:5000/AuthorizationHeaderUnauthenticated/{api_name}?AgentIdentity={agent_id}
```

Returns:
```json
{
  "Authorization": "Bearer eyJ0eXAi..."
}
```

### Configuration (via ConfigMap)

| Key | Purpose |
|-----|---------|
| `AzureAd__TenantId` | Azure AD tenant ID |
| `AzureAd__ClientId` | Workload identity client ID |
| `AzureAd__ClientCredentials__0__SourceType` | `SignedAssertionFilePath` (uses fed token) |
| `Kestrel__Endpoints__Http__Url` | `http://[::]:5000` (override default 8080) |
| `AGENT_ID_SIDECAR_URL` | Worker env var pointing to `http://localhost:5000` |
| `AGENT_ID_AGENT_IDENTITY` | Agent identity (client ID) passed to sidecar |

### Deployment Notes

- **Image:** `mcr.microsoft.com/entra-sdk/auth-sidecar:1.0.0-azurelinux3.0-distroless` (no `latest` tag exists)
- **Readiness probe:** TCP socket on port 5000 (HTTP probes conflict with Istio rewriting)
- **Volume:** Requires writable `/app/keys` emptyDir for ASP.NET data protection keys
- **Init containers:** Run BEFORE the sidecar starts — `init_agents.py` must use DAC, not the sidecar

### Fallback Behavior

The `SidecarTokenCredential` is gated by the `AGENT_ID_SIDECAR_URL` environment variable:
- **Set** (AKS production): Worker uses sidecar for Foundry tokens
- **Not set** (local dev): Worker falls back to DefaultAzureCredential for everything

This enables the same code to work locally (with `az login`) and in production (with the sidecar).

---

[← Azure Deployment](deployment-azure.md) | [Home](README.md) | [Next: Testing →](testing.md)
