# Decision Drop — Accounts page regression / Cosmos casing drift (#121 review → #125)

**Author:** Basher  
**Date:** 2026-05-13  
**Branch:** `squad/p2-wave-3`  
**Files:** `src/account-service/Repositories/CosmosAccountRepository.cs`

## Decision

**Reader-side OR-pattern is the right hot fix; pin a camelCase serializer + migrate data is the right long-term fix.**

For `account-service` Cosmos queries that filter on persisted property paths, always assume **mixed casing exists in the live container** until proven otherwise, and use `WHERE c.PascalName = @v OR c.camelName = @v`. This is a pragmatic shim — the proper fix is to (a) pin `CosmosClientOptions.Serializer` to a deterministic camelCase Newtonsoft serializer (matching API output and the most-recent writes), then (b) one-shot migrate the legacy PascalCase docs, then (c) revert the OR-pattern.

Do **not** "just fix the model" by sprinkling `[JsonProperty("camelName")]`. That changes the deserializer too, but the existing PascalCase docs in production will become invisible (Newtonsoft case-insensitive deserialize was the only thing keeping reads working after the writer flipped).

## Rationale

1. **Cosmos JSON field paths are case-sensitive in WHERE clauses.** A query for `c.UserId` returns 0 rows for docs whose property is `userId`. The C# entity round-trips fine because Newtonsoft deserialize is case-insensitive — so the bug is invisible on a single-doc read but catastrophic on a list query.
2. **Cosmos SDK v3 default serializer (Newtonsoft, preserve-case) can silently change behaviour between package versions.** Today's evidence: docs created 2026-05-12 in our `Accounts` container are PascalCase, docs created 2026-05-13 are camelCase, with no explicit code change in `Account.cs` or `Program.cs`. Either an SDK update or an alternate writer flipped the casing. Until we identify the source, we have to assume future writes could flip again.
3. **Hot-fix the readers first** because the user-visible regression (empty `/accounts` page for any user with camelCase docs, incl. brian@sample.com) is severity-1. Migration + serializer pin can ship next wave with proper review.
4. **Iterator drain bug** (only reading first page of `ReadNextAsync()`) was hiding behind the casing bug; fixing both at once costs nothing extra and prevents the next 100+-account user from hitting a different silent truncation.

## Alternatives considered

1. **Migrate Cosmos data immediately as the only fix.** Rejected — leaves the writer behaviour ambiguous; if writes flip again tomorrow we're back in the same hole. OR-pattern in the reader is defensive.
2. **Add `[JsonProperty("camelName")]` to `Account.cs` and revert nothing else.** Rejected — Newtonsoft deserialize is case-insensitive but the **serializer** would now write camelCase exclusively, leaving the existing 29 PascalCase e2e docs unreadable on UPSERT round-trips (would create new docs instead of updating). Worse, would break any other service that reads from this container expecting PascalCase fields.
3. **Use `CosmosClient.GetItemLinqQueryable<Account>()` instead of raw QueryDefinition.** Tempting because LINQ would translate property names through the serializer, but it still emits a single-casing field path — same problem, just hidden behind the LINQ provider.
4. **Ignore Brian's accounts (treat as test data loss).** Rejected — same bug affects every user provisioned via the `account-opening-service` flow, which is the demo's headline feature.

## Operational notes

- **Smoke creds for cheap auth verification:** `tests/e2e/fixtures/authFixture.ts` has `e2e-default@banking-demo.com / password123`. Login → bearer token → `curl https://${CUSTOM_DOMAIN}/api/accounts` is the fastest live-prod check, no Playwright needed. The user has 38+ accounts (smoke pollution), so it's also a good case for catching pagination/truncation bugs.
- **Cosmos has Local Auth disabled (Entra RBAC only).** Direct queries must run from a pod with `serviceAccountName: banking-workload-identity` and the `azure.workload.identity/use: "true"` label. `account-opening-service` pods already satisfy this and ship `azure-cosmos==4.15.0` — reuse them for any one-shot Cosmos investigation. Pattern documented in 2026-05-13 history entry.
- **`task cloud:deploy` is now confirmed to `kubectl rollout restart` all deployments** (per coordinator commit `e57d5f0`). Rebuilding only the changed service image and then `task cloud:deploy` is the supported flow.

## Follow-ups (filed as #125)

1. Identify what flipped writer casing between 2026-05-12 and 2026-05-13. Likely candidates: `Microsoft.Azure.Cosmos` package version bump in `Directory.Packages.props`, or a non-`account-service` writer.
2. Pin `CosmosClientOptions.Serializer` to a deterministic camelCase serializer in `account-service/Program.cs`.
3. One-shot migration of PascalCase docs → camelCase. After migration, revert `OR` clause in `CosmosAccountRepository`.
4. Audit `transaction-service`, `prompt-eval-service`, `user-service` Cosmos repos for the same case-sensitivity assumption.
5. Add an integration test that writes via the API + queries Cosmos directly to assert field casing — would catch any future drift on the next CI run.
