# Quickstart — Loan Origination Workflow

**Branch:** `017-loan-origination-workflow`
**Audience:** Developers and operators bringing this feature up locally and in AKS.

## Prerequisites

- The base `online-banking-demo` stack is already running (see `docs/deployment-local.md` or `docs/deployment-azure.md`).
- For cloud: spec **001-azure-private-endpoints** has been applied — Foundry project, capability host, and BYO connections exist privately.
- `task` (Taskfile runner), Docker, .NET 10 SDK, Node.js 18+ all installed for local dev.

## Local Development

### 1. Bring up the base stack

```bash
docker-compose up -d
```

This starts Cosmos emulator (or Cosmos in cloud-mode), Redis, the four core .NET services, the Python services, and the React UI on `http://localhost:3000`.

### 2. Build and run loan-origination-service

```bash
cd src/loan-origination-service
dotnet restore
dotnet run --urls=http://localhost:5290
```

The service registers Foundry agents on startup (logs: `Registered version v1 for credit-profile-agent`, etc.). For pure local dev (no Foundry), set `Foundry__Mode=offline` to use canned recommendations:

```bash
Foundry__Mode=offline dotnet run
```

In offline mode the orchestrator skips agent calls and returns deterministic stub recommendations based on `applicationNo` — useful for UI iteration.

### 3. Seed policy rules and demo applicants

```bash
./scripts/seed-data.sh --include loans
```

This loads:
- POL-001 through POL-010 into the `loan-policy` Cosmos container.
- Three demo applications (Alice / Bob / Charlie) into `loan-applications`.

### 4. Run the React UI

```bash
cd src/ui-app
npm install
npm start
```

Navigate to `http://localhost:3000/loans` to see the intake form.

### 5. Try the happy path

1. Log in as `alice@example.com` (seeded by `seed-data.sh`).
2. Open `/loans` → "Apply for a Loan" → submit (form is pre-filled with Alice's profile).
3. Watch the workflow visualization stream S01 → S10 (~30s in cloud mode, ~1s in offline mode).
4. Switch to an admin user and open the same application from `/loans/admin/review`.
5. Approve. Verify a `LoanAccount` appears under `/loans/accounts` with the approved principal, APR, term, and monthly payment. **Do NOT** look in `/accounts` for a new entry — that page is for deposit accounts only and is not modified by this feature. **Do NOT** look in `/transactions` for a funding entry — loan disbursements live inside the loan domain.

### 6. Edge case — user with zero deposit accounts

The whole point of in-domain ownership is that a loan does not require a deposit account. Demonstrate this:

```bash
# Create a fresh user with no accounts (uses the existing user-service registration path,
# NOT account-opening-service):
curl -sf https://${CUSTOM_DOMAIN}/api/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"newhire@example.com","password":"demo","name":"New Hire"}'

# Verify they have zero deposit accounts:
TOKEN=$(curl -sf https://${CUSTOM_DOMAIN}/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"newhire@example.com","password":"demo"}' | jq -r .token)
curl -sf https://${CUSTOM_DOMAIN}/api/accounts -H "Authorization: Bearer $TOKEN" | jq 'length'  # → 0

# Submit and approve a loan for them. Verify it succeeds end-to-end.
# Then verify they STILL have zero deposit accounts:
curl -sf https://${CUSTOM_DOMAIN}/api/accounts -H "Authorization: Bearer $TOKEN" | jq 'length'  # → 0
curl -sf https://${CUSTOM_DOMAIN}/api/loans/accounts -H "Authorization: Bearer $TOKEN" | jq 'length'  # → 1
```

## Cloud Deployment

### 1. Apply the Terraform additions

```bash
cd infra/cloud
terraform plan   # should show only 6 new Cosmos containers + RBAC verifications
terraform apply
```

No new Azure resources are introduced — only Cosmos containers (`loan-applications`, `loan-runs`, `underwriting-decisions`, `loan-policy`, `loan-accounts`, `loan-disbursements`) and (if missing) Foundry RBAC role assignments on the existing workload identity.

### 2. Build the image

```bash
task cloud:build:loan-origination-service
```

This builds via ACR and tags the image. Image name: `${ACR_NAME}.azurecr.io/loan-origination-service:latest`.

### 3. Deploy

```bash
task cloud:deploy
```

The kustomize base now includes `loan-origination-service.yaml` (Deployment + Service + ServiceAccount binding) and an Istio VirtualService routing `/api/loans/*` to the service.

### 4. Verify

```bash
kubectl rollout status -n banking-demo deploy/loan-origination-service

# Health checks
kubectl exec -n banking-demo deploy/loan-origination-service -- curl -sf localhost:8080/healthz
kubectl exec -n banking-demo deploy/loan-origination-service -- curl -sf localhost:8080/readyz

# Confirm agents registered in Foundry
kubectl logs -n banking-demo deploy/loan-origination-service | grep "Registered version"
# Expect 7 lines (6 specialists + 1 health-check)
```

### 5. Smoke test against the real domain

```bash
# JWT for a demo user (via /api/auth/login)
TOKEN=$(curl -sf https://${CUSTOM_DOMAIN}/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"alice@example.com","password":"demo"}' | jq -r .token)

# Submit + run an application
curl -sf https://${CUSTOM_DOMAIN}/api/loans/applications \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d @- <<'EOF' | jq
{
  "applicant": { "name":"Alice Goodman","dob":"1985-03-14","ssnLast4":"4321","email":"alice@example.com","currentAddress":"123 Pine St","cityStateZip":"Austin, TX 78701" },
  "loanRequest": { "amount":25000,"purpose":"home_improvement","termMonths":36,"loanType":"personal","paymentMethod":"AUTO_DEBIT" },
  "financials": { "grossAnnualIncome":120000,"monthlyNetIncome":7500,"otherIncomeMonthly":0,"totalMonthlyDebtPayments":400,"housingStatus":"rent","housingPaymentMonthly":1800,"declaredDtiPct":5.3,"estimatedSavings":25000,"retirementInvestments":80000 }
}
EOF

# Capture the applicationNo, then run
APP_NO=APP-...   # from previous response
curl -sf -X POST "https://${CUSTOM_DOMAIN}/api/loans/applications/${APP_NO}/run" \
  -H "Authorization: Bearer $TOKEN" | jq '.recommendation.recommendationStatus'
# Expect: "APPROVE"
```

## Operations

### Re-deploy without re-creating Foundry agents

`AgentRegistration.cs` is idempotent — existing identical prompt versions are skipped. Use this freely on rolling deploys.

### Force a new agent version

Edit a prompt in `src/loan-origination-service/prompts/*.txt` and re-deploy. The next startup detects the diff and creates `v{N+1}`. Older versions remain in Foundry for audit.

### Disable a problem agent

Set the env var `Loan__DisabledAgents=fraud-screening-agent` (comma-separated). The orchestrator skips disabled steps and emits a `failed` step with detail `"Agent disabled by config"`.

### Read OTEL traces

In Application Insights, filter `dependencies` by `cloud_RoleName == "loan-origination-service"`. A full workflow run shows up as one parent operation with 10 child spans (S01–S10).

### Clean up failed runs

`loan-runs` has TTL disabled by default (we want history). To purge runs older than N days:

```bash
# From any pod with cosmos-cli or via the shared Cosmos query console
SELECT * FROM c WHERE c.startedAt < @cutoff
# Then bulk-delete via SDK script
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Service stays `NotReady` | Foundry RBAC missing | Verify `banking-workload-identity` has `Cognitive Services User` on the project |
| All workflow runs return `503 AGENT_UNAVAILABLE` | Agents not registered | Check startup logs for `Registered version`; manually run `kubectl exec ... -- dotnet LoanOrigination.dll --register-agents-only` |
| `recommendation.recommendationStatus` always `DECLINE` for everyone | Policy rules not seeded | Re-run `./scripts/seed-data.sh --include loans` |
| SSE stream cuts at ~30s in cloud | Istio idle timeout | Confirm the loan-origination VirtualService sets `timeout: 120s` (matches chatbot-service) |
| Approval succeeds but no `LoanAccount` created | Cosmos write to `loan-accounts` failed, or partial success between the two writes | Check logs for the `LoanAccount` repository; the decision handler is wrapped in a saga that rolls forward — re-running the decision should be idempotent (NFR-5) |
| `loan.funded` event missing from `banking-events` | Redis stream publish failed | Check `LoanEventPublisher` logs; the publish is best-effort post-write — re-running the decision will re-publish |
| Loan shows up in `/accounts` page | Bug — should never happen | The UI's `/accounts` page reads only `account-service` `GET /api/accounts`. If a loan appears there, something modified `account-service` — check `git diff main -- src/account-service/` (must be empty) |
