# Decision: Remove ORDER BY from prompt-eval-service Cosmos queries (#125 follow-up)

**Date:** 2026-05-12  
**Agent:** Turk  
**Status:** Implemented  
**Issue:** Startup crash — BadRequest 400: "The order by query does not have a corresponding composite index"

## Problem

Commit 243457f (#125) introduced OR-both-casings defensive queries in prompt-eval-service to handle historical PascalCase/camelCase field drift. Two queries included `ORDER BY` clauses:

1. **CosmosEvaluationRunRepository.GetAllAsync():**  
   `ORDER BY c.createdAt DESC, c.CreatedAt DESC`

2. **CosmosPromptTemplateRepository.GetAllAsync():**  
   `ORDER BY c.updatedAt DESC, c.UpdatedAt DESC`

**Root cause:** Cosmos DB cannot efficiently serve OR-pattern queries with ORDER BY unless a **composite index** exists on each field combination. The PromptTemplates and EvaluationRuns containers do not have these composite indexes defined in Terraform.

## Options Considered

### Option A (Selected): In-Memory Sort

**Approach:** Remove ORDER BY from Cosmos query, fetch all results, sort in-memory using LINQ.

**Pros:**
- No infrastructure changes required
- No terraform apply dependency (deploy-ready immediately)
- Perfectly acceptable for small admin tables (global templates, evaluation runs)
- Preserves same API semantics (sorted by date descending)

**Cons:**
- Consumes slightly more RU (full scan, no server-side sort optimization)
- Not suitable for large result sets (100s-1000s of docs)

**Assessment:** These are **global admin tables** with ~10-50 total docs max. In-memory sort is the right choice.

### Option B (Rejected): Add Composite Index to Terraform

**Approach:** Define composite indexes in `infra/cloud/cosmos.tf`:
```hcl
composite_index {
  indexes {
    path  = "/userId"
    order = "ascending"
  }
  indexes {
    path  = "/createdAt"
    order = "descending"
  }
}
# ... repeat for UserId, CreatedAt, updatedAt, UpdatedAt
```

**Pros:**
- Server-side sort (lower RU cost)
- Better for large result sets

**Cons:**
- **Blocks deployment:** Brian must run `terraform apply` before code deploy
- Couples code changes to infra changes (bad practice)
- Overkill for small admin tables
- Requires 4 composite indexes (2 containers × 2 casing variations each)

**Assessment:** Not justified for admin tables.

## Implementation

**Files changed:**
1. `src/prompt-eval-service/Repositories/CosmosEvaluationRunRepository.cs`  
   - Removed `ORDER BY` clause from query  
   - Added `.OrderByDescending(r => r.CreatedAt).ToList()` in-memory

2. `src/prompt-eval-service/Repositories/CosmosPromptTemplateRepository.cs`  
   - Removed `ORDER BY` clause from query  
   - Added `.OrderByDescending(t => t.UpdatedAt).ToList()` in-memory

3. `.squad/skills/cosmos-casing-audit/SKILL.md`  
   - Added "ORDER BY Pitfall" section documenting composite index requirement
   - Recommended in-memory sort for admin tables

**Verification:**
```bash
cd src/prompt-eval-service
dotnet build --no-incremental
# Result: Build succeeded. 0 Warning(s) 0 Error(s)
```

## Learning: When to Use Composite Indexes

**Use composite index (Option B) when:**
- User-scoped queries returning 100s-1000s of docs per user
- High-traffic endpoints where RU cost matters
- Pagination scenarios (need server-side ORDER BY + OFFSET/LIMIT)

**Use in-memory sort (Option A) when:**
- Admin/global tables with <100 total docs
- Low-traffic admin endpoints
- Result set easily fits in memory

**Key insight:** OR-both-casings + ORDER BY = composite index requirement. For small tables, avoid the infra coupling by sorting in-memory.

## References

- Original issue: #125 (Cosmos casing audit + serializer pinning)
- Commit: 243457f (introduced OR-pattern queries)
- This fix commit: (pending)
- Skill: `.squad/skills/cosmos-casing-audit/SKILL.md`
