# Decision: OpenAPI Spec Generation for .NET Services

**Status:** IMPLEMENTED  
**Date:** 2026-05-13  
**Author:** Basher  
**Issue:** #109 — Add OpenAPI/Swagger API documentation  
**Branch:** squad/p2-wave-3  
**Commit:** ff310d0

## Context

Architecture documentation referenced Swagger endpoints, but no OpenAPI specs were committed to the repository. All .NET services had Swagger enabled at runtime, but lacked:
1. Proper API titles and security definitions in Swagger config
2. Committed OpenAPI specs for developer reference and API client generation
3. A repeatable process for regenerating specs after API changes

## Decision

### Swagger Configuration

All .NET services now use a standardized Swashbuckle configuration:

```csharp
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "Service Name", Version = "v1" });
    c.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Description = "JWT Authorization header using the Bearer scheme",
        Name = "Authorization",
        In = ParameterLocation.Header,
        Type = SecuritySchemeType.Http,
        Scheme = "bearer"
    });
    c.AddSecurityRequirement(new OpenApiSecurityRequirement
    {
        {
            new OpenApiSecurityScheme { Reference = new OpenApiReference { Id = "Bearer", Type = ReferenceType.SecurityScheme } },
            Array.Empty<string>()
        }
    });
});
```

### Spec Generation Process

**Tool:** `Swashbuckle.AspNetCore.Cli` 6.9.0

**Command:**
```bash
swagger tofile --output <path> <service.dll> v1
```

**Environment Requirements:**
- `UseInMemoryDatabase=true` — avoids Cosmos/Redis dependencies
- `Jwt__Key`, `Jwt__Issuer`, `Jwt__Audience` — minimal JWT config
- `CosmosDb__ConnectionString` — fake connection string for services that require it

**Special Cases:**
- `prompt-eval-service` requires temporary commenting of startup initialization code (lines 108-113 in Program.cs) because it attempts to create Cosmos containers during startup before Swagger can be extracted.

### Committed Specs

All specs committed to `docs/api/`:
- `user-service-openapi.json`
- `account-service-openapi.json`
- `transaction-service-openapi.json`
- `transfer-service-openapi.json`
- `prompt-eval-service-openapi.json`

### Regeneration Script

Created `scripts/generate-openapi-specs.sh` to:
1. Install `Swashbuckle.AspNetCore.Cli` if not present
2. Build each .NET service in isolated output directory
3. Extract OpenAPI spec using `swagger tofile`
4. Handle prompt-eval-service's startup initialization automatically
5. Write specs to `docs/api/{service-name}-openapi.json`

Usage:
```bash
./scripts/generate-openapi-specs.sh
```

## Rationale

### Why commit OpenAPI specs?

1. **Developer reference** — Easier to review API contracts without running services
2. **API client generation** — Specs can be used to generate TypeScript, Python, or other clients
3. **Documentation** — Can be viewed in Swagger UI, Redoc, or other OpenAPI viewers
4. **Version control** — API changes are tracked in git

### Why Swashbuckle CLI instead of runtime extraction?

- **Pros:** No need to run services or configure infrastructure
- **Cons:** Requires service to be buildable and initialize successfully
- **Tradeoff:** Acceptable for our use case; services are lightweight enough to start with minimal config

### Why not add CI generation?

Deferred as follow-up. Regeneration is currently manual via script. CI generation could:
- Run on PR to detect API changes
- Auto-commit updated specs
- Validate no breaking changes

However, this adds complexity and wasn't required for initial implementation.

## Coordination with Turk

**Python/FastAPI services** (ai-service, budget-service, chatbot-service, account-opening-service) are handled by Turk in parallel. FastAPI generates OpenAPI specs automatically at runtime, so the approach differs:
- FastAPI: Fetch spec from `/openapi.json` endpoint
- .NET: Build and extract using Swashbuckle CLI

Both approaches commit specs to `docs/api/` for consistency.

## Open Questions

1. **CI generation** — Should we auto-generate specs in CI and fail PR if specs are out of date?
2. **Breaking change detection** — Should we add tooling to detect breaking API changes between commits?
3. **Spec validation** — Should we validate specs against OpenAPI 3.0 schema in CI?

## References

- Issue: #109
- Commit: ff310d0
- Script: `scripts/generate-openapi-specs.sh`
- Docs: `docs/README.md` (API Documentation section)
