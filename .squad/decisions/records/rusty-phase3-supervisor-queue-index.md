# Decision — Phase 3 supervisor queue: composite index verified, no pointer doc

**Author:** Rusty (platform/infra) · **Date:** 2026-09-04 · **Epic:** #332 Phase 3

## Ruling

The cross-partition "approvals awaiting a supervisor co-signature" query (Q3) is served by the
composite index **`(status, awaitingSeniority, createdAt)`** on `copilot-approvals`. It is
**already present** in `infra/cloud/cosmos.tf` — I added it in Phase 1 against design §5.5. No
Terraform change was required in Phase 3; the Phase 3 work was to **verify it against the
actually-persisted document**, not the docs, and to confirm no pointer document crept back in.

## What I verified (PROVED, against source — not the epic)

The three indexed paths exist at the document top level with exactly this casing, read from the
writer (`authority-service`, .NET), not from the design doc:

| Path | Writer field | Persisted casing |
|---|---|---|
| `/status` | `Approval.Status` + `ThrowingApprovalStatusConverter` → `SharedIdentifiers.Status.*` | lowercase `"pending"` etc. |
| `/awaitingSeniority` | `Approval.AwaitingSeniority` (`[JsonProperty("awaitingSeniority")]`, top-level `int?`) | camelCase, top-level |
| `/createdAt` | `Approval.CreatedAt` (`[JsonProperty("createdAt")]`) | camelCase, top-level |

`RefreshPendingSlot` (`ApprovalRepositoryBase.cs`) recomputes `AwaitingSeniority` /
`PendingSlotOrdinal` to the next unfilled slot on every signature, so the denormalised
`WHERE status='pending' AND awaitingSeniority >= 2` predicate of design §5.5 is backed by a
value the writer maintains. This matters because **Cosmos returns zero rows, not an error, on a
path mismatch** — a composite index on a field the writer never persists fails the exact same
silent way. The paths match the persisted shape.

## No pointer document — and why it must never come back (epic §5.2.2)

There is **no** `copilot-approval-queue` container and **no** `cosignerId` field anywhere in
`cosmos.tf`, the `Approval` model, or the audit/notification payloads. This is not an oversight
to "optimise later":

- Naming a co-signer at proposal time hands the requesting banker — or an agent under their
  identity — **the ability to choose their own reviewer.** That is the self-dealing the L2 rung
  exists to prevent, reintroduced as a "performance" change.
- A pointer keyed by `cosignerId` is a second write on a different partition key, outside any
  transactional batch; a crash between the two writes leaves either an approval no supervisor
  can see (a silent drop in the component that gates money movement) or a pointer to nothing.

The denormalised `awaitingSeniority` / `pendingSlotOrdinal` are the sanctioned replacement
**because they describe the KIND of signer still needed, never WHICH person.** The queue is a
property of the work, not of an individual. Any future optimisation here must key on the queue
(`/queueKey`), never on a person.

## Consequence

Item 1 of the Phase 3 platform scope needed no code change. The honest deliverable was the
verification above plus this record, so the next person does not "add the missing index" on top
of the one that is already correct, or re-derive the pointer-doc temptation from scratch.
