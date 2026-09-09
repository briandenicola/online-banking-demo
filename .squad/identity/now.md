# Now — where the team is

**Last updated:** 2026-09-09 18:40 CDT
**Branch:** `332-beta` — 97 commits ahead of `main`, **nothing pushed**.
**`main` is untouched and stays untouched** until Brian personally deploys, tests and validates in `332-beta`.

---

## The one thing to do first, tomorrow morning

**Reseed before you touch the UI. Nothing else is required.**

```
task cloud:demo:reset -- --reseed
```

Takes roughly 4-6 minutes. The scoring poll now waits for a *qualifying* subject, so the
"waiting for ai-service…" lines will run ~35-60s and that is normal, not a hang.

**Why you must reseed even though tonight's seed worked:** approvals now live 8 hours.
Tonight's seed was created at 23:37 UTC, so it expires at **07:37 UTC / 02:37 CDT** — before
any reasonable morning. The 8-hour TTL does not make a seed survive overnight; it makes a
seed survive *a working day once you create it*. Create it in the morning and it lasts
through the whole walkthrough.

The cluster itself is healthy and deployed. **No rebuild, no redeploy needed.**

---

## What is now true that was not true this morning

**The reseed works, and it is deterministic.** Proven by an actual run at 23:37 UTC, not
reasoned about:

- `flag-review-denied` lands at **L2**, escalated by `large-flagged-amount`, every time.
  It picks the `61200.00` offshore wire deliberately instead of whatever happened to be
  scored first. Verified live: `requiredRung L2`, `payloadAmount 61200`, and the subject
  returns **200** from `get_flagged_transaction`.
- All 10 pending approvals carry **8-hour TTLs**, verified from the cluster.
- The whole escalator queue survives the walkthrough. Previously 8 of 10 approvals — the
  entire escalator set — were dead within 20 minutes.

**Four evidence fixtures now exist**, including a **403 and a 404 captured live for the first
time**. The 403 is the empty-ledger denial Danny upheld; Turk controlled it rather than
assuming it (dana's non-empty account → 200 with 6 rows, her empty one → 403, one variable).
That ruling is now *observed*.

---

## Three defects cleared today, in order

1. **§B2.2 empty-ledger 403.** `ownsEveryRow` requires `Count > 0`, so an owner cannot prove
   ownership of a zero-row ledger. Danny **upheld the service**; the seeder was wrong.
   `demo.sh` now uses `GET /api/transactions/my`.
2. **`newScore` canonicalizer rejection.** The canonicalizer forbids fractional non-money
   numbers. `0.25` → `"0.25"`, plus a guard so the class cannot return.
3. **Scoring poll too short, then waiting for the wrong thing.** `pollSeconds` 90 → 300, and
   then the real fix: the poll now waits for a *qualifying* subject rather than any subject.

---

## Guards that must not be "fixed" — read before touching the seeder

**A flagged row's `.id` is the Redis lookup key. Its inner `.transactionId` is NOT.**
Verified live: `.id` → 200, `.transactionId` → 404. Only 14 of 128 flagged rows even carry a
non-empty `transactionId`. `demo.sh` uses `.id` and that is correct. Changing it to
`.transactionId` breaks every evidence read in the demo.

**A seeder must wait for the thing it will later require.** Any predicate used to SELECT a
subject must be the same predicate that TERMINATES the wait. Filtering on a property the poll
did not wait for is a race with an assertion bolted on the end. This is Danny's §R10 and it is
the generalisable finding of the day.

**The policy version hash SHOULD move when a threshold is env-overridden** —
`ComputeVersion` hashes *resolved* values. `pv1:d7b3db9f5ada15b8` → `pv1:6b4dec9a0d13aa4b` is
correct and expected. An *unchanged* hash after an override would mean the override failed.

**Azure AI Foundry rate-limits every scoring call** (HTTP 429, ~3s retry, ~5-6s per
transaction). This is normal throttling, not a fault.

---

## Open items, honestly stated

| Item | State |
|---|---|
| **Stale verification ids** | `tests/verification/e2e_cases.py` and `supervisor_cases.py` each hard-code 6 account/transaction ids deleted by the reseed. **Unfixed.** Will affect Livingston's run. |
| **Verification check 2.5** | The 8h TTL means no seeded approval expires in a test window, so `TTL_EXPIRED` goes unexercised. The sweeper still runs. Needs a purpose-seeded short-TTL approval. **Livingston must be told.** |
| **Compaction manifest** | `.squad/decisions-compaction-plan.md`, 129 rows. Committed as a plan, **never executed** — awaiting Brian. `decisions.md` is now ~500KB. |
| **Linus wording deviation** | Linus shipped "stated no key factors" instead of Danny's "does not emit", claiming the primary now *does* emit factors. Contradicts the ruling's premise. **Unresolved.** |
| **Torn ruling in the ledger** | The `decisions.md` copy of the banker-customer-read ruling is torn mid-sentence. `docs/design/banker-customer-read-ruling.md` is intact — trust that one. |
| **Empty `transactionId`** | 114 of 128 flagged rows have an empty `transactionId`, empty `accountId`, or zero `amount`. **Observation, not a finding.** Cause uninvestigated. Recorded so it can be falsified. |

---

## Sequence from here

1. **Reseed** (morning, mandatory).
2. **Brian walks §7.1-§7.7** in the browser. Sign in as `banker`, open `/copilot`.
   Queue should show banker NEEDS YOU ~7, supervisor NEEDS YOU ~1.
3. **Livingston measures stage 1.** He must be told three things: the reseed invalidated his
   previous 42 runs; three policy actions now gather one extra evidence item; check 2.5 is
   unexercised under the 8h TTL. Danny's §R9 proviso is now **satisfied** — the rung is pinned,
   so the earlier "must not read the rung" caveat no longer binds.
4. **Stage 2** (ceiling 0→3, config-only). Must be a **separate deploy** to preserve
   attribution. Blocked on Turk's `quarantined` pin.
5. **#140** may open for research but must not touch `harness-limits.yaml`,
   `authority-policy.yaml`, `copilot-tools.yaml`, or `banker-copilot-service/` until stage 2
   is measured.

---

## The pattern worth carrying forward

**Five times this week a written claim turned out false, and each was caught only because it
was written down.** Turk's "nothing else calls this endpoint" (scoped to `src/`, missed
`scripts/`). The Go `publishedEventTypes` comment. Fixtures agreeing with the renderer instead
of the service. Danny's own §R7, which would have produced a seeder that died 21 runs in 23.
And my own §R6 diagnostic, which reported the subject *absent* and nearly discarded a good
seed — caught only because a known-present control case also came back absent.

**When a check returns the same surprising answer for a case you already know the answer to,
the check is the suspect.** A control case is cheap and it is the only thing standing between
a matcher bug and a wrong decision.

Standing rules: confirm before any action touching Brian's machine or Azure — reading is fine.
Verify commit claims with `git log`; a SHA or it did not happen. Keep responses short.
