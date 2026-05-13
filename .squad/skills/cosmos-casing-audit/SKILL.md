# Cosmos DB Field-Casing Audit & Fix

## When to Apply

Any time you suspect **Cosmos serializer drift** across .NET services — documents written with different field casings (PascalCase vs camelCase) causing queries to silently miss rows.

**Symptoms:**
- Query returns 0 rows for some users but not others (same entity type)
- User reports "data is missing" but direct Cosmos Data Explorer shows the docs exist
- Logs show query completed successfully but returned empty result set
- The issue is **user-specific** or **time-based** (docs created before/after a certain deploy)

## The Problem

Cosmos SQL queries are **case-sensitive on field paths**:
```sql
WHERE c.UserId = @x   -- only matches docs with PascalCase "UserId"
WHERE c.userId = @x   -- only matches docs with camelCase "userId"
```

If historical docs use `UserId` but the query uses `userId`, those docs are invisible. This can happen when:
1. Cosmos SDK's default serializer changes behavior across versions
2. Different services (or different versions of the same service) write with different serializers
3. Manual writes (scripts, admin tools) use a different casing than app writes

## Step-by-Step Fix

### 1. Identify Affected Services

Find all .NET services that query user-scoped or account-scoped fields:

```bash
cd /home/brian/code/online-banking-demo
grep -r "WHERE c\." src/**/*.cs | grep -v "WHERE c.id"
```

Look for queries that filter on fields like:
- `c.UserId` / `c.userId`
- `c.AccountId` / `c.accountId`
- `c.Username` / `c.username`
- `c.Email` / `c.email`
- `c.Role` / `c.role`
- `c.CreatedAt` / `c.createdAt`
- `c.UpdatedAt` / `c.updatedAt`
- `c.TemplateId` / `c.templateId`

### 2. Check Iterator Drain Bug

While you're at it, verify that queries **drain the iterator** correctly:

```csharp
// ❌ WRONG — silently truncates at page size (~100 docs)
var results = await iterator.ReadNextAsync();
return results.Take(limit);

// ✅ CORRECT — drains all pages
var results = new List<T>();
while (iterator.HasMoreResults)
{
    var page = await iterator.ReadNextAsync();
    results.AddRange(page);
}
return results;
```

### 3. Apply Defensive OR-Pattern

For each query that filters on a user-scoped field, update to **OR both casings**:

```csharp
// Before
var query = new QueryDefinition("SELECT * FROM c WHERE c.userId = @userId")
    .WithParameter("@userId", userId);

// After (defensive — matches both casings)
var query = new QueryDefinition("SELECT * FROM c WHERE c.UserId = @userId OR c.userId = @userId")
    .WithParameter("@userId", userId);
```

Apply to ALL casings in the query:
```csharp
// Multi-field example
var query = new QueryDefinition(
        "SELECT * FROM c WHERE (c.UserId = @userId OR c.userId = @userId) " +
        "AND (c.AccountNumber = @accNum OR c.accountNumber = @accNum)")
    .WithParameter("@userId", userId)
    .WithParameter("@accNum", accountNumber);
```

**Ordering:** If using `ORDER BY`, OR both casings there too:
```sql
ORDER BY c.CreatedAt DESC, c.createdAt DESC
```

### 4. Pin the Serializer (Stop Future Drift)

In **every** service's `Program.cs`, replace default `CosmosClient()` with explicit serializer:

```csharp
// Before (non-deterministic — SDK version-dependent)
builder.Services.AddSingleton<CosmosClient>(sp =>
{
    var endpoint = sp.GetRequiredService<IConfiguration>()["CosmosDb:Endpoint"];
    return new CosmosClient(endpoint, new DefaultAzureCredential());
});

// After (deterministic — always camelCase)
builder.Services.AddSingleton<CosmosClient>(sp =>
{
    var configuration = sp.GetRequiredService<IConfiguration>();
    var endpoint = configuration["CosmosDb:Endpoint"];
    
    var clientOptions = new CosmosClientOptions
    {
        SerializerOptions = new CosmosSerializationOptions
        {
            PropertyNamingPolicy = CosmosPropertyNamingPolicy.CamelCase,
            IgnoreNullValues = true
        }
    };
    
    if (!string.IsNullOrEmpty(endpoint))
    {
        return new CosmosClient(endpoint, new DefaultAzureCredential(), clientOptions);
    }
    return new CosmosClient(configuration["CosmosDb:ConnectionString"], clientOptions);
});
```

**⚠️ DO NOT USE `CosmosSystemTextJsonSerializer`** — it is an **internal type** in Microsoft.Azure.Cosmos and will cause build failures. Always use the public `CosmosSerializationOptions` API shown above.

**Why camelCase?**
- Matches API surface (ASP.NET Core defaults to camelCase JSON)
- JavaScript/TypeScript convention (frontend expects it)
- Easier to read (most devs prefer `userId` over `UserId`)

### 5. Document the Migration Plan

The OR-pattern is **defensive but temporary**. Once docs are normalized to a single casing, you should revert to single-casing queries for cleaner SQL and better index usage.

Create a migration plan document (`.squad/decisions/inbox/<agent>-<issue>-cosmos-migration-plan.md`) with:
1. Cosmos containers affected
2. SQL to identify PascalCase docs: `SELECT * FROM c WHERE IS_DEFINED(c.UserId)`
3. UPSERT script to normalize to camelCase (use workload-identity pod + `azure.cosmos` Python client)
4. Rollback plan (safe — UPSERT is idempotent)
5. Post-migration cleanup (revert OR-pattern to single-casing)

### 6. Verification

After deploying the fix:
1. Test with a user who was previously affected (e.g., `brian@sample.com` if that's the repro case)
2. Query should now return docs regardless of their original casing
3. Check logs for iterator warnings — should see `AddRange()` calls, not just single-page results

## Gotchas

- **Don't forget Program.cs startup queries:** Some services have admin-promotion logic or seed queries that run at startup. Those need the OR-pattern too.
- **ORDER BY needs both casings:** If you ORDER BY a dual-casing field, you need `ORDER BY c.CreatedAt DESC, c.createdAt DESC` or results will be partially sorted.
- **COUNT queries:** `SELECT VALUE COUNT(1) FROM c WHERE c.Role = 'admin'` → `WHERE c.Role = 'admin' OR c.role = 'admin'`

## Related Skills

- **redis-stream-consumer-resilience** — Defensive pattern for XGROUP CREATE (similar "fail on retry" trap)
- **preview-sdk-pinning** — Exact-pin pattern to stop SDK drift (same root cause as serializer drift)

## Reference

- Issue: #125
- Decision drop: `.squad/decisions/inbox/turk-cosmos-serializer-pin.md`
- Migration plan: `.squad/decisions/inbox/turk-125-cosmos-migration-plan.md`
