---
date: 2026-09-04
author: Rusty (Platform/Infra)
status: proposed
component: epic/banker-copilot
issue: 332
---

# The approval document schema differs between the epic and the design doc

## What

The epic (§5.2) and Turk's design doc (§5.3) both give a full `copilot-approvals`
document, and they are **not the same document**. This matters to me because the
Cosmos indexing policy I just wrote in `infra/cloud/cosmos.tf` indexes field
paths, and Cosmos SQL field paths are case- and name-sensitive: a mismatch
returns **zero rows rather than an error**.

Fields that differ, epic → design:

| Epic §5.2 | Design §5.3 | Notes |
|---|---|---|
| `signatures[]` | `signatureSlots[]` | Different shape, not just a rename — slots are pre-declared with `minSeniority` / `mustDifferFrom` |
| `proposedAtUtc` | `createdAt` | §0.1 rules `…Utc` suffixes are noise, which favours the design doc |
| `signedAtUtc` (inside signature) | `signedAt` | same |
| `requiredRung` (top level) | `policy.requiredRung` (nested) | §0.1 ratifies the *name*, not the *depth* |
| `policyVersion` (top level) | `policy.policyVersion` (nested) | epic explicitly says "appears exactly once — here, at the top level" |
| `cosignerId` + a pointer doc | no pointer doc; a cross-partition query bounded by a composite index | **materially different**: the pointer-doc design needs a second write per approval and changes the write path |
| `rungExplanation.firedEscalators[]` | `policy.firedEscalators[]` | |
| — | `awaitingSeniority`, `pendingSlotOrdinal` | denormalised in the design doc for Q3; absent from the epic |
| — | `expiresAtEpoch` | the sweeper query and one composite index depend on it |

## What I did, and why

I indexed **the design doc's shape** (`createdAt`, `expiresAtEpoch`,
`awaitingSeniority`, `terminalReason`, `terminalAt`), because that document is
the one that specifies the query patterns the indexes exist to serve, and Turk is
writing the service against it right now.

I did **not** implement the epic's `cosignerId` pointer-document approach. The
two designs solve the same problem (a supervisor's inbox spans many requesters'
partitions) in incompatible ways; picking the pointer doc would have required a
second container-shaped decision I do not own.

## Risk if left unarbitrated

The failure is silent. If `authority-service` writes `proposedAtUtc` and the
index is on `createdAt`, nothing errors — the ORDER BY simply stops being served
by the composite index and the query degrades to a cross-partition scan, which at
demo volume looks fine and only shows up as an RU bill later. The
banker-copilot-service (Python) read path has the same failure mode in the
opposite direction: zero rows, no error.

## Ask

Danny to declare one of the two documents authoritative for the approval schema
(I recommend Turk's design §5.3, since it is the one with the query analysis
attached), and to rule explicitly on the `cosignerId` pointer document —
in or out. If it is in, the container design and my index set both change.
