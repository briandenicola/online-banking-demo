# Session Log — Reseed Unblocked

**Date:** 2026-09-09T21:42:28Z
**Branch:** `332-beta`
**Event:** Demo reseed now succeeds end to end

## Summary

Three cascading defects cleared this session:

1. **§B2.2 empty-ledger 403** — Fixed by moving demo.sh to GET `/api/transactions/my` (Turk + Rusty's change). Seeder now asks "what have I posted" through its own token's view instead of querying an account-scoped endpoint without entitlement on an empty ledger.

2. **Canonicalizer fractional payload rejection** — HTTP 400 at approval 11 where `"newScore": 0.25` (JSON float) was rejected on a non-money field. Fixed by type change only: `"newScore": "0.25"` (string). Guard added to `test-demo-dataset.sh` to catch the whole class of defect before a reseed, not during one.

3. **Scoring poll window too short** — `scoring.pollSeconds: 90` could not accommodate 23 transactions when ai-service scoring costs ~5–6s per call under Azure Foundry rate-limiting (HTTP 429). Raised to 300 (5 minutes).

**Outcome:** Reseed completed end to end. `Seed complete`.

**No redeploys required.** Live reseed is the remaining proof of correctness.
