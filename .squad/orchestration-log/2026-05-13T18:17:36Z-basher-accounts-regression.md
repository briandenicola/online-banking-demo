# Orchestration Log — Basher Accounts Regression Investigation

**Date:** 2026-05-13  
**Time (UTC):** 2026-05-13T18:17:36Z  
**Agent:** Basher  
**Outcome:** COMPLETED  

## Event Summary

Basher completed root cause investigation of the Accounts page regression (#121 → #125 reclassification).

## Root Cause

CosmosAccountRepository.cs queries assumed PascalCase property names (`UserId`, `AccountNumber`), but live production Cosmos container contains mixed casing:
- Docs created 2026-05-12: PascalCase
- Docs created 2026-05-13: camelCase

Cosmos WHERE clauses are case-sensitive on property paths, causing queries to return 0 rows for camelCase docs.

## Fix Implemented

**Hot fix (production deployed):**
- `GetAccountsAsync()` now OR-matches both casings: `WHERE c.UserId = @v OR c.userId = @v`
- Fixed iterator drainage bug (was only reading first page of `ReadNextAsync()`)

**Long-term fix (filed as #125):**
- Pin `CosmosClientOptions.Serializer` to deterministic camelCase
- Migrate legacy PascalCase docs
- Remove OR-pattern after migration

## Files Modified

- `src/account-service/Repositories/CosmosAccountRepository.cs`

## Related Issues

- **#121** (original report): Turk's chatbot fix confirmed as correct; regression was unrelated
- **#123**: AI dashboard tiles 0 post-purge (Basher's follow-up)
- **#125**: Cosmos serializer cleanup (long-term, filed by Basher)

## Deployment

- **Branch:** `squad/p2-wave-3`
- **Commit:** fb96f47
- **Status:** Built, deployed, verified live
- **Verification:** `/api/accounts` now returns all accounts for users with camelCase docs (confirmed via smoke creds)

## Decision Recorded

Entry written to `.squad/decisions/inbox/basher-accounts-regression.md` for inbox → decisions.md merge.
