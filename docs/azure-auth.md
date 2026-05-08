# Azure Authentication in Docker

[← Azure Deployment](deployment-azure.md) | [Home](README.md) | [Next: Testing →](testing.md)

The Python services (ai-service, budget-service, chatbot-service) use `DefaultAzureCredential` from the `azure-identity` SDK to authenticate with Azure AI services. This document explains how credentials are provided when running inside Docker containers.

## How DefaultAzureCredential Works

`DefaultAzureCredential` tries multiple credential sources in order:

1. Environment variables (service principal)
2. Workload Identity (Kubernetes)
3. Managed Identity (Azure VMs, App Service)
4. Azure CLI credentials (`~/.azure` token cache)
5. Azure PowerShell
6. Azure Developer CLI

In Docker, only options 1 and 4 are practical.

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
- In production Kubernetes deployments, prefer Workload Identity over service principal secrets.

---

[← Azure Deployment](deployment-azure.md) | [Home](README.md) | [Next: Testing →](testing.md)
