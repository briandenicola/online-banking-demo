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
| **I-5** | A signature binds to a **payload hash**, not an intent. Payload changes ⇒ signature void ⇒ re-propose. **`policyVersion` is bound into that hash**, and the action is re-evaluated under the current policy at execution: a higher rung voids the signature, an unchanged or lower rung honors it (§5.3.2). |
| **I-6** | TTL expiry means **denied**. Never auto-approved, never silently retried. |
| **I-7** | The agent runs under a **delegated banker identity** + explicit capability allowlist. No god-mode service principal. |
| **I-8** | Tools call **existing REST APIs**. Never the database directly. |
| **I-9** | The agent loop runs **server-side**. The browser is a thin streaming client. |
| **I-10** | No blanket "Approve All". Batch only within one action type, under threshold, never L2. |

## 0.1 Canonical vocabulary — NORMATIVE

Three documents describe this system: this epic, `docs/design/banker-copilot-policy-engine.md`
(Turk), and `docs/design/banker-copilot-ui.md` (Linus). **Where they name the same thing they
must spell it identically.** A cross-document audit on 2026-09-04 found four independent naming
drifts (§11.1); these are the arbitrated results. I own the contract, so these are decided, not
proposed. §5.3.1a makes them testable.

### The three entities

| Entity | Definition | Not to be confused with |
|---|---|---|
| **approval** | The durable record of a **request for human authorization** — created by the agent, signed or refused by humans, and immutable once terminal. Shorthand for *approval request*: it names the object, never the outcome. A `denied` approval is still an approval. | The *act* of approving |
| **session** | A banker's Copilot conversation. Durable, spans many turns, holds Foundry thread state. Keyed `sessionId`, container `copilot-sessions`. | A run |
| **run** | **One intent → plan → tools → artifact cycle** inside a session. Bracketed by `run.started` / `run.done`. Keyed `runId`; every trace frame carries it. A session contains many runs. | A session |

**`proposal` is not an entity.** It was one in an earlier draft of this document; it is now
retired as a noun. The word survives in exactly two places, both correct: **`proposed`**, the
approval's initial status, and **`propose_action` / `propose`**, the agent's tool and the verb
for what the agent does. Each word now does one job:

> **The agent *proposes*; the object is an *approval*; its first state is *proposed*.**

Why `approval` won over `proposal` as the entity: `proposal` describes only how the document was
born, and goes stale the moment it is signed and executed. `approval` names what the document
*is for* across its whole life, and it was already the dominant noun in the two design documents
and the API surface both were written against — choosing it left the fewest stragglers, which
matters most in a fix whose whole purpose is eliminating stragglers. The obvious objection — that
I-1 says *agents never approve*, so the agent should not create a thing called an approval — is
answered by the entity being an approval **request**: the agent requests, humans grant or refuse.
`proposed` as the initial status keeps that visible in the state machine.

**Session and run are genuinely two entities, not a naming drift.** This is worth stating
explicitly because the documents did not, and a reader could not tell. The SSE stream stays
**session-scoped** (a banker watches a conversation, not a turn) while every envelope carries
`runId`, so the UI and #333 replay can partition by run. Both properties already exist in the
design; only the definition was missing.

### The decided names

| Concept | Canonical | Rejected variants | Why |
|---|---|---|---|
| Supersede link | **`supersededByApprovalId`** | `supersededBy`, `supersededByProposalId` | Says *what it holds* (an id) and *what it points at* (an approval). `supersededBy` says neither and reads like it might hold an object. |
| Re-plan terminal reason | **`PAYLOAD_SUPERSEDED`** | `SUPERSEDED_BY_REPLAN` | The other three members are `<subject>_<participle>` (`HUMAN_DENIED`, `TTL_EXPIRED`, `POLICY_RUNG_ESCALATED`). `SUPERSEDED_BY_REPLAN` is the only one that would need a preposition. It also names the right subject: the payload is what changed, and the payload is what the hash binds. |
| Requester / partition key | **`requesterId`** | `actorId` | "Actor" is ambiguous once signers exist — a co-signer is also an actor. "Requester" can only mean one party. |
| Approval id prefix | **`apr_`** | `prop_` | Follows the entity. |
| Cosmos container | **`copilot-approvals`**, PK `/requesterId` | `authority-proposals`, PK `/actorId` | Follows the entity; Turk's partition-key analysis is the load-bearing part and is unchanged. |
| Timestamps | **`expiresAt`, `terminalAt`** | `expiresAtUtc`, `resolvedAtUtc` | `terminalAt` pairs with `terminalReason`; `…Utc` suffixes are noise when everything is UTC by convention. |
| Rung on the record | **`requiredRung`** (+ `baseRung`) | bare `rung` | Bare `rung` is ambiguous next to `baseRung` and the rung a signature satisfied. |
| Signature count | **`requiredSigners`** (+ `distinctIdentitiesRequired`) | `signaturesRequired` | Counts people, and the distinction between signatures and identities is the whole of separation of duties. |
| Action-type id | **`actionId`** | `actionTypeId` | Shorter, already dominant, unambiguous in context. |
| Escalators on the record | **`firedEscalators`** | `matchedEscalators` | An escalator *fires*; "matched" suggests it might have matched and not applied. |
| Browser-facing prefixes | **`/api/authority/*`** (approvals, policy, evaluate) and **`/api/copilot/*`** (sessions, runs, stream, messages) | everything under `/api/copilot` | One prefix per service = one nginx `location` block per service, matching the existing gateway pattern, and the enforcement boundary is legible in the URL. Routing `/api/copilot/approvals` to a different service than `/api/copilot/sessions` needs a more-specific location block whose ordering, if disturbed, silently sends approval writes to the harness. |

### Action-type id naming rule

Action ids are **policy lookup keys**, so a mismatch is a silent policy miss rather than a
compile error. Format is `<domain>.<entity>.<verb>` or `<domain>.<verb>`, where `<domain>` is the
**owning service's domain**, not the surface a banker sees it on. Applying that rule split the
adjudication between both documents rather than either winning wholesale: `transaction.flag.review`
and `loan.decision.record` from this epic; `account_opening.application.review` /
`.resubmit` and `user.lock` / `user.unlock` from Turk's (`account.application.review` wrongly
implied account-service, and `user.account.lock` invented an `account` entity inside the user
domain).

---

**Trajectory/agentic evaluation** is tracked separately in **#333**. It is not built here — but it
imposes one hard requirement on this epic that cannot be retrofitted cheaply: **the harness must
emit structured, replayable traces from day one.** See §8.0.

**Ratified rulings (Brian, 2026-09-04):** service split, role provisioning in Phase 1, the
two-session L2 demo, and the trace-schema requirement are all decided. See
`.squad/decisions/inbox/danny-banker-copilot-decisions-ratified.md`.

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

   > **The L2 beat requires two authenticated sessions — one banker, one supervisor — and this
   > is intentional.** Separation of duties means separation of *people*; a co-signature you
   > can produce from a single session is not a control, it is a second click. We are
   > deliberately **not** building any mechanism to collapse L2 into one session. Present it
   > as two browser windows (or two profiles) side by side. The visible handoff between two
   > humans is the point being demonstrated, not friction to be engineered away.

7. **The kicker.** The banker says *"actually make it $250,000 instead"* after signing.
   The payload hash changes, the signature goes void, and the card resets to `proposed`.
   That single interaction demonstrates TOCTOU resistance better than any slide.

   **Keep the disagreement beat as the centerpiece.** The strongest version of the demo is one
   where the supervisor agent's independent work-up *disagrees* with the primary — the card
   renders both positions side by side, and a human resolves it. That is the moment that
   distinguishes this from a chatbot with a confirmation dialog. Seed the demo data so at
   least one scenario produces genuine disagreement.

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

### 2.2 Why the harness is Python and `authority-service` is .NET — RATIFIED

> **Ruling (Brian, 2026-09-04): two services. `banker-copilot-service` in Python/FastAPI,
> `authority-service` in .NET.**
>
> Turk independently reached a different recommendation in
> `docs/design/banker-copilot-policy-engine.md` §1.3 — a **single Python service with two
> internal planes** — and his reasoning is sound and worth reading. His argument: every
> first-class agent construct in this repo exists only in Python; the one .NET service that
> touches Foundry (`prompt-eval-service`) does so by hand-rolled REST with no agent SDK; a
> *process* boundary rather than a *language* boundary is what buys the security property; and
> splitting languages doubles the config-consistency surface — precisely the class of bug this
> squad keeps fixing (env-var drift between AKS ConfigMap and docker-compose, Cosmos casing
> drift between .NET and Python serializers).
>
> **That recommendation was considered and overruled.** The rationale for the ruling:
>
> 1. **The enforcement boundary matters more than language affinity.** Turk is right that the
>    security property comes from the process/network boundary. But a language boundary buys
>    something his framing understates: it makes "`authority-service` contains no model SDK" a
>    *mechanically checkable* property rather than a code-review norm. In a single Python
>    service, `import agent_framework` inside the mediator plane is one careless line away and
>    will pass review on a busy day. Across a `.csproj` with no such package available at all,
>    it is not expressible. The constraint engine should not share a runtime with the thing it
>    constrains.
> 2. **`authority-service` does no Foundry or model work whatsoever.** The Python-affinity
>    argument is decisive for the harness and simply does not apply here. This service is
>    policy evaluation + Cosmos persistence + JWT verification + an outbound REST broker —
>    which is *exactly* what `user-service`, `account-service`, `transaction-service`,
>    `transfer-service`, and `prompt-eval-service` already do well in .NET. We inherit
>    `Banking.Observability`, the JWT validation pattern, central package management, and the
>    `EvaluationBackgroundService` shape for the expiry sweeper. Nothing is hand-rolled.
> 3. **Static typing genuinely helps on the security-critical component** — Turk concedes this
>    as a "genuine .NET advantage" twice (typing, and exact decimal money math). On the one
>    component where a rung-comparison bug is a control failure, we should take it rather than
>    recover it via an opt-in mypy gate.
>
> **Turk's cost objection is real and is accepted, not waved away.** A split does mean a second
> ConfigMap contract and a second Cosmos serializer to keep casing-aligned. Mitigations are
> mandatory, not optional: `authority-service` owns its containers exclusively (no Python
> service reads or writes `copilot-approvals`), so the casing-drift surface is *within* one
> service rather than across two; and the harness↔authority contract is REST with a published
> schema, not a shared document format. See `.squad/skills/cosmos-casing-audit`.
>
> Everything else in Turk's document is language-neutral and holds unchanged — it is the
> detailed design under this epic, and his §1.3 "ratification alternative"
> (`banker-copilot-harness` Python + `banker-copilot-mediator` .NET) is the shape we are
> building, under the names `banker-copilot-service` and `authority-service`.

**Why the harness is Python.** Look at what the repo actually does, not what it nominally is.
Every piece of real Foundry/Agent Framework work here is Python:

- `src/ai-service` — `agent-framework-core 1.16.0`, `agent-framework-foundry 1.10.0`,
  `FoundryAgent` / `FoundryChatClient`, `init_agents.py` bootstrap, OTEL instrumentation via
  `agent_framework.observability.enable_instrumentation`.
- `src/chatbot-service`, `src/account-opening-service` — same pinned Agent Framework stack;
  `account-opening-service`'s multi-agent pipeline is the closest existing analogue to a harness.
- `src/prompt-eval-service` — **is .NET, and its csproj contains no Foundry package at all.**
  It holds Cosmos state and delegates every model call to `ai-service` over
  `HttpClient("AiService")`.

`prompt-eval-service` is therefore not a counterexample; it is the precedent. The established
repo pattern is exactly the one ratified here: **.NET owns durable state and control; Python
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

**`banker-copilot-service` calls** — `authority-service` (approvals, approval status),
`ai-service`, `account-service`, `transaction-service`, `transfer-service`, `user-service`,
`account-opening-service`, and later `loan-origination-service`. All over HTTP, all
forwarding the banker's JWT.

**`authority-service` owns**
- `POST /api/authority/evaluate` — dry-run rung evaluation (no side effect)
- `POST /api/authority/approvals` — create durable approval request
- `GET /api/authority/approvals`, `GET /api/authority/approvals/{id}`
- `POST /api/authority/approvals/{id}/sign`, `.../deny`
- `GET /api/authority/policy` — the effective, resolved policy (for the UI to render "why L2")
- The action broker: on final signature, executes the downstream REST call
- Cosmos: `copilot-approvals` (PK `/requesterId`), `authority-policy` (PK `/id`)
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
   `actionId` fails registration at service start. Fail closed, loudly.

### 3.2 Manifest schema

```jsonc
{
  "$schema": "https://onlinebankingdemo.bjdazure.tech/schemas/tool-manifest/v1.json",
  "toolId": "string",                 // stable, snake_case, unique
  "displayName": "string",
  "description": "string",            // becomes the model-facing tool description
  "mode": "read" | "write",           // 'write' tools are ALWAYS routed via propose_action
  "actionId": "string | null",    // null iff mode == 'read'
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
re-validates it server-side against the submitted trace; an approval whose trace lacks a
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
    "actionId": null,
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
    "actionId": null,
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
    "actionId": null,
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
    "actionId": "transaction.flag.review",
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
    "actionId": "transaction.score.override",
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
    "actionId": "account_opening.application.review",
    "authority": { "declaredRung": "L1", "policyRef": "account_opening.application.review" },
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
# policyVersion is DERIVED from the resolved policy content at load time, not written here —
# it is bound into every signature's payload hash (§5.3.1, §5.3.2), so a stale hand-maintained
# value would let a signature from the old policy validate under the new one. Turk owns the
# derivation rule; the constraint is that it must be computable from content alone.
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
    requiredSigners: 1
    signerRoles: [banker, admin]
    distinctIdentities: 1
  L2:
    requiredSigners: 2
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

  account_opening.application.review:
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

  user.lock:
    displayName: Lock a customer account
    baseRung: L1
    ttlMinutes: 15
    thresholds: []
    requiredEvidence: [get_user, list_login_audits]

  user.unlock:
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
    description: Approval touches an account or user related to the acting banker.
    when: { field: context.selfDealing, op: eq, value: true }
    raiseBy: 1
    minRung: L2

  - id: bulk-fan-out
    description: More than N approvals of the same action type in one session.
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

**This same function is called a second time, at execution.** §5.3.2 re-invokes `evaluate()`
against the *current* policy and compares the result to the rung the signatures satisfied. That
comparison uses this same `max`/total-order machinery — it is the monotonic rule applied over
time rather than over context, not a separate mechanism. Purity is what makes that reuse safe:
the same inputs must yield the same rung whether evaluated at propose time or execution time.

### 4.4 How bypass is prevented

Four layers, defence in depth:

1. **Tool shape.** `banker-copilot-service` registers *no* write tool with the Foundry agent.
   The only write-shaped affordance is `propose_action(actionId, payload, evidenceRefs)`,
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
   recomputes the payload hash. The approval body's `declaredRung` is advisory telemetry only.

Layer 1 alone is a prompt-injection away from failing. Layers 2 and 3 mean that failing layer 1
is not a security incident. **Turk: layer 2 is not optional and is not a stretch goal.**

> ⚠️ **Layers 2 and 3 are currently unimplementable as written. Two pre-existing platform
> defects block them, both filed standalone and both verified against the source:**
>
> - **#334 — all services share one JWT audience (`banking-demo`) and one symmetric signing
>   key.** All 5 .NET services (`appsettings.json`) and all 4 Python services (`app/auth.py`,
>   confirmed in `docker-compose.yml`) validate the same audience. There is no way to mint a
>   broker-only token that `banker-copilot-service` cannot also obtain — and with HS256 and a
>   shared secret, any service can *forge* one. **Layer 2 does not exist until #334 lands.**
> - **#336 — one shared workload identity (`banking-workload-identity` → the
>   `banking_services` UAMI) for all 11 pods**, holding account-scoped Cosmos Data Contributor.
>   The layer-1 claim above ("`banker-copilot-service` receives no domain Cosmos role
>   assignment") is not achievable today: the harness pod would inherit write access to every
>   container, so tool-shape isolation degrades to *not putting a container name in a
>   ConfigMap* — a convention, not a control. It also means "`authority-service`'s pod
>   identity" in layer 3 does not currently exist as a distinguishable thing.
>
> **This is the honest status: the four-layer defence is currently a one-and-a-half-layer
> defence.** Phase 1 must include a dedicated workload identity for `authority-service`
> (smallest slice of #336 that makes layer 1 real). #334 should be sequenced alongside Phase 3,
> before L2 means anything outside a demo. Shipping the harness while believing all four layers
> hold would be the worst outcome here — worse than shipping with the gap documented.

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
    complete        │   │   └───────────────┐
                    │   │ human denies      │
                    │   └───────────────────┤
                    │                       ▼
                    │                 ┌───────────┐
                    │                 │  denied   │  SINGLE terminal rejection state.
                    │                 └───────────┘  terminalReason says which:
                    │                                HUMAN_DENIED | TTL_EXPIRED
                    │                                POLICY_RUNG_ESCALATED
                    │                                PAYLOAD_SUPERSEDED
                    │
              ┌─────▼──────┐
              │   signed   │
              └─────┬──────┘
                    │  ┌──────────────────────────────────────────────┐
                    ├─►│ re-evaluate under CURRENT policy (§5.3.2)    │
                    │  └───────┬──────────────────────────┬───────────┘
                    │          │ rungNow > rungSigned     │ rungNow <= rungSigned
                    │          ▼                          ▼
                    │   denied                       broker executes
                    │   POLICY_RUNG_ESCALATED        downstream REST call
                    │   + NEW approval at            │
                    │     the new rung  ─────────────┤
                    │                                ▼
                    └───────────────────────►  executed  (failure keeps `signed`;
                                                        see execution.state below)
```

**Every execution passes through the re-evaluation gate.** There is no path from `signed` to
`executed` that skips it. A signature is a claim about a policy version, and that claim is
re-checked at the moment it is spent.

**The full lifecycle is `proposed → pending → signed → executed`, with `denied` as the single
terminal rejection state** (RATIFIED — see §5.1.1). **There is no `expired` state.**

> ### ⚠️ Expiry means DENIED. It has always meant denied, and collapsing the state does not
> soften it.
>
> Invariant **I-6** is untouched: **a TTL that runs out is a denial, never an approval, never a
> silent retry.** This is restated loudly here precisely *because* the state was collapsed — the
> word `expired` no longer appears in the state machine to remind a future reader, so the
> invariant has to carry itself. If you are ever tempted to make an un-signed, timed-out approval
> execute "because nobody objected", that is the single worst bug this system could have.
> **Silence is not consent.**

#### `status` vs `execution.state` — a failed execution does NOT move `status`

**There is no `execution_failed` lifecycle status.** An earlier draft of this document had one;
Turk's model (`docs/design/banker-copilot-policy-engine.md` §8.8) is correct and this section is
restated to match it **identically**, because a retry needing no new human signature is a
security-relevant claim and it must read the same in both documents or in neither:

| Situation | `status` | `execution.state` |
|---|---|---|
| Quorum met, not yet attempted | `signed` | `not_attempted` |
| Downstream call in flight | `signed` | `in_flight` |
| Downstream returned 2xx | **`executed`** | `succeeded` |
| Downstream failed / refused / hash mismatch | **`signed`** | `failed` |

**A failed execution leaves `status = signed`, because the signatures remain valid and the action
remains legitimately executable — a retry needs no new human.** Only a *successful* downstream
call advances the lifecycle to `executed`. Making failure terminal would either strand valid
signatures or force a "reopen" transition, and reopening a terminal state is exactly the edge the
four-value enum exists to avoid.

**This is safe only because retry re-enters the gate.** A retry is a fresh `execute` call and
therefore passes through §5.3.2's re-evaluation *again* — so a retry attempted after a policy
tightening is voided exactly like a first attempt. The signatures survive a downstream failure;
they do not survive a policy escalation. `ApprovalExecutionFailed` remains an audit *event*
(§5.7); events and states answer different questions.

A failed downstream call must never look like a denial, and must never silently auto-retry
without passing the gate.

#### 5.1.1 Terminal states and `terminalReason` — RATIFIED (O9)

> **Ruling (Brian, 2026-09-04).** Policy-voided approvals **persist as `denied` carrying a
> `terminalReason`. There is no first-class `voided` lifecycle state.** Turk's choice stands;
> **my counter-recommendation for a distinct `voided` state was overruled.** The reasoning,
> recorded so this reads as a decision and not a coin flip:
>
> - **Fewer lifecycle states means fewer places the state machine can be wrong.** Every state
>   multiplies the transition matrix, and this state machine guards money.
> - **`terminalReason` already carries the distinguishing semantics** — an auditor can separate
>   *policy voided* from *human denied* without a new state.
> - **It keeps re-plan supersede and policy void the same shape** rather than growing two
>   similar-but-different terminal paths that will drift apart.
>
> *"Voided" is a presentation label, not a state.*

> **Follow-on ruling (Brian, 2026-09-04) — `expired` is collapsed too.** I raised the leftover
> asymmetry as a residual and declined to act on it unilaterally; Brian has now ruled to **apply
> the principle uniformly. There is no `expired` lifecycle state.** TTL expiry writes `denied`
> with `terminalReason = TTL_EXPIRED`.
>
> Reasoning: **I-6 already declares expiry to BE a denial.** Keeping `expired` as its own state
> meant carrying a distinction `terminalReason` already carries — *the exact redundancy O9
> rejected for `voided`.* Applying the rule to `voided` but not to its twin would have left the
> principle half-applied, which is the worst of both: the cost of a rule and none of the
> consistency. It is nearly free today and expensive once dashboards, queries and UI branches
> are written against the state.
>
> **What does NOT change:** the TTL sweeper still exists and still runs (§5.5). It writes a
> different value, not a different behaviour. **Expiry still means denied, never auto-approved.**

**This ruling is only safe if the reason is genuinely load-bearing.** A `terminalReason` that is
nullable, defaulted, or free-text collapses `denied` back into an undifferentiated bucket and we
lose the distinction the ruling assumes we keep. Four conditions make it load-bearing:

**(a) `terminalReason` is mandatory on every transition to a negative terminal state.** Not
nullable, not defaulted. **A `denied` record with no reason must be impossible to write** —
enforced in the model, not by convention: non-nullable on the C# record, a required constructor
parameter (so there is no object-initializer path that omits it), and rejected by the write
guard before the Cosmos upsert. The field is nullable *only* while `status` is non-terminal.

**(b) The reasons are a closed enum of exactly four values, not free text.** Free text cannot be
grouped, so free text silently defeats (c). **All four resolve to the same state, `denied`** —
that is the point of the collapse:

| `terminalReason` | State | Meaning | What it measures |
|---|---|---|---|
| `HUMAN_DENIED` | `denied` | An eligible human signer rejected it. The only reason representing a human judgement about the *action*. | Agent judgement |
| `POLICY_RUNG_ESCALATED` | `denied` | Re-evaluation at the execution gate returned a higher rung than the signature satisfied (§5.3.2). A machine discarded a human's signature. | Policy churn |
| `PAYLOAD_SUPERSEDED` | `denied` | The agent re-planned; a replacement approval carries the changed payload. | Agent plan stability |
| `TTL_EXPIRED` | `denied` | The signature window closed unsigned. A denial by I-6 — **never an approval.** | Banker responsiveness, notification latency |

Exactly four. Adding a member requires a spec change, not just a string literal, and the enum is
enforced at the persistence layer rather than only at the API surface — an unrecognized value
must fail the write.

> **Two reconciliations with Turk's `docs/design/banker-copilot-policy-engine.md`, both of which
> he should take as corrections to shape only — his model is the ratified one:**
>
> 1. **`superseded_by:<newId>` must not encode an id inside the reason.** A reason whose value
>    embeds a unique identifier is not a closed set — it has cardinality equal to the number of
>    supersedes, so the "group by `terminalReason`" requirement in (c) degenerates into thousands
>    of one-row buckets and the denial dashboard becomes unreadable. The reason is
>    `PAYLOAD_SUPERSEDED`; the id moves to its own field, `supersededByApprovalId`. Same for the
>    policy-void path, which reuses supersede: reason `POLICY_RUNG_ESCALATED`, pointer in
>    `supersededByApprovalId`.
> 2. **Casing is normalized to `SCREAMING_SNAKE_CASE`** (`policy_change` → `POLICY_RUNG_ESCALATED`,
>    `ttl_expired_denied` → `TTL_EXPIRED`, `human_denied` → `HUMAN_DENIED`). Brian named
>    `POLICY_RUNG_ESCALATED` in the ruling; enum-shaped values also read as an enum at a glance,
>    which matters when the alternative failure mode is someone writing a string literal.

**(c) No consumer may treat `denied` as a single undifferentiated outcome — NORMATIVE.** Any
audit query, report, metric, dashboard, or UI surface that counts denials **must group by
`terminalReason`**. A bare "denial rate" that blends human rejections with policy voids and TTL
expiries is not merely imprecise, it is **actively misleading in the direction that hurts most**:
a burst of policy edits would render as bankers rejecting more of the agent's work, and we would
"fix" agent quality that was never the problem. The three have nothing to do with one another —
`HUMAN_DENIED` measures agent judgement, `POLICY_RUNG_ESCALATED` measures policy churn,
`TTL_EXPIRED` measures banker responsiveness and notification latency. Only the first belongs in
anything called agent accuracy.

> **`TTL_EXPIRED` is the most likely version of this mistake, so it is called out by name.**
> Now that the state is collapsed, every timed-out approval *is* a `denied` row. A naive
> `COUNT(*) WHERE status = 'denied'` no longer under-reports (the old failure) — it now silently
> **over-reports agent rejection** by absorbing every approval a busy banker simply never got to.
> A slow afternoon, a broken notification sink, or a TTL set too short would all read as *"the
> agent is getting worse."* The collapse traded one failure mode for a subtler one, and the
> grouping rule is what pays for it. **No metric labelled as agent or human denial rate may
> include `TTL_EXPIRED`.** A timeout is a statement about us, not about the agent.

**(d) A discarded signature must be recorded in full.** See §5.7 — a policy void is the only
event in the system where a machine throws away a human's signature, and the audit record must
name whose signature it was, which rung it satisfied, and the policy version it was bound to.

**Transitions restated under this ruling.** Both re-proposal paths now have **one shape** — the
original document reaches a terminal `denied`, and a *new* approval document is created. There
is no in-place mutation of a signed approval, and specifically **no `denied → proposed` edge**;
an approval document, once terminal, is immutable:

| Trigger | Original document | Replacement |
|---|---|---|
| Agent re-plans / payload mutates | `denied` + `PAYLOAD_SUPERSEDED` | new approval, new `id`, new hash |
| Policy escalation at the gate (§5.3.2) | `denied` + `POLICY_RUNG_ESCALATED` | new approval at the **new** rung, new slots |

*(This supersedes an earlier draft of this section in which both paths returned the existing
document to `proposed` with signatures cleared. Turk's supersede-by-new-document shape is
better and is what O9 ratifies: an immutable terminal record is what an auditor can actually
rely on, and a mutable one lets a document's history be silently rewritten.)*

### 5.2 Cosmos design

**Container `copilot-approvals`, PK `/requesterId`.**

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
  "id": "apr_01JQ...",
  "requesterId": "user:banker-mchen",       // PARTITION KEY
  "cosignerId": null,
  "sessionId": "sess_01JQ...",
  "actionId": "transaction.flag.review",
  "toolId": "review_flagged_transaction",
  "status": "pending",
  "requiredRung": "L2",
  "rungExplanation": {
    "baseRung": "L1",
    "matchedThresholds": ["transaction.amount >= 25000"],
    "firedEscalators": ["low-agent-confidence"]
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
  "requiredSigners": 2,
  "distinctIdentitiesRequired": 2,
  "proposedAtUtc": "2026-09-04T13:58:02Z",
  "expiresAt": "2026-09-04T14:28:02Z",
  "terminalAt": null,
  "terminalReason": null,                  // MANDATORY once status is terminal (§5.1.1)
  "supersededByApprovalId": null,          // set with PAYLOAD_SUPERSEDED / POLICY_RUNG_ESCALATED
  "batchId": null,
  "policyVersion": "sha256:4a1f...",
  "ttl": 7776000
}
```

> **`policyVersion` appears exactly once in this document — here, at the top level.** It was
> previously duplicated inside `rungExplanation`; that copy has been removed. See §5.3.1 for
> the single-definition rule. Two copies of a value that is bound into a security hash is a
> drift bug waiting to happen, and it would have shipped.

**Container `authority-policy`, PK `/id`.** Doc `active` plus immutable versioned history docs,
keyed by `policyVersion`. Every approval stamps `policyVersion`, so a decision can always be
re-explained under the policy in force at the time — not today's policy. Auditors ask this
question, and "we changed the YAML" is not an answer.

### 5.3 Payload-hash signing scheme

1. Canonicalize the payload with **JCS (RFC 8785)** — deterministic key ordering, no
   whitespace ambiguity. Hand-rolled `JSON.stringify` ordering is a rejectable shortcut.
2. `payloadHash = SHA-256(JCS(payload) || "\n" || actionId || "\n" || policyVersion)`.
   **`policyVersion` is bound into the hash** (RATIFIED — §5.3.2). A signature is therefore
   valid only for the exact policy version under which it was produced; it cannot be replayed
   under a different policy.
3. The signature record stores the hash the human actually saw. On execution the broker
   recomputes the hash from the stored payload and compares to **every** signature. Any
   mismatch ⇒ abort, do not execute, take the approval terminal as `denied` +
   `PAYLOAD_SUPERSEDED` (§5.1.1), and emit `ApprovalDenied`. Re-proposal creates a new
   document; the mismatched one is never repaired in place.
4. **The UI renders the hash's first 8 hex chars next to the payload preview — permanently, not
   as a demo affordance (RATIFIED, Q2).** It is the most legible security property in the
   system and it costs one line. Under §5.3.2 the hash also changes on a **policy escalation**,
   which is what makes it load-bearing rather than decorative: a visible hash is the thing that
   *explains* a re-sign request to a banker who would otherwise experience it as the system
   arbitrarily discarding their signature. "The figure you signed is not the figure being
   executed" is an abstract claim; a changed hash next to a changed number is a demonstration.
   `payloadHash` must therefore be present on the approval read model the UI consumes, not
   merely stored server-side.

This is the concrete answer to the $5k→$50k TOCTOU attack, and it is demoable in ten seconds.

#### 5.3.1 One definition of `policyVersion` — normative

`policyVersion` is a **single value with one authoritative home**, referenced everywhere else.
It must never be independently computed, defaulted, or re-derived at any of its use sites.

| Site | Field | Relationship |
|---|---|---|
| Policy document | `authority-policy` doc identity | **Authoritative source.** The value IS the identity of the resolved policy. |
| Approval record (§5.2) | `approval.policyVersion` | Copied once at `proposed`, then **immutable for the life of the approval**. |
| Payload hash (§5.3) | hash input | Reads `approval.policyVersion`. Never re-reads the live policy. |
| Trace envelope (§8.0) | `approval.required` payload | Copied from `approval.policyVersion` at emit. |
| Audit events (§5.7) | `Approval*` / `PolicyReloaded` | Copied from `approval.policyVersion`. |

**Invariant (testable):** for any approval, the `policyVersion` in the approval record, the
value bound into every signature's `payloadHash`, the value on the `approval.required` trace
frame, and the value on every audit event **are byte-identical**. A contract test asserts this;
`rungExplanation` deliberately carries no copy.

The failure this prevents is specific and quiet: the envelope's copy drifts (say it gets
defaulted to "current" at emit time), #333 replays a run and judges the rung against the wrong
policy, and the eval reports a ladder failure that never happened — or worse, misses a real one.

#### 5.3.1a The shared-identifier contract test — normative, and it covers more than `policyVersion`

**`policyVersion` was never the only value at risk.** The same failure mode — one concept, N
spellings, drifting independently across documents and then across code — produced three further
mismatches found in a cross-document audit on 2026-09-04 (§11.1). The test that catches one must
catch all of them, so it is generalized here from a `policyVersion` check into a **shared
identifier contract test**.

**Scope — every identifier that appears in more than one of the three Banker Copilot documents:**

| Class | Covered identifiers |
|---|---|
| Closed enum | The **full** `terminalReason` set: `HUMAN_DENIED`, `POLICY_RUNG_ESCALATED`, `PAYLOAD_SUPERSEDED`, `TTL_EXPIRED` — exactly four, no more, no other spelling |
| Supersede link | `supersededByApprovalId` — one name, on the approval record, the audit event, and the UI read model |
| Approval fields | `requesterId`, `requiredRung`, `baseRung`, `requiredSigners`, `payloadHash`, `policyVersion`, `expiresAt`, `terminalAt`, `terminalReason`, `actionId` |
| Audit event names | The eleven of §5.7 |
| Trace frame kinds | The envelope kinds of `docs/design/banker-copilot-ui.md` §4.2 |
| Action-type ids | Every key of the §4.2 policy file — **these are policy lookup keys; a mismatch is a silent policy miss, not a compile error** |
| Endpoint paths | `/api/authority/*`, `/api/copilot/*` |

**Mechanism.** A single generated `SharedIdentifiers` constant set is the authoritative home;
`authority-service`, `banker-copilot-service` and the UI all reference it rather than restating
literals. The test asserts (a) no string literal in any of the three codebases duplicates a
member of the set, and (b) the member list matches the spec. **The docs are checked too** — a CI
grep gate scans all three markdown files for known-bad variants, because these drifted *in the
documents first* and the documents are where the next one will start.

> **Why this is worth a test rather than care.** Turk and I independently reached the *correct*
> design — lift the id out of the reason value so the enum stays closed — and then named the
> result differently (`supersededBy` vs `supersededByProposalId`, `SUPERSEDED_BY_REPLAN` vs
> `PAYLOAD_SUPERSEDED`). Good instincts converged on the same idea and still produced a broken
> contract. **A shared vocabulary is not an outcome of everyone being careful; it is an outcome
> of something checking.** That is the entire argument for this test, and it is the same argument
> as §5.1.1(c): the rule only holds if something enforces it.

The specific way this one would have surfaced: someone writes the `GROUP BY terminalReason`
query the anti-aggregation rule (§5.1.1c) depends on, and gets two buckets for one reason —
discovered late, in the artifact whose correctness the rule exists to guarantee.

Turk owns the derivation rule for the value itself (content hash vs. semver) in
`docs/design/banker-copilot-policy-engine.md`. **My constraint on that choice:** whatever is
chosen must be *derivable from the policy content alone*, so it cannot be forgotten on edit. A
hand-maintained semver that someone neglects to bump produces two different policies sharing one
version — which silently defeats the entire binding, because a signature from the old policy
would still validate under the new one. The example above shows `sha256:4a1f...` in the
expectation that Turk lands on a content hash.

#### 5.3.2 Policy change vs. signature in flight — RATIFIED

> **Ruling (Brian, 2026-09-04), closing Q1.** A signature is valid only for the policy version
> under which it was produced, and **at execution time the action is re-evaluated under the
> CURRENT policy**:
>
> - Required rung is **higher** than the rung the signature satisfied → **signature is void.**
>   Re-propose; gather signatures again at the new rung.
> - Required rung is **unchanged or lower** → **honor the existing signature. Execute.**
> - **Never auto-downgrade, and never auto-honor an under-signed action.** A signature can only
>   ever be *invalidated* by a policy change, never *strengthened into sufficiency* by one.

**Why this shape, and why it is not a new rule.** This is **the same monotonic rule as the
dynamic escalators (§4.3, invariant I-4), applied over time instead of over context.**
Escalators only push a rung up; policy drift only invalidates, never rescues. One principle,
two axes:

| Axis | Rule | Mechanism |
|---|---|---|
| **Over context** (§4.3) | Escalators only raise the rung | `max` over the total order `L1 < L2 < L3` |
| **Over time** (§5.3.2) | Policy drift only voids, never rescues | Same `max`; compare `rungNow` to `rungSigned` |

Note what this deliberately rejects: my own earlier recommendation was *"void if the rung would
change."* That was symmetric, and symmetric is wrong. Voiding on a **downward** change would
punish a banker for a policy relaxation and generate needless re-signing churn; the signature
they gave was for *more* scrutiny than is now required, which is strictly safe. The ruling is
asymmetric because the underlying principle is.

**Implementation — one comparison, no special-casing:**

```
executeProposal(p):
    rungSigned := p.requiredRung                            # rung the signatures actually satisfied
    rungNow    := evaluate(p.actionId, p.payload, currentContext, activePolicy)

    if rungNow > rungSigned:                        # SAME max/total-order comparison as §4.3
        # O9 (§5.1.1): the ORIGINAL document goes terminal and immutable — it is never
        # rewound to `proposed`. A replacement approval carries the new rung.
        p.status         := 'denied'
        p.terminalReason := POLICY_RUNG_ESCALATED   # mandatory, closed enum
        p.terminalAt  := now()
        emit('ApprovalVoidedByPolicyChange', {           # see §5.7 for the full shape
            signedRung: rungSigned, newRung: rungNow,
            signedUnderPolicyVersion:     p.policyVersion,
            evaluatedUnderPolicyVersion:  activePolicy.version,
            discardedSignatures: p.signatures })         # WHOSE signature was thrown away
        q := propose(p.actionId, p.payload, rung = rungNow,
                     policyVersion = activePolicy.version)   # new id, new hash, new slots
        p.supersededByApprovalId := q.id
        notify(p.requesterId, POLICY_CHANGED_WHILE_PENDING, q.id)
        return                                      # do NOT execute

    # rungNow <= rungSigned  →  honor and execute. No downgrade of p.rung is recorded;
    # the audit trail preserves the rung that was actually signed.
    broker.execute(p)
```

> ⚠️ **If you find yourself writing special-case logic here, stop.** The whole point is that
> this is `max` over the same total order used in §4.3. A second, differently-shaped rule for
> the temporal case means the model has diverged, and it comes back to Brian rather than getting
> patched locally.

**Worked example (use this in the docs and the demo).** A banker signs a **$40,000 loan
decision at L1**. While it sits pending, the policy is updated to drop the L1 ceiling from
$50,000 to **$25,000**. At execution, re-evaluation returns **L2**. `L2 > L1`, so:

1. The banker's signature is **void**, and the discarded signature is recorded in full (§5.7).
2. The original approval goes **terminal**: `denied` with `terminalReason =
   POLICY_RUNG_ESCALATED` (O9, §5.1.1). It is not rewound; terminal documents are immutable.
3. A **new** approval is created at **L2** under the new `policyVersion` — new id, new
   `payloadHash`, new signature slots — linked from the original by `supersededByApprovalId`.
   The supervisor agent produces its independent second opinion (§6.4), and a **human
   supervisor co-signs** alongside the banker.

**The banker must be told why, specifically.** The UI shows *"The approval policy changed while
this was pending — your signature was invalidated because this action now requires supervisor
co-approval (L1 → L2)."* **Not** a generic error, and not a silent reset. A person who signed
something in good faith and finds it un-signed deserves the reason; anything less trains people
to distrust the card. Requirement flagged for Linus — the void path already exists in his
`approval.voided` event kind (`docs/design/banker-copilot-ui.md` §4.2), and this ruling adds
`POLICY_RUNG_ESCALATED` as a distinct reason code that must render differently from a
payload-mutation void.

**Operational consequence (Turk owns the detail):** editing the policy can invalidate N pending
approvals at once. Blast radius, banker notification, and a bulk "these were invalidated"
surface are real requirements, not edge cases — see §9 risk 5.

### 5.4 Separation of duties

Enforced in `authority-service`, not in the UI:

- `signerId` uniqueness across the `signatures` array — a replayed signature is a no-op.
- Distinct-identity count must reach `distinctIdentitiesRequired`. The same human with two
  sessions or two tokens counts once.
- Co-signer's role must appear in `rungs.L2.cosignerRoles`.
- Co-signer must not be the approval's `requesterId`, and must not be a subject of the payload —
  the self-dealing check runs a second time at signing, against the co-signer.
- If the co-signer is the acting banker's direct report, escalate rather than accept.
  (Requires an org-graph stub; see §9.)

#### 5.4.1 Step-up auth is not a substitute for a second human — RATIFIED (Q4)

> **Ruling (Brian, 2026-09-04). NO.** The acting banker's own second signature **never** suffices
> at L2 — step-up auth and MFA included. **Separation of duties means separation of people.**

On the record with the reasoning, because **this will be asked again** — it is the most natural
"efficiency" suggestion anyone will make about this system, and it arrives sounding reasonable:

**The moment step-up auth substitutes for a second human, L2 becomes L1 wearing a hat, and the
ladder collapses to a single signature.** Every threshold above L1 would then be theatre.

The precise error is a category confusion between two controls that feel similar and are not:

| Control | Answers | Defends against |
|---|---|---|
| MFA / step-up auth | **Who** is signing | A stolen session or credential |
| Separation of duties | **How many people** reviewed | A *legitimate* user making a bad or self-interested decision |

MFA proves identity; it does nothing about *count of independent judgements*. A banker who is
mistaken, pressured, or acting in their own interest is **fully authenticated the entire time**
— re-proving they are themselves adds no information whatsoever about the decision. The two are
orthogonal, and one can never stand in for the other.

This rests on the same principle as §5.8.2's decision to keep `admin` outside the banking ladder:
both prevent one identity from satisfying two signature slots.

#### 5.4.2 Denial reasons are required — RATIFIED (Q3)

> **Ruling (Brian, 2026-09-04).** A human denial **requires a reason, minimum 20 characters**,
> validated **server-side in `authority-service`** — not only in the UI.

Applies to `HUMAN_DENIED` only. The other three `terminalReason` values are machine-generated
and carry structured explanation instead (§5.7).

**It must not be satisfiable by whitespace or a single repeated character.** `"                    "`
and `"aaaaaaaaaaaaaaaaaaaa"` both clear a naïve `length >= 20` check, and a required field that
can be defeated by holding down a key is a required field in name only. Turk owns the precise
rule; the requirement is that the check operates on *meaningful* content — trim first, then
apply the length test, and reject degenerate input. Client-side validation may mirror it for
responsiveness but **is never the enforcement point**; the API rejects a bad reason with 400
regardless of what the UI did.

**Why this is worth the friction.** A denial is the only moment a human tells us the agent was
wrong. We currently capture *that* it was denied, never *why* — and denial reasons are the
cheapest and only corpus of labelled agent misjudgement we will ever have. #333 needs real
labels, so the text has to be real. This is also the last remaining input to *"why was the agent
wrong?"* that §5.1.1's structured reasons do not already answer.

### 5.5 TTL and the sweeper

A hosted `BackgroundService` in `authority-service` (same shape as
`prompt-eval-service/Services/EvaluationBackgroundService.cs`) polls for `pending` approvals
past `expiresAt` and transitions them to **`denied` with `terminalReason = TTL_EXPIRED`**,
emitting `ApprovalExpired`.

**The sweeper is unchanged in behaviour by the state collapse — it writes a different value, not
a different outcome.** It must keep existing: expiry has to be an *explicit, observable
transition*, never a document quietly vanishing or a status inferred lazily at read time from a
clock. A approval that times out is rendered in the UI as **Denied (timed out)**, so nobody can
read silence as consent. The event name stays `ApprovalExpired` — **audit events remain
differentiated even though the states merged**, which is the same principle as `terminalReason`:
collapse the state machine, never collapse the explanation.

Cosmos TTL deletion must never be the mechanism (§5.2). Losing the record is not the same as
denying the request.

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
consumed by `src/event-processor/main.go`). **Event names use `PascalCase`, matching the
existing stream vocabulary** (`TransactionCreated`, `TransferInitiated`) and Turk's design doc —
an earlier draft of this section used dotted lowercase names, which matched nothing in the repo:

`CopilotSessionStarted`, `ApprovalProposed`, `ActionProposalRejected`, `PolicyEscalated`,
`ApprovalSigned`, `ApprovalDenied`, `ApprovalExpired`, `ApprovalExecuted`,
`ApprovalExecutionFailed`, `ApprovalVoidedByPolicyChange`, `PolicyReloaded` — **eleven**.

Two naming rules, both reconciled with Turk's §7:

- **Events about a persisted approval document use `Approval*`; an action that never became one
  uses `Action*`.** `ActionProposalRejected` (policy refuses at propose time — L3, unknown
  action, under-evidenced) is correctly `Action*`, because no approval document exists to name.
- **There is no `ApprovalCosigned`.** A co-signature is an `ApprovalSigned` with `slotOrdinal: 2`
  — Turk's shape, and better than mine: a consumer counting signatures handles one case instead
  of two, and "was this the second signature?" is a field lookup rather than an event-type test.

**Every terminal-state event carries `terminalReason`** from the closed enum in §5.1.1 —
`ApprovalDenied` with `HUMAN_DENIED` or `PAYLOAD_SUPERSEDED`, `ApprovalExpired` with
`TTL_EXPIRED`, `ApprovalVoidedByPolicyChange` with `POLICY_RUNG_ESCALATED`. All four write
`status = denied`; the event and the reason carry the distinction the state no longer does.
Consumers group by reason and never aggregate across it (§5.1.1c).

`ApprovalDenied` with `HUMAN_DENIED` additionally carries the **required denial reason text**
(§5.4.1) — the only human-authored explanation in the audit trail, and the training corpus #333
needs.

**`ApprovalVoidedByPolicyChange` is the audit-critical event of this epic.** It is the *only*
record in the system that **a machine discarded a human's signature**, and it is the fact an
incident review or a regulator will ask about first. Shape agreed with Turk's §7:

| Field | Why it must be there |
|---|---|
| `discardedSignatures[] {signerId, slotOrdinal, signedAt, rungSatisfied, boundPolicyVersion}` | Names *whose* signature was thrown away. Must not be reconstructible only by inference from the superseded document — inference is not an audit trail. |
| `signedUnderPolicyVersion` / `evaluatedUnderPolicyVersion` | Both endpoints of the drift. With only one, replay cannot tell a correct escalation from a mis-resolution (§8.0). |
| `signedRung` / `newRung` | The ladder movement, without re-deriving it from policy documents. |
| `newEscalators[]` | *Which* rule fired. "It escalated" is not an explanation. |
| `terminalReason: POLICY_RUNG_ESCALATED`, `supersededByApprovalId` | Links the discarded signature to the work that replaced it. |

Emitted at the **best-effort-with-retry** tier, never fire-and-forget. `PolicyReloaded` carries
`previousPolicyVersion`, `newPolicyVersion`, `affectedApprovalCount`, `voidedApprovalIds[]` —
the audit-side half of risk 5's blast-radius question.

`event-processor` needs new cases added to its `switch evt.EventType` — currently it warns
`Audit Unknown event type` on anything unrecognized, which would make the audit trail
technically present but operationally invisible. Small change; do not skip it.

**This is not hypothetical — it is already happening.** See **#335**: `UserRegistered` and
`InsufficientFundsAttempt` are published to `banking-events` today and both fall through to the
`default:` branch. Our eleven authority event types would inherit exactly that fate. The durable
fix requested in #335 (make the `default:` branch emit an alertable metric) is what stops this
recurring; the nine `case` handlers are the local fix.

### 5.8 Role model and provisioning — Phase 1 (RATIFIED)

> **Ruling (Brian, 2026-09-04): `banker` and `supervisor` are introduced in Phase 1.** The
> ladder has no rungs without them. This moved from "open question" to Phase 1 scope.

#### 5.8.1 Current state

`src/user-service/Constants.cs` defines exactly one privileged role — `Roles.Admin` — and
`docs/adr/003-jwt-claim-roles.md` documents the single `role` claim. Controllers gate on
`[Authorize(Roles = "admin,Admin")]` (note the existing case-tolerance hack in
`transaction-service/Controllers/AdminController.cs`). There is no `banker`, no `supervisor`,
and no notion of a role hierarchy.

#### 5.8.2 Role hierarchy — decided

**`supervisor` implies `banker`. `admin` does NOT imply either.**

```
admin        — platform operator. Break-glass console, L3 actions, user lifecycle.
supervisor   — banker + co-signature authority. Implies every banker capability.
banker       — the harness operator. L1 signing, read tools.
user         — customer. No harness access at all.
```

Justification, and the second half matters more than the first:

- **`supervisor` ⊃ `banker`** because a supervisor doing ordinary case work should not need a
  second account. Every capability scope granting `banker` also grants `supervisor`
  (see `capabilityScopes` in §4.2, which already reflects this).
- **`admin` ⊅ `banker`/`supervisor`, deliberately.** The tempting shortcut is
  "admin is a superset of everything." **That is how authority ladders get quietly defeated.**
  If `admin` implied `supervisor`, then a single admin identity could satisfy both signatures
  on an L2 approval — the requester and the co-signer — and separation of duties evaporates
  while every test still passes. An admin who genuinely needs to co-sign must hold an explicit
  `supervisor` grant. Platform authority and banking authority are different axes and must not
  be modelled as one ladder.

Implementation: keep the flat `role` claim from ADR-003 for compatibility, and add an
`effectiveRoles` claim (array) computed at token issuance by expanding the hierarchy once, in
`AuthService.cs`. Consumers check `effectiveRoles`; nothing downstream re-implements expansion
logic. Expansion rules live in config (`config/role-hierarchy.yaml`), per I-3 — the hierarchy is
a policy statement, not a constant.

#### 5.8.3 Bootstrapping the first supervisor

The chicken-and-egg: `user.role.promote` is **L3** (§4.2), so the harness may not create
supervisors. Something outside the harness must.

**Recommended: Terraform-seeded bootstrap supervisor, admin break-glass thereafter.**

1. `infra/cloud` provisions a `bootstrap-supervisor-upn` value and writes the seed identity to
   Key Vault alongside the existing `jwt-key` secret pattern.
2. `user-service` gains a startup seeding path (extending the existing
   `InMemoryUserService`/Cosmos seed) that creates the bootstrap supervisor **only if no
   identity with `supervisor` exists**. Idempotent, no-op on every subsequent boot.
3. Ongoing promotion to `supervisor` happens through the **existing admin console**
   (`POST /api/admin/promote`, extended to accept the new roles) — *never* through Copilot.
   That endpoint stays L3 and stays absent from the tool manifest.
4. Every promotion emits `authority.role.granted` onto the audit stream.

Rejected alternatives, for the record: a Copilot-driven bootstrap (violates L3 outright); a
manual Cosmos document edit (unauditable, and exactly the "someone edits the database" path
this epic exists to eliminate); and an env-var superuser (a permanent standing credential with
no audit trail).

**Demo consequence, and this is the actionable bit:** the seed must create **at least two
distinct identities** — one `banker`, one `supervisor` — or the L2 beat in §1.3 cannot be
shown at all. Seed data is a Phase 1 deliverable, not a demo-day scramble.

#### 5.8.4 Separation-of-duties enforcement — server-side only

Enforced in `authority-service`, in the signature-acceptance path. **Never in the UI.** The UI
may hide a disabled button; that is a courtesy, not a control. Restating §5.4 with the role
model attached:

```
POST /api/authority/approvals/{id}/sign
  1. Verify JWT (issuer, audience, lifetime, signature).
  2. signerId := sub claim.                     // never from the request body
  3. Reject if signerId already present in signatures[].
  4. Reject if role/effectiveRoles lacks the rung's required signerRole/cosignerRole.
  5. Reject if this is a co-signature AND signerId == approval.requesterId.   ← the core check
  6. Re-run the self-dealing escalator against THIS signer (not just the requester).
  7. Accept only if distinct(signerIds) would reach distinctIdentitiesRequired.
  8. Recompute payloadHash; reject on mismatch (§5.3).
```

Step 5 is the one that must never be conditional on anything. An `admin` who is also the
requester cannot co-sign their own approval — which is precisely why `admin` does not imply
`supervisor` (§5.8.2).

#### 5.8.5 Migration impact

- **`users` Cosmos container** — additive only. Existing documents have `role: "user"` or
  `role: "admin"`; both remain valid and unchanged. New optional fields: `effectiveRoles`
  (array, computed at issuance — **not persisted**, to avoid a stale-copy consistency bug) and
  `managerId` (nullable string, see §9 risk 10). No backfill required, no downtime, no
  container recreation.
- **Existing seeded users** — unaffected. `demo@banking-demo.com` and existing admins keep
  their current authority exactly. Nobody silently gains `banker` or `supervisor`; those must
  be granted explicitly, which is the safe default and makes the change auditable.
- **Existing tokens** — remain valid. Absent `effectiveRoles` is treated as
  `[role]`, so tokens issued before the change degrade gracefully rather than 401-ing. No
  forced re-login.
- **Controller guards** — `[Authorize(Roles = "admin,Admin")]` on existing admin routes is
  untouched by this epic. Do not opportunistically refactor it here; it is entangled with the
  case-tolerance issue and belongs in its own change.
- **Interaction with #334** — the shared-audience defect means a token minted for any service
  carries these new roles everywhere. Adding roles does not worsen #334, but it does raise the
  stakes: a forged `supervisor` claim under the shared symmetric key would defeat the ladder
  outright. **#334 is therefore a hard dependency for L2 to be meaningful in a non-demo
  context**, and should be sequenced alongside Phase 3.

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

### 8.0 Cross-cutting requirement: replayable traces from day one

> **Ruling (Brian, 2026-09-04):** trajectory/agentic evaluation is **not** built in this epic —
> it is tracked in **#333**. But #333 imposes one requirement on us that cannot be retrofitted
> cheaply: **the harness must emit structured, replayable traces starting in Phase 2.**

The trace *is* the eval input. If we ship a stream shaped only for live UI rendering and try to
reconstruct eval trajectories from logs later, we will be reverse-engineering our own agent's
behaviour from prose. That is the expensive failure mode, and it is entirely avoidable by
agreeing the envelope once, now.

**One envelope serves both the live UI stream and offline eval replay.** Linus has already
defined it in `docs/design/banker-copilot-ui.md` §4.2 — `CopilotEventEnvelope` with
`{id, seq, runId, kind, ts, payload}` over 20 event kinds (`run.started`, `plan.proposed`,
`tool.started/completed/failed`, `subagent.spawned/progress/completed`,
`approval.required/updated/voided`, `artifact.created/updated`, `run.done`, …).

**I am ratifying that envelope as the single trace schema.** It is well designed for this —
`seq` is monotonic and gapless per run, which is exactly the property replay needs, and it was
chosen for UI resync. The eval-driven additions are small and must land with the envelope, not
after:

| Requirement | Why eval needs it | Status |
|---|---|---|
| `seq` monotonic + gapless per run | Deterministic replay ordering | ✅ already in Linus's design |
| Server clock `ts`, never client | Latency and timeout analysis | ✅ already in Linus's design |
| **Durable persistence of every frame** | UI streams are ephemeral; eval replays historical runs | ➕ **add** — persist to `copilot-traces` (PK `/runId`) as the frame is emitted, not reconstructed after |
| **`traceId` / `spanId` on tool frames** | Correlate agent decisions with OTEL spans across services | ➕ **add** — already captured in `evidence[]` (§5.2); lift into the frame |
| **Model, deployment, token counts on model-call frames** | Cost and regression attribution per run | ➕ **add** |
| **`parentRunId` on subagent frames** | Reconstruct the fan-out tree offline | ➕ **add** (`subagent.spawned` carries it) |
| **Redaction applied at emit, not at render** | Persisted traces outlive the session; PII must never be written | ➕ **add** — reuse the manifest `redaction` JSONPaths (§3.2) |
| **`policyVersion` + resolved rung on `approval.required`** | Eval must judge *"was the rung correct?"* | ➕ **add** — value copied from `approval.policyVersion`, never re-derived (§5.3.1) |
| **`terminalReason` on every terminal approval frame** | *"Did the ladder resolve correctly?"* is unanswerable in replay if a policy void and a human denial look identical | ➕ **add** (O9, §5.1.1) — closed enum, mandatory |

**Composition with O9 (§5.1.1).** Because policy voids, supersedes, TTL expiries and human
denials now share the single terminal state `denied`, **the trace loses the distinction
entirely unless `terminalReason` rides on the terminal frame.** Offline, a replay that sees only
"this approval ended negative" would score a policy-driven void as the banker rejecting the
agent's recommendation — scoring agent quality on an event the agent had no part in, and doing
it in the direction that makes a policy rollout look like a model regression. Same grouping rule
as §5.1.1(c) applies to every eval metric #333 builds: **group by `terminalReason`, never
aggregate across it.** Only `HUMAN_DENIED` is evidence about the agent.

The last row is the one that matters most for #333 and is easy to miss: the highest-value eval
question for this system is not *"was the recommendation good?"* but **"did the authority
ladder resolve correctly given the evidence?"** — and that is unanswerable unless the resolved
rung and the policy version that produced it are in the trace.

**Composition with §5.3.2 — one `policyVersion`, not three.** The Q1 ruling binds
`policyVersion` into the payload hash, which means the same value now appears in the approval
record, in every signature's hash input, on the `approval.required` trace frame, and on the
audit events. **These are one value with one authoritative home, not four fields that happen to
agree** — the normative rule and the contract test are in §5.3.1. Two consequences for the
trace schema specifically:

- The `approval.required` frame **copies** `approval.policyVersion`. It must never default to
  "whatever policy is active at emit time." That default would be invisible in normal operation
  and wrong exactly when it matters — during a policy change, which is precisely the scenario
  #333 most needs to replay correctly.
- Policy escalation at the execution gate emits an `approval.voided` frame with reason
  `POLICY_RUNG_ESCALATED`, carrying **both** the old and new `policyVersion` and both rungs.
  Without both endpoints of the transition in the trace, an offline replay cannot distinguish
  "the ladder escalated correctly under a policy change" from "the ladder mis-resolved" — and
  those two want opposite responses from us.

**Action for Linus and Turk:** the envelope in `docs/design/banker-copilot-ui.md` §4.2 is the
contract of record. Additions above go into that document, not into a parallel schema. Any
divergence between what the UI consumes and what we persist is a bug, not a design choice.
Cross-reference #333 when the schema lands.

> **Frontend requirement for Linus (flagged, not designed here — O9).** Because policy voids and
> human denials now share the `denied` state, the UI must key off `terminalReason` and give the
> four outcomes visibly different treatment. **A banker whose signature was voided by a policy
> change must never see a screen that reads as though a colleague rejected their work.** They
> did nothing wrong; the ground moved. The copy should name the cause — *"the approval policy
> changed while this was pending; this action now requires supervisor co-approval (L1 → L2)"* —
> and link to the replacement approval via `supersededByApprovalId` so the path forward is
> obvious rather than a dead end. Getting this wrong is not cosmetic: an approval card that
> blames the banker for a policy edit teaches people to distrust the card, and the card is the
> one artifact this entire epic rests on. Same rule for any denial *count* the UI renders —
> group by reason (§5.1.1c).

### Phase 1 — Authority engine + role model (no agent)
**Ships against:** flagged transactions, account-opening applications.
**Depends on:** nothing.

- `authority-service` scaffold (.NET 10, JWT, `Banking.Observability`, Cosmos client), modelled
  on `prompt-eval-service`.
- Policy loader + evaluator + property-based rung tests.
- `copilot-approvals` / `authority-policy` containers in `infra/cloud/cosmos.tf`.
- Approval CRUD, JCS payload hashing, signature verification, separation of duties.
- **Execution-time re-evaluation gate (§5.3.2)** — `policyVersion` bound into the hash, void on
  escalation, honor on relaxation. Both directions tested.
- Expiry sweeper `BackgroundService`.
- Redis Stream audit publishing + new `event-processor` event cases (see #335).
- Gateway route `/api/authority/`.
- **Role model (§5.8) — `banker` + `supervisor` roles in `user-service`, `effectiveRoles`
  claim, `config/role-hierarchy.yaml`, Terraform-seeded bootstrap supervisor, and seed data
  containing at least one `banker` and one distinct `supervisor` identity.**
- **Dedicated workload identity for `authority-service`** (see #336) — without it, §4.4
  layer 1 is a configuration convention rather than a control.

**Exit:** curl an approval, watch it evaluate to L2, sign twice from two identities, watch the
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
- **`CopilotEventEnvelope` emitted and persisted to `copilot-traces` per §8.0** — the eval
  contract lands here, with the harness, not later.
- UI `/copilot` three-pane shell; approval card with hash display and Sign.
- Gateway route `/api/copilot/` with SSE buffering off.

**Exit:** the flagged-wire narrative in §1.3 steps 1–5 runs end to end.

### Phase 3 — L2, supervisor agent, subagent fan-out
**Depends on:** Phase 2. **Sequence #334 alongside** — see below.

- Supervisor agent with blind construction; independence assertions in tests.
- Fan-out engine, limits config, nested trace rendering.
- Co-signature flow, second-inbox pointer doc, out-of-band notification sinks.
- Payload-mutation void path, wired into the UI.
- Batch approval within one action type, L1 only.
- **#334 (per-service JWT audience + asymmetric signing) should land in this window.** L2 is
  the rung where a forged `supervisor` claim defeats the whole ladder, and under the current
  shared symmetric key any service can mint one. L2 is demoable without #334; it is not
  *meaningful* without it. Say which one we are claiming.

**Exit:** §1.3 steps 6–7 run end to end across two browser identities (banker + supervisor —
two sessions by design, per §1.3).

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
   that the harness must produce *fewer, better* approvals. We should track signatures-per-hour
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
   cover "did it land?". A failure leaves `status = signed` / `execution.state = failed`, so a
   retry needs no new signature (§5.1) — but an *ambiguous* failure is the genuinely hard case:
   we cannot distinguish "never landed" from "landed, response lost". `Idempotency-Key:
   <approvalId>` on the downstream call is what makes the retry safe, which means **every
   mutating endpoint the broker calls must honour it** — several in this repo do not today.
   That is the real work hiding in this risk.
5. **Policy edits invalidate pending approvals in bulk — RULED, but the operational shape is
   still real work.** The correctness question is closed (§5.3.2: re-evaluate at execution;
   void only on escalation). What remains is operational: a single policy edit can invalidate
   **N pending approvals at once**, and the people who signed them find out asynchronously.
   Open sub-questions, owned by Turk with a UI requirement for Linus:
   - **Blast radius** — is escalation detected eagerly on policy change (sweep all pending
     approvals, void immediately) or lazily at execution? Lazy is simpler and is what §5.3.2's
     pseudocode specifies, but it means a banker's card can look validly signed for hours
     before failing at the moment of execution. Eager is kinder to humans and more expensive.
     My lean: **lazy for correctness, plus an eager notification sweep** — void lazily, but tell
     people eagerly.
   - **Notification** — bankers must learn their signature was invalidated without polling.
     Reuses the §5.6 out-of-band sinks.
   - **Bulk surface** — a "these were invalidated by the policy change" view. Linus's
     `approval.voided` event kind already exists; this needs a distinct `POLICY_RUNG_ESCALATED`
     reason code rendering differently from a payload-mutation void.
   - **Rollout discipline** — a careless threshold edit during a demo voids everything pending.
     Worth a confirmation step on policy writes that reports the count of affected approvals
     *before* the change lands.
6. **SSE through the nginx gateway and Istio.** `proxy_buffering off` handles nginx. Istio
   sidecars and idle-timeout defaults have bitten this repo before. Budget real time; a
   fallback to long-poll should exist.
7. **Cost.** Independent second opinions double reads and add a model call on every L2. At demo
   scale this is noise. Saying it aloud is better than discovering it on the bill.

### Things I do not think Brian has considered yet

8. **~~Who is the supervisor in a demo with one browser?~~ RESOLVED — not an issue.** Brian
   runs multi-browser demos routinely. The L2 beat uses two authenticated sessions (banker +
   supervisor) and that is intentional: separation of duties means separation of people, and
   the visible handoff is the thing being demonstrated. **No engineering work will be done to
   collapse L2 into a single session.** The only residual requirement is seed data containing
   two distinct identities — now a Phase 1 deliverable (§5.8.3).
9. **~~`role: supervisor` does not exist today.~~ RESOLVED — moved into Phase 1.** Fully
   designed in §5.8: role hierarchy (`supervisor` ⊃ `banker`; `admin` deliberately implies
   neither), Terraform-seeded bootstrap supervisor, server-side SoD enforcement, and additive
   migration on the `users` container. The subtle part worth re-reading is §5.8.2 — making
   `admin` a superset would let one identity satisfy both L2 signatures while every test still
   passed.
10. **The org graph for "is my direct report" does not exist.** §5.4's report-relationship check
    has no data behind it. Decision: add a nullable `managerId` to the user document in Phase 1
    (§5.8.5) so the check has a substrate. If we choose not to populate it, **delete the check
    rather than shipping it unenforced** — a control that exists only in the spec is worse than
    no control, because it gets counted in the security story.
11. **Denial has no learning loop.** When a banker denies an approval we capture *that* it was
    denied, not *why the agent was wrong*. A required short denial reason, stored on the
    approval, costs almost nothing now and is the only corpus we will ever have. **This gains
    urgency now that #333 exists:** trajectory eval needs labelled examples of agent
    misjudgement, and denial reasons are the cheapest possible source. Still awaiting a ruling
    (Q3 below).
12. **`GET /api/authority/policy` leaks the bank's control map.** Exposing exact thresholds to
    every authenticated banker tells an insider precisely how to structure activity to stay at
    L1. Recommendation: return the *matched* rationale for a specific approval, not the whole
    threshold table.
13. **The read surface is itself a privacy event.** Today a banker manually opens five tabs and
    that friction is an implicit control. The Copilot dissolves it — one sentence pulls a
    customer's full financial and session history. We should log read-tool fan-out per customer
    and treat unusual breadth as auditable, even though reads need no signature.
14. **`AdminPage.tsx` is used by demo scripts and Playwright tests.** Phase 5's retirement will
    break `tests/e2e`. Plan the migration; do not discover it.
15. **NEW — the four-layer defence is currently one-and-a-half layers.** #334 and #336 (both
    verified, both filed) mean layers 2 and 3 of §4.4 cannot be built as specified. This is the
    single most important honest caveat in the document. Phase 1 takes the smallest slice of
    #336; #334 is sequenced with Phase 3.
16. **NEW — persisted traces are a new PII surface.** §8.0 requires durable trace persistence
    for #333 replay. Those traces contain customer financial data pulled by read tools, and
    they will outlive the session by design. Redaction must be applied **at emit**, not at
    render — a UI-side redaction leaves the raw data in Cosmos forever. Flagged in the §8.0
    table; calling it out here because it is the kind of thing that gets deferred and then
    discovered in a compliance review.

### Open questions for Brian

**Resolved 2026-09-04:** service split (two services, .NET `authority-service` — §2.2) ·
role provisioning in Phase 1 and the role hierarchy (§5.8) · two-session L2 demo (§1.3) ·
trajectory eval → #333 with the trace-schema requirement (§8.0) · **Q1 — policy version bound
into the payload hash, execution-time re-evaluation, void only on escalation (§5.3.2)** ·
**O9 — policy voids persist as `denied` + mandatory `terminalReason`; no `voided` state
(§5.1.1)** · **`expired` collapsed into `denied` + `TTL_EXPIRED` (§5.1.1)** · **Q2 —
`payloadHash` display is permanent (§5.3)** · **Q3 — denial reasons required, 20 chars,
server-side (§5.4.2)** · **Q4 — step-up auth never substitutes for a second human (§5.4.1)**.

**Everything is closed. See the ZERO-open-questions statement below.**

**O9 is closed.** ✅ Policy-voided approvals persist as `denied` with a `terminalReason`; there
is no first-class `voided` lifecycle state. **Turk's choice stands and my counter-recommendation
was overruled** — correctly, I think, on the strongest of the three reasons Brian gave: it keeps
re-plan supersede and policy void the *same shape*, and two similar-but-different terminal paths
would have drifted apart the first time one of them got a bug fix. The ruling comes with four
conditions that make the reason load-bearing rather than decorative — mandatory non-nullable
`terminalReason`, a closed enum, a normative "never aggregate across reasons" rule for every
consumer, and full recording of the discarded signature. All four are in §5.1.1.

**O9's residual is closed too — `expired` is collapsed.** ✅ I flagged that O9's own logic
(*fewer states, fewer places to be wrong*) applied equally to `expired`, and declined to act on
it unilaterally. **Brian ruled: apply the principle uniformly. There is no `expired` state.** TTL
expiry writes `denied` + `TTL_EXPIRED`. Keeping it would have left the principle half-applied —
the cost of a rule with none of the consistency — since I-6 already declares expiry to *be* a
denial. The sweeper is unchanged in behaviour; it writes a different value, not a different
outcome, and **expiry still means denied, never auto-approved** (§5.1, §5.5). Full ruling in
§5.1.1.

**Q1 is closed.** ✅ `policyVersion` is bound into the payload hash; the action is re-evaluated
under the current policy at execution; a higher rung voids the signature, an unchanged or lower
rung honors it. Never auto-downgrade, never auto-honor an under-signed action. This is the
monotonic escalator rule (I-4) applied over time rather than over context — one principle, two
axes. **My original recommendation was symmetric ("void if the rung would change") and was
wrong**: voiding on a downward change punishes a banker for a policy relaxation and creates
re-signing churn, when the signature they gave was for strictly more scrutiny than is now
required. Full ruling, worked example, and pseudocode in §5.3.2.

**Q2 is closed.** ✅ `payloadHash` display in the UI is **permanent**, not a demo affordance. It
is the most legible security property in the system, it costs one line, and because the hash
also changes on a policy escalation (§5.3.2) it is what *explains* a re-sign request that would
otherwise look arbitrary to the banker. §5.3 item 4.

**Q3 is closed.** ✅ Human denials **require a reason, minimum 20 characters, validated
server-side** in `authority-service` — and not satisfiable by whitespace or a repeated
character. The labels feed #333, so they have to be real. §5.4.2.

**Q4 is closed.** ✅ **No.** The acting banker's own second signature never suffices at L2, step-up
auth and MFA included. The moment step-up auth substitutes for a second human, L2 becomes L1
wearing a hat and the ladder collapses to a single signature. MFA proves *who* is signing; it
says nothing about *how many people reviewed*. Those are different controls and one cannot stand
in for the other. Recorded with reasoning in §5.4.1 **because it will be asked again** — it is
the most natural efficiency suggestion anyone will make about this system, and it arrives
sounding reasonable.

### ✅ The epic has ZERO open questions.

Every question raised in this document has been ruled on. Nothing in the design is
under-specified, nothing is awaiting a decision, and no phase is gated on an answer. What
remains is genuinely open in a different sense — the **risks** above (1–7) and the **things not
yet considered** (8–16) are conditions to manage during delivery, not decisions to make before
it. Two deserve to stay visible rather than being mistaken for closed:

- **Risk 15 — the four-layer defence is currently one-and-a-half layers.** #334 and #336 are
  filed, verified, and sequenced, but until they land, layers 2 and 3 of §4.4 cannot be built as
  specified. This is a delivery dependency, not an open question, and it is the most important
  honest caveat in the document.
- **Risk 5 — policy-edit blast radius.** The correctness rule is settled (§5.3.2); the
  operational shape (lazy voiding + eager notification, and the bulk "these were invalidated"
  surface) is Turk's to design and Linus's to render.

The one thing I would still put in front of Brian is not a question but a **prediction**: the
first sustained pressure on this design will be a request to make L2 cheaper — batching
co-signatures, a standing supervisor delegation, or step-up auth again under a new name. §5.4.1
answers the last of those. The other two do not have answers yet because nobody has asked, and
they will.

---

## 10. Acceptance criteria (epic level)

- [ ] `authority-service` deployed to AKS; `/api/authority/*` reachable through the gateway.
- [ ] `banker-copilot-service` deployed to AKS; `/api/copilot/*` reachable; SSE streams cleanly
      through nginx and Istio.
- [ ] Zero thresholds in application code — verified by a repo grep gate in CI.
- [ ] Property-based test proving no escalator combination can lower a rung.
- [ ] Payload mutation after signature voids the signature; demonstrated in an e2e test.
- [ ] **Policy escalation while pending voids the signature**: sign at L1, raise the policy so
      the action requires L2, confirm execution is refused, the original goes terminal as
      `denied` + `POLICY_RUNG_ESCALATED`, and a new L2 approval is linked via
      `supersededByApprovalId` (§5.3.2, §5.1.1).
- [ ] **Policy relaxation while pending does NOT void**: sign at L2, lower the policy so the
      action requires L1, confirm the existing signature is honored and the action executes.
      The asymmetry is the ruling; test both directions or you have tested neither.
- [ ] **One `policyVersion`**: a contract test asserts the value is byte-identical across the
      approval record, every signature's hash input, the `approval.required` trace frame, and
      the audit events (§5.3.1).
- [ ] No path from `signed` to `executed` bypasses the re-evaluation gate (§5.1).
- [ ] TTL expiry produces **`denied` + `TTL_EXPIRED`**, renders as **Denied (timed out)**, and
      **never executes** — no path exists by which an unsigned, timed-out approval is acted on
      (I-6). There is no `expired` state anywhere in the codebase; a grep gate enforces it.
- [ ] **`terminalReason` is mandatory**: a persistence-layer test proves a `denied`
      record with a null/empty reason **cannot be written** — rejected by the model, not caught
      by a code review (§5.1.1a).
- [ ] **`terminalReason` is a closed enum**: no free text, no id embedded in the value.
      `supersededByApprovalId` is a separate field (§5.1.1b).
- [ ] **No consumer aggregates across `terminalReason`**: every denial count in audit queries,
      metrics and UI groups by reason. Test the misleading case explicitly — a burst of policy
      voids must **not** move a metric labelled as human/agent denial rate (§5.1.1c).
- [ ] **A policy void records the discarded signature in full** — signer, slot, rung satisfied,
      and bound policy version present on `ApprovalVoidedByPolicyChange` (§5.7).
- [ ] A terminal approval document is **immutable**: no `denied → proposed` edge exists;
      re-proposal always creates a new document linked by `supersededByApprovalId` (§5.1.1).
- [ ] **No metric labelled as agent or human denial rate includes `TTL_EXPIRED`** — tested
      explicitly, because a slow afternoon or a broken notification sink must never read as
      "the agent is getting worse" (§5.1.1c).
- [ ] **`payloadHash` is on the approval read model the UI consumes** and rendered next to the
      payload preview as a permanent feature, not behind a demo flag (Q2, §5.3).
- [ ] **A human denial without a valid reason is rejected with 400 by `authority-service`** —
      server-side, and not satisfiable by 20 spaces or 20 copies of one character. Tested with
      both degenerate inputs (Q3, §5.4.2).
- [ ] **Step-up auth / MFA does not satisfy the second L2 signature** — a negative test proves
      the acting banker cannot complete their own L2 approval by re-authenticating (Q4, §5.4.1).
- [ ] L2 requires two distinct identities; same-human double-sign is rejected.
- [ ] Supervisor prompt-construction test proves no primary-agent output reaches the supervisor.
- [ ] An agent cannot reach a mutating endpoint without a broker-issued token — proven by a
      negative test that attempts the direct call with the banker JWT and gets 403.
- [ ] All eleven authority event types land in `event-processor` without hitting the
      `Audit Unknown event type` branch (see #335)
- [ ] `banker` and `supervisor` roles exist; seed data contains two distinct identities; an
      `admin` who is the requester **cannot** co-sign their own L2 approval
- [ ] `CopilotEventEnvelope` frames are persisted to `copilot-traces` with redaction applied at
      emit, and a historical run can be replayed offline from them (#333 precondition)
- [ ] `authority-service` runs under its own workload identity, distinct from the harness (#336)
- [ ] The §1.3 demo narrative runs end to end on `${CUSTOM_DOMAIN}`, including the two-session
      L2 co-signature and the supervisor-disagreement beat
- [ ] OpenTelemetry traces span browser → harness → subagents → authority → downstream service

---

## 11. Cross-document contract

### 11.1 Naming audit, 2026-09-04 — findings

Brian found two naming drifts by grep; a systematic pass over all three documents found **four
classes**, of which the two flagged were the *smallest*. All are now swept and covered by
§5.3.1a. Recorded because the pattern matters more than any individual rename.

| # | Drift | Epic (Danny) | Policy engine (Turk) | UI (Linus) | Canonical |
|---|---|---|---|---|---|
| 1 | Supersede link | `supersededByProposalId` | `supersededBy` | `supersededBy` **and** `supersededByApprovalId` (self-inconsistent) | **`supersededByApprovalId`** |
| 2 | Re-plan reason | `PAYLOAD_SUPERSEDED` | `SUPERSEDED_BY_REPLAN` | — | **`PAYLOAD_SUPERSEDED`** |
| 3 | **Entity noun** | proposal | approval | approval | **approval** (§0.1) |
| 4 | **Action-type ids** — 5 of 13 disagreed | `account.application.review`, `user.account.lock/unlock`, `transaction.flag.review`, `loan.decision.record` | `account_opening.application.review`, `user.lock/unlock`, `flagged_transaction.review`, `loan.decision` | — | Split by the `<domain>` rule in §0.1 |
| 5 | Requester field / PK | `actorId` | `requesterId` | — | **`requesterId`** |
| 6 | Container | `authority-proposals` | `copilot-approvals` | — | **`copilot-approvals`** |
| 7 | Id prefix | `prop_` | `apr_` | — | **`apr_`** |
| 8 | Timestamps | `expiresAtUtc`, `resolvedAtUtc` | `expiresAt`, `terminalAt` | `expiresAt` | **`expiresAt`, `terminalAt`** |
| 9 | Rung / signer fields | `rung`, `signaturesRequired` | `requiredRung`, `requiredSigners` | `requiredRung` | **`requiredRung`, `requiredSigners`** |
| 10 | Action id field | `actionId` (was `actionTypeId`) | `actionId` | — | **`actionId`** |
| 11 | Escalators | `matchedEscalators` | `firedEscalators` | `firedEscalators` | **`firedEscalators`** |
| 12 | Audit event prefix | `ApprovalProposed/Executed/ExecutionFailed` | `ActionProposed/Executed/ExecutionFailed` | — | **`Approval*`** for persisted approvals; `Action*` only where no approval exists |
| 13 | Co-signature event | `ApprovalCosigned` | folded into `ApprovalSigned` + `slotOrdinal` | — | **Turk's** — no `ApprovalCosigned` |
| 14 | Trace frame kinds | `tool.started/completed` | `tool.call` / `tool.result` | `tool.started/completed/failed` | **Linus's envelope** (§8.0 already declared it the contract of record) |
| 15 | Approval SSE frame | `approval.required` | `approval.created` | `approval.required` | **`approval.required`** |
| 16 | Endpoint prefix | `/api/authority/approvals` | `/api/copilot/approvals` | — | **`/api/authority/*`** (§0.1) |
| 17 | **session vs run** | both, undefined | `sessionId` only | `runId` only | **Two distinct entities** — defined in §0.1 |
| 18 | **Lifecycle state union** | 5 states | 5 states | `proposed/pending/signed/denied/`**`expired`**`/`**`void`** | **Four + `executed`** — Linus's `ApprovalState` still carried both states the O9 and TTL rulings collapsed. Corrected in place. |
| 19 | Signer count field | `requiredSigners` | `signaturesRequired` | **`requiredSignatureCount`** | **`requiredSigners`** — a *fourth* spelling of one concept, found only on the second pass |
| 20 | Void reason field | `terminalReason` | `terminalReason` | **`voidedReason`** (+ `blockedReason: 'void'`) | **`terminalReason`** (closed enum) + `terminalDetail` (free text) |

**Findings 18–20 are the argument for the contract test, not just for this audit.** They were not
in the set Brian grepped and they were not in my first pass either — they surfaced only when I
re-ran the straggler check *after* believing the sweep was complete. #18 is the sharpest: Linus's
`ApprovalState` union still contained `'expired'` and `'void'`, the two states the TTL and O9
rulings deleted. **A ruling was ratified in the epic and never propagated to the type that the UI
would have been built against.** That is not naming drift — that is a ratified decision failing to
land, and nothing except a mechanical check was ever going to catch it.

**Two of these were materially worse than the naming drift Brian caught:**

- **#4, the action-type ids, is the most dangerous thing in this table.** Those strings are the
  **primary keys of the policy file**. A mismatch is not a compile error and not a 404 — it is a
  *silent policy miss*: the lookup fails, and whatever the fallback does becomes the security
  behaviour. Five of thirteen disagreed. This is the one that would have shipped.
- **#17, session vs run, was not a drift at all** — they are genuinely two entities and neither
  document said so, so a reader could not tell whether one concept had two names or two concepts
  shared one. Left alone, this becomes a data-model bug rather than a rename.

**What I take from it.** Turk and I independently made the *correct* call on the supersede id —
lift it out of the reason value so the enum stays closed — and then named the result differently.
**Two people reasoning well, converging on the same design, still produced a broken contract.**
Shared vocabulary is not a product of everyone being careful; it is a product of something
checking. Hence §5.3.1a, and hence the docs being grep-gated too — every one of these drifted in
the documents *first*.

### 11.2 Turk's three findings — confirmed

1. **Supersede id as its own field — agreed**, and independently reached. Naming arbitrated to
   `supersededByApprovalId` (§0.1). His reasoning is the same as mine: an interpolated value
   cannot be a member of a closed set, and the anti-aggregation rule (§5.1.1c) depends on the
   set being closed.
2. **Persistence-layer enum enforcement is not achievable in Cosmos — accepted, and my §5.1.1(b)
   wording was too strong.** Cosmos is schemaless; there is no CHECK constraint to lean on. Turk's
   substitute is the right shape: a repository type that is the **single writer** (no raw
   `Container.ReplaceItemAsync` anywhere else, enforced by an architecture test), a strongly-typed
   enum at the boundary, and **readers that fail closed** on an unrecognized value rather than
   defaulting. The last part is what actually matters — *"unknown reason"* must never silently
   become *"treat as human denial"*. The guarantee is preserved; the mechanism is application-side
   because the datastore cannot provide it. I should have written "enforced by the persistence
   *layer*", not "by the datastore".
3. **`executed` vs `execution.state` — confirmed, and my document was wrong.** I had
   `execution_failed` as a terminal lifecycle status; it is not one. A failed execution leaves
   `status = signed` / `execution.state = failed`, and **a retry needs no new human signature**.
   That is a security-relevant claim, so §5.1 now states it in the same words as his §8.8 with
   the same table. I added the half that makes it safe: **a retry re-enters the §5.3.2 gate**, so
   signatures survive a downstream failure but not a policy escalation.

---

## 12. References

- `.squad/decisions/inbox/copilot-directive-banker-copilot-*.md` — source directives
- `.squad/decisions/inbox/danny-banker-copilot-decisions-ratified.md` — **Brian's rulings,
  2026-09-04** (service split, Phase 1 roles, two-session demo, trace schema)
- `docs/design/banker-copilot-policy-engine.md` — Turk's detailed design. §1.3's Python
  recommendation was considered and overruled (§2.2); everything else holds unchanged.
- `docs/design/banker-copilot-ui.md` — Linus's UI design. **§4.2 `CopilotEventEnvelope` is the
  ratified trace schema of record** (§8.0).
- **#333** — Trajectory (agentic) evaluation for multi-agent systems. Consumes our traces.
- **#334** — Shared JWT audience + symmetric key. **Blocks §4.4 layer 2.**
- **#335** — `event-processor` audit gap. Our nine event types would inherit it.
- **#336** — Single shared workload identity. **Blocks §4.4 layers 1 and 3.**
- **#140** — Loan Originations port
- `docs/adr/003-jwt-claim-roles.md`, `docs/adr/004-redis-streams-event-bus.md`,
  `docs/adr/005-foundry-agents-over-direct-openai.md`
- `src/prompt-eval-service/` — the .NET Cosmos + delegate-to-Python precedent
- `src/ai-service/app/config.py` — the Agent Framework / Foundry client precedent
- `src/event-processor/main.go` — audit stream contract
