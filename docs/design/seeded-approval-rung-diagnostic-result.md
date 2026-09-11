# §R6 Diagnostic Result — the current seed is state (b-i), USABLE

**Run by:** Squad (Coordinator), on Brian's explicit authorisation for live read-only calls
**Date:** 2026-09-09T21:55Z
**Decides:** the open question left by `seeded-approval-rung-nondeterminism-ruling.md` §R6
**Method:** read-only calls against `https://onlinebankingdemo.bjdazure.tech` as `admin`.
No identity, account, transaction, or approval was created, modified, or deleted.

---

## Verdict

**State (b-i). The seed is usable.** The `flag-review-denied` subject is a genuinely flagged
transaction that resolves live; its amount is simply under the escalator threshold.

Per §R6, this is the branch where *"the seed is usable. Livingston may measure now, provided
the measurement does not read this approval's rung or its evidence amounts, and the ruling's
fix proceeds in parallel."*

---

## A correction I have to record first

My initial check reported the subject **absent** from the flagged list, which would have been
state (b-ii) — seed broken, discard and reseed. **That conclusion was wrong**, and I published
it to Brian before catching it.

The error: I matched the approval's `payload.transactionId` against the `transactionId` **field**
of each flagged row. The correct key is the row's **`id`**. Matching on the wrong field returned
zero hits and looked exactly like a genuine absence.

What exposed it: the run A subject (`68417477…`, amount `61200`) also came back absent. Two
absences where at least one was expected to be present meant the *matcher* was the more likely
fault than the data. That falsifiability check is the only reason this was caught, and it is the
fifth time this week that a written premise was the sole handle on a false claim.

---

## Evidence

### 1. Danny's §R1 arithmetic is confirmed exactly

Both `transaction.flag.review` approvals, read from `/api/authority/approvals?scope=all`:

| Approval | createdAt | `payload.amount` | Escalator | Rung |
|---|---|---|---|---|
| `apr_dd707c2a4ddb46ca8f7e537b` (run A) | 21:16:49Z | `61200` | `large-flagged-amount` fired, `thresholdValue 25000.00` | base L1 → **L2** |
| `apr_2241a79e38b64cacb9bc43ce` (run B, current seed) | 21:35:21Z | `9350` | none fired | **L1** |

The rung divergence is entirely explained by the payload amount straddling the
`flagged_transaction_dual_control_amount` threshold of `$25,000`. Nothing else differs.
`pollSeconds` and `newScore` are not involved, exactly as Danny said.

### 2. The subject is genuinely flagged, not a merely-scored substitute

The current seed's subject `6a026fdc-a2af-4162-9825-689dd57fd958`, as returned by
`/api/admin/flagged-transactions`:

- `riskScore` **0.72** — at or above the `FLAGGING_THRESHOLD` of 0.7
- `flags` `["large_amount","cash_deposit","atm_deposit","potential_structuring"]`
- `flaggedAt` `2026-09-09T21:33:57Z` — inside the successful run's window
- `amount` `9350`, `type` `Deposit` — the ATM cash deposit, one of casey's near-threshold trio

So the §598 fallback (`flagged_pool` → `pool`) **did not fire on this run**. The winner was a
real flagged record that happened to sit below the escalator line.

### 3. The seeder's use of `.id` is CORRECT — this is the key finding

`demo.sh` sets the subject refs with `set_ref_from "$flagged_pool" … '.id'`. A flagged row
carries **both** an `id` and a different inner `transactionId`, so this looked like a field bug.
It is not. Tested live:

| Call | Result |
|---|---|
| `GET /api/admin/flagged-transactions/6a026fdc…` (the row's `.id`) | **200** |
| `GET /api/admin/flagged-transactions/ddcb537f…` (its `.transactionId`) | **404** |
| `GET /api/admin/scored-transactions/6a026fdc…` | **200** |
| `GET /api/admin/scored-transactions/ddcb537f…` | **404** |

`src/ai-service/app/routes/api.py:244` keys the lookup on the Redis suffix
`FLAGGED_TRANSACTION_PREFIX{tx_id}`, and `.id` is that suffix. **`.transactionId` is an inner
field, not a lookup key.** Any future change that "fixes" `demo.sh` to use `.transactionId`
would break every evidence read in the demo. Recording this so nobody makes that change.

---

## What is still broken, and still needs Danny's §R4/§R7 fix

Being usable today is not the same as being reproducible. Three defects survive this diagnostic:

1. **The rung is still first-past-the-post.** `minScoredRequired: 1` breaks the poll at the
   first scored transaction on a seeded account. Of the 23 seeded, only two clear `$25,000`.
   Rerunning the seed will keep flipping `flag-review-denied` between L1 and L2.
2. **The §598 fallback is still live.** It did not fire this time. Nothing prevents it firing
   next time, and when it does the approval claims a flagged subject that
   `get_flagged_transaction` will 404 on — the exact thing
   `probe-idempotency-and-divergence-silence-ruling.md` §F5 forbids.
3. **Observed data-quality issue, not previously recorded:** of 128 rows returned by
   `/api/admin/flagged-transactions`, only **14** carry a non-empty `transactionId`, **17** a
   non-empty `accountId`, and **10** a non-zero `amount`. The remaining rows are inert as far as
   the seeder's `accountId` filter is concerned. This shrinks the flagged pool and therefore
   makes the §598 fallback *more* likely to fire, not less. Cause not investigated here.

---

## Consequences

- **Livingston MAY measure stage 1 on the current seed**, under the §R6 proviso: the measurement
  must not read `flag-review-denied`'s rung or its evidence amounts.
- **The §R4 fix must still land** before any baseline that is meant to be regenerable.
- The seed does **not** need to be discarded. No reseed is required for correctness today.

## Standing caution

Item 3 above is an observation from a single snapshot. It is written here as an observation, not
a finding, precisely so that it can be falsified by whoever picks it up.
