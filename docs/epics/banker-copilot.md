# Epic: Banker Copilot — Agentic Harness for the Banker/Admin Experience

**Status:** Proposed
**Owner:** Danny (Lead/Architect)
**Related epics:** #140 (Loan Originations port)
**Supersedes:** #140 Phase 2 "review dashboard / decision panel"
**Source directives:**
`.squad/decisions/inbox/copilot-directive-banker-copilot-epic.md`,
`...-authority-model.md`, `...-scope-boundary.md`

---

## 0. Non-negotiable invariants

These are decided. Do not relitigate them in design review; a PR that violates one is
rejected on sight.

| # | Invariant |
|---|---|
| **I-1** | **Agents never approve.** Every state-changing action carries a human signature. There is no auto-execute tier, no "low-risk auto-apply", no "the agent may act if confidence > X". |
| **I-2** | Thresholds govern **how many humans sign and how senior** — never *whether* a human signs. |
| **I-3** | **All thresholds are configuration-driven.** Zero hardcoded dollar amounts, counts, or rung assignments in application code. |
| **I-4** | Dynamic escalators only push **up** a rung. Nothing in the system can lower a rung at runtime. |
| **I-5** | A signature binds to a **payload hash**, not an intent. Payload changes ⇒ signature void ⇒ re-propose. |
| **I-6** | TTL expiry means **denied**. Never auto-approved, never silently retried. |
| **I-7** | The agent runs under a **delegated banker identity** + explicit capability allowlist. No god-mode service principal. |
| **I-8** | Tools call **existing REST APIs**. Never the database directly. |
| **I-9** | The agent loop runs **server-side**. The browser is a thin streaming client. |
| **I-10** | No blanket "Approve All". Batch only within one action type, under threshold, never L2. |

Out of scope for this epic: agentic/trajectory evaluation (deferred by directive).

---

## 1. Problem statement & demo narrative

### 1.1 The problem

`AdminPage.tsx` is an eight-tab console: Account Applications, User Management, All
Transactions, Flagged Transactions, Chatbot Prompt, AI Evaluation, Login Audit, System
Health. Each tab is a competent CRUD surface and each one is a dead end. A banker
investigating "why did Maria's wire get flagged and should we release it?" must:

1. Open **Flagged Transactions**, find the row, read a risk score with no provenance.
2. Switch to **All Transactions**, hand-filter for the same account to build a baseline.
3. Switch to **User Management** to check whether the customer is locked or newly promoted.
4. Switch to **Login Audit** to see whether the session that initiated it was anomalous.
5. Switch to **Account Applications** if the customer is recently onboarded.
6. Hold all of that in their head, then click one button on tab 4.

The information architecture is *the data model*, not *the job*. Every cross-cutting
question costs the banker a manual join across tabs, and the resulting decision is recorded
as a single state flip with no attached reasoning.

### 1.2 The product answer

Banker Copilot replaces tab-hunting with a single conversational surface driven by
**intent → plan → tool calls → artifact**. The banker states a goal. A server-side agent
loop plans, calls read tools across the existing services to gather evidence, and produces
a **decision artifact**: a structured, cited recommendation. When the artifact implies a
state change, the agent does not make it — it emits an **approval request** that the banker
(and, above threshold, a supervisor) signs.

The win is not "chat with your bank data". The win is that **the evidence bundle and the
signature are the same object**. Today the reasoning evaporates and only the flip is stored.
Here, the flip is a child of the evidence.

### 1.3 What a viewer sees on screen (demo script)

Three panes: **task queue** (left), **live trace** (center), **artifact canvas** (right).

> **Banker types:** *"Maria Chen's $12,400 wire got flagged this morning. Work it up and tell
> me what to do."*

1. **Plan renders in the trace pane, streamed token by token.** Five steps, each labelled
   with the tool it will use. The viewer immediately understands this is not a chatbot —
   it is a work plan.
2. **Tools fire, visibly.** `get_flagged_transaction`, `list_account_transactions`,
   `get_user`, `list_login_audits`, `get_account_application`. Each row shows the service it
   hit and latency. Five tabs of manual work collapse into four seconds of visible I/O.
3. **A subagent spawns.** For the 90-day baseline the harness fans out a `pattern-analysis`
   subagent; the trace pane nests it. The viewer sees fan-out *and* sees it rejoin.
4. **Artifact canvas fills in.** A cited recommendation: *Release with note.* Risk score,
   contributing factors, baseline comparison, and a citation chip on every claim. Clicking a
   chip jumps to the tool call that produced it.
5. **The moment that sells the demo.** The agent does **not** release the wire. It renders an
   **approval card**: action `transaction.flag.review`, payload preview, payload hash,
   authority rung **L1**, TTL 30 minutes, and a **Sign** button. The banker signs. Only then
   does the write hit `ai-service`.
6. **Then we raise the stakes.** *"Now do the same for the $250,000 wire on the Delgado
   account."* Same flow — but the policy engine returns **L2**. A supervisor agent runs an
   **independent** work-up (its own tools, its own evidence, it never reads the primary
   agent's conclusion) and the card now demands **two signatures from two identities**. The
   banker clicks Sign and the card stays pending: *"Awaiting supervisor co-signature."*
   A second browser, logged in as the supervisor, receives the request out-of-band.
7. **The kicker.** The banker says *"actually make it $250,000 instead"* after signing.
   The payload hash changes, the signature goes void, and the card resets to `proposed`.
   That single interaction demonstrates TOCTOU resistance better than any slide.

Once #140 lands, the same shell handles loans: the six specialist underwriting agents are
evidence producers, and `CONDITIONAL` verdicts are structurally incapable of single-signature
approval.

---

## 2. Service boundary

### 2.1 Decision: two new services, split by runtime affinity

| Service | Stack | Owns |
|---|---|---|
| **`banker-copilot-service`** | Python 3.11 / FastAPI | The agentic harness: session lifecycle, planner loop on Foundry Agent Service, tool dispatch, subagent fan-out/join, SSE streaming to the browser, artifact assembly. |
| **`authority-service`** | .NET 10 / ASP.NET Core | The authority policy engine, the approval object model on Cosmos, signature verification, separation-of-duties enforcement, and **the action broker** — the only component in the system that performs an agent-originated write. |

Yes, this is two services rather than one. The split is deliberate and is the enforcement
mechanism for I-1 (see §4.4). A single service would put the policy engine in the same
process, same identity, and same code review blast radius as the LLM loop that it exists to
constrain.

### 2.2 Why the harness is Python, not .NET

Look at what the repo actually does, not what it nominally is.

Every piece of real Foundry/Agent Framework work in this repo is Python:

- `src/ai-service` — `agent-framework-core 1.16.0`, `agent-framework-foundry 1.10.0`,
  `FoundryAgent` / `FoundryChatClient`, `init_agents.py` bootstrap, OTEL instrumentation via
  `agent_framework.observability.enable_instrumentation`.
- `src/chatbot-service`, `src/account-opening-service` — same pinned Agent Framework stack.
- `src/prompt-eval-service` — **is .NET, and its csproj contains no Foundry package at all.**
  It holds Cosmos state and delegates every model call to `ai-service` over
  `HttpClient("AiService")`.

`prompt-eval-service` is therefore not a counterexample; it is the precedent. The established
repo pattern is exactly the one proposed here: **.NET owns durable state and control; Python
owns the model runtime.** Banker Copilot follows it at a larger scale.

Supporting reasons: the Agent Framework Python surface is the one the team has already
debugged (see `.squad/skills/foundry-eval-debugging`, `agent_framework-eval-shapes`,
`preview-sdk-pinning`); token-level SSE streaming is idiomatic in FastAPI/Starlette; and
subagent fan-out is `asyncio.gather` rather than a hand-rolled `Task` orchestration.

### 2.3 Why authority is .NET, not Python

The approval store is durable, transactional, and security-critical. The repo's convention
for exactly that shape is .NET + `Microsoft.Azure.Cosmos` + JWT bearer: `user-service`,
`account-service`, `transaction-service`, `transfer-service`, `prompt-eval-service`. It gets
`Banking.Observability` (`UseBankingSerilog`, `AddBankingOpenTelemetry`) for free, it inherits
the JWT validation pattern including `Jwt:Issuer`/`Jwt:Audience`/`Jwt:Key`, and it can reuse
the `CosmosPromptTemplateRepository` shape verbatim. It also gets `net10.0` + central package
management via `Directory.Packages.props` with no new dependency decisions.

Critically: **authority-service contains no LLM call and no model SDK.** That is a reviewable,
enforceable property. Adding one is a rejectable PR.

### 2.4 Ownership map

**`banker-copilot-service` owns**
- `POST /api/copilot/sessions`, `GET /api/copilot/sessions/{id}/stream` (SSE)
- `POST /api/copilot/sessions/{id}/messages`
- The tool manifest registry and tool→REST dispatch (read tools only, plus `propose_action`)
- Planner loop, subagent orchestration, artifact assembly
- Cosmos: `copilot-sessions` (PK `/id`), `copilot-artifacts` (PK `/sessionId`)

**`banker-copilot-service` calls** — `authority-service` (proposals, approval status),
`ai-service`, `account-service`, `transaction-service`, `transfer-service`, `user-service`,
`account-opening-service`, and later `loan-origination-service`. All over HTTP, all
forwarding the banker's JWT.

**`authority-service` owns**
- `POST /api/authority/evaluate` — dry-run rung evaluation (no side effect)
- `POST /api/authority/proposals` — create durable approval request
- `GET /api/authority/proposals`, `GET /api/authority/proposals/{id}`
- `POST /api/authority/proposals/{id}/sign`, `.../deny`
- `GET /api/authority/policy` — the effective, resolved policy (for the UI to render "why L2")
- The action broker: on final signature, executes the downstream REST call
- Cosmos: `authority-proposals` (PK `/actorId`), `authority-policy` (PK `/id`)
- Publishes audit events onto the existing Redis Stream consumed by `event-processor`

**`authority-service` explicitly does NOT own** — any model call, any planning, any UI state,
any domain logic. It knows action *types* and how to invoke *endpoints*; it does not know what
a loan is.

**UI** — new route `/copilot` (three-pane shell). `/admin` remains for one release as a
fallback, then the tabs collapse into Copilot-sourced saved views.

**Gateway** — two new `location` blocks in `infra/local/gateway.nginx.conf`:
`/api/copilot/` → `banker-copilot-service` (with `proxy_buffering off` for SSE),
`/api/authority/` → `authority-service`.

---

## 3. Tool contract

### 3.1 Rules

1. **Tools call REST, never Cosmos/Redis.** The harness has no Cosmos connection to any
   domain container. This is enforced by config: `banker-copilot-service` receives no
   domain-container names and no domain Cosmos role assignment.
2. **The banker's JWT is forwarded on every tool call.** The agent cannot see or do anything
   the banker could not. Delegated identity, per I-7.
3. **Read tools execute directly. Write tools do not exist.** There is exactly one
   write-shaped tool — `propose_action` — and it targets `authority-service`. See §4.4.
4. Every tool declares its manifest fields below. A tool with a missing or unknown
   `actionTypeId` fails registration at service start. Fail closed, loudly.

### 3.2 Manifest schema

```jsonc
{
  "$schema": "https://onlinebankingdemo.bjdazure.tech/schemas/tool-manifest/v1.json",
  "toolId": "string",                 // stable, snake_case, unique
  "displayName": "string",
  "description": "string",            // becomes the model-facing tool description
  "mode": "read" | "write",           // 'write' tools are ALWAYS routed via propose_action
  "actionTypeId": "string | null",    // null iff mode == 'read'
  "authority": {
    "declaredRung": "L1" | "L2" | "L3",   // static floor; policy engine may raise, never lower
    "policyRef": "string"                  // key into the policy file; source of truth
  },
  "target": {
    "service": "string",              // logical upstream name
    "method": "GET|POST|PUT|PATCH|DELETE",
    "path": "string",                 // RFC 6570 template, e.g. /api/admin/flagged-transactions/{txId}/review
    "timeoutMs": 8000
  },
  "parameters": { "...": "JSON Schema draft 2020-12" },
  "requiredEvidence": [               // tool IDs that MUST appear in the trace before propose
    "string"
  ],
  "capabilityScope": "string",        // allowlist key; absent from banker's grant => tool hidden
  "redaction": ["string"],            // JSONPath list scrubbed before entering model context
  "idempotencyKeyFrom": ["string"]    // param names composing the idempotency key (write only)
}
```

`requiredEvidence` is the teeth behind "agents gather evidence". `authority-service`
re-validates it server-side against the submitted trace; a proposal whose trace lacks a
required evidence tool call is rejected with `422 EVIDENCE_INCOMPLETE`. A model that decides
to skip its homework cannot get a card in front of a human.

### 3.3 Worked manifest — six real endpoints

```jsonc
[
  // ---------- READ ----------
  {
    "toolId": "get_flagged_transaction",
    "displayName": "Get flagged transaction",
    "description": "Retrieve one flagged transaction with its AI risk score and contributing factors.",
    "mode": "read",
    "actionTypeId": null,
    "authority": { "declaredRung": "L1", "policyRef": "read.any" },
    "target": { "service": "ai-service", "method": "GET",
                "path": "/api/admin/flagged-transactions/{txId}", "timeoutMs": 8000 },
    "parameters": {
      "type": "object",
      "properties": { "txId": { "type": "string" } },
      "required": ["txId"], "additionalProperties": false
    },
    "requiredEvidence": [],
    "capabilityScope": "risk.read",
    "redaction": ["$.customer.ssn", "$.customer.dateOfBirth"]
  },
  {
    "toolId": "list_account_transactions",
    "displayName": "List account transactions",
    "description": "List transaction history for one account, for baseline and pattern comparison.",
    "mode": "read",
    "actionTypeId": null,
    "authority": { "declaredRung": "L1", "policyRef": "read.any" },
    "target": { "service": "transaction-service", "method": "GET",
                "path": "/api/transactions/account/{accountId}", "timeoutMs": 8000 },
    "parameters": {
      "type": "object",
      "properties": {
        "accountId": { "type": "string" },
        "limit": { "type": "integer", "minimum": 1, "maximum": 500, "default": 100 }
      },
      "required": ["accountId"], "additionalProperties": false
    },
    "requiredEvidence": [],
    "capabilityScope": "transactions.read",
    "redaction": []
  },
  {
    "toolId": "list_login_audits",
    "displayName": "List login audit events",
    "description": "Retrieve login audit history to assess whether the initiating session was anomalous.",
    "mode": "read",
    "actionTypeId": null,
    "authority": { "declaredRung": "L1", "policyRef": "read.any" },
    "target": { "service": "user-service", "method": "GET",
                "path": "/api/admin/login-audits", "timeoutMs": 8000 },
    "parameters": {
      "type": "object",
      "properties": {
        "userId": { "type": "string" },
        "sinceUtc": { "type": "string", "format": "date-time" }
      },
      "required": ["userId"], "additionalProperties": false
    },
    "requiredEvidence": [],
    "capabilityScope": "identity.read",
    "redaction": ["$[*].ipAddress"]
  },

  // ---------- WRITE (always routed through propose_action) ----------
  {
    "toolId": "review_flagged_transaction",
    "displayName": "Clear or confirm a flagged transaction",
    "description": "Record a review decision (clear / confirm-fraud) on a flagged transaction. Requires human signature.",
    "mode": "write",
    "actionTypeId": "transaction.flag.review",
    "authority": { "declaredRung": "L1", "policyRef": "transaction.flag.review" },
    "target": { "service": "ai-service", "method": "PUT",
                "path": "/api/admin/flagged-transactions/{txId}/review", "timeoutMs": 8000 },
    "parameters": {
      "type": "object",
      "properties": {
        "txId": { "type": "string" },
        "decision": { "type": "string", "enum": ["cleared", "confirmed_fraud"] },
        "note": { "type": "string", "maxLength": 2000 }
      },
      "required": ["txId", "decision", "note"], "additionalProperties": false
    },
    "requiredEvidence": ["get_flagged_transaction", "list_account_transactions"],
    "capabilityScope": "risk.write",
    "redaction": [],
    "idempotencyKeyFrom": ["txId", "decision"]
  },
  {
    "toolId": "override_risk_score",
    "displayName": "Override an AI risk score",
    "description": "Override the model-assigned risk score on a scored transaction. Requires human signature; overriding the model is dual-control by default.",
    "mode": "write",
    "actionTypeId": "transaction.score.override",
    "authority": { "declaredRung": "L2", "policyRef": "transaction.score.override" },
    "target": { "service": "ai-service", "method": "PUT",
                "path": "/api/admin/scored-transactions/{txId}/override", "timeoutMs": 8000 },
    "parameters": {
      "type": "object",
      "properties": {
        "txId": { "type": "string" },
        "newScore": { "type": "number", "minimum": 0, "maximum": 1 },
        "justification": { "type": "string", "minLength": 40, "maxLength": 2000 }
      },
      "required": ["txId", "newScore", "justification"], "additionalProperties": false
    },
    "requiredEvidence": ["get_scored_transaction", "list_account_transactions"],
    "capabilityScope": "risk.write",
    "redaction": [],
    "idempotencyKeyFrom": ["txId", "newScore"]
  },
  {
    "toolId": "review_account_application",
    "displayName": "Decide an account-opening application",
    "description": "Approve, reject, or request-more-info on a pending account-opening application. Requires human signature.",
    "mode": "write",
    "actionTypeId": "account.application.review",
    "authority": { "declaredRung": "L1", "policyRef": "account.application.review" },
    "target": { "service": "account-opening-service", "method": "PATCH",
                "path": "/api/account-opening/applications/{applicationId}/review", "timeoutMs": 10000 },
    "parameters": {
      "type": "object",
      "properties": {
        "applicationId": { "type": "string" },
        "decision": { "type": "string", "enum": ["approved", "rejected", "more_info"] },
        "reason": { "type": "string", "maxLength": 2000 }
      },
      "required": ["applicationId", "decision", "reason"], "additionalProperties": false
    },
    "requiredEvidence": ["get_account_application", "get_application_audit"],
    "capabilityScope": "onboarding.write",
    "redaction": ["$.applicant.ssn"],
    "idempotencyKeyFrom": ["applicationId", "decision"]
  }
]
```

Endpoints deliberately **not** exposed as tools, at any rung —
`DELETE /api/admin/users/{id}`, `POST /api/admin/promote`,
`PUT /api/admin/users/{id}/reset-password`, `POST /api/admin/replay-events`. These are the L3
set. They are absent from the manifest entirely; the agent cannot even name them. See §4.3.

---

## 4. Authority policy engine

### 4.1 Format

Declarative YAML, versioned, loaded by `authority-service` at boot and hot-reloadable. Stored
in Cosmos (`authority-policy`, PK `/id`, doc id = `active`) and seeded from
`config/authority-policy.yaml` in the repo. **The application code contains no thresholds.**
It contains a rung-comparison function and an escalator evaluator, nothing more.

### 4.2 Complete policy file

```yaml
# config/authority-policy.yaml
apiVersion: authority/v1
policyVersion: "1.0.0"
description: Banker Copilot authority ladder. Agents propose; humans dispose.

defaults:
  ttlMinutes: 30
  ttlExpiryOutcome: denied          # I-6. Not configurable to anything else.
  batchApproval:
    enabled: true
    maxItems: 25
    sameActionTypeOnly: true
    maxRung: L1                     # I-10. Never L2.
  signature:
    algorithm: SHA-256
    bindsTo: payloadHash            # I-5
    voidOnPayloadChange: true

rungs:
  L1:
    signaturesRequired: 1
    signerRoles: [banker, admin]
    distinctIdentities: 1
  L2:
    signaturesRequired: 2
    signerRoles: [banker, admin]
    cosignerRoles: [supervisor, admin]
    distinctIdentities: 2           # separation of duties
    requiresIndependentSecondOpinion: true
  L3:
    proposable: false               # agent may not even propose
    reason: Out-of-harness action. Perform in the admin console with break-glass audit.

actionTypes:

  transaction.flag.review:
    displayName: Clear / confirm a flagged transaction
    baseRung: L1
    ttlMinutes: 30
    thresholds:
      - when: { field: transaction.amount, op: gte, value: 25000, currency: USD }
        rung: L2
      - when: { field: decision, op: eq, value: confirmed_fraud }
        rung: L2
    requiredEvidence: [get_flagged_transaction, list_account_transactions]

  transaction.score.override:
    displayName: Override an AI risk score
    baseRung: L2                    # overriding the model is dual-control, always
    ttlMinutes: 60
    thresholds: []
    requiredEvidence: [get_scored_transaction, list_account_transactions]

  account.application.review:
    displayName: Decide an account-opening application
    baseRung: L1
    ttlMinutes: 120
    thresholds:
      - when: { field: decision, op: eq, value: rejected }
        rung: L2                    # adverse action against a customer is never solo
      - when: { field: applicant.riskTier, op: in, value: [high, sanctions_hit] }
        rung: L2
    requiredEvidence: [get_account_application, get_application_audit]

  transfer.reverse:
    displayName: Reverse a completed transfer
    baseRung: L1
    ttlMinutes: 20
    thresholds:
      - when: { field: transfer.amount, op: gte, value: 10000, currency: USD }
        rung: L2
      - when: { field: transfer.ageHours, op: gte, value: 72 }
        rung: L2
    requiredEvidence: [get_transfer, list_account_transactions]

  account.balance.adjust:
    displayName: Post a balance adjustment
    baseRung: L1
    ttlMinutes: 20
    thresholds:
      - when: { field: adjustment.amount, op: gte, value: 1000, currency: USD }
        rung: L2
      - when: { field: adjustment.direction, op: eq, value: credit }
        rung: L2                    # creating money is always dual-control
    requiredEvidence: [get_account, list_account_transactions]

  user.account.lock:
    displayName: Lock a customer account
    baseRung: L1
    ttlMinutes: 15
    thresholds: []
    requiredEvidence: [get_user, list_login_audits]

  user.account.unlock:
    displayName: Unlock a customer account
    baseRung: L2                    # relaxing a control is dual-control; tightening is not
    ttlMinutes: 30
    thresholds: []
    requiredEvidence: [get_user, list_login_audits]

  # ---- Loans (#140). Inert until loan-origination-service ships. ----
  loan.decision.record:
    displayName: Record an underwriting decision on a loan application
    baseRung: L1
    ttlMinutes: 240
    thresholds:
      - when: { field: loan.amount, op: gte, value: 100000, currency: USD }
        rung: L2
      - when: { field: loan.amount, op: gte, value: 1000000, currency: USD }
        rung: L3
      - when: { field: underwriting.verdict, op: eq, value: CONDITIONAL }
        rung: L2                    # §7. CONDITIONAL is never single-signature.
      - when: { field: underwriting.verdict, op: eq, value: DECLINE }
        rung: L2                    # adverse action
    requiredEvidence:
      [get_loan_application, get_underwriting_decision, get_policy_evaluation]

  # ---- L3: declared so the UI can explain the refusal. Never exposed as a tool. ----
  user.delete:        { displayName: Delete a user,              baseRung: L3 }
  user.role.promote:  { displayName: Promote a user to admin,    baseRung: L3 }
  user.password.reset:{ displayName: Reset a user password,      baseRung: L3 }
  events.replay:      { displayName: Replay the event stream,    baseRung: L3 }
  authority.policy.edit:
    displayName: Modify the authority policy or capability allowlist
    baseRung: L3
    note: The harness may never edit its own leash.

escalators:
  # Every escalator can only raise. `raiseBy: 1` moves L1->L2, L2->L3. Never negative.
  - id: self-dealing
    description: Proposal touches an account or user related to the acting banker.
    when: { field: context.selfDealing, op: eq, value: true }
    raiseBy: 1
    minRung: L2

  - id: bulk-fan-out
    description: More than N proposals of the same action type in one session.
    when: { field: session.proposalCountForActionType, op: gt, value: 10 }
    raiseBy: 1

  - id: velocity
    description: Signature rate exceeds N per rolling window — approval-fatigue guard.
    when: { field: actor.signaturesInWindow, op: gt, value: 20 }
    window: PT15M
    raiseBy: 1

  - id: low-agent-confidence
    description: Primary agent confidence below floor.
    when: { field: agent.confidence, op: lt, value: 0.70 }
    raiseBy: 1

  - id: policy-exception
    description: One or more underwriting/compliance policy exceptions present.
    when: { field: underwriting.policyExceptions, op: countGte, value: 1 }
    raiseBy: 1

  - id: severe-policy-exception
    description: A hard-stop policy code is present.
    when:
      field: underwriting.policyExceptions
      op: intersects
      value: [POL-001, POL-002, POL-007]
    raiseBy: 1
    minRung: L3

  - id: high-risk-customer
    when: { field: customer.riskTier, op: in, value: [high, sanctions_hit, pep] }
    raiseBy: 1

  - id: anomalous-session
    description: Acting banker's own session flagged by login-audit heuristics.
    when: { field: session.anomalyScore, op: gte, value: 0.80 }
    raiseBy: 1
    minRung: L2

capabilityScopes:
  risk.read:        { roles: [banker, supervisor, admin] }
  risk.write:       { roles: [banker, supervisor, admin] }
  transactions.read:{ roles: [banker, supervisor, admin] }
  identity.read:    { roles: [banker, supervisor, admin] }
  onboarding.write: { roles: [banker, supervisor, admin] }
  lending.read:     { roles: [banker, supervisor, admin] }
  lending.write:    { roles: [supervisor, admin] }
```

### 4.3 Evaluation algorithm

```
rung = actionType.baseRung
for t in actionType.thresholds:            # ordered; take the MAX matched rung
    if matches(t.when, payload+context): rung = max(rung, t.rung)
for e in escalators:
    if matches(e.when, payload+context):
        rung = max(rung, rung + e.raiseBy, e.minRung ?? L1)
if rung == L3: reject NOT_PROPOSABLE
return rung
```

`max` is over the total order `L1 < L2 < L3`. There is no code path that decreases `rung`.
The function is pure, side-effect free, and gets exhaustive unit tests including a
property-based test asserting *"for all policies and payloads, adding an escalator match never
lowers the returned rung"* (I-4 as an executable invariant).

### 4.4 How bypass is prevented

Four layers, defence in depth:

1. **Tool shape.** `banker-copilot-service` registers *no* write tool with the Foundry agent.
   The only write-shaped affordance is `propose_action(actionTypeId, payload, evidenceRefs)`,
   whose target is `authority-service`. There is no tool the model can call whose target is a
   mutating domain endpoint.
2. **Identity.** The downstream mutating endpoints require a JWT bearing an
   `action-broker` claim that only `authority-service` can obtain (its own managed identity
   exchanges for a broker token). `banker-copilot-service`'s forwarded banker JWT is
   sufficient for reads and insufficient for the mutating admin routes. Even a
   fully-compromised prompt yields read access only.
3. **Network.** AKS `NetworkPolicy` restricts `banker-copilot-service` egress to the read
   endpoints plus `authority-service`. The mutating admin routes are reachable only from
   `authority-service`'s pod identity.
4. **Server-side re-validation.** `authority-service` never trusts the rung the caller claims.
   It recomputes from policy, re-verifies `requiredEvidence` against the submitted trace, and
   recomputes the payload hash. The proposal body's `declaredRung` is advisory telemetry only.

Layer 1 alone is a prompt-injection away from failing. Layers 2 and 3 mean that failing layer 1
is not a security incident. **Turk: layer 2 is not optional and is not a stretch goal.**

---

## 5. Approval object model

### 5.1 Lifecycle

```
                 ┌──────────────┐
   agent calls   │   proposed   │  policy evaluated, hash computed, no human notified yet
propose_action → └──────┬───────┘
                        │ harness attaches artifact + surfaces card
                 ┌──────▼───────┐
                 │   pending    │  TTL clock running; out-of-band notification fired
                 └──┬───┬───┬───┘
    signature(s)    │   │   │   TTL elapses
    complete        │   │   └──────────────► expired  ── treated as ── ► DENIED (I-6)
                    │   │ human denies
                    │   └──────────────────► denied
                    │
              ┌─────▼──────┐   broker executes downstream REST call
              │   signed   │ ─────────────────────────────► executed | execution_failed
              └────────────┘
```

Additional transition: **payload mutation** at any point from `pending` → `proposed` with all
signatures cleared and a `signatures_voided` audit event. Also `superseded` when the agent
re-plans and issues a replacement proposal.

`executed` and `execution_failed` are terminal and distinct — a failed downstream call must
never look like a denial, and must never silently auto-retry under the old signature.

### 5.2 Cosmos design

**Container `authority-proposals`, PK `/actorId`.**

PK justification: the dominant query is *"what is waiting for me?"* — a single-partition read
by the signed-in banker on every harness poll and every UI refresh. `/id` (the repo default)
would make the inbox a cross-partition fan-out on the hottest path. Supervisor co-signing is
handled by a **second document**, a `cosignerId`-keyed pointer doc written in the same logical
operation, so the supervisor's inbox is also single-partition. Duplicating a pointer beats
fanning out a query.

TTL: container-level `defaultTimeToLive = -1` (opt-in), per-item `ttl` set to the policy TTL
**plus a 90-day retention tail** — the document must outlive the decision window for audit.
Expiry-as-denial is driven by an explicit sweeper (see §5.5), never by Cosmos TTL deletion.
Losing the record is not the same as denying the request.

```jsonc
{
  "id": "prop_01JQ...",
  "actorId": "user:banker-mchen",       // PARTITION KEY
  "cosignerId": null,
  "sessionId": "sess_01JQ...",
  "actionTypeId": "transaction.flag.review",
  "toolId": "review_flagged_transaction",
  "status": "pending",
  "rung": "L2",
  "rungExplanation": {
    "baseRung": "L1",
    "matchedThresholds": ["transaction.amount >= 25000"],
    "matchedEscalators": ["low-agent-confidence"],
    "policyVersion": "1.0.0"
  },
  "payload": { "txId": "tx_884", "decision": "cleared", "note": "..." },
  "payloadHash": "sha256:9f2c...",
  "canonicalization": "JCS/RFC-8785",
  "target": { "service": "ai-service", "method": "PUT",
              "path": "/api/admin/flagged-transactions/tx_884/review" },
  "idempotencyKey": "tx_884:cleared",
  "evidence": [
    { "toolId": "get_flagged_transaction", "traceId": "...", "spanId": "...", "hash": "sha256:..." },
    { "toolId": "list_account_transactions", "traceId": "...", "spanId": "...", "hash": "sha256:..." }
  ],
  "agentAssessment": { "recommendation": "clear", "confidence": 0.62, "agentId": "primary" },
  "secondOpinion": {
    "agentId": "supervisor",
    "independenceMode": "blind",
    "recommendation": "clear",
    "confidence": 0.81,
    "agreesWithPrimary": true
  },
  "signatures": [
    { "signerId": "user:banker-mchen", "role": "banker",
      "signedAtUtc": "2026-09-04T14:02:11Z", "payloadHash": "sha256:9f2c...",
      "authMethod": "jwt", "jti": "...", "ipHash": "sha256:..." }
  ],
  "signaturesRequired": 2,
  "distinctIdentitiesRequired": 2,
  "proposedAtUtc": "2026-09-04T13:58:02Z",
  "expiresAtUtc": "2026-09-04T14:28:02Z",
  "resolvedAtUtc": null,
  "batchId": null,
  "policyVersion": "1.0.0",
  "ttl": 7776000
}
```

**Container `authority-policy`, PK `/id`.** Doc `active` plus immutable versioned history docs.
Every proposal stamps `policyVersion`, so a decision can always be re-explained under the
policy in force at the time — not today's policy. Auditors ask this question, and "we changed
the YAML" is not an answer.

### 5.3 Payload-hash signing scheme

1. Canonicalize the payload with **JCS (RFC 8785)** — deterministic key ordering, no
   whitespace ambiguity. Hand-rolled `JSON.stringify` ordering is a rejectable shortcut.
2. `payloadHash = SHA-256(JCS(payload) || "\n" || actionTypeId || "\n" || policyVersion)`.
   Binding the action type and policy version into the hash means a signature obtained under
   the old policy cannot be replayed under a new one.
3. The signature record stores the hash the human actually saw. On execution the broker
   recomputes the hash from the stored payload and compares to **every** signature. Any
   mismatch ⇒ abort, void all signatures, revert to `proposed`, emit
   `authority.signature.voided`.
4. The UI renders the hash's first 8 hex chars next to the payload preview so the demo can
   show it changing.

This is the concrete answer to the $5k→$50k TOCTOU attack, and it is demoable in ten seconds.

### 5.4 Separation of duties

Enforced in `authority-service`, not in the UI:

- `signerId` uniqueness across the `signatures` array — a replayed signature is a no-op.
- Distinct-identity count must reach `distinctIdentitiesRequired`. The same human with two
  sessions or two tokens counts once.
- Co-signer's role must appear in `rungs.L2.cosignerRoles`.
- Co-signer must not be the proposal's `actorId`, and must not be a subject of the payload —
  the self-dealing check runs a second time at signing, against the co-signer.
- If the co-signer is the acting banker's direct report, escalate rather than accept.
  (Requires an org-graph stub; see §9.)

### 5.5 TTL and the sweeper

A hosted `BackgroundService` in `authority-service` (same shape as
`prompt-eval-service/Services/EvaluationBackgroundService.cs`) polls for `pending` proposals
past `expiresAtUtc` and transitions them to `expired`, emitting `authority.proposal.expired`.
Explicit and observable — an expired proposal is a *visible event*, not a document quietly
vanishing. `expired` is rendered in the UI as **Denied (timed out)** so nobody can read
silence as consent.

### 5.6 Out-of-band notification hooks

`INotificationSink` with pluggable implementations, config-selected:

- `redis-stream` (default, ships first) — publishes to the existing banking events stream;
  the supervisor's open Copilot session receives it over SSE.
- `webhook` — POST to a configured URL, for Teams/Slack in a live demo.
- `email` — stub in the demo; interface exists so it is not a refactor later.

Notification is **fire-and-forget and never gates state.** A failed notification must not block
or auto-approve anything. Notification failures are logged and surfaced in System Health.

### 5.7 Audit into event-processor

`authority-service` publishes to the existing Redis Stream (`BankingEvent{eventType, data}`,
consumed by `src/event-processor/main.go`) for:
`authority.proposal.created`, `.signed`, `.cosigned`, `.denied`, `.expired`, `.executed`,
`.execution_failed`, `.signatures_voided`, `authority.policy.changed`.

`event-processor` needs new cases added to its `switch evt.EventType` — currently it warns
`Audit Unknown event type` on anything unrecognized, which would make the audit trail
technically present but operationally invisible. Small change; do not skip it.

---

## 6. Subagent policy

### 6.1 Default is single-threaded

The harness stays single-threaded. Fan-out is opt-in per trigger, because concurrency costs
trace legibility and the trace pane *is* the demo.

### 6.2 Fan-out triggers (concrete)

Spawn a subagent when **any** holds:

| Trigger | Rule |
|---|---|
| **Independent second opinion** | Rung resolves to L2. **Mandatory** — this is the only non-negotiable fan-out. |
| **Bounded parallel evidence** | ≥ 3 independent read tools with no data dependency between them, each expected > 1s. Fan out as leaf workers. |
| **Domain specialization** | The task spans ≥ 2 domains (risk + identity + lending) and each needs > 5 tool calls. One subagent per domain. |
| **Wide scan** | The task ranges over > 25 entities (e.g. "review today's flagged queue"). Shard by entity, cap concurrency. |

Stay single-threaded when: the plan is < 5 tool calls; steps are sequentially dependent; the
answer is a single entity lookup; or a human is mid-approval (never fan out while a card is
pending — new evidence arriving after a human read the card is a TOCTOU hazard).

### 6.3 Limits

`maxConcurrentSubagents: 4`, `maxSubagentDepth: 2` (no grandchildren), per-subagent tool budget
20, wall-clock budget 60s, and **subagents inherit the parent's capability allowlist and cannot
call `propose_action`**. Only the root harness proposes. This keeps one throat to choke on the
approval path.

All limits live in `config/harness-limits.yaml`, per I-3.

### 6.4 Independence of the second opinion

A "second opinion" that reads the first opinion is a rubber stamp with extra latency. Enforce
independence structurally, not by prompting:

1. **Blind by construction.** The supervisor agent is spawned with a fresh Foundry thread. Its
   input is the **task framing and the raw entity IDs only** — never the primary's plan,
   narrative, recommendation, or confidence. The harness constructs this input from the
   original banker intent, not from the primary's output.
2. **Independent retrieval.** The supervisor re-executes its own read tools. It may not consume
   the primary's cached tool results. Yes, that doubles read cost; reads are cheap and the
   whole point is a second draw from the evidence.
3. **Different system prompt and posture.** The primary is framed as *"work the case"*; the
   supervisor as *"determine whether the requested action is defensible on the evidence, and
   state the strongest argument against it."* Adversarial framing, not confirmatory.
4. **Different model deployment where available.** Config-driven
   (`supervisor.modelDeployment`). Correlated errors between two instances of the same model
   on the same evidence are real; a different deployment is cheap partial mitigation.
5. **Structural output only.** The supervisor returns
   `{recommendation, confidence, keyFactors[], strongestCounterArgument}`. It never sees, and
   therefore cannot echo, the primary's phrasing.
6. **Disagreement is a first-class signal.** If `secondOpinion.agreesWithPrimary == false`, the
   card renders both positions side by side and prose-agreement is *not* required to proceed —
   the human decides. But agreement rate is tracked. If it runs > 95% over a meaningful sample,
   independence is broken and we should say so rather than enjoy the number.

**Turk: assert independence in tests.** A unit test must verify the supervisor's constructed
prompt contains none of the primary's output tokens. If the code ever passes the primary's
conclusion downstream, the test fails.

---

## 7. #140 integration seams

### 7.1 Boundary (restated for the record)

**#140 keeps:** `loan-origination-service`, Cosmos `loan-applications` / `underwriting-decisions`,
the 6 specialist agents, the orchestration pattern choice, the intake form, the workflow
visualization, and Phase 3 downstream integration (loan → account → seed transaction).

**Banker Copilot takes:** the review dashboard and the decision panel from #140 Phase 2. Those
become the Copilot artifact canvas and the approval card. Turk should not build a decision
panel we then delete.

**Contract #140 must expose** — read-only, plus one broker-called write:

- `GET /api/loans/applications/{id}` → `get_loan_application`
- `GET /api/loans/applications/{id}/decision` → `get_underwriting_decision`
- `GET /api/loans/applications/{id}/policy-evaluation` → `get_policy_evaluation`
- `GET /api/loans/applications?status=pending_review` → `list_pending_loan_applications`
- `POST /api/loans/applications/{id}/decision` → **broker-only**, `action-broker` claim required

That last one is the whole seam. #140 builds the endpoint; it must reject any caller lacking
the broker claim. That single guard is what keeps loans inside the authority ladder.

### 7.2 Mapping #140 outputs into ladder inputs

| #140 output | Ladder input field | Effect |
|---|---|---|
| Verdict `APPROVE` | `underwriting.verdict` | Base `L1`; amount thresholds still apply. |
| Verdict `CONDITIONAL` | `underwriting.verdict` | **Threshold match → L2. Never single-signature.** Conditions are unresolved obligations; one human should not silently accept them. |
| Verdict `DECLINE` | `underwriting.verdict` | → `L2`. Adverse action against a customer is dual-control. |
| Confidence score (0–1) | `agent.confidence` | `< 0.70` fires `low-agent-confidence`, `raiseBy: 1`. |
| POL-001..POL-010 exceptions | `underwriting.policyExceptions` (array) | ≥ 1 exception fires `policy-exception` (+1). Intersection with the hard-stop set `[POL-001, POL-002, POL-007]` fires `severe-policy-exception` with `minRung: L3` — not proposable. |
| Loan amount | `loan.amount` | `≥ 100k → L2`; `≥ 1M → L3`. |
| Applicant risk tier | `customer.riskTier` | `high`/`sanctions_hit`/`pep` fires `high-risk-customer` (+1). |
| Per-agent findings | `evidence[]` | Each specialist agent's output is an evidence entry with its own hash and trace/span IDs. |

Worked example: a `CONDITIONAL` verdict at $150,000 with confidence 0.64 and POL-004 present
resolves as base `L1` → threshold `CONDITIONAL` → `L2` → threshold `amount ≥ 100k` → `L2` →
escalator `low-agent-confidence` → `L3` → escalator `policy-exception` → `L3`. Result: **not
proposable**. The agent hands the banker a complete work-up and says *"this is out of my
authority to even propose."* That is a strong demo beat and it falls out of the config, not
out of code.

The exact hard-stop membership of POL-001..POL-010 is a **#140 input** — Turk owns that list;
the placeholder above must be reconciled with the ported rule set before loans go live.

### 7.3 Sequencing

Nothing in Phases 1–3 below depends on #140. The `loan.*` action types sit inert in the policy
file until `loan-origination-service` registers its tools. When #140 lands, loans light up with
a manifest addition and no policy-engine change. That is the test of whether this design is
right.

---

## 8. Phased delivery plan

### Phase 1 — Authority engine standalone (no agent)
**Ships against:** flagged transactions, account-opening applications.
**Depends on:** nothing.

- `authority-service` scaffold (.NET 10, JWT, `Banking.Observability`, Cosmos client), modelled
  on `prompt-eval-service`.
- Policy loader + evaluator + property-based rung tests.
- `authority-proposals` / `authority-policy` containers in `infra/cloud/cosmos.tf`.
- Proposal CRUD, JCS payload hashing, signature verification, separation of duties.
- Expiry sweeper `BackgroundService`.
- Redis Stream audit publishing + new `event-processor` event cases.
- Gateway route `/api/authority/`.

**Exit:** curl a proposal, watch it evaluate to L2, sign twice from two identities, watch the
broker execute the downstream review call. Zero LLM involved. **This phase is independently
valuable and independently demoable.**

### Phase 2 — Harness shell, single-threaded
**Depends on:** Phase 1.

- `banker-copilot-service` scaffold (FastAPI, Agent Framework pinned to match `ai-service`).
- Tool manifest registry + loader with fail-closed validation.
- Read tools for the six manifest entries in §3.3 plus `get_account`, `get_transfer`,
  `get_user`, `get_account_application`, `get_application_audit`, `get_scored_transaction`.
- `propose_action` as the sole write affordance.
- Planner loop + SSE streaming; sessions/artifacts containers.
- UI `/copilot` three-pane shell; approval card with hash display and Sign.
- Gateway route `/api/copilot/` with SSE buffering off.

**Exit:** the flagged-wire narrative in §1.3 steps 1–5 runs end to end.

### Phase 3 — L2, supervisor agent, subagent fan-out
**Depends on:** Phase 2.

- Supervisor agent with blind construction; independence assertions in tests.
- Fan-out engine, limits config, nested trace rendering.
- Co-signature flow, second-inbox pointer doc, out-of-band notification sinks.
- Payload-mutation void path, wired into the UI.
- Batch approval within one action type, L1 only.

**Exit:** §1.3 steps 6–7 run end to end across two browser identities.

### Phase 4 — Loans light up (#140 showcase)
**Depends on:** Phase 3 **and** #140 Phases 1 & 3.

- Loan read tools + broker-only decision endpoint.
- `loan.*` action types activated; POL hard-stop list reconciled with Turk.
- Specialist agent outputs mapped into `evidence[]`.
- Loan review flows through the Copilot artifact canvas — no separate decision panel.

**Exit:** the "not proposable" beat from §7.2 runs live.

### Phase 5 — Admin tab retirement
- Saved Copilot views replace tabs; `/admin` becomes the break-glass console for L3 actions
  with heightened audit.
- Docs, ADRs, smoke tests against `${CUSTOM_DOMAIN}`.

---

## 9. Risks and open questions

### Genuinely hard

1. **Approval fatigue is the real threat model, not prompt injection.** If a banker signs 40
   cards an hour, "human in the loop" is theatre and we have built a slower autonomous system
   with a liability shield. The `velocity` escalator is a partial answer. The honest answer is
   that the harness must produce *fewer, better* proposals. We should track signatures-per-hour
   and time-to-sign, and treat a falling time-to-sign as a **defect**, not adoption.
2. **Independence of the second opinion is probably weaker than we want.** Same model family,
   same underlying data, same tool set ⇒ correlated errors. Blind construction and adversarial
   framing help; they do not make the opinions statistically independent. We should measure
   agreement rate and be publicly honest that a 97% agreement rate means the second opinion is
   nearly worthless as a control.
3. **`requiredEvidence` verifies presence, not relevance.** An agent can call
   `list_account_transactions` with `limit=1` and satisfy the gate. Hardening (minimum result
   counts, evidence-to-payload relevance checks) is real work and is not in Phase 1.
4. **Distributed-transaction gap in the broker.** Between `signed` and `executed` the broker
   makes a network call that can fail ambiguously. Idempotency keys cover retry; they do not
   cover "did it land?". `execution_failed` requires human re-proposal — deliberately
   conservative, and it will be annoying in a demo when a pod restarts.
5. **Policy hot-reload versus in-flight proposals.** A proposal stamped `policyVersion 1.0.0`
   signed after a reload to `1.1.0` — do we honour the old rung or void? Proposal: **void and
   re-propose** if the rung would change; leave alone otherwise. Needs Brian's ruling.
6. **SSE through the nginx gateway and Istio.** `proxy_buffering off` handles nginx. Istio
   sidecars and idle-timeout defaults have bitten this repo before. Budget real time; a
   fallback to long-poll should exist.
7. **Cost.** Independent second opinions double reads and add a model call on every L2. At demo
   scale this is noise. Saying it aloud is better than discovering it on the bill.

### Things I do not think Brian has considered yet

8. **Who is the supervisor in a demo with one browser?** L2 requires two distinct identities.
   Live demos have one presenter. We need a seeded supervisor account and a rehearsed
   two-window flow, or the marquee L2 beat cannot be shown. **This is a demo-blocking
   logistics issue, and it is cheaper to solve in Phase 1 than in dress rehearsal.**
9. **`role: supervisor` does not exist today.** `docs/adr/003-jwt-claim-roles.md` and
   `UserService.Constants.Roles` know `admin` and `user`. The ladder needs `banker` and
   `supervisor` as real claims. Adding roles touches JWT issuance, the promote endpoint, and
   seed data — and note that `user.role.promote` is itself L3, so the *mechanism for creating
   supervisors* is outside the harness. That is correct, but it means someone must provision
   supervisors out of band. Small work item, easy to discover late.
10. **The org graph for "is my direct report" does not exist.** §5.4's report-relationship check
    has no data behind it. Either stub a `managerId` on the user document in Phase 1 or drop the
    check and document the gap. Silently shipping an unenforced control is the worst option.
11. **Denial has no learning loop.** When a banker denies a proposal we capture *that* it was
    denied, not *why the agent was wrong*. A required short denial reason, stored on the
    proposal, costs almost nothing now and is the only corpus we will ever have for improving
    the harness. Trajectory evaluation is deferred — denial reasons are the cheap substitute.
12. **`GET /api/authority/policy` leaks the bank's control map.** Exposing exact thresholds to
    every authenticated banker tells an insider precisely how to structure activity to stay at
    L1. Recommendation: return the *matched* rationale for a specific proposal, not the whole
    threshold table.
13. **The read surface is itself a privacy event.** Today a banker manually opens five tabs and
    that friction is an implicit control. The Copilot dissolves it — one sentence pulls a
    customer's full financial and session history. We should log read-tool fan-out per customer
    and treat unusual breadth as auditable, even though reads need no signature.
14. **`AdminPage.tsx` is used by demo scripts and Playwright tests.** Phase 5's retirement will
    break `tests/e2e`. Plan the migration; do not discover it.

### Open questions for Brian

- **Q1.** Policy-version change with a signature in flight — void, or honour? (Risk 5)
- **Q2.** Are `banker` and `supervisor` new first-class roles, or is `supervisor` just `admin`?
  (Risk 9) Recommendation: new roles; `admin` as a superset is how ladders get quietly defeated.
- **Q3.** Is `payloadHash` display in the UI a demo feature or a permanent one? I want it
  permanent; it is the most legible security property we have.
- **Q4.** Do we require a denial reason? (Risk 11) Recommendation: yes, minimum 20 characters.
- **Q5.** Does the acting banker's *own* second signature ever suffice at L2 with a step-up
  auth (re-auth / MFA) instead of a second human? Recommendation: **no.** Separation of duties
  means separation of *people*. But it will be asked, and the answer should be on record.

---

## 10. Acceptance criteria (epic level)

- [ ] `authority-service` deployed to AKS; `/api/authority/*` reachable through the gateway.
- [ ] `banker-copilot-service` deployed to AKS; `/api/copilot/*` reachable; SSE streams cleanly
      through nginx and Istio.
- [ ] Zero thresholds in application code — verified by a repo grep gate in CI.
- [ ] Property-based test proving no escalator combination can lower a rung.
- [ ] Payload mutation after signature voids the signature; demonstrated in an e2e test.
- [ ] TTL expiry produces `expired`, renders as **Denied (timed out)**, never executes.
- [ ] L2 requires two distinct identities; same-human double-sign is rejected.
- [ ] Supervisor prompt-construction test proves no primary-agent output reaches the supervisor.
- [ ] An agent cannot reach a mutating endpoint without a broker-issued token — proven by a
      negative test that attempts the direct call with the banker JWT and gets 403.
- [ ] All nine authority event types land in `event-processor` without hitting the
      `Audit Unknown event type` branch.
- [ ] The §1.3 demo narrative runs end to end on `${CUSTOM_DOMAIN}`.
- [ ] OpenTelemetry traces span browser → harness → subagents → authority → downstream service.

---

## 11. References

- `.squad/decisions/inbox/copilot-directive-banker-copilot-*.md` — source directives
- #140 — Loan Originations port
- `docs/adr/003-jwt-claim-roles.md`, `docs/adr/004-redis-streams-event-bus.md`,
  `docs/adr/005-foundry-agents-over-direct-openai.md`
- `src/prompt-eval-service/` — the .NET Cosmos + delegate-to-Python precedent
- `src/ai-service/app/config.py` — the Agent Framework / Foundry client precedent
- `src/event-processor/main.go` — audit stream contract
