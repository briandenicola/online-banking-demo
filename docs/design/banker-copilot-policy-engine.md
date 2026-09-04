# Banker Copilot — Authority & Approval Policy Engine (Design Spike)

**Status:** DESIGN SPIKE — not implemented. Feeds Danny's epic spec (`docs/epics/banker-copilot.md`).
**Author:** Turk (Backend Dev)
**Date:** 2026-09-04
**Ratification required from:** Danny (Lead/Architect) on §1, §4, and all items in §9.

---

## 0. Ground rules inherited (not re-litigated here)

From `.squad/decisions/inbox/copilot-directive-banker-copilot-{epic,authority-model,scope-boundary}.md`:

| Invariant | Consequence for this design |
|---|---|
| **Agents never approve** | There is no code path in the mediator that transitions an approval to `signed` from a non-human principal. Enforced by principal-class check, not by policy config. |
| Ladder **L1 / L2 / L3** | Rung is data, not code. `L3` = mediator refuses to even create a proposal. |
| Thresholds decide *how many* and *how senior*, never *whether* | The schema has no "auto" / "none" rung. The minimum expressible signer count is 1. |
| Escalators only push **up** | Enforced structurally: the only combinator in the evaluator is `max` over a total order. See §3.4. |
| **All thresholds config-driven** | Every numeric/temporal value in the policy file is a *named* config key with an env-var override. No literals in code. Verified by a CI lint (§2.6). |
| Lifecycle `proposed → pending → signed \| denied \| expired`, TTL expiry == **denied** | Rules out Cosmos native TTL as the expiry mechanism for live approvals. See §5.4. |
| Signature binds a **payload hash** | Canonicalization is a spec-level concern, not an implementation detail. See §6. |
| No blanket "Approve All" | Batch endpoint is constrained by action-type + rung + per-item threshold. See §8.6. |
| Runtime = Azure AI Foundry Agent Service, delegated banker identity + capability allowlist | Harness is a *host* for Foundry agents, not a hand-rolled loop. |
| Tools call REST APIs, never the DB | Mediator is an HTTP egress proxy, not a data-access layer. |

---

## 1. Language / runtime recommendation

### 1.1 What this repo actually does with Foundry today (measured, not assumed)

| Service | Language | Foundry/agent stack in use | Notes |
|---|---|---|---|
| `ai-service` | Python 3.11 / FastAPI | `agent-framework-core 1.16.0`, `agent-framework-foundry 1.10.0`, `azure-ai-inference 1.0.0b9`, `azure-identity` | Imports `FoundryAgent`, `FoundryChatClient`, `Agent` behind an `AGENT_FRAMEWORK_AVAILABLE` try/except so the service still boots without the SDK. Also owns a Foundry-based evaluation path. |
| `chatbot-service` | Python 3.11 / FastAPI | `agent-framework-core 1.16.0`, `agent-framework-foundry 1.10.0`, `azure-ai-projects >= 2.1.0`, `openai`, `azure-cosmos-agent-memory 0.3.0b2`, `azure-core-tracing-opentelemetry` | The most complete Foundry integration — threads, persisted agent memory in Cosmos. |
| `account-opening-service` | Python 3.11 / FastAPI | `agent-framework-core 1.16.0`, `agent-framework-foundry 1.10.0`, `azure-ai-projects >= 2.1.0`, `azure-ai-contentunderstanding` | Multi-agent pipeline (document extraction → identity verification → compliance → provisioning) driven off Redis Streams. This is the closest existing analogue to a harness. |
| `prompt-eval-service` | C# / .NET 10 (`net10.0`) | **None.** `IHttpClientFactory` + hand-rolled REST calls to the Foundry data plane. csproj has `Azure.Identity`, `Microsoft.Azure.Cosmos`, `Newtonsoft.Json` — no `Azure.AI.Agents` / `Azure.AI.Projects`. | The one .NET service that touches Foundry does so *without* an agent SDK, by hand. |

**Signal:** every first-class agent construct in this repo — agent definition, tool binding, thread/run lifecycle, Foundry chat client, agent memory — exists **only in Python**, on a pinned pair of `agent-framework-*` versions. The .NET side has zero agent-framework surface and reaches Foundry through raw HTTP. That gap is the single strongest input to this decision.

### 1.2 Comparison

| Dimension | Python 3.11 / FastAPI | .NET 10 / ASP.NET Core |
|---|---|---|
| Foundry Agent Service integration | 3 services already do it with `agent-framework-foundry`; tool-calling, threads, streaming all covered by SDK | Would be hand-rolled HTTP, as `prompt-eval-service` already is. We'd be inventing our own agent loop — directly contrary to the "not a hand-rolled orchestrator" directive |
| Agent tool definitions | Native — decorated callables, typed via Pydantic; mirrors `account-opening-service` agent pattern | No equivalent in-repo precedent |
| SSE / long-lived streaming to the browser | `StreamingResponse` + async generators; already the idiom for FastAPI here | Fully capable (`IAsyncEnumerable`), no in-repo precedent for agent trace streaming |
| Policy file parsing / schema validation | Pydantic v2 models over YAML — declarative, generates JSON Schema for CI lint for free | `System.Text.Json` + `IValidateOptions`; workable, more ceremony |
| Decimal money math | `decimal.Decimal` — exact; must be explicit (never `float`) | `decimal` — exact and idiomatic. **Genuine .NET advantage** |
| Cosmos SDK | `azure-cosmos 4.x` — used by `chatbot-service`, `account-opening-service` | `Microsoft.Azure.Cosmos` 3.x + Newtonsoft — used by all .NET services; the repo's casing-drift hazard lives here (see `.squad/skills/cosmos-casing-audit`) |
| Redis Streams producer | `redis` asyncio — used by `ai-service`, `account-opening-service` | `StackExchange.Redis` — used by all .NET services |
| Dual-mode auth (`AZURE_CLIENT_ID` present → Entra, absent → simple) | Already implemented in `app/auth.py` (canonical copy, PyJWT HS256) | Already implemented in each `Program.cs` (`JwtBearer` HS256) |
| Static typing / compile-time guarantees on a security-critical component | mypy, opt-in | **Genuine .NET advantage** — the mediator is the security boundary |
| Team/Squad familiarity | Turk's primary surface | Also covered |

### 1.3 Recommendation — split by plane, majority Python

> **RECOMMENDATION FOR DANNY TO RATIFY.**

Build **one new Python 3.11 / FastAPI service, `banker-copilot-service`**, containing two *internally separated* planes:

- **Harness plane** — Foundry Agent Service session host, tool registry, SSE trace stream. Python is not close here: `agent-framework-foundry 1.10.0` is already the house standard across three services, and re-solving agent/tool/thread lifecycle in .NET would violate the "no hand-rolled orchestrator" directive.
- **Policy + mediator plane** — policy evaluation, approval store, payload hashing, signature verification, egress execution.

The mediator plane is the security boundary, and .NET's static typing genuinely helps there. I still recommend Python for it, for three reasons: (1) a *process* boundary between harness and mediator is what actually buys the security property (§4), not a *language* boundary, and we get that boundary via network policy regardless of language; (2) splitting languages doubles the config-consistency surface — the exact class of bug this squad keeps fixing (env-var drift between AKS ConfigMap and docker-compose); (3) the money-math and typing advantages are recoverable in Python with `Decimal`-only arithmetic plus a strict-mypy gate on the mediator package specifically.

**Non-negotiable if Python is ratified:**
- `decimal.Decimal` everywhere for money; `float` banned in the policy/mediator packages (CI-enforced via a lint rule).
- `mypy --strict` on `app/policy/` and `app/mediator/`.
- Reuse the canonical `app/auth.py` verbatim — do not fork it.

**Ratification alternative:** if Danny wants the mediator in .NET, split into `banker-copilot-harness` (Python) + `banker-copilot-mediator` (.NET 10). Everything else in this document is language-neutral and holds unchanged. The cost is a second ConfigMap contract and a second Cosmos serializer to keep casing-aligned.

---

## 2. The declarative policy file

### 2.1 Where it lives and how it loads

`config/banker-copilot/policy.yaml`, mounted into the pod from a ConfigMap (`banker-copilot-policy`), and bind-mounted in docker-compose from the same repo path so local dev and AKS read a byte-identical file. Path is itself config: `POLICY_FILE_PATH` (default `/etc/banker-copilot/policy.yaml`, docker-compose override `./config/banker-copilot/policy.yaml`).

Changing the policy file is itself an **L3** action (§0, "changes to the harness's own policy/allowlist"): the agent may not propose it, and it ships through the normal GitOps/Flux path like any other manifest.

### 2.2 Threshold indirection — the "no magic numbers" mechanism

No action rule contains a literal number. Every threshold is a **named reference** into a `thresholds:` block, and every entry in that block declares its own env-var override:

```yaml
thresholds:
  transfer_l2_amount:
    kind: money            # money | count | ratio | duration_seconds
    currency_scale: 2
    default: "5000.00"     # decimal STRING — never a YAML float
    env: POLICY_TRANSFER_L2_AMOUNT
    description: "Transfer amount at or above which a supervisor co-signature is required."
```

Resolution order (highest wins): **environment variable → `default` in the policy file**. There is no third source; no code-level fallback is permitted. If a referenced name is missing from `thresholds:`, the service **fails to start** — fail-closed, never fail-open to a hardcoded value.

`kind: money` values are parsed as `Decimal` and rejected if they carry more precision than `currency_scale`. `kind: duration_seconds` values are integers.

### 2.3 Schema

```yaml
version: 1                    # integer; bumping requires a migration note

metadata:
  policy_id: string           # e.g. "banker-copilot-authority-v1"
  effective_from: RFC3339
  owner: string

defaults:
  rung: L2                    # fail-closed default for unlisted actions... see `unknown_action`
  unknown_action: deny        # deny | escalate_l3   (NEVER "allow")
  approval_ttl: <threshold-ref>
  evidence_required: [ list of evidence keys ]

thresholds:
  <name>:
    kind: money | count | ratio | duration_seconds
    currency_scale: int       # money only
    default: string           # ALWAYS a string, even for counts — avoids YAML type coercion
    env: SCREAMING_SNAKE_ENV_VAR
    description: string

signer_roles:                 # maps ladder rungs to who may sign; roles resolve against JWT `role` claim
  <role_key>:
    claim_values: [ "admin", "Admin" ]
    seniority: int            # higher = more senior; used by "how senior" escalators

evidence:                     # reusable evidence definitions the agent must attach to a proposal
  <evidence_key>:
    description: string
    source: string            # which existing REST endpoint supplies it
    required_fields: [ string ]

escalators:                   # global; each may RAISE the rung and/or RAISE signer count
  <escalator_key>:
    description: string       # human-readable; surfaced verbatim in the UI
    when: <predicate-expr>
    raise_to: L2 | L3
    min_signers: <int or threshold-ref>
    min_seniority: <int or threshold-ref>
    reason_template: string   # rendered with evaluation context, shown to the human signer

actions:
  <action_id>:
    description: string
    target:
      service: string         # logical service name (resolved via *_SERVICE_URL env, never a literal URL)
      method: GET|POST|PUT|PATCH|DELETE
      path: string            # templated, e.g. /api/admin/users/{userId}/lock
    agent_may_propose: bool   # false ⇒ hard L3; mediator rejects the proposal outright
    base_rung: L1 | L2 | L3
    base_signers: int
    payload_schema: <json-schema ref or inline>
    hash_fields: [ string ]   # ordered list of payload paths included in the signed hash (§6)
    evidence_required: [ evidence_key ]
    rules:                    # ordered; ALL are evaluated, none short-circuits (monotonic max)
      - when: <predicate-expr>
        raise_to: L2 | L3
        min_signers: int
        reason_template: string
    approval_ttl: <threshold-ref>
    batchable: bool           # batch sign allowed at all
    batch_max_items: <threshold-ref>
    idempotency: header | natural_key
```

**Predicate expression language** — deliberately tiny and total (no loops, no function calls, no I/O). Grammar: comparisons (`>= <= > < == !=`), boolean `and`/`or`/`not`, membership `in`, field access on a fixed context object (`payload.*`, `actor.*`, `customer.*`, `agent.*`, `session.*`), and `threshold("<name>")`. Numeric comparisons involving a `money` threshold coerce both sides to `Decimal`. Anything else is a load-time schema error. There is intentionally **no** `lower_to`, `exempt`, `override`, or `skip_approval` construct anywhere in the grammar — see §3.4.

### 2.4 Complete working example

Enumerated from the actual controllers/routes in this repo: `account-service/Controllers/AccountsController.cs`, `transaction-service/Controllers/{Transactions,Admin}Controller.cs`, `transfer-service/Controllers/TransfersController.cs`, `user-service/Controllers/{Admin,Users}Controller.cs`, `prompt-eval-service/Controllers/{Prompts,Evaluations}Controller.cs`, `ai-service/app/routes/api.py`, `account-opening-service/app/routes/api.py`.

```yaml
version: 1

metadata:
  policy_id: banker-copilot-authority-v1
  effective_from: "2026-09-04T00:00:00Z"
  owner: banking-demo-platform

defaults:
  rung: L2
  unknown_action: deny
  approval_ttl: approval_ttl_default_seconds
  evidence_required: [agent_rationale, actor_context]

#############################################
# THRESHOLDS — every number in this file lives here, and every one has an env override
#############################################
thresholds:
  approval_ttl_default_seconds:
    kind: duration_seconds
    default: "900"
    env: POLICY_APPROVAL_TTL_DEFAULT_SECONDS
    description: "Default lifetime of a pending approval before it becomes DENIED."
  approval_ttl_short_seconds:
    kind: duration_seconds
    default: "300"
    env: POLICY_APPROVAL_TTL_SHORT_SECONDS
    description: "Lifetime for time-critical approvals (fraud holds, account locks)."
  approval_ttl_long_seconds:
    kind: duration_seconds
    default: "86400"
    env: POLICY_APPROVAL_TTL_LONG_SECONDS
    description: "Lifetime for non-urgent review queues (account opening, prompt changes)."

  balance_adjust_l2_amount:
    kind: money
    currency_scale: 2
    default: "1000.00"
    env: POLICY_BALANCE_ADJUST_L2_AMOUNT
    description: "Absolute balance adjustment at or above which a supervisor co-signs."
  balance_adjust_l3_amount:
    kind: money
    currency_scale: 2
    default: "25000.00"
    env: POLICY_BALANCE_ADJUST_L3_AMOUNT
    description: "Absolute balance adjustment at or above which the harness refuses entirely."

  transfer_l2_amount:
    kind: money
    currency_scale: 2
    default: "5000.00"
    env: POLICY_TRANSFER_L2_AMOUNT
    description: "Transfer amount at or above which a supervisor co-signs."
  transfer_l3_amount:
    kind: money
    currency_scale: 2
    default: "50000.00"
    env: POLICY_TRANSFER_L3_AMOUNT
    description: "Transfer amount at or above which the harness refuses entirely."

  txn_manual_l2_amount:
    kind: money
    currency_scale: 2
    default: "2500.00"
    env: POLICY_TXN_MANUAL_L2_AMOUNT
    description: "Manually-booked transaction amount requiring supervisor co-signature."

  loan_l2_amount:
    kind: money
    currency_scale: 2
    default: "100000.00"
    env: POLICY_LOAN_L2_AMOUNT
    description: "Loan principal at or above which a supervisor co-signs. (Epic #140.)"
  loan_l3_amount:
    kind: money
    currency_scale: 2
    default: "1000000.00"
    env: POLICY_LOAN_L3_AMOUNT
    description: "Loan principal above the harness's authority envelope entirely."

  risk_override_l2_delta:
    kind: ratio
    default: "0.30"
    env: POLICY_RISK_OVERRIDE_L2_DELTA
    description: "Absolute change to an AI risk score at or above which a supervisor co-signs."

  event_replay_l2_limit:
    kind: count
    default: "1000"
    env: POLICY_EVENT_REPLAY_L2_LIMIT
    description: "Replay batch size at or above which a supervisor co-signs."

  bulk_fanout_l2_count:
    kind: count
    default: "5"
    env: POLICY_BULK_FANOUT_L2_COUNT
    description: "Number of distinct customers touched by one plan before bulk escalation fires."
  bulk_fanout_l3_count:
    kind: count
    default: "25"
    env: POLICY_BULK_FANOUT_L3_COUNT
    description: "Fan-out size beyond which the harness refuses to act at all."

  velocity_window_seconds:
    kind: duration_seconds
    default: "3600"
    env: POLICY_VELOCITY_WINDOW_SECONDS
    description: "Rolling window for counting same-actor mutating proposals."
  velocity_l2_count:
    kind: count
    default: "10"
    env: POLICY_VELOCITY_L2_COUNT
    description: "Proposals by one actor inside the velocity window before escalation fires."

  agent_confidence_l2_floor:
    kind: ratio
    default: "0.75"
    env: POLICY_AGENT_CONFIDENCE_L2_FLOOR
    description: "Agent self-reported confidence below which a supervisor co-signs."
  agent_confidence_l3_floor:
    kind: ratio
    default: "0.40"
    env: POLICY_AGENT_CONFIDENCE_L3_FLOOR
    description: "Confidence below which the proposal is not worth a human's time at all."

  high_risk_customer_score:
    kind: ratio
    default: "0.80"
    env: POLICY_HIGH_RISK_CUSTOMER_SCORE
    description: "Customer risk score at or above which the customer counts as high-risk."

  supervisor_seniority_min:
    kind: count
    default: "2"
    env: POLICY_SUPERVISOR_SENIORITY_MIN
    description: "Minimum seniority level that satisfies an L2 co-signature."

  batch_max_items_default:
    kind: count
    default: "10"
    env: POLICY_BATCH_MAX_ITEMS_DEFAULT
    description: "Maximum items in a single batch-sign request."

signer_roles:
  banker:
    claim_values: ["banker", "admin", "Admin"]
    seniority: 1
  supervisor:
    claim_values: ["supervisor", "admin", "Admin"]
    seniority: 2
  risk_officer:
    claim_values: ["risk_officer"]
    seniority: 3

evidence:
  agent_rationale:
    description: "The agent's stated reasoning and the tool calls that produced it."
    source: internal
    required_fields: [summary, tool_calls, confidence]
  actor_context:
    description: "Who is asking, their role, and the session they are in."
    source: internal
    required_fields: [actorId, role, sessionId]
  account_snapshot:
    description: "Current account state immediately before the proposed mutation."
    source: "GET {ACCOUNT_SERVICE_URL}/api/accounts/{id}"
    required_fields: [accountId, balance, ownerUserId, retrievedAt]
  recent_transactions:
    description: "Recent activity on the affected account."
    source: "GET {TRANSACTION_SERVICE_URL}/api/transactions/account/{accountId}"
    required_fields: [items, retrievedAt]
  risk_assessment:
    description: "Current AI risk score and contributing factors."
    source: "GET {ANOMALY_SERVICE_URL}/api/admin/scored-transactions/{txId}"
    required_fields: [riskScore, factors, scoredAt]
  kyc_packet:
    description: "Account-opening agent results: extraction, identity, compliance."
    source: "GET {ACCOUNT_OPENING_SERVICE_URL}/api/applications/{applicationId}"
    required_fields: [agentResults, status, auditTrail]
  customer_risk_profile:
    description: "Customer-level risk classification driving the high-risk escalator."
    source: "GET {ANOMALY_SERVICE_URL}/api/admin/stats"
    required_fields: [customerId, riskScore]
  policy_exceptions:
    description: "Underwriting/compliance exceptions raised against this case (POL-xxx)."
    source: internal
    required_fields: [codes]
  prior_decision:
    description: "The previous decision on this entity, if any, and who made it."
    source: internal
    required_fields: [decision, decidedBy, decidedAt]

#############################################
# ESCALATORS — global, monotonic, each carries a human-readable reason
#############################################
escalators:
  self_dealing:
    description: "The actor is a party to, or owner of, the thing they are acting on."
    when: >
      actor.userId == payload.targetUserId
      or actor.userId == customer.ownerUserId
      or actor.userId in customer.relatedUserIds
    raise_to: L2
    min_seniority: supervisor_seniority_min
    reason_template: "Escalated to supervisor co-signature: you are a party to this {action_label}. Separation of duties requires a different signer."

  bulk_fanout:
    description: "One agent plan mutates many distinct customers."
    when: session.distinctCustomersInPlan >= threshold("bulk_fanout_l2_count")
    raise_to: L2
    reason_template: "Escalated: this plan touches {session.distinctCustomersInPlan} distinct customers (threshold {threshold_value}). Bulk changes require a supervisor."

  bulk_fanout_refuse:
    description: "Fan-out beyond the harness's authority envelope."
    when: session.distinctCustomersInPlan >= threshold("bulk_fanout_l3_count")
    raise_to: L3
    reason_template: "Refused: this plan touches {session.distinctCustomersInPlan} customers, beyond the harness limit of {threshold_value}. Take this outside the Copilot."

  velocity:
    description: "The actor has proposed an unusual number of mutations recently."
    when: actor.mutatingProposalsInWindow >= threshold("velocity_l2_count")
    raise_to: L2
    reason_template: "Escalated: {actor.mutatingProposalsInWindow} mutating proposals in the last {velocity_window_label}. Elevated activity requires a second signer."

  low_confidence:
    description: "The agent is not confident in its own recommendation."
    when: agent.confidence < threshold("agent_confidence_l2_floor")
    raise_to: L2
    reason_template: "Escalated: agent confidence {agent.confidence} is below {threshold_value}. A supervisor should review the reasoning."

  very_low_confidence:
    description: "Confidence so low the proposal should not consume human attention."
    when: agent.confidence < threshold("agent_confidence_l3_floor")
    raise_to: L3
    reason_template: "Refused: agent confidence {agent.confidence} is below the minimum of {threshold_value}. The agent must gather more evidence and re-plan."

  policy_exception:
    description: "A compliance/underwriting exception (POL-xxx) is open on this case."
    when: not (policy_exceptions.codes == [])
    raise_to: L2
    min_seniority: supervisor_seniority_min
    reason_template: "Escalated: open policy exception(s) {policy_exceptions.codes}. Exceptions are never single-signature."

  high_risk_customer:
    description: "The affected customer is classified high-risk."
    when: customer.riskScore >= threshold("high_risk_customer_score")
    raise_to: L2
    reason_template: "Escalated: customer risk score {customer.riskScore} is at or above {threshold_value}."

  anomalous_session:
    description: "The harness session itself looks abnormal (new device, odd hours, impossible travel)."
    when: session.anomalyFlags != []
    raise_to: L2
    reason_template: "Escalated: this session was flagged as anomalous ({session.anomalyFlags}). A second identity must confirm."

#############################################
# ACTIONS — one entry per real mutating endpoint in this repo
#############################################
actions:

  account.balance.adjust:
    description: "Adjust an account balance (credit or debit)."
    target: { service: account-service, method: POST, path: "/api/accounts/{accountId}/balance" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [accountId, amount, currency, reasonCode, memo]
    evidence_required: [agent_rationale, actor_context, account_snapshot, recent_transactions]
    rules:
      - when: abs(payload.amount) >= threshold("balance_adjust_l2_amount")
        raise_to: L2
        min_signers: 2
        reason_template: "Adjustment of {payload.amount} is at or above {threshold_value}; supervisor co-signature required."
      - when: abs(payload.amount) >= threshold("balance_adjust_l3_amount")
        raise_to: L3
        reason_template: "Adjustment of {payload.amount} exceeds the harness limit of {threshold_value}. Use the core banking back office."
    approval_ttl: approval_ttl_default_seconds
    batchable: false
    idempotency: header

  transfer.initiate:
    description: "Initiate a transfer between accounts on the customer's behalf."
    target: { service: transfer-service, method: POST, path: "/api/transfers" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [fromAccountId, toAccountId, amount, currency, memo]
    evidence_required: [agent_rationale, actor_context, account_snapshot, recent_transactions, customer_risk_profile]
    rules:
      - when: payload.amount >= threshold("transfer_l2_amount")
        raise_to: L2
        min_signers: 2
        reason_template: "Transfer of {payload.amount} is at or above {threshold_value}; supervisor co-signature required."
      - when: payload.amount >= threshold("transfer_l3_amount")
        raise_to: L3
        reason_template: "Transfer of {payload.amount} exceeds the harness limit of {threshold_value}."
    approval_ttl: approval_ttl_short_seconds
    batchable: false
    idempotency: header

  transaction.create:
    description: "Book a manual transaction (adjustment, fee reversal, correction)."
    target: { service: transaction-service, method: POST, path: "/api/transactions" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [accountId, amount, type, description, reasonCode]
    evidence_required: [agent_rationale, actor_context, account_snapshot, recent_transactions]
    rules:
      - when: abs(payload.amount) >= threshold("txn_manual_l2_amount")
        raise_to: L2
        min_signers: 2
        reason_template: "Manual booking of {payload.amount} is at or above {threshold_value}; supervisor co-signature required."
    approval_ttl: approval_ttl_default_seconds
    batchable: false
    idempotency: header

  user.lock:
    description: "Lock a customer account (fraud hold, compliance freeze)."
    target: { service: user-service, method: PUT, path: "/api/admin/users/{userId}/lock" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [userId, reasonCode, memo]
    evidence_required: [agent_rationale, actor_context, customer_risk_profile, recent_transactions]
    rules: []
    approval_ttl: approval_ttl_short_seconds
    batchable: true
    batch_max_items: batch_max_items_default
    idempotency: natural_key

  user.unlock:
    description: "Release a lock on a customer account."
    target: { service: user-service, method: PUT, path: "/api/admin/users/{userId}/unlock" }
    agent_may_propose: true
    base_rung: L2          # unlocking is the risk-bearing direction — never single-signature
    base_signers: 2
    hash_fields: [userId, reasonCode, memo]
    evidence_required: [agent_rationale, actor_context, prior_decision, customer_risk_profile]
    rules: []
    approval_ttl: approval_ttl_default_seconds
    batchable: false       # L2 is never batchable (see §8.6)
    idempotency: natural_key

  user.password.reset:
    description: "Force-reset a customer's password."
    target: { service: user-service, method: PUT, path: "/api/admin/users/{userId}/reset-password" }
    agent_may_propose: true
    base_rung: L2          # account-takeover primitive
    base_signers: 2
    hash_fields: [userId, reasonCode]   # NOTE: the new secret is deliberately NOT hashed — see §6.5
    evidence_required: [agent_rationale, actor_context, prior_decision]
    rules: []
    approval_ttl: approval_ttl_short_seconds
    batchable: false
    idempotency: header

  user.role.promote:
    description: "Grant administrative role to a user."
    target: { service: user-service, method: POST, path: "/api/admin/promote" }
    agent_may_propose: false     # HARD L3 — mediator refuses to create a proposal
    base_rung: L3
    base_signers: 2
    hash_fields: [userId, role]
    evidence_required: []
    rules: []
    approval_ttl: approval_ttl_default_seconds
    batchable: false
    idempotency: header

  user.delete:
    description: "Delete a user record."
    target: { service: user-service, method: DELETE, path: "/api/admin/users/{userId}" }
    agent_may_propose: false     # HARD L3
    base_rung: L3
    base_signers: 2
    hash_fields: [userId]
    evidence_required: []
    rules: []
    approval_ttl: approval_ttl_default_seconds
    batchable: false
    idempotency: natural_key

  account.delete:
    description: "Close/delete a customer account. No endpoint exists today; reserved so the ladder is defined before the capability lands."
    target: { service: account-service, method: DELETE, path: "/api/accounts/{accountId}" }
    agent_may_propose: false     # HARD L3
    base_rung: L3
    base_signers: 2
    hash_fields: [accountId]
    evidence_required: []
    rules: []
    approval_ttl: approval_ttl_default_seconds
    batchable: false
    idempotency: natural_key

  account_opening.application.review:
    description: "Approve / reject / return an account-opening application."
    target: { service: account-opening-service, method: PATCH, path: "/api/applications/{applicationId}/review" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [applicationId, decision, notes]
    evidence_required: [agent_rationale, actor_context, kyc_packet, policy_exceptions, customer_risk_profile]
    rules:
      - when: payload.decision == "approved" and not (policy_exceptions.codes == [])
        raise_to: L2
        min_signers: 2
        reason_template: "Approving an application with open exception(s) {policy_exceptions.codes} requires a supervisor."
    approval_ttl: approval_ttl_long_seconds
    batchable: true
    batch_max_items: batch_max_items_default
    idempotency: natural_key

  account_opening.application.resubmit:
    description: "Re-run a failed stage of the account-opening agent pipeline."
    target: { service: account-opening-service, method: POST, path: "/api/applications/{applicationId}/resubmit" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [applicationId, failedStage]
    evidence_required: [agent_rationale, actor_context, kyc_packet]
    rules: []
    approval_ttl: approval_ttl_long_seconds
    batchable: true
    batch_max_items: batch_max_items_default
    idempotency: natural_key

  flagged_transaction.review:
    description: "Clear or confirm a flagged (suspicious) transaction."
    target: { service: ai-service, method: PUT, path: "/api/admin/flagged-transactions/{txId}/review" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [txId, decision, rationale]
    evidence_required: [agent_rationale, actor_context, risk_assessment, recent_transactions, customer_risk_profile]
    rules:
      - when: payload.decision == "cleared" and customer.riskScore >= threshold("high_risk_customer_score")
        raise_to: L2
        min_signers: 2
        reason_template: "Clearing a flag on a high-risk customer (score {customer.riskScore}) requires a supervisor."
    approval_ttl: approval_ttl_short_seconds
    batchable: true
    batch_max_items: batch_max_items_default
    idempotency: natural_key

  risk_score.override:
    description: "Override an AI-produced risk score on a scored transaction."
    target: { service: ai-service, method: PUT, path: "/api/admin/scored-transactions/{txId}/override" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [txId, decision, correctedScore, rationale]
    evidence_required: [agent_rationale, actor_context, risk_assessment]
    rules:
      - when: abs(payload.correctedScore - risk_assessment.riskScore) >= threshold("risk_override_l2_delta")
        raise_to: L2
        min_signers: 2
        reason_template: "Score change of {delta} is at or above {threshold_value}; a supervisor must co-sign a material model override."
    approval_ttl: approval_ttl_default_seconds
    batchable: false
    idempotency: header

  risk_score.rescore:
    description: "Re-run scoring on a transaction (read-mostly, but produces a new stored score)."
    target: { service: ai-service, method: POST, path: "/api/admin/scored-transactions/{txId}/rescore" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [txId]
    evidence_required: [agent_rationale, actor_context]
    rules: []
    approval_ttl: approval_ttl_default_seconds
    batchable: true
    batch_max_items: batch_max_items_default
    idempotency: natural_key

  prompt_template.change:
    description: "Create, update, or delete a prompt template used by production agents."
    target: { service: prompt-eval-service, method: PUT, path: "/api/evaluations/prompts/{promptId}" }
    agent_may_propose: false     # HARD L3 — this changes the behaviour of the agents themselves
    base_rung: L3
    base_signers: 2
    hash_fields: [promptId, name, content, version]
    evidence_required: []
    rules: []
    approval_ttl: approval_ttl_long_seconds
    batchable: false
    idempotency: header

  evaluation.run:
    description: "Launch a prompt evaluation run (consumes model quota, writes evaluation-runs)."
    target: { service: prompt-eval-service, method: POST, path: "/api/evaluations/run" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [promptTemplateId, datasetId, evaluators]
    evidence_required: [agent_rationale, actor_context]
    rules: []
    approval_ttl: approval_ttl_long_seconds
    batchable: false
    idempotency: header

  event.replay:
    description: "Replay banking events from the stream (transaction-service admin)."
    target: { service: transaction-service, method: POST, path: "/api/admin/replay-events" }
    agent_may_propose: true
    base_rung: L2                # replay has blast radius across every consumer; never single-signature
    base_signers: 2
    hash_fields: [limit]
    evidence_required: [agent_rationale, actor_context]
    rules:
      - when: payload.limit >= threshold("event_replay_l2_limit")
        raise_to: L2
        min_signers: 2
        reason_template: "Replay of {payload.limit} events is at or above {threshold_value}."
    approval_ttl: approval_ttl_default_seconds
    batchable: false
    idempotency: header

  loan.decision:
    description: "Record an underwriting decision on a loan application. FUTURE — depends on epic #140 loan-origination-service."
    target: { service: loan-origination-service, method: POST, path: "/api/loans/{loanId}/decision" }
    agent_may_propose: true
    base_rung: L1
    base_signers: 1
    hash_fields: [loanId, decision, principal, currency, rate, termMonths, conditions]
    evidence_required: [agent_rationale, actor_context, kyc_packet, policy_exceptions, customer_risk_profile, prior_decision]
    rules:
      - when: payload.principal >= threshold("loan_l2_amount")
        raise_to: L2
        min_signers: 2
        reason_template: "Principal of {payload.principal} is at or above {threshold_value}; supervisor co-signature required."
      - when: payload.principal >= threshold("loan_l3_amount")
        raise_to: L3
        reason_template: "Principal of {payload.principal} exceeds the harness limit of {threshold_value}."
      - when: payload.decision == "CONDITIONAL"
        raise_to: L2
        min_signers: 2
        reason_template: "CONDITIONAL verdicts are never single-signature."
      - when: payload.decision == "DECLINE"
        raise_to: L3
        reason_template: "Adverse action requires the formal decline workflow outside the Copilot."
    approval_ttl: approval_ttl_long_seconds
    batchable: false
    idempotency: header
```

### 2.5 Deliberately out of scope (read-only or customer-self-service)

`GET` endpoints are unrestricted for the agent within its capability allowlist. Customer self-service mutations — `PUT /api/users/me/password`, `/me/avatar`, `/me/categories`, `POST /api/users/register`, `POST /api/accounts`, `POST /api/applications`, `POST /api/applications/{id}/documents`, `POST /api/budget/categorize` — are **not in the banker capability allowlist at all**. The agent cannot reach them; they need no ladder entry. This is an allowlist, so omission = denial.

### 2.6 CI guard — "no magic numbers"

A test in the new service's suite (`tests/test_policy_no_literals.py`) walks the parsed policy AST and fails if:
1. any `when` expression contains a numeric or money literal not wrapped in `threshold(...)`;
2. any `threshold` entry lacks an `env` key;
3. any `<threshold-ref>` names an entry absent from `thresholds:`;
4. any `default` for `kind: money` is a YAML float rather than a string;
5. the mediator source tree contains a numeric literal in a comparison against a payload field (AST lint).

---

## 3. Policy evaluation algorithm

### 3.1 Inputs and output

```
EvaluationContext:
  action_id      : str
  payload        : dict                 # the exact body that would be sent downstream
  actor          : { userId, username, role, seniority, sessionId,
                     mutatingProposalsInWindow: int }
  customer       : { customerId, ownerUserId, relatedUserIds[], riskScore: Decimal }
  agent          : { agentId, confidence: Decimal, toolCalls[], rationale }
  policy_exceptions : { codes: [str] }
  session        : { sessionId, distinctCustomersInPlan: int, anomalyFlags: [str] }
  evidence       : { <evidence_key>: <collected evidence document> }

PolicyDecision:
  action_id          : str
  admissible         : bool             # false ⇒ agent may not even propose
  required_rung      : "L1" | "L2" | "L3"
  required_signers   : [ SignerRequirement ]   # ordered
  fired_escalators   : [ { key, reason, raised_to, threshold_name, threshold_value } ]
  base_rung          : str              # for the audit record and the UI diff
  payload_hash       : str
  expires_at         : RFC3339
  evidence_gaps      : [ evidence_key ] # non-empty ⇒ proposal rejected as under-evidenced

SignerRequirement:
  ordinal            : int
  min_seniority      : int
  must_differ_from   : [ userId ]       # separation of duties
  satisfied_by       : userId | null
```

### 3.2 Pseudocode

```python
RUNG_ORDER = {"L1": 1, "L2": 2, "L3": 3}   # total order; the ONLY ordering in the engine

def evaluate(ctx: EvaluationContext, policy: Policy, cfg: ResolvedThresholds) -> PolicyDecision:

    # ---- 1. Action must be known. Unknown ⇒ fail closed. -----------------------
    action = policy.actions.get(ctx.action_id)
    if action is None:
        return DENY(reason="Unknown action '%s'. The harness only performs "
                           "explicitly allowlisted actions." % ctx.action_id)

    # ---- 2. Hard L3: agent may not even propose. ------------------------------
    if not action.agent_may_propose:
        return DENY(rung="L3",
                    reason="'%s' is outside the Copilot's authority. It cannot be "
                           "proposed here; use the back-office workflow." % action.description)

    # ---- 3. Evidence completeness gate (before any policy math). --------------
    required_ev = union(policy.defaults.evidence_required, action.evidence_required)
    gaps = [k for k in required_ev if not evidence_complete(ctx.evidence.get(k), policy.evidence[k])]
    if gaps:
        return UNDER_EVIDENCED(gaps)   # agent must gather more, then re-propose

    # ---- 4. Baseline from the action's static rung. ---------------------------
    rung     = action.base_rung
    signers  = action.base_signers
    seniority_needed = policy.signer_roles["banker"].seniority
    fired    = []

    # ---- 5. Action-local rules. ALL evaluated; none short-circuits. -----------
    for rule in action.rules:                       # order is irrelevant to the result
        if predicate_eval(rule.when, ctx, cfg):
            rung             = rung_max(rung, rule.raise_to)
            signers          = max(signers, rule.min_signers or 0)
            seniority_needed = max(seniority_needed, resolve(rule.min_seniority, cfg) or 0)
            fired.append(Fired(rule.key, render(rule.reason_template, ctx, cfg),
                               rule.raise_to, rule.threshold_name,
                               cfg.value_of(rule.threshold_name)))

    # ---- 6. Global escalators. Same combinator, same monotonicity. ------------
    for esc in policy.escalators.values():
        if predicate_eval(esc.when, ctx, cfg):
            rung             = rung_max(rung, esc.raise_to)
            signers          = max(signers, resolve(esc.min_signers, cfg) or 0)
            seniority_needed = max(seniority_needed, resolve(esc.min_seniority, cfg) or 0)
            fired.append(Fired(esc.key, render(esc.reason_template, ctx, cfg),
                               esc.raise_to, esc.threshold_name,
                               cfg.value_of(esc.threshold_name)))

    # ---- 7. Structural floors that policy config cannot weaken. ---------------
    signers = max(signers, 1)                       # a human ALWAYS signs
    if rung == "L2":
        signers          = max(signers, 2)          # dual control is definitional
        seniority_needed = max(seniority_needed, cfg.int_of("supervisor_seniority_min"))
    if rung == "L3":
        return DENY(rung="L3", fired=fired,
                    reason="Escalated out of the harness: " +
                           "; ".join(f.reason for f in fired if f.raised_to == "L3"))

    # ---- 8. Build signer slots with separation of duties. ---------------------
    reqs = [SignerRequirement(ordinal=0,
                              min_seniority=policy.signer_roles["banker"].seniority,
                              must_differ_from=[])]
    for i in range(1, signers):
        reqs.append(SignerRequirement(
            ordinal=i,
            min_seniority=seniority_needed,
            must_differ_from=[ctx.actor.userId]))   # co-signer is never the requester

    # ---- 9. Bind the payload and the clock. -----------------------------------
    ttl  = cfg.int_of(action.approval_ttl or policy.defaults.approval_ttl)
    return PolicyDecision(
        action_id        = ctx.action_id,
        admissible       = True,
        required_rung    = rung,
        base_rung        = action.base_rung,
        required_signers = reqs,
        fired_escalators = fired,
        payload_hash     = canonical_hash(ctx.payload, action.hash_fields),   # §6
        expires_at       = now_utc() + seconds(ttl),
        evidence_gaps    = [],
    )


def rung_max(a: str, b: str | None) -> str:
    if b is None:
        return a
    return a if RUNG_ORDER[a] >= RUNG_ORDER[b] else b
```

### 3.3 The "why", surfaced to humans

`fired_escalators[]` is the UI contract. Each entry renders as one line in the approval card, e.g.:

> **Escalated to supervisor co-signature**
> • Transfer of 7,500.00 is at or above 5,000.00 — *(POLICY_TRANSFER_L2_AMOUNT)*
> • Customer risk score 0.86 is at or above 0.80 — *(POLICY_HIGH_RISK_CUSTOMER_SCORE)*
> Base authority for this action was **L1**; it is now **L2**.

Naming the threshold's env key in the UI is deliberate: it makes the policy auditable by the person signing, and makes "why did this escalate?" a one-line answer rather than a support ticket. The rendered reason strings are frozen into the approval document at proposal time, so an approval read back a year later shows the reasons *as they were evaluated*, not as re-rendered against today's config.

### 3.4 Monotonicity — why escalators can only raise

Let `(R, ≤)` be the total order `L1 < L2 < L3`. Let `b ∈ R` be the action's `base_rung` and `E = {e₁…eₙ}` the set of fired rules/escalators, each contributing `rᵢ ∈ R`.

The engine computes `final = max(b, r₁, …, rₙ)`.

1. `max` over a total order satisfies `max(x, y) ≥ x` for all `y`. Therefore `final ≥ b`: **no escalator can produce a rung below the action's base.**
2. `max` is commutative and associative, so evaluation order is irrelevant — there is no "last rule wins" hazard, and no rule can undo an earlier one.
3. Adding a fired escalator can only weakly increase the result: `max(S ∪ {r}) ≥ max(S)`. **Firing more escalators never lowers the outcome.**
4. The same argument applies pointwise to `required_signers` and `min_seniority`, which are also folded with `max` over ℕ.
5. **The grammar has no lowering operator.** The schema (§2.3) admits only `raise_to`, `min_signers`, `min_seniority`. There is no `lower_to`, `set_rung`, `exempt`, `waive`, or `skip_approval`. A policy author *cannot express* a downgrade, so this is not a discipline the reviewer has to enforce — it is unrepresentable.
6. Step 7 of the algorithm applies floors *after* all policy input, and those floors also use `max`. Config can raise `signers` above 1; nothing can push it below 1.

Corollary: a mis-tuned or even maliciously-edited threshold value can make the system *more* restrictive or fail to escalate a case it should have — but it can never turn a signature-required action into an autonomous one, because `signers ≥ 1` is a code-level floor outside the config surface. The worst config-driven outcome is "one banker signed something that should have needed two," never "no human signed."

### 3.5 Determinism

`evaluate()` is a pure function of `(ctx, policy, cfg)`. It performs no I/O — evidence is collected *before* evaluation, by the proposal pipeline. The resolved `cfg` snapshot and `policy.metadata.policy_id` are recorded on the approval document, so a decision is exactly reproducible from the audit record.

---

## 4. Enforcement architecture

### 4.1 The threat, stated plainly

The policy engine is worthless if the agent can skip it. The question is not "will the agent behave?" — an LLM under adversarial prompting is an untrusted caller. The question is: **what makes an unsigned write structurally impossible, assuming the agent is fully compromised and actively trying to bypass the ladder?**

### 4.2 What this repo looks like today (measured)

- **Cluster:** namespace `banking-demo`, labelled `istio.io/rev: asm-1-28` → Azure Service Mesh is present and sidecar-injecting. Deployments already carry `traffic.sidecar.istio.io/excludeOutboundPorts: "10000"` (Azure Managed Redis).
- **Workload identity:** every deployment uses `serviceAccountName: banking-workload-identity` and `azure.workload.identity/use: "true"`. **A single shared KSA across all services.** In-mesh, that means every workload presents the *same* SPIFFE identity — Istio cannot currently tell transfer-service from ai-service.
- **Service-to-service auth:** HS256 JWTs minted by `user-service` (`AuthService.cs`: claims `sub`, `unique_name`, `jti`, `role`), signed with a **symmetric key shared by every service** via the `jwt-key` secret. Every service validates `ValidIssuer = user-service` and `ValidAudience` = the same value (`banking-demo`). Python services use the canonical `app/auth.py` with the same key/issuer/audience.
- **Consequence:** today, *any* holder of a banker's bearer token can call `POST /api/transfers` directly. Audience validation exists but does not discriminate, because there is exactly one audience.

That last point is the crux: **the current token model provides no way to say "this principal may talk to the mediator but not to transfer-service."** Fixing it is the core of this section.

### 4.3 The mediator (chokepoint) model

```
  Browser (thin client)
        │  banker JWT   aud=banking-demo
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │ banker-copilot-service            (KSA: banker-copilot)  │
  │                                                          │
  │  ┌────────────────┐        in-process,                   │
  │  │ HARNESS plane  │  ───►  no network hop  ───►  ┌──────────────────┐
  │  │ Foundry Agent  │                             │ MEDIATOR plane   │
  │  │ Service host   │  ◄── tool results ◄──       │ policy + approval│
  │  └────────────────┘                             │ + executor       │
  │        │                                        └────────┬─────────┘
  │        │ tool calls                                      │
  └────────┼─────────────────────────────────────────────────┼──────────┘
           │                                                 │
           ▼                                                 ▼
   Azure AI Foundry Agent Service              domain services (account, transfer,
   (model + tool-call protocol)                 transaction, user, ai, account-opening,
                                                prompt-eval)
```

Every agent tool is a thin wrapper over a mediator call. There is no HTTP client in the harness plane pointed at a domain service — **the harness plane owns no downstream credential at all.** Read tools go through `POST /internal/mediate/read`; write tools go through `POST /internal/mediate/propose`, which *never* executes. Execution happens only on `POST /api/copilot/approvals/{id}/execute`, and that handler's first three lines are:

```
approval = store.get(id)                            # point read
assert_signatures_complete(approval, policy)        # count, seniority, distinct identities
assert_payload_hash_matches(approval, request)      # §6
```

The executor is the *only* component in the system holding downstream write credentials.

### 4.4 Defence in depth — five independent layers

Any one of these alone is bypassable. All five must fail simultaneously for an unsigned write to land.

**Layer 1 — Token audience separation (the highest-value change).**
Introduce a second audience. `user-service` learns to mint a **harness token** with `aud=banking-copilot` (config: `JWT_AUDIENCE_COPILOT`, default `banking-copilot`) alongside today's `aud=banking-demo`. The harness plane and the Foundry agent receive *only* the `banking-copilot`-audience token. Domain services keep validating `aud=banking-demo` and change not at all. Result: if a compromised agent constructs a raw HTTP call to `POST /api/transfers`, transfer-service rejects it at `ValidateAudience` — **401 before any handler runs**, with zero new code in transfer-service. This is the single cheapest, strongest control available, precisely because the repo already validates audience everywhere; it just needs a second value.

**Layer 2 — Per-execution, single-use, hash-bound credentials.**
The mediator's executor mints a short-lived downstream token per execution, with claims:

| Claim | Meaning |
|---|---|
| `aud` | `banking-demo` (accepted by domain services) |
| `sub` | the delegated banker's userId — the action is attributed to the human, per the delegated-identity directive |
| `act` | `banker-copilot-service` (actor claim: who is carrying the delegation) |
| `apid` | approval document id |
| `pah` | payload hash (§6) |
| `scp` | the single action_id authorised, e.g. `transfer.initiate` |
| `exp` | `now + EXECUTION_TOKEN_TTL_SECONDS` (config, default `60`) |
| `jti` | recorded; replay of the same `jti` is refused by the executor |

The agent never sees this token — it is created inside the execute handler and dies with the request. Phase 2 (needs Danny + Basher, touches every service): domain services optionally require `apid`/`pah` and reject writes lacking them when `REQUIRE_APPROVAL_CLAIMS=true`. That closes the loop end-to-end, but it is *not* needed for the primary guarantee, which Layer 1 already provides.

**Layer 3 — Mesh authorization (Istio / ASM).**
Give the harness its **own** KSA (`banker-copilot`) instead of the shared `banking-workload-identity`. That yields a distinct SPIFFE identity and makes mesh policy expressible for the first time:

- `PeerAuthentication` → `STRICT` mTLS in `banking-demo`.
- Namespace-wide default-deny `AuthorizationPolicy`.
- Per-service `AuthorizationPolicy` allowing `principals: [<mesh identity of banking-workload-identity>]` and the mediator's identity — but **not** the harness identity — as sources for domain services.
- `AuthorizationPolicy` on `banker-copilot-service` allowing the ingress gateway only.

If harness and mediator are split into two pods (Danny's call, §1.3), this becomes a genuine network partition: the harness pod's egress allowlist is `{mediator, Foundry endpoint, OTLP collector}` and nothing else. In one pod they share a sidecar identity, so Layer 3 protects the perimeter but not the internal split — which is why Layers 1 and 2 carry the load in the single-service design.

**Layer 4 — Capability allowlist at tool-registration time.**
The tool registry is built *from* `policy.actions`. An action with `agent_may_propose: false` yields no tool at all — it is not in the Foundry agent's tool schema, so the model has no name to call. Actions absent from the policy file are similarly unreachable (`unknown_action: deny`). Prompt injection cannot invent a tool that was never registered.

**Layer 5 — Structural code invariants in the mediator.**
- The `propose` code path has no reference to the HTTP executor. Enforced by an import-graph test: `app.mediator.propose` may not import `app.mediator.executor`.
- `transition_to_signed()` takes a `HumanSigner` type constructed only from a verified end-user bearer token that arrived on an inbound HTTP request. There is no constructor reachable from agent context. An agent-originated call cannot even *build the argument*.
- The executor refuses any approval whose `signedBy` list contains a principal with `act` present (i.e. a delegated/service principal) — agents cannot appear as signers, by type and by runtime assertion.

### 4.5 "What stops a clever agent from calling transfer-service directly?" — answered

| Attack | Blocked by |
|---|---|
| Agent builds a raw HTTP call to `TRANSFER_SERVICE_URL` | **Layer 1**: its token carries `aud=banking-copilot`; transfer-service validates `aud=banking-demo` → 401. **Layer 3**: if split-pod, egress denied before the packet leaves. |
| Agent steals the banker's browser token from conversation context | Mitigated by never placing the browser token in agent-visible context — the harness exchanges it for a `banking-copilot` token at session start and holds the original in a server-side session record the model cannot read. Residual risk R2 (§9). |
| Agent replays a previously-issued execution token | `exp` ≤ 60s + `jti` single-use ledger in Redis (`copilot:exec:jti:<jti>`, TTL = token TTL). |
| Agent mutates the payload after the human signs ("approved $5k, executed $50k") | **§6** — executor recomputes the canonical hash from the outbound body and compares to `pah`. Mismatch ⇒ 409 + `ActionExecutionFailed` audit event. |
| Agent calls `execute` on its own proposal | `assert_signatures_complete` requires ≥1 `HumanSigner`; a proposal with zero signatures cannot pass. Agents cannot construct a `HumanSigner` (Layer 5). |
| Agent self-signs by impersonating the banker's identity | Signing requires a *fresh inbound* request bearing a `banking-demo`-audience end-user token; the agent has no such token (Layer 1), and separation-of-duties additionally forbids the requester from filling a co-signer slot. |
| Agent proposes an L3 action | Not in the tool schema (Layer 4); rejected at step 2 of `evaluate()` even if injected. |
| Agent edits the policy file to lower a threshold | Policy is a read-only ConfigMap mount; the pod filesystem is `readOnlyRootFilesystem: true` (already the repo standard); env vars are set at pod spec level. `prompt_template.change` and policy edits are hard-L3. |
| Compromised agent floods proposals | Velocity escalator raises the rung; plus a mediator-level rate limit (`COPILOT_PROPOSALS_PER_MINUTE`, config). |

### 4.6 Local dev (docker-compose) parity

Docker-compose has no Istio and no workload identity, and must keep working. Dual-mode, matching the existing repo convention:

| Control | AKS (`AZURE_CLIENT_ID` set) | docker-compose (`AZURE_CLIENT_ID` absent) |
|---|---|---|
| Audience separation (Layer 1) | **Active** — real second audience | **Active** — same HS256 key, `JWT_AUDIENCE_COPILOT=banking-copilot`. Costs nothing locally and keeps the control tested. |
| Execution token (Layer 2) | Active, minted per execution | Active — HS256 with the shared dev key |
| Mesh policy (Layer 3) | Active | N/A — documented as an environment gap, not silently skipped. Startup logs a single warning: `mesh_enforcement=unavailable`. |
| Tool allowlist (Layer 4) | Active | Active — same policy file, bind-mounted |
| Code invariants (Layer 5) | Active | Active |
| Approval store | Cosmos | Cosmos emulator, or the repo's existing local fallback path |
| Signing key | Key Vault via CSI | `APPROVAL_SIGNING_MODE=hmac` with the dev key |

The rule is: **the only control that degrades locally is the one that is a property of the cluster.** Everything else runs identically, so a developer cannot accidentally build against a weaker model.

---

## 5. Approval store (Cosmos DB)

### 5.1 Context from the existing account

`infra/cloud/cosmos.tf`: database `BankingDemo`, **serverless**, `Session` consistency, `public_network_access_enabled = false` (private endpoint only). Existing containers: `Users` (`/id`), `Accounts` (`/id`), `Transactions` (`/accountId`), `Transfers` (`/id`), `login-audits` (`/id`, `default_ttl` 30d), `ChatSessions` (`/userId`), `account-applications` (`/id`).

Serverless matters: there is no autoscale to hide sloppy cross-partition queries, and RU is billed per request. It also means no dedicated throughput per container, so container count is cheap.

### 5.2 Container

| Property | Value |
|---|---|
| Name | `copilot-approvals` |
| Database | `BankingDemo` |
| Partition key | `/requesterId` |
| `default_ttl` | `-1` (TTL **enabled but not defaulted**) — see §5.4 |
| Terraform | `infra/cloud/cosmos.tf`, matching the existing `azurerm_cosmosdb_sql_container` style |

**Partition key justification.** The dominant read is "the approvals belonging to the banker who is looking at the screen." Keying on `/requesterId` makes *that* query single-partition and cheap, and gives high cardinality (one partition per banker) with naturally bounded per-partition size (an individual banker's approvals over a retention window). Rejected alternatives:

- `/id` — matches the repo's habit for `Users`/`Accounts`/`Transfers` and gives the cheapest point reads, but turns *every* list query into a cross-partition fan-out. Rejected: the approval queue is a list-first workload, unlike those containers.
- `/status` — catastrophic. Three or four values ⇒ hot partitions and a physical partition limit hit as soon as volume grows.
- `/sessionId` — good write locality, but nobody queries by session; the human queues would all be cross-partition.
- `/tenantId` — no tenancy concept exists in this repo.

**Honest limitation:** "approvals awaiting supervisor" is *inherently* cross-partition, because separation of duties guarantees the co-signer is not the requester, so the supervisor's queue spans many requesters' partitions. This is accepted: L2 volume is low by construction (it is the exception path), and the query is bounded by a composite index and a page size. If it ever becomes hot, the escape hatch is a second lightweight container `copilot-approval-queue` partitioned by `/queueKey` holding pointer documents — explicitly deferred as premature.

### 5.3 Document schema

Camel-cased throughout, and the .NET/Python serializer settings must agree — see `.squad/skills/cosmos-casing-audit`. If Danny ratifies a split-language design, this schema is the exact place casing drift will bite.

```jsonc
{
  "id": "apr_01JQ8Z3M4W7K",
  "requesterId": "user_9f3a",              // PARTITION KEY — the acting banker
  "docType": "approval",

  "status": "pending",                      // proposed | pending | signed | denied | expired
  "actionId": "transfer.initiate",
  "actionLabel": "Initiate a transfer between accounts",

  "sessionId": "sess_7c21",
  "agentId": "asst_banker_copilot_v1",
  "correlationId": "0af7651916cd43dd8448eb211c80319c",   // matches X-Correlation-ID convention

  "target": {
    "service": "transfer-service",
    "method": "POST",
    "pathTemplate": "/api/transfers",
    "pathParams": {}
  },

  "payload": { "fromAccountId": "acc_11", "toAccountId": "acc_42",
               "amount": "7500.00", "currency": "USD", "memo": "wire recall" },
  "payloadHash": "sha256:9f2b…",           // §6 — what the signature binds to
  "hashFields": ["fromAccountId","toAccountId","amount","currency","memo"],
  "canonicalizationVersion": 1,

  "policy": {
    "policyId": "banker-copilot-authority-v1",
    "policyVersion": 1,
    "baseRung": "L1",
    "requiredRung": "L2",
    "requiredSigners": 2,
    "minSeniority": 2,
    "firedEscalators": [
      { "key": "transfer_amount_l2", "raisedTo": "L2",
        "thresholdName": "transfer_l2_amount", "thresholdEnv": "POLICY_TRANSFER_L2_AMOUNT",
        "thresholdValue": "5000.00",
        "reason": "Transfer of 7500.00 is at or above 5000.00; supervisor co-signature required." },
      { "key": "high_risk_customer", "raisedTo": "L2",
        "thresholdName": "high_risk_customer_score", "thresholdEnv": "POLICY_HIGH_RISK_CUSTOMER_SCORE",
        "thresholdValue": "0.80",
        "reason": "Customer risk score 0.86 is at or above 0.80." }
    ],
    "resolvedThresholdSnapshot": { "transfer_l2_amount": "5000.00", "high_risk_customer_score": "0.80" }
  },

  "evidence": {
    "agentRationale": { "summary": "...", "toolCalls": [ ... ], "confidence": "0.82" },
    "accountSnapshot": { "accountId": "acc_11", "balance": "18240.55", "retrievedAt": "..." },
    "customerRiskProfile": { "customerId": "cust_5", "riskScore": "0.86" }
  },

  "signatureSlots": [
    { "ordinal": 0, "minSeniority": 1, "mustDifferFrom": [],
      "signedBy": "user_9f3a", "signedByUsername": "b.torres", "signedAt": "2026-09-04T13:41:02Z",
      "signature": "…", "signerTokenJti": "…", "nonce": "…" },
    { "ordinal": 1, "minSeniority": 2, "mustDifferFrom": ["user_9f3a"],
      "signedBy": null, "signedAt": null, "signature": null }
  ],

  "createdAt": "2026-09-04T13:39:00Z",
  "expiresAt": "2026-09-04T13:54:00Z",
  "expiresAtEpoch": 1788529, 
  "terminalAt": null,
  "terminalReason": null,

  "execution": {
    "state": "not_attempted",              // not_attempted | in_flight | succeeded | failed
    "idempotencyKey": "apr_01JQ8Z3M4W7K",
    "attempts": 0,
    "downstreamStatus": null,
    "downstreamRef": null,
    "lastError": null                      // shape per .squad/skills/cosmos-workflow-state
  },

  "ttl": null,                              // set ONLY after terminal state — retention purge
  "_etag": "\"…\""                          // optimistic concurrency on every transition
}
```

**Concurrency.** Every transition is an `ItemReplace` with `IfMatchEtag`. Two supervisors racing to fill slot 1 → one wins, the loser gets `412` and the UI refreshes. This is also what prevents a double-execute: the `not_attempted → in_flight` transition is an etag-guarded write, and the executor only proceeds if it wins.

### 5.4 Expiry — sweeper, not native TTL. And here is why.

Cosmos native TTL **deletes** the document. The directive says TTL expiry means **DENIED** — a semantic state transition that must be observable, auditable, and visible in the UI as "this expired and was therefore denied." A vanished document is indistinguishable from one that never existed. Native TTL alone is therefore **wrong** for live approvals.

**Recommendation: sweeper for semantics + native TTL for retention purge, plus lazy read-side expiry.**

1. **Lazy expiry on read (the actual safety property).** Every code path that loads an approval — `sign`, `deny`, `execute`, `get` — compares `expiresAt` to `now()` *before* acting. If past, it refuses and transitions the doc to `expired`. This means sweeper lag can never permit a late signature. The sweeper is a *housekeeper*, not a security control — that separation matters, because a background job that is also a security control is a single point of failure.
2. **Sweeper (housekeeper).** A background task in `banker-copilot-service` (asyncio task, same pattern as the account-opening consumer) runs every `APPROVAL_SWEEP_INTERVAL_SECONDS` (config, default `60`) and queries:
   `SELECT * FROM c WHERE c.docType='approval' AND c.status='pending' AND c.expiresAtEpoch <= @now OFFSET 0 LIMIT @batch`
   For each: etag-guarded transition to `expired`, `terminalReason = "ttl_expired_denied"`, emit `ApprovalExpired` to the audit stream (§7), and set `ttl = APPROVAL_RETENTION_SECONDS`. Multi-replica safety via a Redis lock (`copilot:sweeper:lock`, SET NX PX) — the repo already uses Redis leases for the chat-memory reconciler.
3. **Native TTL for retention.** `default_ttl = -1` (enabled, no default). `ttl` is set on a document **only when it reaches a terminal state**, to `APPROVAL_RETENTION_SECONDS` (config, default `7776000` = 90 days). Live approvals have `ttl: null` and are immortal until a human or the sweeper resolves them — so a stalled sweeper can never cause silent deletion of a pending approval.
4. **The permanent record lives elsewhere.** Cosmos purge is fine because every lifecycle transition is also emitted to the `banking-events` audit stream (§7). Cosmos is the *operational* store; the stream is the *audit* record.

### 5.5 Query patterns and indexing

| # | Need | Query | Cost |
|---|---|---|---|
| Q1 | Point read | `ReadItem(id, pk=requesterId)` | ~1 RU, single partition |
| Q2 | **My pending approvals** | `SELECT ... WHERE c.docType='approval' AND c.status='pending' ORDER BY c.createdAt DESC` with `PartitionKey=<me>` | Single partition |
| Q3 | **Approvals awaiting supervisor** | `SELECT ... WHERE c.docType='approval' AND c.status='pending' AND c.policy.requiredRung='L2' AND ARRAY_LENGTH(c.signatureSlots)>1 AND NOT IS_DEFINED(c.signatureSlots[1].signedBy) ORDER BY c.createdAt ASC` | Cross-partition, bounded by page size + composite index |
| Q4 | **Expired sweep** | `SELECT c.id, c.requesterId WHERE c.status='pending' AND c.expiresAtEpoch <= @now OFFSET 0 LIMIT @batch` | Cross-partition, projection-only, batched |
| Q5 | Session trace reconstruction | `WHERE c.sessionId=@s ORDER BY c.createdAt` | Cross-partition, rare |
| Q6 | Executed-but-unconfirmed reconciliation | `WHERE c.execution.state='in_flight' AND c.execution.startedAtEpoch < @cutoff` | Cross-partition, rare |

Q3's ragged-array predicate is awkward. Denormalise it: maintain a top-level `pendingSlotOrdinal` (int, `null` when complete) and `awaitingSeniority` (int), giving `WHERE c.status='pending' AND c.awaitingSeniority >= 2` — flat, indexable, cheap.

Indexing policy: default indexing **off** for `/payload/*` and `/evidence/*` (large, never filtered — pure RU waste on write), included for the rest, plus composite indexes `(status, createdAt)`, `(status, expiresAtEpoch)`, `(status, awaitingSeniority, createdAt)`.

---

## 6. Payload-hash signing scheme

### 6.1 What is hashed

Not the raw request body. The **projection** of the payload onto `action.hash_fields`, in the order declared in the policy file, canonicalized. Projecting explicitly (rather than hashing everything) means adding a non-material field later does not invalidate in-flight approvals, and — more importantly — it makes "what did the human actually agree to?" a reviewable list in the policy file rather than an emergent property of whatever the agent happened to serialize.

### 6.2 Canonicalization rules (v1)

Based on **RFC 8785 (JCS)** with two deliberate deviations for money. `canonicalizationVersion` is stored on every approval so the rules can evolve without invalidating history.

1. **Object keys** sorted by UTF-16 code unit, ascending (JCS rule). Deterministic regardless of dict insertion order or language.
2. **No insignificant whitespace.** Separators are exactly `,` and `:`.
3. **Strings** serialized per JSON, minimal escaping, UTF-8, and **NFC-normalized** before hashing (so visually identical Unicode cannot produce two hashes).
4. **Numbers — deviation from JCS.** JCS uses ES6 double serialization, which is unsafe for money. Instead: **every value whose policy `kind` is `money` is canonicalized as a fixed-scale decimal string** at `currency_scale` — `7500` → `"7500.00"`, `7500.5` → `"7500.50"`. Non-money numbers must be integers and are emitted without exponent or leading zeros. **Floats are rejected outright** for money fields; a float in a money position is a 400, not a coercion. This kills the `7500.00` vs `7500.0` vs `7.5e3` ambiguity class entirely.
5. **Booleans** `true`/`false`. **Null:** a field explicitly `null` is *omitted* from the projection, and a field absent is likewise omitted — the two are indistinguishable by construction. This removes the `{"memo": null}` vs `{}` ambiguity. If a field's presence is itself material, the policy must model it as a boolean, not a nullable.
6. **Arrays** preserve order (order is semantic). Elements canonicalized recursively.
7. **Nested objects** recurse with the same rules; `hash_fields` may name dotted paths (`conditions.rateCapBps`).
8. **Missing declared field** → hard error, never silently skipped. A proposal that cannot supply a `hash_fields` entry is malformed.

```
canonical_string = JCS_MODIFIED( project(payload, action.hash_fields) )
payload_hash     = "sha256:" + hex(SHA256(
                       "bcp.v1\n" + action_id + "\n" + canonical_string ))
```

The domain-separation prefix (`bcp.v1` + `action_id`) means an identical payload under a different action produces a different hash — a signature for `risk_score.rescore` can never be replayed against `risk_score.override`.

### 6.3 What the signature binds

```
signing_input =
    "bcp-sig.v1"                 // scheme + version
  + "\n" + approval_id
  + "\n" + action_id
  + "\n" + payload_hash
  + "\n" + signer_user_id        // WHO
  + "\n" + signer_token_jti      // WHICH authenticated session — ties to user-service's jti claim
  + "\n" + slot_ordinal          // WHICH slot; stops one signature filling both slots
  + "\n" + signed_at_rfc3339     // WHEN
  + "\n" + nonce                 // 128-bit random, per signing request, single-use

signature = SIGN(signing_input)
```

- **`slot_ordinal` in the input is load-bearing:** without it, a captured signature could be replayed into the second slot, defeating dual control even though the identities differ. With it, each slot needs its own distinct signature.
- **`signer_token_jti`** binds the signature to a specific authenticated session, so a stale/exfiltrated signature blob cannot be reused under a re-issued token.
- **`nonce`** is issued by the server when the UI opens the approval card and is consumed on use (Redis `copilot:sig:nonce:<id>`, TTL = remaining approval TTL). One nonce, one signature.

**Signing mode (config: `APPROVAL_SIGNING_MODE`).**
- `hmac` (default; docker-compose and initial AKS): `HMAC-SHA256` with a dedicated key `APPROVAL_SIGNING_KEY` — **distinct from `Jwt__Key`**, delivered via the existing Key Vault CSI path in AKS. Key separation matters: the JWT key is shared with every service, so reusing it would let any service forge a signature.
- `keyvault` (recommended target): sign with an Azure Key Vault EC key (ES256) via `Azure.Identity` / `DefaultAzureCredential` — the same credential pattern already used across this repo. This buys real non-repudiation: the service can verify but the key never leaves the HSM boundary.

Either way, the signature is produced **server-side after verifying an inbound human bearer token**. This is not a client-side crypto scheme; the browser is a thin client and holds no key. The security claim is "the mediator observed a fresh, authenticated human action and bound it immutably to this exact payload" — not "the human personally wielded a private key." That distinction should be stated plainly to Danny (open question O4).

### 6.4 Re-plan invalidation

`payload_hash` is derived from the payload; it is not a token that travels with intent.

- The agent re-plans and changes *any* `hash_fields` value → new hash → **the existing approval is untouched and unusable**. `PATCH`-ing the payload of a `pending` approval is not an operation the API offers. The agent must call `propose` again, producing a **new** approval document with a new id, and the human must sign again against the changed figure. Superseded approvals are transitioned to `denied` with `terminalReason = "superseded_by:<newId>"` and audited.
- At execute time the executor **recomputes** the canonical hash from the body it is about to send and compares to `approval.payloadHash`. Mismatch ⇒ `409`, `execution.state = failed`, `ActionExecutionFailed` emitted. This is the TOCTOU backstop: even a bug (not just an attack) between propose and execute is caught at the last possible moment.
- Any signature already collected is cleared if the policy decision itself changes (e.g. a threshold was lowered by a config rollout and the required rung is now higher). Re-evaluation happens at execute time and, if `requiredRung` or `requiredSigners` increased, execution refuses and the approval reverts to `pending` with the new slots — **the ladder can tighten under an in-flight approval, never loosen.**

### 6.5 Secret-bearing payloads

For `user.password.reset`, `hash_fields` deliberately excludes the new secret: `[userId, reasonCode]`. Hashing a secret would put a verifier for it into a 90-day-retained audit document. The material fact the human approves is "reset this user's password for this reason," not the secret bytes, which are generated at execution time and never stored. Same principle applies to any future action carrying PII/secret material.

---

## 7. Audit trail

### 7.1 The existing pipeline (read from the Go source, not assumed)

`src/event-processor/main.go`:

```go
const (
    streamName    = "banking-events"
    dlqStreamName = "banking-events-dlq"
    consumerGroup = "event-processor-group"
    consumerName  = "event-processor-1"
)

type BankingEvent struct {
    EventType string                 `json:"eventType"`
    Timestamp string                 `json:"timestamp"`
    Data      map[string]interface{} `json:"data"`
}
```

`processMessage` reads `message.Values["payload"]` as a **string**, `json.Unmarshal`s it into `BankingEvent`, sets OTEL span attributes `event.type` / `event.timestamp` / `message.id`, then switches on `EventType` (`TransactionCreated`, `TransferInitiated`, default → `slog.Warn("Audit Unknown event type", ...)`). Failures route to `banking-events-dlq` after `DLQ_MAX_RETRIES`, then `XAck`.

The .NET producers (`RedisEventPublisher.cs` in transfer-, transaction-, user-service) all do:
```csharp
db.StreamAddAsync(streamName, new NameValueEntry[] { new("payload", payload) });
```
— i.e. **one stream field named `payload` holding the whole JSON envelope.**

> ⚠️ **Divergence found.** `src/account-opening-service/app/events.py` publishes *flat* fields (`eventType`, `applicationId`, `timestamp`, `data` as a JSON string) to a **different** stream (`account-opening-events`). It is not read by the Go processor. Banker Copilot must follow the **.NET `payload`-envelope form on `banking-events`**, not the account-opening form, or its events will be silently invisible to the audit consumer. Flagging this divergence for Basher/Danny as a separate cleanup — out of scope here.

### 7.2 Events emitted by Banker Copilot

Same envelope, same stream, same field name:

```json
{
  "eventType": "ApprovalSigned",
  "timestamp": "2026-09-04T13:41:02.117Z",
  "data": {
    "approvalId": "apr_01JQ8Z3M4W7K",
    "actionId": "transfer.initiate",
    "requesterId": "user_9f3a",
    "sessionId": "sess_7c21",
    "agentId": "asst_banker_copilot_v1",
    "correlationId": "0af7651916cd43dd8448eb211c80319c",
    "payloadHash": "sha256:9f2b…",
    "requiredRung": "L2",
    "slotOrdinal": 1,
    "signerId": "user_2c88",
    "signerUsername": "m.okafor",
    "signerSeniority": 2,
    "signaturesCollected": 2,
    "signaturesRequired": 2
  }
}
```

| Event type | Emitted when | Key `data` fields beyond the common set |
|---|---|---|
| `CopilotSessionStarted` | Harness session opens | `bankerId`, `capabilityAllowlist`, `policyId` |
| `ActionProposed` | Agent calls `propose`, policy admits it | `baseRung`, `requiredRung`, `firedEscalators[]`, `agentConfidence`, `evidenceKeys[]` |
| `ActionProposalRejected` | Policy denies (L3, unknown action, under-evidenced) | `rejectionReason`, `evidenceGaps[]` |
| `PolicyEscalated` | ≥1 escalator fired (emitted alongside `ActionProposed`) | `escalators[] {key, raisedTo, thresholdName, thresholdValue, reason}` |
| `ApprovalSigned` | A slot is filled | `slotOrdinal`, `signerId`, `signaturesCollected/Required` |
| `ApprovalDenied` | Human denies, or superseded by re-plan | `deniedBy`, `terminalReason` |
| `ApprovalExpired` | Sweeper or lazy read-side expiry | `expiresAt`, `terminalReason: "ttl_expired_denied"` |
| `ActionExecuted` | Downstream returns 2xx | `downstreamStatus`, `downstreamRef`, `latencyMs` |
| `ActionExecutionFailed` | Non-2xx, hash mismatch, or refusal | `failureCode`, `downstreamStatus` |

Every one of these carries `approvalId` + `correlationId`, so an auditor can reconstruct a complete chain — proposal → escalation → each signature → execution — by filtering on either.

### 7.3 Consumer-side change (small, additive, coordinate with Basher)

Today these land in the Go `default:` branch and log as `"Audit Unknown event type"` — functional, but it loses the structured fields. Add cases to the existing switch:

```go
case "ActionProposed", "PolicyEscalated", "ApprovalSigned", "ApprovalDenied",
     "ApprovalExpired", "ActionExecuted", "ActionExecutionFailed", "CopilotSessionStarted":
    slog.Info("Audit "+evt.EventType,
        "approval_id", evt.Data["approvalId"],
        "action_id",   evt.Data["actionId"],
        "requester",   evt.Data["requesterId"],
        "rung",        evt.Data["requiredRung"],
        "signer",      evt.Data["signerId"],
        "correlation", evt.Data["correlationId"],
    )
```

No schema change, no new stream, no consumer-group change — purely additive, and the system is correct (if less legible) even without it.

### 7.4 Publish reliability

Audit emission must not be best-effort where it matters. Two tiers:

- **Terminal/decision events** (`ApprovalSigned`, `ApprovalDenied`, `ApprovalExpired`, `ActionExecuted`) — written to the Cosmos document **and** the stream. The Cosmos doc is the source of truth; a small outbox reconciler replays any event whose `auditPublished` flag is false. Redis being down must never silently lose a signature record.
- **Informational events** (`CopilotSessionStarted`, `PolicyEscalated`) — fire-and-forget with a warning log, matching the existing `publish_event` behaviour in this repo.

---

## 8. API surface — `banker-copilot-service`

Base path `/api/copilot`. All endpoints require a valid `banking-demo`-audience end-user JWT (the browser's token) except the `/internal/*` mediator routes, which require the `banking-copilot` audience and are not exposed through ingress. Health endpoints follow the repo convention: `/healthz`, `/readyz`. Every response carries `X-Correlation-ID`.

### 8.1 `POST /api/copilot/sessions` — start an agent session

```jsonc
// request
{ "objective": "Review the flagged wire on account acc_11 and act.",
  "context": { "customerId": "cust_5", "accountId": "acc_11" } }

// 201
{ "sessionId": "sess_7c21",
  "agentId": "asst_banker_copilot_v1",
  "policyId": "banker-copilot-authority-v1",
  "capabilities": ["transfer.initiate", "user.lock", "flagged_transaction.review", "..."],
  "traceUrl": "/api/copilot/sessions/sess_7c21/stream",
  "expiresAt": "2026-09-04T14:39:00Z" }
```
Exchanges the browser token for a `banking-copilot`-audience harness token held **server-side**; it is never returned to the client and never enters model context.

### 8.2 `GET /api/copilot/sessions/{sessionId}/stream` — live trace (SSE)

`text/event-stream`. SSE over WebSocket: unidirectional server→client fits the trace pane, survives the existing ingress without protocol upgrade config, and matches FastAPI's `StreamingResponse` idiom already used in this repo. User turns go through §8.3 as ordinary POSTs.

```
event: agent.thinking     data: {"seq":12,"text":"Checking recent activity…"}
event: tool.call          data: {"seq":13,"tool":"get_account","args":{"accountId":"acc_11"}}
event: tool.result        data: {"seq":14,"tool":"get_account","summary":"balance 18240.55"}
event: approval.required  data: {"seq":15,"approvalId":"apr_01JQ8Z3M4W7K","actionId":"transfer.initiate",
                                 "requiredRung":"L2","firedEscalators":[…],"expiresAt":"…"}
event: approval.updated   data: {"seq":16,"approvalId":"apr_01JQ8Z3M4W7K","status":"signed",
                                 "signaturesCollected":2,"signaturesRequired":2}
event: action.executed    data: {"seq":17,"approvalId":"apr_01JQ8Z3M4W7K","downstreamStatus":201}
event: heartbeat          data: {"t":"2026-09-04T13:42:00Z"}
```
`seq` is monotonic per session; `Last-Event-ID` supports resume. Heartbeat interval is config (`COPILOT_SSE_HEARTBEAT_SECONDS`, default `15`) to survive idle-timeout proxies.

### 8.3 `POST /api/copilot/sessions/{sessionId}/messages` — user turn
`{ "content": "Go ahead, but cap it at the disputed amount." }` → `202 {"accepted": true, "seq": 18}`. Output arrives on the stream.

### 8.4 `POST /internal/mediate/propose` — agent tool → approval (never executes)

```jsonc
// request (from a registered tool, harness-audience token only)
{ "sessionId": "sess_7c21", "actionId": "transfer.initiate",
  "payload": { "fromAccountId": "acc_11", "toAccountId": "acc_42",
               "amount": "7500.00", "currency": "USD", "memo": "wire recall" },
  "agentConfidence": "0.82",
  "rationale": "Customer disputes the wire; recall to the originating account.",
  "evidence": { "accountSnapshot": {...}, "customerRiskProfile": {...} } }

// 201 — admitted
{ "approvalId": "apr_01JQ8Z3M4W7K", "status": "pending",
  "requiredRung": "L2", "baseRung": "L1",
  "requiredSigners": 2, "payloadHash": "sha256:9f2b…",
  "expiresAt": "2026-09-04T13:54:00Z",
  "firedEscalators": [ { "key":"transfer_amount_l2", "raisedTo":"L2",
                         "thresholdEnv":"POLICY_TRANSFER_L2_AMOUNT", "thresholdValue":"5000.00",
                         "reason":"Transfer of 7500.00 is at or above 5000.00; supervisor co-signature required." } ] }

// 403 — L3 / not proposable
{ "error": "action_not_permitted", "requiredRung": "L3",
  "reason": "'Grant administrative role to a user' is outside the Copilot's authority." }

// 422 — under-evidenced
{ "error": "insufficient_evidence", "evidenceGaps": ["recentTransactions"] }
```
The tool returns this verbatim to the model, so the agent *knows* it is blocked pending signature and can say so — rather than assuming success.

### 8.5 `GET /api/copilot/approvals` — list

Query params: `scope=mine|awaiting_supervisor|session`, `status`, `actionId`, `sessionId`, `limit` (default `COPILOT_PAGE_SIZE_DEFAULT`), `continuationToken`.
`scope=mine` → Q2 (single-partition). `scope=awaiting_supervisor` → Q3, and additionally filters out approvals where the caller is in `mustDifferFrom` — **a supervisor never sees their own proposals in their co-sign queue**, which is separation of duties made visible rather than merely enforced.

```jsonc
{ "items": [ { "approvalId":"apr_…", "actionId":"transfer.initiate",
               "actionLabel":"Initiate a transfer between accounts",
               "status":"pending", "requiredRung":"L2",
               "signaturesCollected":1, "signaturesRequired":2,
               "requesterUsername":"b.torres", "amountSummary":"7500.00 USD",
               "firedEscalators":[…], "expiresAt":"…", "secondsRemaining":612,
               "canSign": true, "cannotSignReason": null } ],
  "continuationToken": null }
```
`canSign` / `cannotSignReason` are server-computed (`"You proposed this action; a different supervisor must co-sign."`) so the UI never has to reimplement policy.

### 8.6 `POST /api/copilot/approvals/{id}/sign`

```jsonc
// request
{ "nonce": "b0f1…",            // from GET /approvals/{id}, single-use
  "payloadHash": "sha256:9f2b…", // client echoes what it displayed — mismatch ⇒ 409
  "comment": "Verified with customer by phone." }

// 200
{ "approvalId":"apr_…", "status":"pending", "slotOrdinal":1,
  "signaturesCollected":2, "signaturesRequired":2, "readyToExecute":true }
```
Refuses with `409` on: expired (lazy check), hash mismatch, slot already filled (etag race), signer in `mustDifferFrom`, insufficient seniority, or a re-evaluated policy that now demands more. **`403` unconditionally if the caller is not a human principal** (token carries `act`).

**Batch:** `POST /api/copilot/approvals/batch-sign` with `{ "approvalIds": [...], "actionId": "flagged_transaction.review", "nonces": {...} }`. Server-enforced: all items share the declared `actionId`; every item is `requiredRung == "L1"`; `batchable: true` on that action; count ≤ `batch_max_items`; **any item that escalated to L2 is rejected from the batch and returned in `rejected[]` for individual handling.** Response `{ "signed": [...], "rejected": [{approvalId, reason}] }`. There is no endpoint that accepts a batch without an `actionId`, so "Approve All" is not expressible.

### 8.7 `POST /api/copilot/approvals/{id}/deny`
`{ "reason": "Customer could not be verified." }` → `200 { "status": "denied", "terminalReason": "human_denied" }`. Always allowed for any eligible signer; denial needs no quorum.

### 8.8 `POST /api/copilot/approvals/{id}/execute`
`{ "payloadHash": "sha256:9f2b…" }` → `200 { "status":"signed", "execution": { "state":"succeeded", "downstreamStatus":201, "downstreamRef":"trf_88a2" } }`.

Ordered gate: (1) not expired; (2) signature quorum, seniority, distinct identities; (3) no signer is a service principal; (4) re-evaluate policy — refuse if the ladder tightened; (5) recompute canonical hash from the outbound body and compare; (6) etag-guarded `not_attempted → in_flight`; (7) mint the single-use execution token (§4.4 Layer 2); (8) call downstream with `Idempotency-Key: <approvalId>`; (9) record result, emit audit. Idempotent: replaying `execute` on a `succeeded` approval returns the recorded result without re-calling downstream.

Auto-execute-on-final-signature is available behind `COPILOT_AUTO_EXECUTE_ON_QUORUM` (config, default `true`) — this is not an autonomy tier; quorum has already been met, and it just saves a click.

### 8.9 `GET /api/copilot/policy` — introspection
Returns `policyId`, version, the action catalogue with base rungs, and **resolved threshold values with their env-var names** (values only, never secrets). This is what makes the ladder self-documenting to the humans operating under it.

### 8.10 Config keys introduced

| Key | Default | Purpose |
|---|---|---|
| `POLICY_FILE_PATH` | `/etc/banker-copilot/policy.yaml` | Policy location |
| `POLICY_*` (per §2.4) | see policy file | Every threshold override |
| `JWT_AUDIENCE_COPILOT` | `banking-copilot` | Harness token audience (Layer 1) |
| `EXECUTION_TOKEN_TTL_SECONDS` | `60` | Single-use downstream token lifetime |
| `APPROVAL_SIGNING_MODE` | `hmac` | `hmac` \| `keyvault` |
| `APPROVAL_SIGNING_KEY` / `APPROVAL_SIGNING_KEY_ID` | — | Key material / Key Vault key id |
| `APPROVAL_SWEEP_INTERVAL_SECONDS` | `60` | Housekeeper cadence |
| `APPROVAL_RETENTION_SECONDS` | `7776000` | Post-terminal Cosmos TTL |
| `COPILOT_SSE_HEARTBEAT_SECONDS` | `15` | SSE keepalive |
| `COPILOT_PAGE_SIZE_DEFAULT` | `25` | List page size |
| `COPILOT_PROPOSALS_PER_MINUTE` | `30` | Anti-flood limit |
| `COPILOT_AUTO_EXECUTE_ON_QUORUM` | `true` | Execute immediately once quorum met |
| `COSMOS_DB_ENDPOINT`, `COSMOS_APPROVALS_CONTAINER` | `copilot-approvals` | Store |
| `REDIS__CONNECTIONSTRING` | — | Nonces, jti ledger, sweeper lock, audit stream |
| `AZURE_CLIENT_ID` | — | Present ⇒ Entra/workload identity; absent ⇒ simple auth |

All must be added to **both** `deploy/kustomize/base/configmap.yaml` and `docker-compose.yml` in the same change — the drift between those two files is the recurring failure mode on this project.

---

## 9. Open questions for Danny, and top risks

### 9.1 Open questions

| # | Question | My lean |
|---|---|---|
| O1 | Ratify **Python/FastAPI, single service, two internal planes** (§1.3)? Or split the mediator into .NET for static-typing assurance? | Single Python service. The security property comes from the process/network boundary and the token audience, not the language. A split doubles the config-drift surface. |
| O2 | Is `banker` / `supervisor` / `risk_officer` a **new role model**? Today `user-service` mints a single `role` claim and everything admin-ish is `admin`/`Admin`. Separation of duties needs at least two distinct senior identities to be meaningful — with one `admin` role, "different identity" is enforceable but "more senior" is not. | Add a `seniority` claim to `user-service` tokens, or map roles→seniority in policy config as an interim. Needs a decision before L2 means anything real. |
| O3 | Should domain services be modified to **require** `apid`/`pah` claims (Layer 2, phase 2)? That touches all seven services and is architecture-level. | Yes eventually, behind `REQUIRE_APPROVAL_CLAIMS`, but not in the first cut — Layer 1 carries the guarantee. Your call on sequencing. |
| O4 | Is a **server-side signature** (mediator observes an authenticated human action and binds it) sufficient "signature," or does compliance narrative demand per-user asymmetric keys / true non-repudiation? | Server-side + Key Vault ES256 is right for a demo and defensible in a real bank. Worth saying out loud in the epic so nobody over-claims. |
| O5 | `account.delete` has **no endpoint today**. Do we define the ladder entry now (as I have) or omit until the capability exists? | Define it now. An action with no policy entry is denied by default, but writing it down means nobody adds the endpoint later without a rung. |
| O6 | The **account-opening event schema divergence** (§7.1) — flat fields on a separate stream vs the `payload` envelope on `banking-events`. Separate cleanup ticket? | Yes, separate ticket, not Banker Copilot's to fix. But it will bite someone. |
| O7 | Should the shared `banking-workload-identity` KSA be **split per service**? Required for Layer 3 to mean anything, and it is a cluster-wide change well outside my lane. | Split at minimum for `banker-copilot`. Full per-service split is a good idea independently. |
| O8 | Where does `session.anomalyFlags` come from? No session-anomaly signal exists in this repo today. | Stub it as an empty list in v1 (the escalator then never fires — safe, since escalators only raise) and wire it to a real signal later. Flagged as a knowingly-inert escalator, not a hidden gap. |

### 9.2 Top 3 technical risks

**R1 — The single shared JWT audience is the whole ballgame.**
Every service validates `aud=banking-demo` against one shared symmetric key. Until the second audience (§4.4 Layer 1) exists in `user-service` and the harness genuinely never holds a `banking-demo` token, the mediator is a *convention*, not a boundary — a compromised agent with a banker token can call `POST /api/transfers` directly and the ladder is decoration. *Mitigation:* land audience separation **first**, before any tool is registered. Test it adversarially: assert that a harness-audience token gets 401 from every domain service. If that test cannot be made to pass, the epic's core security claim is not yet true and we should say so rather than ship the appearance of control.

**R2 — Token/secret leakage into model context.**
The browser's `banking-demo` token, evidence payloads, and execution tokens must never reach model-visible context. Foundry threads persist message history; `chatbot-service` already persists agent memory to Cosmos. One careless "include the request headers for debugging" and a bearer token is durably stored in an agent memory container. *Mitigation:* a redaction layer on every tool result (deny-list on `authorization`, `token`, `key`, `secret`, `password`, plus a JWT-shaped regex), tool results capped in size, and a test asserting no tool result matches the JWT pattern. Treat agent memory as a **published** surface.

**R3 — Approval fatigue turning L1 into de facto autonomy.**
The design is technically sound and still fails if a banker clicks through forty identical cards. Batch-sign is constrained (§8.6), but the deeper risk is that a well-behaved agent trains the human to trust it, and then one poisoned proposal sails through. *Mitigation:* (a) approval cards must lead with the **diff and the escalation reasons**, not the agent's confident summary; (b) instrument time-to-sign and alert on sustained sub-threshold signing latency — a metric on the humans, not the agent; (c) keep `bulk_fanout` thresholds genuinely low; (d) never let batch cross an action type. This is a product/UX risk with a technical surface, and it is the one most likely to be under-weighted — worth an explicit line in the epic.

---

## 10. Summary of what needs to exist (not built here)

1. `banker-copilot-service` (Python/FastAPI) — harness plane + mediator plane, pending O1.
2. `config/banker-copilot/policy.yaml` + ConfigMap `banker-copilot-policy` + docker-compose bind mount.
3. Cosmos container `copilot-approvals` (`/requesterId`, TTL enabled, not defaulted) in `infra/cloud/cosmos.tf`.
4. `user-service` change: mint a second-audience harness token; ideally add a `seniority` claim (O2).
5. Own KSA `banker-copilot`; Istio `PeerAuthentication` STRICT + default-deny + per-service `AuthorizationPolicy` (O7).
6. Additive `case` arms in `src/event-processor/main.go` for the nine new audit event types.
7. Key Vault entry for `APPROVAL_SIGNING_KEY`, distinct from `jwt-key`, via the existing CSI SecretProviderClass.
8. CI: policy-lint (no literals), import-graph test (propose ⊥ executor), adversarial audience test, redaction test.
