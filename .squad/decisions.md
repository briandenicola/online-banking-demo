---
date: 2026-09-04
author: Brian Denicola (via Copilot)
status: approved
component: epic/banker-copilot
---

# Banker Copilot epic — foundational decisions

## What

1. Agent identity = delegated banker identity (acts as the signed-in banker, banker's RBAC) plus an explicit capability allowlist. No standalone god-mode service principal.
2. All write/mutating actions are approval-gated. Certain classes escalate to a **banker supervisor agent** for secondary approval (dual control).
3. Orchestration runtime = **Azure AI Foundry Agent Service** (not a hand-rolled orchestrator).
4. Agentic/trajectory evaluation is **deferred** — out of scope for the initial epic.

## Why

User request during epic ideation for the admin/banker agentic harness ("Banker Copilot").

---

---
date: 2026-09-04
author: Brian Denicola (via Copilot)
status: approved
component: epic/banker-copilot
---

# Banker Copilot — authority & approval model

## Core Invariant

**Agents NEVER approve.** Every state-changing action carries a human signature. Agents propose, gather evidence, and recommend only. No auto-execute tier.

*Note: This supersedes the earlier draft that included an L0 agent-autonomous execution tier.*

## Authority Ladder

Dollar/severity thresholds govern **how many humans sign and how senior**, not whether a human signs.

- **L1** — acting banker signs (e.g. loans <= threshold)
- **L2** — supervisor agent produces an independent second opinion; a **human supervisor** co-signs. Separation of duties: co-signer must be a different identity than the requester.
- **L3** — outside the harness; agent may not even propose (deletes, role promotion, adverse action, changes to the harness's own policy/allowlist).

## Escalation Rules

Dynamic escalators only ever push **up** a rung, never down:
- Self-dealing
- Bulk fan-out
- Velocity
- Low agent confidence
- Policy exception (POL-xxx)
- High-risk customer
- Anomalous session

## Implementation Details

- All thresholds are **configuration-driven**, never hardcoded.
- Approval requests are durable first-class objects: proposed → pending → signed/denied/expired. TTL expiry means **denied**, never auto-approved.
- Requests reach the banker in the harness OR via out-of-band notification.
- **Signature binds to a payload hash**, not to an intent. If the agent re-plans and the payload changes, the signature is void and it must re-propose (prevents TOCTOU escalation).
- **No blanket "approve all."** Batch approval permitted only within a single action type under threshold, and never for L2 — guards against approval fatigue becoming de facto autonomy.
- Runtime is Azure AI Foundry Agent Service; agent acts under the **delegated banker identity** plus an explicit capability allowlist.
- Agentic/trajectory evaluation deferred.

## Why

Banker Copilot epic ideation with Brian. Supersedes the earlier draft that included an L0 agent-autonomous execution tier.

---

---
date: 2026-09-04
author: Brian Denicola (via Copilot)
status: approved
component: epic/banker-copilot
---

# Banker Copilot vs #140 — epic boundary

## Ownership

- **Banker Copilot** is a layer **on top of** epic #140 (loan originations port), not a fork.
- **#140 owns:** `loan-origination-service`, Cosmos containers, the 6 specialist underwriting agents, loan intake form, workflow visualization.
- **Banker Copilot owns:** the authority/approval policy engine, the agentic harness shell (task queue + live trace pane + artifact canvas), and the **review/decision surface** — which replaces the static "review dashboard / decision panel" currently in #140 Phase 2. #140 Phase 2 should be amended so Turk does not build a panel that gets replaced.

## Integration Seams

- #140's APPROVE/CONDITIONAL/DECLINE verdict is the recommendation the ladder acts on
- Its confidence score drives the low-confidence escalator
- POL-001..POL-010 exceptions drive the policy-exception escalator
- CONDITIONAL is never single-signature

## Sequencing

The policy engine and harness shell are buildable **immediately** against existing domains (transfers, account-opening, flagged transactions) and do not block on #140. Loans become the showcase vertical once both land.

#138 (Foundry private networking) is CLOSED, so #140 is unblocked.

## Why

Prevents duplicate/competing UI work across the two epics.

---

---
date: 2026-09-04
author: Linus (Frontend Dev)
status: proposed
component: epic/banker-copilot
---

# Banker Copilot — frontend UX & component design

## Design Decisions (Danny owns architecture-level sign-off)

### 1. Work surface, not chat

New full-bleed route `/copilot` with three panes — task queue (left, 280–340px) / live plan-trace (centre) / artifact canvas (right) — and the command input demoted to a ~48px strip at the **bottom**, spanning full width. Design test applied throughout: remove the text input and the surface must still be usable. Approval cards dock at the bottom of the artifact pane, **never in a modal** — a modal hides the evidence behind the thing you're being asked to trust.

### 2. Admin tabs — three-bucket split, phased, `/admin` survives

- *Subsumed*: Flagged Transactions, All Transactions, Account Applications → become task sources + agent tool surfaces; tabs remain as read-only "Classic Admin" through Phase 2, demoted in Phase 3, removed only once the harness demonstrably covers the workflow.
- *Retained unchanged*: Chatbot Prompt, AI Evaluation, Login Audit, System Health — config/ops surfaces with no per-item decision loop.
- *Explicitly L3*: User Management. Agent may not even propose; a typed "promote X to admin" yields a refusal card naming L3 and linking to Classic Admin.

Rationale: the agent's credibility depends on the banker being able to verify its claims. Removing the ground-truth tables on day one makes the agent unfalsifiable.

### 3. Transport: SSE over `fetch` + `ReadableStream`

Not native `EventSource` (cannot set an `Authorization` header; our token is in `localStorage` per `api/client.ts`, so `EventSource` forces it into a query string → nginx logs, browser history, APM spans). Not WebSocket (traffic is ~all server→client, and sign/deny are high-stakes discrete actions that want real HTTP status codes, idempotency keys, and the existing axios interceptors). Full discriminated-union event envelope with a monotonic per-run `seq` specified — 21 event kinds, so an unhandled new server event becomes a compile error rather than a silent no-op.

### 4. ⚠ Blocking infra dependency — `proxy_buffering off`

**CRITICAL FINDING:** `infra/local/gateway.nginx.conf` and `ui-app.nginx.conf` have no `proxy_buffering off` on any `/api/` location. Without it (local **and** cloud ingress) the entire trace arrives as one lump when the run ends and the "live" harness is a lie. This is the single highest-risk non-frontend dependency in the epic and needs an owner **now**.

### 5. State: external store + `useSyncExternalStore`, no new dependency

Plain-object store mutated outside React, `requestAnimationFrame` coalescing (40 events in 16ms → one render), per-node version counters so a tool call re-renders one subtree not the run, narrow selector hooks, one shared 1s ticker for all countdowns. Reducer is a pure `(state, event) => state`, which also buys a **deterministic fixture-driven demo mode** — build it week one, not week six.

### 6. Approval UX invariants expressed in the UI

Button labels are `Sign — <action>`, never "Approve" (that word is reserved for the thing agents may never do). Countdown copy is always `expires in MM:SS → DENIED`, never "auto-approves". Evidence rows deep-link back to the originating trace node, making the trace the citation index for the recommendation. Denial is a first-class path with a required reason and equal visual weight.

### 7. L2 disagreement is the flagship screen

Primary and supervisor opinions side by side with comparable confidence bars, divergent factors marked on both sides, and a **full-width `role="alert"` banner** — "THE TWO AGENTS DISAGREE. A HUMAN MUST DECIDE." The banker must select *which* recommendation they're signing (no neutral approve that papers over the dispute), overriding the supervisor requires written justification stored on the signature, and `Request more analysis` is a real third door. Signature roster explicitly shows the self-co-sign path as *disabled and explained*, not merely absent.

### 8. Signature-void handling

On `approval.voided` the card must not quietly update — that is exactly the TOCTOU the payload-hash design exists to prevent. Old card freezes/greys/stamps VOID and stays in history; new card renders a **field-level** diff (not a text diff) with material changes highlighted; dwell gate resets to full; first two lines of copy answer the banker's real first fear: *"Nothing was executed."*

### 9. Anti-approval-fatigue — concrete mechanisms

Stakes-scaled dwell timers (0s sub-threshold batch item → 25s + written justification for an L2 disagreement, full reset after a void); `IntersectionObserver` gate requiring material payload fields to actually be scrolled into view; batch approval capped at **10 items, single action type, under threshold, never L2**; randomised ~7% transcribe-one-fact spot checks; per-session approval meter with a soft pause card at 10/hour; bounded visual variance on irreversible items to break rubber-stamp muscle memory; 30s undo for reversible actions only. Explicitly rejected: hard blocks (worked around via a second login), CAPTCHAs, mandatory free-text on every item (produces "ok" fourteen times and devalues the field exactly where it matters).

### 10. Accessibility — the visual region and the announced region are different regions

Trace tree is `aria-live="off"` + `role="tree"` + `aria-busy` (explorable on demand); a separate visually-hidden region receives **coalesced 2500ms plan-level summaries**. `assertive` is reserved for exactly three events: approval required, approval voided, agent disagreement. Countdowns are `role="timer"` with `aria-hidden` digits plus discrete announcements at 5:00/1:00/0:30. Focus is never stolen by a stream event. Keyboard-first throughout, but consequential actions require a modifier (`Shift+S` to sign, never a bare `S`) and **no shortcut can bypass the dwell or disclosure gates**.

### 11. `AppShell` gains an optional `disableContainer?: boolean` prop

So `/copilot` can go full-bleed without forking the shell. Touches shared chrome — Danny's call.

## Backend Asks (Turk)

- `disagreement.kind` / `summary` / `divergentFactors` computed **server-side** and delivered on the approval object; audit-record consistency beats client flexibility.
- Escalator `explanation` strings server-supplied and rendered verbatim — the client must never assemble them from codes.
- Event replay window depth per run and the `resync_required` (409) contract for stale cursors.
- All anti-fatigue thresholds config-driven per the "thresholds never hardcoded" directive — need a source for that config.
- Persist `dwellMs` on signatures; it's the only way to measure whether the anti-fatigue design actually works.

## Sequencing Recommendation

Build the harness against **flagged transactions** first (simplest payload, real L1 flow, available today), and light up loans once #140 lands for the L2 disagreement showcase. Consistent with the scope-boundary directive.

## Why

Anticipatory frontend spike feeding Danny's epic spec, so the UX and component architecture land before implementation rather than after.

## Artifacts Produced

`.squad/skills/streaming-agent-trace-ui/SKILL.md` — reusable pattern for SSE-over-fetch with bearer auth, idempotent seq-based reducers, external-store rendering at 60fps, and coalesced `aria-live` for high-frequency live regions.

---

---
date: 2026-09-04
author: Danny (Lead/Architect)
status: proposed
component: epic/banker-copilot
---

# Banker Copilot — architecture decision

## Service Architecture: Two Services, Split by Runtime Affinity

### 1. Service Separation is the Enforcement Mechanism

**Two new services, split by runtime affinity — not one.**

- `banker-copilot-service` (Python 3.11 / FastAPI) — agent loop on Foundry Agent Service, tool dispatch, subagent fan-out, SSE streaming, artifact assembly.
- `authority-service` (.NET 10 / ASP.NET Core) — policy engine, durable approval objects on Cosmos, signature verification, separation of duties, **and the action broker**.

The split IS the enforcement mechanism for "agents never approve." A single service would put the policy engine in the same process, identity, and code-review blast radius as the LLM loop it exists to constrain.

### 2. Python for the Harness, Justified Against Repo Precedent

Every real Foundry/Agent Framework integration here is Python:
- `ai-service` (1.16.0/1.10.0)
- `chatbot-service`
- `account-opening-service`

`prompt-eval-service` is .NET and has **no Foundry package at all** — it holds Cosmos state and delegates model calls to `ai-service` over HttpClient. That is the precedent, not the counterexample: **.NET owns durable state and control; Python owns the model runtime.**

### 3. `authority-service` Contains No LLM Call and No Model SDK

This is a reviewable, enforceable property. Adding one is a rejectable PR.

### 4. Four-Layer Bypass Prevention (Defence in Depth)

Layer 1 alone is insufficient. All four must be in place:

- **Tool shape:** no write tool is registered with the model; only `propose_action` exists.
- **Identity:** mutating endpoints require an `action-broker` claim only `authority-service` can obtain. The forwarded banker JWT is read-sufficient, write-insufficient.
- **Network:** AKS NetworkPolicy restricts harness egress.
- **Server-side re-validation:** authority recomputes rung, evidence, and payload hash; caller-claimed rung is advisory telemetry only.

A fully prompt-injected agent yields **read access only**.

### 5. Payload-Hash Signing

**Signature = `SHA-256(JCS(payload) ‖ actionTypeId ‖ policyVersion)`.**

RFC 8785 canonicalization (hand-rolled key ordering is a rejectable shortcut). Binding actionType + policyVersion prevents replaying an old-policy signature under a new policy.

### 6. Cosmos `authority-proposals` Partition Key

PK = `/actorId`, NOT `/id`. Departs from the repo's `/id` default deliberately: the hot path is "what's waiting for me?" and `/id` makes every inbox read a cross-partition fan-out. Supervisor co-signing uses a duplicated `cosignerId` pointer doc — duplicating a pointer beats fanning out a query.

### 7. TTL Expiry Driven by Explicit Sweeper, Never Cosmos TTL

**Never use destructive Cosmos TTL deletion.** TTL expiry is driven by an explicit sweeper `BackgroundService`. Losing the record is not the same as denying the request. Per-item TTL carries a 90-day audit retention tail beyond the decision window.

### 8. Second-Opinion Independence is Structural, Not Prompted

Fresh Foundry thread; input is the original banker intent + raw entity IDs only; the supervisor never sees the primary's plan/narrative/recommendation/confidence; re-executes its own reads; adversarial system prompt; structured output only; different model deployment where config allows. A unit test must assert no primary-agent output tokens appear in the supervisor's constructed prompt.

### 9. Subagents Inherit Parent Allowlist and Cannot Call `propose_action`

Only the root harness proposes — one throat to choke on the approval path.

### 10. `requiredEvidence` Re-validated Server-Side

`requiredEvidence` is re-validated server-side against the submitted trace; `422 EVIDENCE_INCOMPLETE` otherwise. A model that skips its homework cannot get a card in front of a human.

### 11. Phase 1 Scope: No LLM in authority-service

Phase 1 ships `authority-service` with no LLM at all, against existing domains (flagged transactions, account-opening). Independently valuable, independently demoable, zero dependency on #140. `loan.*` action types sit inert in the policy file until `loan-origination-service` registers its tools — when #140 lands, loans light up with a manifest addition and no policy-engine change. That is the test of whether this design is right.

### 12. #140 Phase 2 Boundary Amendment

Review dashboard + decision panel move to Banker Copilot. #140 keeps intake form, workflow visualization, the 6 specialist agents, service, containers, and Phase 3 integration. #140 must add 4 read endpoints plus a broker-only `POST /api/loans/applications/{id}/decision`.

## Why

Brian's directives established the invariants (agents never approve, config-driven thresholds, payload-hash signing, separation of duties). This decision translates them into a service topology where the invariants are *enforced by structure* rather than by discipline.

## Escalations to Brian (Unresolved)

- Policy-version change with a signature in flight — void or honour? (recommend: void if the rung would change)
- Are `banker`/`supervisor` new first-class JWT roles? (recommend: yes; `admin`-as-superset is how ladders get quietly defeated)
- Single-browser demo cannot show L2 (needs 2 distinct identities) — seed a supervisor account in Phase 1, not at dress rehearsal
- Require a denial reason? (recommend: yes, min 20 chars — with trajectory eval deferred it is the only improvement corpus we will have)
- Can step-up auth substitute for a second human at L2? (recommend: **no**)

## Honest Risks Recorded in Spec

- Approval fatigue is the real threat model (falling time-to-sign should be treated as a defect, not adoption)
- Second-opinion independence is weaker than we'd like (correlated errors — measure agreement rate and be public about it)
- `requiredEvidence` verifies presence not relevance
- The read surface is itself a privacy event now that tab-hunting friction is gone

## Artifacts Produced

- `docs/epics/banker-copilot.md` (epic spec)
- GitHub epic #332
- Boundary-amendment comment on #140
- `.squad/skills/agent-authority-ladder/` (skill)

---

---
date: 2026-09-04
author: Turk (Backend Dev)
status: proposed
component: epic/banker-copilot
---

# Banker Copilot policy engine — backend design spike

## Status & Scope

**Status:** PROPOSED — requires Danny's ratification on items marked (D)
**Artifact:** `docs/design/banker-copilot-policy-engine.md`

## Design Proposals

### 1. Runtime — Python 3.11/FastAPI (Marked D)

**(D) Runtime = one new Python 3.11/FastAPI service, `banker-copilot-service`**, with two internally separated planes (harness / policy+mediator). 

Grounded in measurement: all three Foundry-integrated services here run `agent-framework-core 1.16.0` + `agent-framework-foundry 1.10.0`; the only .NET service touching Foundry (`prompt-eval-service`, net10.0) has no agent SDK and hand-rolls REST. A .NET harness would mean re-inventing the agent loop, contrary to the "not a hand-rolled orchestrator" directive.

**Conditions if ratified:**
- `Decimal`-only money math (no `float`)
- `mypy --strict` on the policy/mediator packages
- Reuse the canonical `app/auth.py` unforked

### 2. Declarative Policy File

**`config/banker-copilot/policy.yaml`** — schema plus a complete, machine-validated example covering **18 real mutating actions** enumerated from the actual controllers/routes.

Four are hard-L3 (`agent_may_propose: false`):
- Role promotion
- User delete
- Account delete
- Prompt-template change

Three are base-L2:
- User unlock
- Password reset
- Event replay

Every threshold is a *named* entry with a mandatory `SCREAMING_SNAKE` env override; resolution is env → file default, with **no code-level fallback** (fail-closed at startup). `kind: money` defaults are decimal **strings**, never YAML floats.

### 3. Escalator Monotonicity is Structural, Not Reviewed

The rule grammar admits only `raise_to` / `min_signers` / `min_seniority`, folded with `max` over the total order L1<L2<L3. There is no `lower_to` / `exempt` / `waive` construct — a downgrade is *unrepresentable*. Code-level floors (`signers >= 1`, L2 ⇒ 2 signers) apply after all config input, so the worst possible misconfiguration is "too strict," never "no human signed."

### 4. Enforcement Rests on Token-Audience Separation (Marked D)

**(D) Enforcement rests on token-audience separation as its primary control.**

**CRITICAL FINDING: Today every service validates one audience against one shared HS256 key (`banking-demo`), so a compromised agent holding a banker token can call `POST /api/transfers` directly and the ladder is decoration.** This is the repo's biggest latent authorization gap.

**Proposal:** `user-service` mints a second `banking-copilot` audience for the harness; domain services keep validating `banking-demo` and change not at all.

**Four further layers:**
- Per-execution single-use hash-bound tokens
- Istio AuthorizationPolicy (requires splitting the shared `banking-workload-identity` KSA)
- Tool-registry allowlist derived from the policy file
- Code-level invariants (propose path cannot import the executor; agents cannot construct a `HumanSigner`)

### 5. Approval Store

**Cosmos container `copilot-approvals`, partition key `/requesterId`** (justified against `/id`, `/status`, `/sessionId`).

**Expiry:**
- Lazy read-side check as the safety control
- Sweeper as housekeeper emitting the `expired`(=denied) transition
- Cosmos native TTL applied **only to terminal documents** for 90-day retention purge

**Native TTL alone is rejected** — it deletes, and a deleted doc cannot express "expired means denied."

### 6. Payload Hashing

**RFC 8785 (JCS)** with two deliberate deviations:
- Money canonicalized as fixed-scale decimal strings (floats rejected outright)
- Null/absent treated identically

Signature binds:
- approvalId
- actionId
- payload hash
- signer id
- token `jti`
- **slot ordinal** (without which one signature could fill both dual-control slots)
- timestamp
- single-use nonce

Re-plan produces a new approval; the executor recomputes the hash from the outbound body as a TOCTOU backstop.

### 7. Audit Integration

Flows into the existing `banking-events` Redis Stream using the **.NET `payload`-envelope shape** the Go `event-processor` actually reads. Nine new event types; consumer change is a purely additive `case` arm.

## Why

Anticipatory design spike for the Banker Copilot epic, feeding Danny's spec. Grounded in what this repo measurably does today rather than in generic agentic-guardrail patterns.

## Critical Findings for the Team

Independent of this epic; these are latent issues discovered during the spike:

### 1. Single Shared JWT Audience

**Finding:** All services validate one audience (`banking-demo`) against one shared HS256 key → no way to express service-to-service authorization boundaries.

**Remediation:** Introduce second `banking-copilot` audience for harness. Requires splitting shared `banking-workload-identity` KSA for per-service mesh policy.

### 2. Single Shared KSA

**Finding:** Single shared `banking-workload-identity` KSA across all deployments. Istio is installed (`istio.io/rev: asm-1-28`) but cannot distinguish workloads, so per-service mesh policy is currently unwritable.

### 3. Audit Schema Divergence

**Finding:** `account-opening-service` publishes flat fields to `account-opening-events`; every .NET publisher uses a `payload` envelope on `banking-events`. Only the latter is read by the Go consumer.

**Recommendation:** Separate cleanup ticket.

### 4. No Seniority Signal

**Finding:** `user-service` mints a single `role` claim, and everything admin-ish is `admin`/`Admin`. "Different identity" is enforceable today; "more senior" is not. L2 is not fully meaningful until this is resolved.

## Top Risks

- **(R1)** The ladder is decorative until audience separation ships — land it first and test it adversarially
- **(R2)** Bearer tokens leaking into persisted Foundry/agent-memory context
- **(R3)** Approval fatigue converting L1 into de facto autonomy

## Open Questions for Danny

- O1: Language/split
- O2: Role & seniority model
- O3: Whether domain services must require approval claims
- O4: Server-side signature vs true non-repudiation
- O5: Defining `account.delete` before the endpoint exists
- O6: Event-schema cleanup ownership
- O7: Splitting the shared KSA
- O8: Source of `session.anomalyFlags`

## Boundaries Respected

Design doc only; no service code modified; no UI work; architecture-level calls deferred to Danny and flagged (D).

---
