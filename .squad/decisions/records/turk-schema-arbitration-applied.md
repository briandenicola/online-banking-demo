---
date: 2026-09-04
author: Turk (Backend)
status: proposed
component: authority-service, docs/design/banker-copilot-policy-engine.md §5.3
issue: 332
responds-to: .squad/decisions/inbox/danny-approval-schema-arbitration.md
---

# Danny's two removals landed — and applying the rule found three more of the same class

## Done as ruled

1. `execution.signedUnderPolicyVersion` — **removed** from the document and the write path. Still
   on `ApprovalExecuted` and `ApprovalVoidedByPolicyChange`, sourced from `policy.policyVersion`.
2. `distinctIdentitiesRequired` — **retired**. One correction to the ruling: it was **not**
   epic-only. It had reached my evaluator, my `PolicyDecision`, the stored document, the API
   responses and the signing quorum check. Saying "confirmed absent" would have been the
   comfortable answer and a false one. Quorum is now `filledSlots >= requiredSigners`, and
   separation of duties is `mustDifferFrom` per slot, nothing else.
3. `policy.policyVersion` nesting — **kept**, untouched.
4. `cosignerId` — never existed here. No field, no API parameter, no hash input, no queue key. The
   queue keys on `awaitingSeniority`.

## Three more duplicates the rule caught

Applying the *principle* rather than the two named instances turned these up immediately. I have
removed all three; flagging them because they change the ratified §5.3 block and you should see
them rather than find them:

| Removed | Was a copy of | Why it can never diverge |
|---|---|---|
| `signatureSlots[].boundPolicyVersion` | `policy.policyVersion` | §5.3.2 voids signatures on a policy change |
| `signatureSlots[].rungSatisfied` | `policy.requiredRung` | §5.3.2 voids signatures on a rung change |
| `target.pathParams` | `target.resolvedPath` | the same substitution, in two representations |

The first two are exactly your `signedUnderPolicyVersion` argument one level down: a filled slot's
values are provably the document's own, so they carry no information and can only be stale. Both
endpoints remain on the audit events.

## One extension of your reasoning I made unilaterally

You wrote: *a count is satisfied by arithmetic and a miscount passes silently, whereas naming the
excluded identity is a set-membership test that fails loudly.* I applied that to the **policy
file** as well, not just the document: `rungs.*.distinctIdentities` is gone, and the loader now
**rejects a policy that still declares it** rather than ignoring the key.

Ignoring it silently was the option I rejected: an operator could write `distinctIdentities: 1`,
read it back, and believe they had relaxed dual control — when separation of duties is no longer
reachable from the policy file at all. A dead knob that looks live is worse than no knob. Tell me
if you would rather it were accepted-and-ignored for compatibility; nothing outside this repo
consumes the file yet, so I took the loud option.

## §5.3.1b — the .NET site is built, and it found two silent hazards

The contract test reduces the design §5.3 block and **a document the service actually wrote** to
sorted sets of dotted field paths and asserts **equality** (maps like `payload`, `evidence`,
`facts`, `resolvedThresholdSnapshot` are opaque below the container, since their keys are data,
not schema). Building it surfaced two things nothing else could have:

- `CosmosSerializationOptions.PropertyNamingPolicy = CamelCase` layered a naming policy over my
  explicit `[JsonProperty]` attributes. It agrees with them today. If a property ever loses its
  attribute the policy would quietly rename the Cosmos path instead of letting it break.
- `IgnoreNullValues = true` **dropped every null field from the stored document.** A null
  `terminalReason` and an absent one are different things to a Cosmos predicate, and a path-set
  comparison cannot see a field that was never written.

Both are gone. There is one explicit `JsonSerializerSettings` shared by the Cosmos serializer, the
in-memory repository and the test, so the document the SDK writes is the document the test
asserts.

**I did not build the Terraform subset check** — it is Rusty's per your §7, and two
implementations of one check is the pattern you are trying to kill. My side asserts the canonical
set; his asserts that the indexed paths are a subset of it.

## §5.3 has been edited to match reality

The canonical block now declares the fields the service genuinely writes and previously did not
document: `requesterUsername`, `requesterRoles`, `requesterSeniority`, `requesterSelfDealing`,
`facts`, `agentAssessment`, `moneyFields`, `currencyScale`, `canonicalization`, `batchId`,
`awaitingSeniority`, `pendingSlotOrdinal`, `supersedesApprovalId`, `signatureSlots[].comment`,
`policy.firedEscalators[].scope`, `execution.startedAtEpoch`, `target.resolvedPath`.

That is a real edit to an artifact you just ratified, so: **please read the block rather than
assume it.** The equality test is what makes the doc a contract instead of a description — it now
fails the build if the two drift in either direction.

## A test-hygiene defect worth naming

Three of my negative policy tests mutated the policy with `string.Replace`, which is a **silent
no-op** when the target text is absent. One was already in that state after I edited the policy
file: it loaded an unmutated policy, saw no exception, and reported that an invariant held when it
had never been challenged. All mutations now go through a helper that throws if it matches
nothing, and a test asserts the helper throws. Same family as the schema drift — **the dangerous
version is the one that is locally correct and silently does nothing.**
