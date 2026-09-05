---
date: 2026-09-04
author: Linus (Frontend)
status: proposed
component: ui-app/copilot
issue: 332
phase: 3
---

# Phase 3 UI: co-signature identity, the four-way terminal-reason split with a live way out,
# L1-only batch that L2 cannot enter, and fan-out attribution

Frontend-only. Branch `squad/332-phase3-supervisor`. No PR — the coordinator owns that. Nothing
committed; work left in the tree. There is no backend in this environment, so everything below is
verified by build + typecheck + the render/reducer tests, and the network-dependent paths (an
actual sign, an actual replacement fetch) are stated as BELIEVED, not proved.

## 1. `terminalReason` is now differentiated *with a door*, not just distinct copy (O9)

Phase-2 already gave each of the four terminal reasons its own blameless copy in `terminalCopy()`.
What it did not do was give a voided banker anywhere to go: `supersededByApprovalId` rendered as a
dead chip reading `replaced by apr_x`. That is the failure O9 warns about wearing a politer mask —
the copy no longer blames you, but the screen still ends in a wall.

`TerminalApprovalCard` now renders a live **"Review the new approval"** button whenever, and only
whenever, the server supplied a `supersededByApprovalId`. It calls a new context method
`openApproval(id)` that selects the replacement if the store already holds it (it usually arrived
on the same stream that voided the old one) and otherwise fetches it via `getApproval`. A fabricated
link would be worse than none, so the button is absent when there is no pointer — a `HUMAN_DENIED`
card shows no "review" affordance, because there is nothing to review.

**Denial counts are grouped by reason and never summed.** New `denialCountsByReason()` splits
denials into `HUMAN_DENIED` (the only bucket that is evidence about the agent) and the three
`systemVoided` causes (the ground moved). `DenialBreakdown` in the queue renders per-reason chips.
There is deliberately no "N denied" total anywhere — a single figure re-merges exactly the
distinction §5.1.1(c) forces apart, and the merge is invisible in a diff, so I made the shape of the
function refuse to produce it.

## 2. Co-signature identity is stated, from a source that cannot decide anything

The two-session demo's worst failure is a supervisor signing while unsure which browser identity the
click binds to. The card now carries a **"Signing as <name>"** banner and, at L2, names it the
*independent supervisor co-signature that counts only because you are a different identity from the
requester*. The signature roster marks the acting identity's own unfilled slot with **"← you sign
here"**.

The load-bearing decision: this identity is **display only**, read from `localStorage`
(`signingIdentity.ts`), and it decides nothing. Eligibility is `callerMaySign`, computed by the
service that holds the signing key; the banner and the slot marker are both suppressed when
`callerMaySign` is false, so neither can ever read as an invitation the policy engine would refuse.
I read from `localStorage` rather than `AuthContext` on purpose — the approval surface renders in
tests and fixtures with no `AuthProvider`, and a label must not throw when the provider is absent.
Crucially this does **not** reintroduce `cosignerId`: it labels the person who is actually here, not
a prospective reviewer chosen at proposal time.

## 3. Batch is L1-only by construction, not by a disabled button

`batchableGroups()` admits an item only through `isBatchEligible()` — L1, one required signer, and
`callerMaySign`. An L2 item fails set membership; there is no code path that builds a batch around
one. `BatchApprovalCard` re-applies the same filter defensively, so even a hand-built group cannot
smuggle an L2 item in — the sharpest test hands it a tampered group and asserts the L2 item never
renders. Batching a second opinion defeats the second opinion, so the wall is structural.

Two more structural facts: the cap is enforced in config as a **ceiling** (`CEILINGS.batchMaxItems`,
10) that an operator may lower but not raise — a batch of 100 is the approve-all this epic exists to
prevent — and every item renders its material fields and its own payload hash in a scannable table.
A batch is N independent signatures against N distinct payloads, never one signature over a digest
of the set, so one item's payload moving rejects that item alone.

## 4. Fan-out stays attributable

Subagent tool calls were already grouped under their owning agent. Added a fan-out header when a
step spawns two or more agents ("N agents in parallel — grouped under each, not interleaved") and an
owner chip on any step-level tool call carrying a `subagentId`, so a fan-out's calls can never read
as the root plan's own. The guarantee is: you can always tell which agent produced which step.

## What I did NOT do

- **The comparison recorder carry-over appears already satisfied** by Phase 2's `TaskMeasurementBar`
  (one shared component wrapping both surfaces via delegated DOM events, with `exportComparisonData`).
  The comparison suites pass. I did not re-instrument, because instrumenting one surface again is the
  precise way to reintroduce the counting-rule drift the carry-over exists to prevent. If the
  coordinator believes a call site is still missing, flag it and I will do both surfaces in one pass.
- **Post-signature undo** remains deferred (no service cancellation contract); an Undo that cannot
  stop execution is a lie at the worst moment.

## Verification

- `npx tsc --noEmit --ignoreDeprecations 6.0` clean. (`tsc` alone still aborts on the two pre-existing
  `TS5107` deprecations — unchanged.)
- `npx craco build` succeeds (285.6 kB gzip). The only eslint warnings are the pre-existing
  `account-opening/ApplicationStatus.tsx` exhaustive-deps ones, identical to `main`; I did not touch
  that file and did not broaden any ignore pattern.
- `npx craco test --watchAll=false` — 214 passed, the 13 failures are the two quarantined
  account-opening suites and nothing else. The copilot pattern alone is 69 passing (was 50).
