# Session Log: Banker Copilot epic — final ruling round + vocabulary reconciliation

**Session Date:** 2026-09-04  
**Session ID:** Banker Copilot epic — final ruling round + vocabulary reconciliation  
**Requested by:** Brian Denicola  
**Agents:** Danny (Lead/Architect), Turk (Backend Dev)  
**Epic:** #332  
**Status:** COMPLETE

---

## Executive Summary

Completed the final ruling round on Banker Copilot epic #332, achieving ZERO OPEN QUESTIONS status. Danny arbitrated outstanding architectural decisions and conducted cross-document vocabulary reconciliation, finding and fixing 17 identifier mismatches across three specification documents. Turk applied all rulings to the policy engine design with three important corrections to own earlier specifications. Epic is now specification-complete with all design decisions ratified and documented.

---

## The Rulings

### O9: Terminal States & `terminalReason` (Ratified)

**Decision:** Policy-voided approvals persist as `denied` carrying `terminalReason`. No first-class `voided` lifecycle state.

**Rationale:**
- Fewer lifecycle states → fewer places to be wrong
- `terminalReason` already carries the distinguishing semantics
- Keeps re-plan supersede and policy void the same shape (avoiding divergence)

**Safety Conditions (All Required):**
1. Mandatory `terminalReason` on every negative terminal transition (non-nullable, required constructor parameter, rejected by write guard)
2. Closed enum: `HUMAN_DENIED`, `POLICY_RUNG_ESCALATED`, `PAYLOAD_SUPERSEDED`, `TTL_EXPIRED`
3. Normative grouping rule: All consumers must group by `terminalReason` (no bare "denial" counting)
4. Full discarded signature recording: `ApprovalVoidedByPolicyChange` event carries full signature state

**Turk's Corrections to O9:**
- Supersede reason was encoded in value (`superseded_by:<newId>`) — moved to own field `supersededByProposalId`
- Audit event names normalized to PascalCase (matching repo patterns)
- Own §5.1 contradicted the ruling (rewinding to proposed) — corrected to immutable terminal record

### Q1: Policy Escalation & Expiry (Resolved in O9)

**Composition with #333 Replay:** `terminalReason` must ride on terminal trace frame, else replay misattributes policy voids as banker rejection.

### Q2: `payloadHash` Display (Ruling: PERMANENT)

**Decision:** Not a demo affordance. Permanent requirement on approval read model.

**Justification:** Most legible security property in system; costs one line; changes on policy escalation (making it load-bearing rather than decorative). Visible hash explains re-sign request to banker without appearing arbitrary.

**Requirement:** Must appear on approval read model UI consumes, not merely server-side storage. Server provides `payloadHashShort` for non-truncation.

### Q3: Denial Reason (Ruling: REQUIRED, ≥20 chars, server-side)

**Decision:** Applies to `HUMAN_DENIED` only (other three reasons machine-generated with structured explanation).

**Validation (6 layers, in `authority-service`):**
1. NFC-normalize
2. Trim whitespace
3. Collapse internal whitespace for measurement only
4. Measure in grapheme clusters (not bytes/UTF-16) — non-Latin reasons don't need triple substance
5. Repeated-unit check: kill `aaaa…` and `asdfasdfasdf`
6. Minimum letter count: kill digit/punctuation padding

**Degenerate Input Examples Rejected:** `"        "` (20 spaces), `"aaaaaaaaaaaaaaaaaaaa"` (repeated char)

**Acknowledgment:** Rules stop lazy input, not determined garbage. If #333 needs trustworthy labels, that is a sampling/review problem.

**Config Keys (All with Env Overrides):**
- `DENIAL_REASON_MIN_LENGTH` (default: 20)
- `DENIAL_REASON_MAX_LENGTH`
- `DENIAL_REASON_MIN_DISTINCT_CHARS`
- `DENIAL_REASON_MAX_REPEAT_UNIT`
- `DENIAL_REASON_MIN_LETTERS`

### Q4: Step-up Auth at L2 (Ruling: NO)

**Decision:** Banker's own second signature never suffices at L2, MFA included. Separation of duties means separation of people.

**Category Confusion Corrected:**

| Control | Answers | Defends Against |
|---------|---------|-----------------|
| MFA / Step-up Auth | **Who** is signing | Stolen session or credential |
| Separation of Duties | **How many people** reviewed | Legitimate user making bad or self-interested decision |

**Why NO Works:** MFA re-proves identity of already fully-authenticated banker — adds no information about the decision. Same principle as keeping `admin` outside banking ladder.

**Enforcement:** Structural — `mustDifferFrom` built by evaluator, no policy verb can empty it.

**Prediction on Record:** First sustained pressure on design will be request to make L2 cheaper (batching, delegation, or step-up under new name). Q4 answers the third; others have no answer yet because no one asked.

### Final Lifecycle Ruling: Collapse `expired` State

**Decision:** No `expired` lifecycle state. `proposed → pending → signed → executed`, `denied` single terminal rejection state.

**Mechanism Unchanged:** TTL sweeper still runs, now writes `denied` + `TTL_EXPIRED` instead of `expired`.

**Critical Invariant:** Expiry still means denied, never auto-approved. (Silence is not consent.)

**Visibility Loss Call-out:** Collapsing the state removes the word `expired` from state machine; the invariant now carries itself.

**Subtle Failure Mode:** `COUNT(*) WHERE status = 'denied'` now over-reports agent rejection by absorbing all timed-out proposals. Slow afternoon, broken notification sink, or TTL too short would all read as "agent is getting worse."

**Mitigation:** §5.1.1(c) grouping rule pays for collapse. `TTL_EXPIRED` explicitly named; misdiagnosis spelled out.

**Audit Events:** Differentiation retained — `ApprovalExpired` remains own event type. Collapse state machine, never collapse explanation.

---

## Canonical Vocabulary (Ratified)

### Entity & Field Names

| Concept | Canonical Name | Notes |
|---------|----------------|-------|
| Core entity | `approval` | Shorthand: approval *request*. Noun only. `proposal` retired except `proposed` status and `propose` verb. |
| Requester identity | `requesterId` | Over `actorId` (ambiguous once co-signers exist). |
| Supersede link | `supersededByApprovalId` | Says what it holds (an id) and points at (an approval). Over `supersededBy`. |
| Terminal reason (when `denied`) | `PAYLOAD_SUPERSEDED`, `HUMAN_DENIED`, `POLICY_RUNG_ESCALATED`, `TTL_EXPIRED` | Closed enum. All `<subject>_<participle>` or `<participle>`. Never `superseded_by:<id>` (moved id to field). |
| Banker's conversation | `session` | One SSE stream. One banker watches. |
| One cycle (intent→plan→tools→artifact) | `run` | Multiple runs per session. Every envelope carries `runId`. |
| Action identifier | `<domain>.<entity>.<verb>` format | E.g., `account_opening.account.create`, `transaction.flag.review`, `loan.decision.record`, `user.lock`. |
| Endpoint prefixes | `/api/authority/*` or `/api/copilot/*` | One per service. Routing boundary legible in URL. |

### Audit Event & Configuration Naming

- **Audit Events:** PascalCase (`ApprovalDenied`, `PolicyReloaded`, `ApprovalExpired`)
- **Reason Enums:** SCREAMING_SNAKE_CASE (`HUMAN_DENIED`, `TTL_EXPIRED`, `PAYLOAD_SUPERSEDED`, `POLICY_RUNG_ESCALATED`)
- **Event Prefix:** `Approval*` (not `proposal*`)
- **Primary Key:** `copilot-approvals`, partitioned by `/requesterId`

### Additional Canonical Names

- `apr_` — event stream/topic prefix
- `expiresAt`, `terminalAt` — timestamp fields (not `expiredAt`)
- `requiredRung` — minimum rung to approve
- `requiredSigners` — count of required human signatures
- `actionId` — what the approval authorizes
- `firedEscalators` — escalators that triggered (e.g., self-dealing)
- No `ApprovalCosigned` event — folded into `ApprovalSigned` with `slotOrdinal` field

### Vocabulary Reconciliation Results

**Finding #4 (Most Dangerous):** 5 of 13 action-type ids disagreed between documents:
- `flagged_transaction.review` vs `transaction.flag.review`
- `loan.decision` vs `loan.decision.record`
- `user.lock` vs `user.account.lock`
- Account-opening actions had multiple spellings

**Impact:** Action-type ids are policy file primary keys. A mismatch is a silent policy miss, not a crash. Lookup fails, fallback silently becomes security behavior.

**Resolution:** Applied `<domain>.<entity>.<verb>` rule uniformly across all documents.

**Finding #18 (Propagation Failure):** Linus's `ApprovalState` TypeScript union still carried `'expired'` and `'void'` — ratified decisions never propagated to type UI would be built against. Corrected in place.

---

## Turk's Design Corrections

### 1. Cosmos Enum Enforcement (Accepted Correction)

**Claim Amended:** "Enforce enum at persistence layer" → "Enforce at application layer"

**Reasoning:** Cosmos is schemaless; no CHECK constraints available.

**Four-Layer Enforcement Specified:**
1. C# `enum` with converter throwing on unknown values (both directions)
2. Single-writer repository type (no raw `Container.ReplaceItemAsync` elsewhere); architecture test enforces
3. Guard query alerts on unknown values without self-healing (evidence preservation)
4. Readers fail closed — unrecognized reason = "denied and not executable" (never implicit "proceed")

### 2. Execution Failure (Own Document Was Wrong)

**Claim Corrected:** `executed` is not a terminal lifecycle status when execution fails.

**Truth:** Failed execution leaves `status = signed` / `execution.state = failed`. Retry needs no new human signature but DOES re-enter policy re-evaluation gate (§5.3.2).

**Why This Matters:** Making failure terminal would either strand valid signatures or force a "reopen" transition. Reopening a terminal state is the exact edge the four-value enum exists to avoid.

**Stated Identically Now:** Both epic §5.1 and policy engine §8.8 use same language.

### 3. Composite Cosmos Index (New Requirement)

**Query:** "Show me what expired" (now `status = 'denied' AND terminalReason = 'TTL_EXPIRED'`)

**Old:** `status = 'expired'`, single-field index  
**New:** Two-predicate filter plus sort on third field

**Index Required:** `(status, terminalReason, terminalAt)` in document order  
**Without It:** Query degrades to cross-partition scan (cheap at demo volume, silently expensive later)

**Consequence:** `terminalAt` must now be reliably populated on every terminal transition (was previously nullable-and-ignored).

---

## Shared-Identifier Contract Test

**Scope:** Generalized from `policyVersion` single-field test into full shared-identifier contract test.

**Enforces Across All Three Documents:**
- Full `terminalReason` enum (4 values exact)
- Supersede link field name and type
- Approval field names (8 critical fields)
- 11 audit event names
- Trace frame kinds
- 13 action-type ids
- 2 endpoint prefixes

**Implementation:** Generated `SharedIdentifiers` set as authoritative home. Test asserts no codebase restates member as literal. **CI grep gate scans three markdown files** — because every mismatch drifted in docs first.

**Key Insight:** Two people reasoning well, converging on same idea, still produced broken contract. Vocabulary is not product of everyone being careful; it is product of something checking.

---

## Status

**EPIC #332: ZERO OPEN QUESTIONS**

Everything raised in the epic has been ruled on:
- O9 ratified by Brian
- Q2 ruled: payloadHash permanent
- Q3 ruled: denial reason required, ≥20 chars
- Q4 ruled: step-up auth cannot substitute for L2 co-signer
- Expired state collapse ruled: no `expired` state
- Canonical vocabulary declared and enforced

Nothing is under-specified. Nothing awaits a decision. No phase is gated on an answer.

**Open Conditions (Not Decisions):**
- **Risk 15:** Four-layer defence is currently 1.5 layers. #334 (JWT signing) and #336 (shared workload identity) must land before full delivery.
- **Risk 5:** Policy-edit blast radius (lazy voiding + eager notification operational shape) is Turk's to design, Linus's to render.

**Visible Dependencies:**
- Composite Cosmos index implementation required
- Config keys to both manifests
- Guard query alerting setup
- UI implementation of Q2/Q3/Q4 implications
- Shared-identifier contract test and CI grep gate

---

## Related Issues & Artifacts

**Epic:** #332  
**Issues Referenced:** #333 (trajectory evaluation), #334 (JWT signing), #335 (audit gap), #336 (workload identity)

**Documents Updated:**
- `docs/epics/banker-copilot.md` — all sections
- `docs/design/banker-copilot-policy-engine.md` — policy implementation
- `docs/design/banker-copilot-ui.md` — vocabulary and type corrections

**Orchestration Logs:**
- `.squad/orchestration-log/2026-09-04T14-20-danny.md`
- `.squad/orchestration-log/2026-09-04T14-26-danny.md`
- `.squad/orchestration-log/2026-09-04T14-32-danny.md`
- `.squad/orchestration-log/2026-09-04T14-45-turk.md`

**Decision Inbox (To Be Merged):**
- `danny-o9-terminal-reason.md`
- `danny-final-rulings.md`
- `danny-canonical-vocabulary.md`
- `turk-final-rulings-implementation.md`
