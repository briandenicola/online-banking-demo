# Cosmos Serializer-Casing Migration Plan

**Issue:** #125  
**Author:** Turk (Backend Dev)  
**Date:** 2026-05-13  
**Status:** Ready for Brian to execute

## Context

Five Cosmos containers have documents written with **two different field casings**:
- **PascalCase**: `UserId`, `AccountId`, `Username`, `Email`, `Role`, `CreatedAt`, `UpdatedAt`, `TemplateId` (likely from Cosmos SDK v3 default Newtonsoft serializer)
- **camelCase**: `userId`, `accountId`, `username`, `email`, `role`, `createdAt`, `updatedAt`, `templateId` (source unknown — possibly SDK behavior change or manual writes)

Cosmos SQL queries are case-sensitive on field paths, so a query written for one casing silently returns 0 rows for docs of the other. This caused the `/accounts` UI page to render empty for any user whose docs happened to be camelCase (incl. `brian@sample.com`).

## Hot Fix (Already Shipped)

All .NET service repositories now **OR both casings** in WHERE clauses. Iterator drain bugs also fixed. This restores read functionality immediately but doesn't normalize the data.

## Affected Containers

1. **Accounts** (`/userId` partition)
   - Fields: `UserId`/`userId`, `AccountNumber`/`accountNumber`
   - Estimated: ~38 docs (29 PascalCase, 9 camelCase based on May 13 live query)

2. **Transactions** (`/accountId` partition)
   - Fields: `AccountId`/`accountId`, `UserId`/`userId`, `Timestamp`/`timestamp`
   - Estimated: ~155 docs (unknown split)

3. **Users** (`/id` partition)
   - Fields: `Username`/`username`, `Email`/`email`, `Role`/`role`, `CreatedAt`/`createdAt`
   - Estimated: ~10 docs (bootstrap users + e2e test user)

4. **PromptTemplates** (`/userId` partition)
   - Fields: `UserId`/`userId`, `UpdatedAt`/`updatedAt`
   - Estimated: ~4 seeded templates

5. **EvaluationRuns** (`/userId` partition)
   - Fields: `UserId`/`userId`, `TemplateId`/`templateId`, `CreatedAt`/`createdAt`
   - Estimated: <10 docs (admin-triggered runs only)

## Migration Approach

### 1. Identify PascalCase Documents

For each container, run a Cosmos SQL query to find docs with PascalCase fields. Example for Accounts:

```sql
SELECT c.id, c.UserId, c.userId, c.AccountNumber, c.accountNumber
FROM c
WHERE IS_DEFINED(c.UserId) OR IS_DEFINED(c.AccountNumber)
```

Run via workload-identity pod (pattern from `.squad/agents/basher/history.md` 2026-05-13 entry):
```python
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

endpoint = "https://{cosmos-account}.documents.azure.com:443/"
credential = DefaultAzureCredential()
client = CosmosClient(endpoint, credential)
db = client.get_database_client("BankingDemo")
container = db.get_container_client("Accounts")

# Query and log PascalCase docs
query = "SELECT c.id, c.UserId FROM c WHERE IS_DEFINED(c.UserId)"
for item in container.query_items(query, enable_cross_partition_query=True):
    print(f"PascalCase doc: {item['id']}")
```

### 2. Normalize to camelCase (UPSERT Pattern)

For each PascalCase doc:
1. Read the full doc
2. Transform field names: `UserId` → `userId`, `AccountNumber` → `accountNumber`, etc.
3. UPSERT with same `id` and partition key (overwrites in-place, preserves TTL/metadata)
4. Verify the new doc has camelCase fields

**Why UPSERT over REPLACE:**
- UPSERT is idempotent (safe to re-run)
- Preserves Cosmos internal metadata (`_rid`, `_self`, `_etag`, `_ts`)
- No race condition on `_etag` (unlike conditional REPLACE)

**Script skeleton:**
```python
for item in container.query_items(query, enable_cross_partition_query=True):
    doc_id = item["id"]
    partition_key = item.get("userId") or item.get("UserId")  # Read from either casing
    
    # Read full doc
    doc = container.read_item(item=doc_id, partition_key=partition_key)
    
    # Transform PascalCase → camelCase
    if "UserId" in doc:
        doc["userId"] = doc.pop("UserId")
    if "AccountNumber" in doc:
        doc["accountNumber"] = doc.pop("AccountNumber")
    # ... repeat for all known PascalCase fields
    
    # UPSERT (overwrites in-place)
    container.upsert_item(doc)
    print(f"Normalized {doc_id}")
```

### 3. Verification Queries

After migration, confirm **zero PascalCase docs** remain:
```sql
-- Should return 0 rows for each container
SELECT COUNT(1) FROM c WHERE IS_DEFINED(c.UserId)
SELECT COUNT(1) FROM c WHERE IS_DEFINED(c.AccountNumber)
SELECT COUNT(1) FROM c WHERE IS_DEFINED(c.Username)
-- ... etc.
```

### 4. Rollback Plan

If migration causes issues:
1. **Immediate:** Hot-fix repo queries already handle both casings — no read disruption
2. **Revert writes:** Deploy previous CosmosClient config (no serializer pinning) to allow PascalCase writes again
3. **Re-normalize:** Re-run migration script (UPSERT is idempotent)

**Data loss risk:** ZERO — UPSERT preserves all fields, only renames keys. Partition key and `id` are unchanged.

### 5. Post-Migration Cleanup

Once **all docs are normalized to camelCase** and the serializer is pinned:
1. Remove the OR-both-casings pattern from repository queries
2. Revert queries to single-casing (cleaner SQL, faster execution)
3. Add integration test (separate issue filed — see #125 follow-up #5)

Example revert for `CosmosAccountRepository.GetByUserIdAsync`:
```csharp
// Before (defensive OR)
WHERE c.UserId = @userId OR c.userId = @userId

// After migration (clean single-casing)
WHERE c.userId = @userId
```

## Acceptance Criteria

1. All 5 containers have **zero PascalCase docs** (verified via `IS_DEFINED` queries)
2. UI `/accounts` page renders correctly for `brian@sample.com` and `e2e-default` user
3. Admin dashboard counters (transactions, prompts) are accurate
4. No 500 errors or missing data in logs post-migration

## Out of Scope

- **Git bisect on Microsoft.Azure.Cosmos** (issue follow-up #1): Root-causing the original writer is optional once serializer is pinned. Not blocking.
- **Historical write timestamps**: No need to trace which deploy introduced camelCase writes — forward-only fix is sufficient.

## Execution Timing

**Best practice:** Run during low-traffic window (e.g., evening UTC) to minimize cross-partition query load. Estimated runtime: <5 minutes for ~200 total docs across all containers.

## References

- Issue: #125
- Hot-fix commit: `squad/p2-wave-3` (Basher's account-service OR-pattern + iterator drain fix)
- Workload-identity pod pattern: `.squad/agents/basher/history.md` 2026-05-13 entry (Redis Stream consumer investigation)
- Serializer pin: `.squad/decisions/inbox/turk-cosmos-serializer-pin.md`
