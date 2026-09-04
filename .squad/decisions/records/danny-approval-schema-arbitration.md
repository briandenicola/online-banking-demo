---
date: 2026-09-04
author: Danny (Lead/Architect)
status: ratified
component: epic/banker-copilot
issue: 332
supersedes: .squad/decisions/inbox/rusty-approval-schema-drift.md (ask answered)
---

# The `copilot-approvals` schema — design §5.3 is authoritative; the duplication was the bug

## 1. Ruling

**`docs/design/banker-copilot-policy-engine.md` §5.3 is the authoritative definition of the
`copilot-approvals` document.** Epic §5.2 has been stripped of its competing copy and now carries
**no schema at all** — only the container identity, partition key, TTL semantics, and a field
*inventory* naming which facts must be recorded and which invariant each serves.

Rusty's recommendation is accepted, and for his reason: authority follows the analysis, not the
document's rank. Design §5.3 is the copy with the query patterns, RU analysis and composite-index
derivation attached; `infra/cloud/cosmos.tf` is already indexed to it and `authority-service` is
being written against it. Two of three consumers agreed with each other; only the epic dissented,
and the dissenting copy was the one with nothing behind it. On the merits it was also worse:
`…Utc` suffixes §0.1 had already ruled to be noise, `matchedThresholds` as opaque strings where
the design has structured escalator objects carrying threshold name/env/value, and no `execution`
block at all.

**But the arbitration is the smaller half.** Choosing a winner fixes today's instance and leaves
the mechanism intact. **Two documents restating one physical schema will drift again**, so the
real ruling is that the shape is now defined in exactly one artifact and the layer boundary is
normative: the epic says *what must be true*, the design says *what it looks like on the wire*,
the design + Terraform say *how it is queried*. **No layer restates another.** If you want to
know whether `policyVersion` is nested, read the design doc — the epic must not answer that
question, because a document that answers it can be wrong about it.

## 2. Why this was urgent and not cosmetic

Rusty is right about the failure mode and it deserves restating, because it is the reason this
outranked everything else in my queue. **Cosmos field paths are name-sensitive and a mismatch
returns zero rows, not an error.** An index on `createdAt` against a service writing
`proposedAtUtc` does not throw: the composite index silently stops serving the `ORDER BY`, the
query degrades to a cross-partition scan, and at demo volume it looks perfectly healthy. The
Python read path fails in the opposite direction — empty result, no error. In the component that
gates money movement, "the supervisor's inbox is empty" is indistinguishable from "there is
nothing to approve."

This is the same failure as the duplicated `policyVersion` I removed in §5.3.1, one level up:
**structural instead of lexical.**

## 3. `policyVersion` nesting — the epic's letter, answered plainly

**`policy.policyVersion` is correct. Turk should not change it.**

The epic said `policyVersion` "appears exactly once — here, at the top level." **That ruling
constrains cardinality, not depth.** It counts copies; there is still exactly one. The words "at
the top level" were describing where it happened to sit in a document the epic no longer owns,
not imposing a depth. I am ruling explicitly rather than by silence because Turk has already
built it and deserves a straight answer instead of an ambiguity he has to guess at.

The nesting is also *better*. Grouping the version with `baseRung`, `requiredRung`,
`firedEscalators` and `resolvedThresholdSnapshot` gives every policy-derived value one obvious
home. **A flat namespace is what invites the second copy** — which is exactly how the original
`rungExplanation.policyVersion` duplicate arose, and how the one in §5 below arose after it.

## 4. The `cosignerId` pointer document — OUT

Turk's cross-partition query, bounded by `(status, awaitingSeniority, createdAt)` and a page
size, is the design of record. Rusty was right not to build the pointer doc.

The performance argument is real but ordinary: a second write, to a different partition key,
therefore **outside any transactional batch**. A crash between the two writes leaves either an
approval no supervisor can see — presenting as a silent drop — or a pointer to nothing.

**The argument that actually decides it is a security argument, and I missed it when I wrote the
epic.** Writing a pointer keyed by `cosignerId` requires knowing **who will co-sign, at proposal
time.** Under separation of duties we specifically do not know that: any sufficiently senior
supervisor who is not the requester may sign. A named co-signer converts the ladder from *"a
second qualified human must review this"* into *"this named person must review this"*, which
makes one person's absence a hard block on the escalation path and — far worse — **hands the
requesting banker, or an agent acting under their identity, the ability to choose their own
reviewer.** Choosing your reviewer is the self-dealing pattern L2 exists to prevent. A
performance optimisation would have quietly reintroduced the thing being defended against.

So `cosignerId` is deleted as a **field**, not merely as an index strategy. The design's
`awaitingSeniority` / `pendingSlotOrdinal` denormalisation is the right replacement **because it
describes what kind of signer is needed, never which person** — the queue is a property of the
work. Turk's deferred `copilot-approval-queue` by `/queueKey` preserves that property if volume
ever justifies it. **Normative: any future optimisation here keys on the queue, never on a
person.** Added to the acceptance criteria.

## 5. Two corrections in neither document's diff

Both documents were internally consistent about these, which is why neither appeared in Rusty's
table.

**(a) `execution.signedUnderPolicyVersion` — removed from the document.** The design annotates it
`// == policy.policyVersion above`, which states the violation outright: a second copy, in the
same document, of a value bound into a security hash. It is also *provably* always equal, and the
ruling that makes it so is §5.3.2 — if the policy version changes while an approval is pending
the signature is void and a **replacement** approval is created, so an executing document's
signatures were always bound to its own `policy.policyVersion`. The field cannot diverge,
therefore carries no information, therefore can only ever be wrong.
`execution.evaluatedUnderPolicyVersion` **stays** — genuinely new (the live ruleset at execute
time), and comparing it to `policy.policyVersion` yields the same audit annotation with no branch
condition.

This does **not** contradict §5.7, which requires both endpoints on the
`ApprovalVoidedByPolicyChange` and `ApprovalExecuted` **events**. An audit event is a standalone
flat record that must be interpretable without joining back to a document; denormalisation there
is correct. **The rule is one copy per document, not one copy per system** — and that distinction
is now written down, because it is the thing a future reader would get wrong.

**(b) `distinctIdentitiesRequired` — retired.** Under Q4 the same human can never satisfy two
slots, so it always equals `requiredSigners`. The slot form is also a stronger control: **a count
is satisfied by arithmetic and a miscount silently passes; `mustDifferFrom: ["user_9f3a"]` names
the excluded identity**, making it a set-membership test against a specific subject rather than a
tally. The §5.4 signing algorithm is updated to check the slot's exclusion set instead of
counting.

## 6. §5.3.1b — the contract test extended to structure

**§5.3.1a would not have caught this, and that is a defect in my test, not in Rusty.** The
identifier test compares *names* across documents; `createdAt` and `proposedAtUtc` are each
perfectly consistent within their own document, so there is no shared name spelled two ways to
grep for. What diverged is the **set of field paths**, and a set difference is not a substring
search.

Every artifact describing the document is reduced to a **sorted set of dotted field paths**
(`policy.policyVersion`, `signatureSlots[].mustDifferFrom`, `execution.state`). Nesting comes for
free — `policyVersion` and `policy.policyVersion` are different strings, so a depth change fails
like a rename. Four sites, and **the directions are deliberately asymmetric**:

- Design §5.3's fenced block **defines** the canonical set.
- A real document written by `authority-service` and read back raw **must equal** it. This is the
  only check that catches a .NET serializer naming-policy mismatch, which no doc-to-doc
  comparison can see.
- The Python read models **must be a subset** — a reader may ignore a field, never invent one.
- `infra/cloud/cosmos.tf` indexed paths **must be a subset** — this is the silent one, Rusty's
  case exactly.

Subset violations **fail closed**, never warn. And the epic asserts nothing here by design: it
no longer holds a copy, and **that absence is the primary fix**. A CI check fails if a
`copilot-approvals` body reappears in the epic.

**The generalisation worth carrying past this epic:** §5.3.1 was "one value, one definition";
§5.3.1a extended it to identifiers; §5.3.1b extends it to shape. One rule — **anything restated
in more than one artifact must be generated from one source or checked against one source, never
maintained in parallel by careful people.** The version that bites is always the one where each
copy is *locally* correct, because local correctness is what makes reviewers sign off. Both of
these documents were coherent, both were reviewed by me, and they specified different databases.

## 7. Work assignments

**Turk** — two removals, nothing else; keep building:
1. Delete `execution.signedUnderPolicyVersion` from the document schema and the write path. Keep
   it on the `ApprovalVoidedByPolicyChange` / `ApprovalExecuted` events, sourced from
   `policy.policyVersion`.
2. Confirm `distinctIdentitiesRequired` never entered your code (it was epic-only); the signature
   acceptance check is `mustDifferFrom` set-membership, not a distinct-identity tally.
3. `policy.policyVersion` nesting is **ratified — do not flatten it.**
4. Your cross-partition supervisor query is **ratified**; no pointer document.

**Rusty** — your indexing is correct as built. Three follow-ups:
1. Confirm no index path references `cosignerId`, `proposedAtUtc`, `signedAtUtc` or
   `signedUnderPolicyVersion`.
2. Own the `infra/cloud/cosmos.tf` half of §5.3.1b: the HCL path extraction and the subset
   assertion. **Fail the build, not a warning.**
3. The container-level TTL must remain opt-in (`-1`) with per-item `ttl` set only after terminal.
   Cosmos deleting a document is not a denial — I-6 needs a surviving `denied` + `TTL_EXPIRED`
   record, and a deleted document carries no `terminalReason`.

**Linus** — no schema change reaches the UI, but the supervisor queue is *never* addressed to a
named person. Do not build "assigned to you"; build "awaiting a supervisor."

## 8. What I got wrong

I wrote the pointer document into the epic as a performance optimisation and did not notice it
required naming the co-signer in advance — in the section immediately adjacent to the one
arguing that separation of duties is the point. **The second copy of a schema is not just a drift
risk; it is a place to hide a design error from yourself**, because it looked locally reasonable
and was never read side-by-side with the constraint it broke. It took a new engineer wiring up an
index to find it, which is the strongest argument in this file for why the shape now lives in one
place.
