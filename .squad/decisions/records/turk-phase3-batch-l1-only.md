# Decision: batch approval is L1-only by RESOLVED rung — and F3-1 stays a config tripwire, not a loader guard

**Author:** Turk (Backend Dev)
**Date:** 2026-09-05
**Branch:** `squad/332-phase3-supervisor`
**Status:** proposed — records why I deliberately did NOT close Livingston's F3-1 in the loader

## The question

Livingston's QA finding **F3-1** notes that `PolicyLoader` enforces the batch invariant only
through the global `defaults.batchApproval.maxRung: L1` cap, and does **not** reject a per-action
`batchable: true` on an action whose base rung is L2 (or whose rules escalate it to L2). It is
latent today — no shipping action sets `batchable`, and there is no batch-sign endpoint — so he
left it as a **config-scanning tripwire** (`No_shipping_action_is_both_batchable_and_above_L1`),
NOT an enforced loader refusal, deliberately, to avoid a test that passes by defending a gap that
was never actually closed.

I tried to close it. I added a loader guard that rejected any `batchable` action whose *resolved*
reach (base rung folded with every escalating rule) exceeded L1. It built, but I reverted it, and
this record is why.

## The ruling: do NOT add the loader guard

The guard encodes the **wrong reading of "L1 only"** — and Livingston's own oracle says so in as
many words. From `src/authority-service.Tests/Spec/BatchSigner.cs`:

> The dangerous reading of "L1 only" is "baseRung L1 only". That is NOT the invariant. An action
> whose baseRung is L1 can ESCALATE to L2 on a threshold — a large amount, an adverse decision, a
> high-risk customer. The resolved rung is what governs how many humans must sign, so the batch
> must key on `RequiredRung` (the resolved rung), never on `BaseRung`.

The invariant I-10 is protected at **sign time, per item, all-or-nothing**: `BatchSigner.SignBatch`
refuses the whole batch if any item's `RequiredRung != L1`, and refuses a batch that spans more than
one action type. An escalated `transaction.flag.review` (L1 base, escalates to L2 above the
dual-control amount) is caught there — it never reaches a single-signature batch. That is where the
guard belongs, because only sign-time resolution knows each item's *payload*, and the rung depends
on the payload.

My loader guard would have made it **impossible to mark `transaction.flag.review` batchable at
all**, even for the L1-resolved instances that batching exists to serve — forbidding the safe case
to defend against one the runtime already refuses. It contradicts the design QA ratified, and it is
exactly the kind of second, independently-stated guard that drifts from the first. Duplication is
the bug; I declined to add a duplicate.

## What actually enforces batch L1-only (all green today)

1. **Config cap** — `PolicyLoader` requires `defaults.batchApproval.maxRung == L1` and
   `sameActionTypeOnly == true`, mirrored by `BatchSigner.ValidateBatchDefaults`.
2. **Sign-time, per-item** — `BatchSigner.SignBatch` keys on `RequiredRung`, refuses any escalated
   item and any cross-action-type batch, before a single signature is applied.
3. **Tripwire** — `BatchApprovalTests.No_shipping_action_is_both_batchable_and_above_L1` scans the
   shipped policy so the latent gap cannot become live silently.

That is belt, braces, and a smoke alarm. The invariant "an L2 item can never be swept into a batch"
holds without my loader guard, and it holds by the resolved rung — the reading QA chose and the one
the epic's Phase 3 bullet ("batch approval within one action type, L1 only") is satisfied by.

## The strongest form of the argument (coordinator, 2026-09-04)

There is no privileged batch path to guard in the first place. A "batch" in the UI is not a bulk
endpoint — it is **N independent `sign(item.id, item.payloadHash)` calls**, each against its own
approval and its own payload hash (`src/ui-app/src/components/copilot/BatchApprovalCard.tsx:105`).
There is no server-side batch verb, no `POST /batch`, nothing that signs many approvals under one
check. An L2 item that found its way into a UI "batch" would be refused by the **ordinary
per-approval server check** — the same `sign` guard it would hit from a single card — because it is
literally the same call. Batching is a **UX affordance, not an authority path**. So even setting
aside the sign-time resolved-rung refusal, there is no distinct code path a loader guard would be
protecting; adding one would harden a door that opens onto the same room. This is the strongest
reason the loader guard is not merely unnecessary but aimed at nothing.

## Scope item #5, honestly

My brief listed "batch approval — L1 only, within a single action type." The batch OPERATION and
its config guards already exist (Livingston's oracle + the loader cap, 224 tests green). I did not
add a production batch-sign endpoint: none is demanded by any test, my earlier attempt at one was
superseded by the oracle-based approach, and adding one now would be net-new surface nobody asked
for. I also did **not** mark any action `batchable`, because the only L1 candidate
(`transaction.flag.review`) escalates to L2 by amount — marking it batchable would be safe at
runtime but is not needed and would only invite confusion. This is a deliberate non-change, recorded
so the next agent does not mistake it for an omission.
