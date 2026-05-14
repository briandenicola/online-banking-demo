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
- **COUNT queries:** `SELECT VALUE COUNT(1) FROM c WHERE c.Role = 'admin'` → `WHERE c.Role = 'admin' OR c.role = 'admin'`

### ORDER BY Pitfall (Composite Index Requirement)

**CRITICAL:** Combining the OR-both-casings pattern with `ORDER BY` forces Cosmos DB to require a **composite index**:

```sql
-- ❌ WRONG — requires composite index [userId, createdAt] + [UserId, CreatedAt]
SELECT * FROM c 
WHERE c.userId = @x OR c.UserId = @x 
ORDER BY c.createdAt DESC, c.CreatedAt DESC
```

**Why?** Cosmos can't use the OR-pattern index efficiently with ORDER BY. It needs composite indexes on each field combination, which:
1. Must be pre-defined in Terraform (`azurerm_cosmosdb_sql_container.indexing_policy.composite_index`)
2. Blocks deployment until Brian runs `terraform apply`
3. Couples code changes to infra changes (bad)

**Solution:** For **admin tables** (small, global-scoped data like templates, settings, evaluation runs), prefer **in-memory sorting**:

```csharp
// ✅ CORRECT — fetch all, sort in-memory
var query = new QueryDefinition("SELECT * FROM c WHERE c.userId = 'global' OR c.UserId = 'global'");

var results = new List<T>();
using var iterator = _container.GetItemQueryIterator<T>(query);
while (iterator.HasMoreResults)
{
    var response = await iterator.ReadNextAsync();
    results.AddRange(response);
}

// Sort in-memory to avoid composite index requirement
return results.OrderByDescending(r => r.CreatedAt).ToList();
```

**When NOT to use in-memory sort:**
- User-scoped queries that return 100s-1000s of docs per user
- High-traffic endpoints where RU cost matters
- Pagination scenarios (need server-side ORDER BY + OFFSET/LIMIT)

In those cases, you MUST add the composite index to Terraform and document the infra dependency.

## Related Skills

- **redis-stream-consumer-resilience** — Defensive pattern for XGROUP CREATE (similar "fail on retry" trap)
- **preview-sdk-pinning** — Exact-pin pattern to stop SDK drift (same root cause as serializer drift)

## Rung 2 — Sentinel-Doc Pollution in Field-Match Queries (2026-05-14)

**Confidence: HIGH (verified via prod-data repro + log evidence)**

The same Cosmos container often holds **multiple document shapes** (real entities + sentinel/lookup docs used for uniqueness or indexing). A query that filters on a field shared by both shapes will return the sentinel doc — which deserializes into the entity POCO with mostly-null fields, silently breaking downstream auth/validation.

### Concrete recurrence (user-service, Users container)

- Real users live as `{id: <guid>, username, email, passwordHash, ...}`.
- A deterministic **email-uniqueness sentinel** (`fix: prevent duplicate email registration via Cosmos lookup document pattern`, commit `1afec6e`) lives as `{id: "email-lookup:<email>", type: "email-lookup", userId, email}`.
- `GetByEmailAsync` query was `SELECT * FROM c WHERE LOWER(c.Email)=@e OR LOWER(c.email)=@e` — no sentinel filter.
- Cosmos returned the **lookup doc first** (no ORDER BY → arbitrary order). Deserialized into `User` with `Username=null`, `PasswordHash=null`.
- Login-by-email path: `ValidateCredentialsAsync(user.Username=null, password)` → fails → 401. Audit log emitted `Login audit logged for user "email-lookup:brian@sample.com"` — the lookup-doc id leaked through as the user id, which was the smoking gun in the logs.

### The pattern (memorize this)

> **Any query that does NOT filter by `c.id` directly, on a container that holds sentinel/lookup docs, MUST include `AND NOT STARTSWITH(c.id, '<sentinel-prefix>:')`.**

The two queries in `CosmosUserRepository` that already had this filter were `IsContainerEmptyAsync` and `GetAllUsersAsync`. The author of those queries knew about the pollution risk. `GetByEmailAsync` was added/modified later and missed the guard. **This is the recurrence pattern: when adding a new query, copy an existing query in the same repo as your template — don't write it from scratch.**

### Audit checklist for any container with sentinel docs

For each query in the repo:

1. Does it filter on a field shared by the sentinel? (e.g., sentinel has `email`, real doc has `email` → AT RISK)
2. Does it deserialize into the real-entity POCO? (yes → silent corruption on hit)
3. Does it have `AND NOT STARTSWITH(c.id, '<prefix>:')`? (no → BUG)

Run this grep before merging any new repo query:

```bash
grep -nE "WHERE c\." src/<service>/Repositories/*.cs | grep -v "STARTSWITH(c.id"
# Each result must be justified — either the field is sentinel-exclusive,
# or the query already filters by c.id directly (point read).
```

### Smoke-test that would have caught this

A `LoginAsync(email, password)` integration test that:
1. Registers a user (creates both real + sentinel docs).
2. Logs in **using the email** (not the username).
3. Asserts a 200 + valid JWT.

Currently login E2E uses username — never exercised the email path post-sentinel-doc introduction.

### Reference (Rung 2)

- Decision drop: `.squad/decisions/inbox/basher-userservice-auth-regression.md`
- Fix commit: pending — `src/user-service/Repositories/CosmosUserRepository.cs:GetByEmailAsync`
- Related: `1afec6e` (introduced the sentinel doc pattern) — author did not retro-fit existing email-lookup queries.

## Reference

- Issue: #125
- Decision drop: `.squad/decisions/inbox/turk-cosmos-serializer-pin.md`
- Migration plan: `.squad/decisions/inbox/turk-125-cosmos-migration-plan.md`
