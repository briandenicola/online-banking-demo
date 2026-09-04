# 2026-09-04T14:30:00Z — Banker Copilot Rulings Round 2 (Session Log)

**Session:** Banker Copilot epic ideation — ruling round 2  
**Requested by:** Brian Denicola  
**Date:** 2026-09-04  
**Status:** CLOSED

---

## Brian's Five Rulings

### 1. Service Split Stands — `authority-service` is .NET

- `banker-copilot-service` (Python/FastAPI, agent loop)
- `authority-service` (.NET 10, policy engine + approval store + sole write path)

**Rationale:** Enforcement boundary and static typing on security-critical component justify language boundary despite Python affinity elsewhere. Language boundary makes "mediator contains no model SDK" mechanically checkable rather than review norm.

**Mitigations mandatory:** `authority-service` owns Cosmos containers exclusively; harness↔authority contract is REST with published schema, not shared document format.

**Reference:** Epic #332 §2.2 rewritten with explicit ruling and rationale; Turk's reasoning preserved in full.

---

### 2. Role Provisioning into Phase 1

`banker` and `supervisor` roles move to Phase 1 (previously deferred).

**Role Hierarchy:**
- `supervisor` ⊃ `banker`
- `admin` implies NEITHER (deliberate; admin-as-superset defeats ladder while every test passes)

**Mechanism:**
- Flat `role` claim retained for ADR-003 compatibility
- New `effectiveRoles` array computed once at token issuance in `AuthService.cs`
- Expansion rules in `config/role-hierarchy.yaml` (per invariant I-3 — hierarchy is policy, not constant)

**Bootstrap:**
- Terraform-provisioned seed identity → idempotent `user-service` startup seed (creates first supervisor only if none exists) → ongoing promotion via admin console (`POST /api/admin/promote`, stays L3, absent from tool manifest)
- Every promotion emits `authority.role.granted`

**Rejected:**
- Copilot-driven bootstrap (violates L3)
- Manual Cosmos edit (unauditable)
- Env-var superuser (standing credential, no audit)

**SoD Enforcement:**
- Server-side in `authority-service`'s signature path (8-step algorithm in §5.8.4)
- Step 5 unconditional: `signerId != proposal.actorId` for co-signatures

**Migration:**
- Additive and non-breaking
- New optional `effectiveRoles` (computed, NOT persisted — avoids stale-copy bug)
- No backfill, no downtime
- Pre-change tokens degrade gracefully; existing seeded users keep current authority

**Seed Data Requirement:**
- Must contain two distinct identities (one banker, one supervisor) for L2 demo

**Reference:** Epic #332 §5.8, acceptance criteria updated.

---

### 3. Two-Browser Demo — Non-Issue, No Work

Intentional constraint. L2 beat uses two authenticated sessions (banker + supervisor) to demonstrate separation of duties as visible handoff.

**Decision:** No work to collapse into single session. Constraint is a feature.

**Reference:** Epic #332 §1.3 step 6 now explicit; supervisor-disagreement beat retained as centerpiece.

---

### 4. Trajectory Evaluation → Epic #333 (Phase 2 Requirement)

"Deferred / out of scope" replaced throughout with pointer to **#333**.

**New Obligation:** Harness must emit structured, replayable traces from day one.

**Single Trace Schema:** Linus's `CopilotEventEnvelope` ratified:
```
{id, seq, runId, kind, ts, payload}
```
Over 20 event kinds; already well suited (seq monotonic/gapless per run; ts server-clock).

**Eval-Driven Additions Landing WITH Envelope:**
- Durable persistence to `copilot-traces` (PK `/runId`) at emit time
- `traceId`/`spanId` on tool frames
- Model/deployment/token counts on model-call frames
- `parentRunId` on subagent frames
- Redaction applied at emit, not render
- **`policyVersion` + resolved rung on `approval.required`**

**Key Insight:** Eval question is not *"was recommendation good?"* but **"did authority ladder resolve correctly given evidence?"** — unanswerable without rung and policy version in trace.

**Reference:** Epic #332 §8.0, Linus's `docs/design/banker-copilot-ui.md` §4.2.

---

### 5. PolicyVersion Binding — Asymmetric Void-on-Escalation-Only (Closes Q1)

**Rule:** `policyVersion` is bound into the payload hash. Signature valid only for exact policy version under which produced.

**At Execution Time — Re-Evaluate Under CURRENT Policy:**
- Required rung HIGHER than rung signature satisfied → **SIGNATURE VOID.** Re-propose; gather signatures at new rung.
- Required rung UNCHANGED or LOWER → **HONOR EXISTING SIGNATURE. EXECUTE.**
- **NEVER auto-downgrade; NEVER auto-honor under-signed action.** Signature only invalidated by policy change, never strengthened by one.

**Principle:** Same monotonic rule as escalators (invariant I-4), applied over time instead of context.

| Axis | Rule | Mechanism |
|---|---|---|
| Over context (§4.3) | Escalators only raise rung | `max` over `L1 < L2 < L3` |
| Over time (§5.3.2) | Policy drift only voids, never rescues | Same `max`; compare `rungNow` vs `rungSigned` |

**Correction to My Q1 Recommendation:** Standing recommendation was symmetric ("void if rung would change"). Asymmetric is right — voiding on downward change punishes banker for relaxation and generates re-signing churn. Signature given was for strictly *more* scrutiny than now required — safe by construction.

**Composition Bug Fixed:** `policyVersion` was duplicated twice in same Cosmos document (would have shipped). Now single-definition normative: one authoritative home (policy document's identity); approval record copies once at `proposed`, immutable; hash, trace frame, audit events all *read*, never re-derive. Contract test asserts byte-identity across all four sites.

**Reference:** Epic #332 §5.1, §5.3, §5.3.1, §5.3.2, new §5.3.2; Turk's `docs/design/banker-copilot-policy-engine.md` §6.2, §6.4.

---

## Issues Filed (Verified Findings)

### #334 — JWT Signing Vulnerability

All 9 services validate audience `banking-demo` with one shared symmetric key (HmacSha256 + SymmetricSecurityKey in `src/user-service/Services/AuthService.cs:41-43`). **Every service can MINT/forge tokens, not merely verify.** Worse than initially reported "shared audience" framing.

**Impact:** Layer 2 (broker-only claim) cannot be built until landed.

**Sequencing:** Phase 3 (before L2 means anything outside demo).

---

### #335 — Audit Gap in Event-Processor

`src/event-processor/main.go:403-410` switch handles only "TransactionCreated" and "TransferInitiated". Other published event types **silently unaudited**.

**Impact:** Nine authority event types would inherit this gap.

---

### #336 — Shared Workload Identity

One workload identity for all 11 pods: `banking-workload-identity` → `banking_services` UAMI, holding account-scoped Cosmos Data Contributor.

**Impact:**
- Layer 1's "no domain Cosmos role assignment" not achievable
- Tool-shape isolation degrades to ConfigMap convention
- Layer 3's "`authority-service`'s pod identity" does not exist as distinct thing

**Sequencing:** Phase 1 takes smallest slice (dedicated identity for `authority-service`).

---

## §4.4 Defense Audit — Honest Documentation

**Four-layer bypass defence is currently one-and-a-half layers.**

Documented honestly in epic §4.4 rather than implied — shipping while believing all four layers hold would be worst outcome available.

---

## Outstanding Open Items (Not Ruled On)

- **Q2** Is `payloadHash` display permanent or demo-only? *Recommend: permanent.*
- **Q3** Require denial reason? *Recommend: yes, ≥20 chars.* More load-bearing with #333.
- **Q4** Can step-up auth/MFA substitute for second human at L2? *Recommend: **no**.*
- **O9** Policy-voided approvals: first-class `voided` lifecycle state or persist as `denied` with terminalReason? Turk chose latter; flagged for Danny's ratification.
- **O10** Wire `/policy/impact` into CI as required check? Defer gate until approval store seeded.

---

## Outcome

**SUCCESS.** Five rulings ratified. Two services reconciled. Composition bug corrected. Verified findings documented. Phase 1 signature path unblocked.
