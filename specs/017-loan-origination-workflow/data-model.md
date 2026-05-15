# Phase 1 Data Model — Loan Origination Workflow

**Branch:** `017-loan-origination-workflow`
**Date:** 2026-05-15

## Cosmos Containers

| Container | Partition Key | Items | Throughput |
|---|---|---|---|
| `loan-applications` | `/id` (== `applicationNo`) | One doc per application | shared 400 RU/s |
| `loan-runs` | `/applicationNo` | One doc per workflow run | shared |
| `underwriting-decisions` | `/applicationNo` | One doc per recorded human decision | shared |
| `loan-policy` | `/id` (== `ruleId`) | 10 seed docs (POL-001..POL-010) | shared |
| `loan-accounts` | `/userId` | One doc per funded loan | shared |
| `loan-disbursements` | `/loanAccountId` | One doc per funding/payment entry | shared |

All six containers are **owned exclusively by loan-origination-service** and share a single 400 RU/s throughput pool — matches the existing convention used by `account-applications`. No cross-partition queries are required by the read patterns. **No other container is read or written by this service.**

> **Note:** A `LoanAccount` is a loan-domain record (principal owed). It is **not** a deposit account and lives in `loan-accounts`, not in the existing `accounts` container. Likewise a `LoanDisbursement` is an internal accounting entry in `loan-disbursements` and is **not** written to the `transactions` container.

---

## Entities

### LoanApplication (`loan-applications`)

```jsonc
{
  "id": "APP-2026-000123",            // applicationNo, also Cosmos PK
  "applicationNo": "APP-2026-000123",
  "userId": "u-9f3...e7c",            // FK → users.id
  "applicationDate": "2026-05-15T14:23:11Z",
  "status": "submitted",              // see state machine below
  "applicant": {
    "name": "Alice Goodman",
    "dob": "1985-03-14",
    "ssnLast4": "4321",
    "phone": "+1-555-0100",
    "email": "alice@example.com",
    "currentAddress": "123 Pine St",
    "cityStateZip": "Austin, TX 78701"
  },
  "loanRequest": {
    "amount": 25000.00,
    "purpose": "home_improvement",
    "termMonths": 36,
    "loanType": "personal",           // personal | auto | mortgage | small_business
    "paymentMethod": "AUTO_DEBIT"
  },
  "financials": {
    "grossAnnualIncome": 120000.00,
    "monthlyNetIncome": 7500.00,
    "otherIncomeMonthly": 0.00,
    "totalMonthlyDebtPayments": 400.00,
    "housingStatus": "rent",          // own | rent | mortgage | other
    "housingPaymentMonthly": 1800.00,
    "declaredDtiPct": 5.3,
    "estimatedSavings": 25000.00,
    "retirementInvestments": 80000.00
  },
  "lastRunId": "RUN-2026-0001234",       // null until first run
  "lastDecisionId": "DEC-2026-00045",    // null until decided
  "fundedLoanAccountId": null,           // populated on approval (FK → loan-accounts.id) — NOT an accounts.id
  "createdAt": "2026-05-15T14:23:11Z",
  "updatedAt": "2026-05-15T14:25:42Z",
  "_etag": "..."                      // Cosmos optimistic concurrency
}
```

**Validation rules** (enforced in controller via DataAnnotations + manual checks):
- `applicationNo` matches `^APP-\d{4}-\d{6}$`.
- `loanRequest.amount` ≥ 1,000 and ≤ 500,000.
- `loanRequest.termMonths` ∈ {12, 24, 36, 48, 60, 72, 84, 120, 180, 240, 360}.
- `loanRequest.loanType` ∈ {personal, auto, mortgage, small_business}.
- `financials.grossAnnualIncome` ≥ 0.
- `applicant.email` is RFC-5322 valid.
- `userId` must resolve to a real user via `user-service` (validated lazily on first run).

### LoanRun (`loan-runs`)

```jsonc
{
  "id": "RUN-2026-0001234",
  "runId": "RUN-2026-0001234",
  "applicationNo": "APP-2026-000123",   // PK
  "startedAt": "2026-05-15T14:24:00Z",
  "completedAt": "2026-05-15T14:24:48Z",
  "durationMs": 48123,
  "triggerKind": "run",                  // run | recompute
  "prepared": {                          // enrichment snapshot at start of run
    "creditProfile": { /* CreditProfile */ },
    "incomeVerification": { /* IncomeVerification */ },
    "fraudSignals": { /* FraudSignals */ },
    "pricingQuote": { /* QuoteResponse */ }
  },
  "workflowLog": [
    { "stepId": "S01", "stepName": "Application Intake",       "status": "completed", "timestamp": "...", "agentName": null,                                  "detail": "Loaded APP-2026-000123" },
    { "stepId": "S02", "stepName": "Data Enrichment",          "status": "completed", "timestamp": "...", "agentName": null,                                  "detail": "Credit/income/fraud/pricing enriched" },
    { "stepId": "S03", "stepName": "Credit Profile Agent",     "status": "completed", "timestamp": "...", "agentName": "credit-profile-agent",                "detail": "Bureau score 760 — Tier A" },
    { "stepId": "S04", "stepName": "Income Verification Agent","status": "completed", "timestamp": "...", "agentName": "income-verification-agent",           "detail": "Verified $7,500/mo" },
    { "stepId": "S05", "stepName": "Fraud Screening Agent",    "status": "completed", "timestamp": "...", "agentName": "fraud-screening-agent",               "detail": "Identity risk 0.04" },
    { "stepId": "S06", "stepName": "Policy Evaluation Agent",  "status": "completed", "timestamp": "...", "agentName": "policy-evaluation-agent",             "detail": "0 critical hits" },
    { "stepId": "S07", "stepName": "DTI & Affordability",      "status": "completed", "timestamp": "...", "agentName": null,                                  "detail": "Verified DTI 18.4%" },
    { "stepId": "S08", "stepName": "Pricing Agent",            "status": "completed", "timestamp": "...", "agentName": "pricing-agent",                       "detail": "APR 7.49%, $778/mo" },
    { "stepId": "S09", "stepName": "Underwriting Recommendation", "status": "completed", "timestamp": "...", "agentName": "underwriting-recommendation-agent","detail": "APPROVE (0.83)" },
    { "stepId": "S10", "stepName": "Human Review Ready",       "status": "completed", "timestamp": "...", "agentName": null,                                  "detail": "Packaged for reviewer" }
  ],
  "recommendation": { /* UnderwritingRecommendation */ },
  "errors": [],                          // populated if any step failed
  "createdAt": "...",
  "_etag": "..."
}
```

### Decision (`underwriting-decisions`)

> **Naming note:** The C# model class for this entity is `DecisionRecord` (to avoid collision with the `System.Decision` namespace). In data-model and spec docs, it is referred to simply as "Decision". Both names refer to the same Cosmos entity in the `underwriting-decisions` container.

```jsonc
{
  "id": "DEC-2026-00045",
  "applicationNo": "APP-2026-000123",   // PK
  "runId": "RUN-2026-0001234",          // which run this decision references
  "reviewerId": "u-...admin",
  "reviewerName": "Reviewer Bob",
  "decision": "approve",                // approve | conditional | decline
  "adjustedAmount": null,                // null => use original requested amount
  "adjustedTermMonths": null,
  "adjustedRate": null,
  "notes": "Strong file, no DTI concerns.",
  "recommendationSnapshot": { /* full UnderwritingRecommendation captured at decision time */ },
  "fundingResult": {
    "loanAccountId": "loan-acc-...beef",         // FK → loan-accounts.id (NOT accounts.id)
    "loanDisbursementId": "loan-disb-...feed",   // FK → loan-disbursements.id (NOT transactions.id)
    "fundedAt": "2026-05-15T14:31:09Z"
  },
  "createdAt": "..."
}
```

### LoanAccount (`loan-accounts`) — **NEW**

> A `LoanAccount` is the funded-loan record (principal owed, APR, term, monthly payment). It is **not** a deposit account. It lives in its own container and the existing `accounts` container is **not** touched.

```jsonc
{
  "id": "loan-acc-7d2f9a3e",            // loanAccountId (also used as the per-loan PK in loan-disbursements)
  "userId": "u-9f3...e7c",              // PK — FK → users.id (read-only reference)
  "applicationNo": "APP-2026-000123",   // FK → loan-applications.id
  "decisionId": "DEC-2026-00045",       // FK → underwriting-decisions.id
  "loanType": "personal",               // personal | auto | mortgage | small_business
  "principalBalance": 25000.00,         // amount currently owed (== disbursedAmount at funding; payments are out of scope)
  "originalPrincipal": 25000.00,        // amount originally disbursed
  "aprPct": 7.49,
  "termMonths": 36,
  "monthlyPayment": 778.00,
  "totalRepayableAmount": 28008.00,
  "originationDate": "2026-05-15T14:31:09Z",
  "firstPaymentDate": "2026-06-15",     // informational; servicing is out of scope
  "payoffDate": "2029-05-15",           // informational
  "status": "funded",                   // funded | (future: paid_off | in_arrears | charged_off — out of scope)
  "createdAt": "...",
  "updatedAt": "...",
  "_etag": "..."
}
```

**Validation:** `id` ∈ `^loan-acc-[a-f0-9]{8,}$`. `principalBalance` ≥ 0 ≤ `originalPrincipal`. `aprPct` > 0. `userId` must resolve via `user-service` (validated when the account is created, not on every read).

### LoanDisbursement (`loan-disbursements`) — **NEW**

> A `LoanDisbursement` is an **internal accounting entry** within the loan domain. It is **not** a deposit-side transaction and is **not** written to the `transactions` container. For this feature, only the initial `funding` kind is recorded.

```jsonc
{
  "id": "loan-disb-3a91c4f2",
  "loanAccountId": "loan-acc-7d2f9a3e", // PK — FK → loan-accounts.id
  "userId": "u-9f3...e7c",              // denormalized for trace lookups
  "kind": "funding",                    // funding | (future: payment | interest_accrual | fee | reversal — out of scope)
  "amount": 25000.00,
  "currency": "USD",
  "occurredAt": "2026-05-15T14:31:09Z",
  "memo": "Initial loan disbursement",
  "metadata": {
    "applicationNo": "APP-2026-000123",
    "decisionId": "DEC-2026-00045"
  },
  "createdAt": "..."
}
```

**Validation:** `kind` is currently restricted to `funding`. `amount` > 0. The combination (`loanAccountId`, `kind=funding`) is unique — re-approving an already-funded loan reuses the existing record (idempotency, NFR-5).

### PolicyRule (`loan-policy`, seed data)

```jsonc
{
  "id": "POL-001",
  "ruleId": "POL-001",
  "metric": "bureau_score",
  "operator": ">=",
  "threshold": "620",
  "severity": "hard",
  "decisionEffect": "DECLINE_IF_FAIL",
  "description": "Minimum FICO floor — applications below 620 are auto-declined."
}
```

Ten rules (POL-001 through POL-010) ported verbatim from the source repo's `policy-thresholds.csv`. Loaded once at deploy time by the seed script; never written by the service.

---

## State Machine — `LoanApplication.status`

```
                 ┌──────────────────────────────────────────────────────┐
                 │                                                      │
   [client]      │                                                      │
   POST          │                                                      ▼
   /applications │                                          ┌────────────────┐
        │        │                          run completed   │                │
        ▼        │           ┌─────────────►│   recommended  │
  ┌──────────┐   │           │              │                │
  │ submitted │──┴──► run ───┘              └────────┬───────┘
  └──────────┘     POST /run                         │
                   creates LoanRun                   │ POST /decisions
                                                    ▼
                                          ┌────────────────┐
                                          │    decided     │
                                          └───────┬────────┘
                                                  │ if decision == approve:
                                                  │   LoanAccount + LoanDisbursement
                                                  │   written (in-domain), then
                                                  │   loan.funded event published
                                                  ▼
                                          ┌────────────────┐
                                          │     funded     │
                                          └────────────────┘
```

Allowed transitions:

| From | To | Trigger |
|---|---|---|
| (none) | `submitted` | `POST /api/loans/applications` |
| `submitted` | `recommended` | `POST /run` completes successfully |
| `recommended` | `recommended` | `POST /recompute` (run again, same status) |
| `recommended` | `decided` | `POST /decisions` |
| `decided` | `funded` | `LoanFundingService` writes a `LoanAccount` to `loan-accounts` and a `LoanDisbursement` to `loan-disbursements` (both in-domain Cosmos containers), then publishes `loan.approved` + `loan.funded` events to `banking-events` Redis Stream. **No cross-domain service calls.** |
| `decided` | `decided` | Re-decision (new `Decision` doc; status unchanged) |

`failed` is never a terminal state — runs that fail leave the application's `status` unchanged but record errors on the `LoanRun` document. The UI surfaces the failure and the user can re-trigger via `POST /run`.

---

## Workflow Step Lifecycle

Each `WorkflowStep` entry in `LoanRun.workflowLog` follows this lifecycle:

```
  pending ──► running ──► completed
                  │
                  └─────► failed
```

- `pending` is the implicit starting state — no entry written yet.
- `running` is written when the step begins (used by SSE to show "thinking…").
- `completed` is written when the step succeeds; `detail` summarizes the agent's output.
- `failed` is written when the step throws or times out (`agentName` and `detail` capture the error).

The orchestrator emits an OTEL span per step with attributes `workflow.step_id`, `workflow.step_name`, `agent.name` (when applicable), and `step.duration_ms`.

---

## Relationships

```
users (existing — read-only FK reference, validated via user-service GET /api/users/{id})
  ├──► loan-applications.userId  (FK)
  ├──► loan-accounts.userId      (FK)
  ├──► loan-disbursements.userId (FK, denormalized)
  └──► underwriting-decisions.reviewerId (FK, admin only)

loan-applications  (loan-origination-service)
  ├──► loan-runs.applicationNo (FK)
  ├──► underwriting-decisions.applicationNo (FK)
  └──► loan-accounts.applicationNo (FK, set on approval)

loan-runs  (loan-origination-service)
  └──► underwriting-decisions.runId (FK)

underwriting-decisions  (loan-origination-service)
  ├──► loan-accounts.decisionId (FK, set on approval)
  └──► loan-disbursements.metadata.decisionId (FK, set on funding)

loan-accounts  (loan-origination-service)
  └──► loan-disbursements.loanAccountId (FK)

loan-policy  (loan-origination-service) — independent seed data, read-only at runtime

# DELIBERATELY NO EDGES into:
#   accounts                 (deposit-account domain owned by account-service)
#   transactions             (deposit-ledger domain owned by transaction-service)
#   account-applications     (account-opening domain owned by account-opening-service)
```

The loan domain is **closed** — every FK either points at a loan-domain container or at the read-only `users` container.

## Lifecycle Events (Redis Stream `banking-events`)

loan-origination-service publishes (publish-only — never consumes):

| Event Type | When | Payload |
|---|---|---|
| `loan.application.submitted` | After `POST /api/loans/applications` | `{event_type, application_no, user_id, amount, term_months, loan_type, timestamp}` |
| `loan.run.completed` | After `POST /run` or `/recompute` finishes successfully | `{event_type, application_no, run_id, recommendation_status, confidence_score, timestamp}` |
| `loan.approved` | After a decision with `decision == "approve"` is recorded, before funding | `{event_type, application_no, decision_id, user_id, timestamp}` |
| `loan.funded` | After the `LoanAccount` + initial `LoanDisbursement` are written | `{event_type, application_no, decision_id, loan_account_id, loan_disbursement_id, user_id, amount, apr_pct, term_months, timestamp}` |
| `loan.declined` | After a decision with `decision == "decline"` | `{event_type, application_no, decision_id, user_id, timestamp}` |

Subscribers are optional. `event-processor` (Go) generically consumes the stream for audit logging — no code change required there.

---

## Indexing & Query Patterns

All six containers use the **default Cosmos indexing policy** (index everything). At demo scale we don't need custom exclusions.

Expected queries:

| Query | Container | Pattern | Frequency |
|---|---|---|---|
| Get application by `applicationNo` | `loan-applications` | Point read on `id`+`pk` | Per request |
| List user's applications | `loan-applications` | `WHERE c.userId = @uid` (cross-partition, paged) | UI dashboard |
| List all applications (admin) | `loan-applications` | `SELECT * FROM c WHERE c.status = @status` | Admin review page |
| Get latest run for application | `loan-runs` | `WHERE c.applicationNo = @app ORDER BY c.startedAt DESC LIMIT 1` | App detail page |
| Get all decisions for application | `underwriting-decisions` | `WHERE c.applicationNo = @app ORDER BY c.createdAt DESC` | App detail page |
| List user's loan accounts | `loan-accounts` | Point query on PK `userId` | "My Loans" page |
| Get loan account by id | `loan-accounts` | `WHERE c.id = @id AND c.userId = @uid` (PK known from caller's JWT) | Loan detail page |
| Get disbursements for a loan | `loan-disbursements` | Point query on PK `loanAccountId` | Loan detail page |
| Get all policy rules | `loan-policy` | `SELECT * FROM c` | Per workflow run (cached in-process for 5 min) |

No cross-partition queries are unbounded; the admin "list all applications" path is paged at 50 items.
