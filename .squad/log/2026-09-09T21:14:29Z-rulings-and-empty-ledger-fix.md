# Session Log — 2026-09-09 — Rulings and Empty-Ledger Fix

**Scribe Pass:** Merge of four-agent spawn (Danny, Turk, Rusty, Linus).

## Summary

**Status:** Complete. No redeploy required. Brian's reseed path unblocked.

Three rulings from Danny merged into `docs/design/`. Nine decision inbox entries merged into `.squad/decisions.md` (one per agent, three inbox files). Two open items flagged for Danny's review. All agent work committed: backend narrowing documentation correction, frontend silence indicator, demo script seeder migration, no logic changes.

## Key Facts

- **Danny's three rulings stand:** §B2.2 empty-ledger narrowing is correct; §E probe idempotency is correct (reusable approval ≠ repeatable question); §F factor-divergence silence requires one visible condition, shipped.
- **No redeploy.** Changes are isolated to `src/transaction-service/` docs (comment only, 19/19 tests), `src/ui-app/` frontend only, `scripts/demo/` and `tests/demo/` caller-side fix, and decision records.
- **Seeder unblocked.** Four `demo.sh` call sites moved from `/api/transactions/account/{id}` (account-scoped, fails on empty ledger) to `/api/transactions/my` (owner's own rows, works at reseed). Verified with two guards: textual (PascalCase tolerance) and behavioural (idempotency offline simulation).
- **Two flags for Danny.** Linus's wording deviation (tense + run-scoped truthiness), Linus's second layer deeper (classification gap), Turk's upstream docs gap at banker-copilot-service.

## Next Gates

- **Stage 1 measurement:** Livingston. Reseed path unblocked; stage 1 measures harness correctness.
- **Brian's reseed run:** proof of seeder working on empty ledger.
- **Danny's decision on Linus's flags:** wording confirmation, factor-classification scope, upstream docs owner contact.

## Compaction Plan Status

Committed to `.squad/decisions-compaction-plan.md` as a plan only. **Not executed.** Pending Brian's authorisation.
