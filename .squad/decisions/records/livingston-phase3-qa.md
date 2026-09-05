---
date: 2026-09-04
author: Livingston (Tester/QA)
status: proposed
component: authority-service / banker-copilot-service — tests
issue: 332
phase: 3
---

# Phase 3 QA: blind-construction independence, SoD re-attacked at the loader, L2-batch impossibility,
# and the payload-supersede void path — with two findings and five honest non-ticks

Written from the SPEC while Turk, Rusty, and Linus coded the same branch in parallel. Nothing here
was derived from their implementation. No PR — the coordinator owns that. Nothing committed; work
left in the tree. **No coverage metrics** (Brian's ruling); every guard is proven by **tamper**.

## Suites and status

- `src/banker-copilot-service.Tests/` (Python): **298 passed, 0 skipped**. Tamper harness: **22 PROVEN**.
- `src/authority-service.Tests/` (.NET, net10.0): **224 passed, 0 skipped**. Seven .NET guards tamper-proven manually.
- Full plan: `docs/design/banker-copilot-phase3-test-plan.md`.

> **Turk's production fan-out landed mid-session.** `app/planner/fanout.py` now exists, so I did not
> stop at the oracle: `tests/production/test_supervisor_blind_construction.py` (5 cases) imports his
> real builder and re-runs the independence attack against it, tamper-proven by `prod-blind-builder-signature`
> and `prod-blind-input-leak-field`. His builder matches the oracle name-for-name and holds up.

## What I proved

**1. Blind construction independence (the headline).** `spec/supervisor.py` +
`tests/test_blind_construction.py` (14 cases). Independence is proven **structurally**, not by a
disclaimer: `build_supervisor_input(intent)` takes only the banker intent, so the proposer's plan,
reasoning, and conclusion have no argument to travel through — the Phase-1 "no payload parameter"
technique applied to the second opinion. A byte-level token scan (`independence_report`) is a
cross-check with a positive control proving it can go red, so an empty corpus cannot pass it. Every
leak channel named in the brief is attacked: shared context object, trace envelope, session state,
cached tool results, and the artifact/intent itself. Tamper: `blind-builder-signature`,
`blind-token-scan`, `blind-subagent-propose-floor` — all PROVEN.

**2. Separation of duties, re-attacked from a fresh angle.** `Engine/RoleModelDivergenceTests.cs`
(7 cases) attacks Turk's fail-closed cross-file check (`authority-policy.yaml` ↔
`role-hierarchy.yaml`), one rung below the existing store-level SoD tests. Both Phase-1 escalations
are re-run against the **real** config: my `banker.claimValues ⊇ user` and the coordinator's admin
in `L2.cosignerRoles`. Each tamper is preceded by a positive control proving the untampered pair
loads clean, so green means "the tamper broke it", not "it was already broken". Tamper: seniority
floor, claim-spelling, and the admin-ladder tripwire — all PROVEN.

**3. L2 batching is impossible, not absent.** `Spec/BatchSigner.cs` + `Store/BatchApprovalTests.cs`
(8 cases). Oracle is fail-closed, all-or-nothing, keyed on **resolved** rung (an L1 base action that
escalated to L2 takes the whole batch down). Production loader refuses `maxRung: L2` and cross-type
batch defaults, tested against the shipping validator. Tamper: 4 guards PROVEN.

**4. Payload-supersede void path — fresh L2-window angle.** `Store/SupersedeSignatureVoidTests.cs`
(2 cases). The existing supersede test never signs the original, so its "starts from zero signatures"
claim was lightly exercised. My test fills a real first co-signature on an L2 approval, mutates the
payload, and proves **no** signature survives into the successor and that the successor still demands
**two** slots (no auto-downgrade dressed as a payload edit). Tamper: leak the old slots into the
replacement → the invariant test goes red — PROVEN. The four `terminalReason` values, the closed
enum, fail-closed-on-unknown, and `supersededByApprovalId` linkage were **already** well covered by
`Store/TerminalReasonTests.cs`; I did not duplicate them.

## Findings

### F3-1 — I-10 ("batch is L1-only") is enforced globally, not per-action *(latent, medium)*

The loader enforces I-10 only through the global `defaults.batchApproval.maxRung: L1` cap. It does
**not** reject a per-action `batchable: true` on an action whose `baseRung` is L2
(`transaction.score.override`, `user.unlock`) or an L1 action that rules up to L2. **Proven
empirically**: adding `batchable: true` to `transaction.score.override` loads without error. Latent
today (no action sets `batchable`; no batch endpoint exists). I did **not** write a test claiming the
loader rejects it — that would be a false pass defending an open gap. Instead
`No_shipping_action_is_both_batchable_and_above_L1` pins the shipping config and fires the day an L2
action is marked batchable. **Turk:** in `PolicyLoader.Validate`, reject any action whose resolved
rung can exceed L1 while `Batchable == true`.

### F3-2 — the seniority floor trusts the ratified ladder *(exposure, low, by design)*

The "signer/cosigner roles need banking seniority ≥ 1" floor consumes `role-hierarchy.yaml`; it does
not independently pin `admin` to platform-only. If a future edit gave `admin` banking seniority ≥ 1,
the loader would accept admin as a cosigner — the Phase-1 shape, one file upstream. By design (this
service consumes the ladder, it does not ratify it). Demonstrated by the exposure test and pinned by
`The_ratified_ladder_keeps_admin_at_platform_zero_implying_nothing`. Not a bug to fix here; a
boundary to know, now with a tripwire on the control file.

## Cross-checks on teammates

- **Linus (`linus-phase3-terminal-reason-and-cosignature.md`):** his UI reads the signing identity
  from `localStorage` as **display-only** and gates every sign affordance on server-computed
  `callerMaySign`, and he explicitly does **not** reintroduce `cosignerId`. That is consistent with
  the invariant — the label names who is present, not who may decide. I did not test UI code; this is
  a read-through, not a verification.
- **Turk (backend):** his loader guards (seniority floor, claim-spelling, batch cap) all tamper-prove
  cleanly against my spec-derived tests. The one gap is F3-1 above.

## Honest non-ticks — what I could NOT verify

**1. production fan-out landed mid-session — builder verified, engine not.** Turk's
`app/planner/fanout.py` now exists, so the "no production code" gap is resolved for the blind-
construction **builder**: proven by an independent structural attack (`tests/production/test_supervisor_blind_construction.py`)
and tamper-proven (`prod-blind-builder-signature`, `prod-blind-input-leak-field`). What remains
unproven is the full fan-out **engine** under a real model (the loop that spawns the supervisor
thread and returns a second opinion) — no Foundry endpoint runs here; the `real-model-tool-choice`
ledger entry still covers it.
2. **No batch-sign endpoint exists.** Batch tests prove the oracle + loader/config; there is no
   `POST /approvals/batch` to attack end-to-end.
3. **No .NET tamper harness.** The seven .NET guards were tamper-proven **manually** (break, run the
   named test, confirm red, revert), documented in the plan §2–§4. Reproducible but not automated. A
   `dotnet`-side tamper runner is worth building; out of scope this phase.
4. **F3-1 is latent, not closed.** I pinned it; I did not fix it. If a batchable action or a batch
   endpoint lands before Turk closes the loader gap, a real exploit path could open in the same PR
   that trips the tripwire.
5. **No CI re-audit this phase.** Phase 2 found CI ran this suite before its dependencies existed
   (F2-9) and the quarantine patterns matched nothing (F2-10). I did not re-check CI; treat those as
   still open until the coordinator confirms.
