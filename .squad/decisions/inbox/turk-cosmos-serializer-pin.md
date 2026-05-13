# Cosmos DB Serializer Convention (camelCase)

**Issue:** #125  
**Author:** Turk (Backend Dev)  
**Date:** 2026-05-13  
**Status:** Active (applied to all .NET services)

## Decision

All `CosmosClient` registrations in .NET services **MUST** pin an explicit camelCase serializer using `CosmosSystemTextJsonSerializer`. This prevents future serializer drift between writes and ensures consistency with the API surface (which already returns camelCase JSON).

## Implementation

In each service's `Program.cs`, configure the `CosmosClient` registration:

```csharp
builder.Services.AddSingleton<CosmosClient>(sp =>
{
    var configuration = sp.GetRequiredService<IConfiguration>();
    var endpoint = configuration["CosmosDb:Endpoint"];
    
    var clientOptions = new CosmosClientOptions
    {
        Serializer = new CosmosSystemTextJsonSerializer(
            new System.Text.Json.JsonSerializerOptions
            {
                PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase
            })
    };
    
    if (!string.IsNullOrEmpty(endpoint))
    {
        return new CosmosClient(endpoint, new DefaultAzureCredential(), clientOptions);
    }
    return new CosmosClient(configuration["CosmosDb:ConnectionString"], clientOptions);
});
```

## Why camelCase?

1. **API consistency**: All ASP.NET Core controllers already return camelCase JSON (default `System.Text.Json` behavior)
2. **JavaScript convention**: Frontend expects camelCase (React/TS standard)
3. **Cosmos SDK v3 drift**: Default Newtonsoft serializer was producing PascalCase, but some writes landed as camelCase (likely from a SDK update or manual writes). Pinning camelCase matches the majority of recent docs and the API surface.

## Affected Services

Applied to:
- `account-service/Program.cs`
- `transaction-service/Program.cs`
- `user-service/Program.cs`
- `transfer-service/Program.cs`
- `prompt-eval-service/Program.cs`

## Future Services

**Any new .NET service** that writes to Cosmos MUST use this pattern. Do NOT use default `CosmosClient()` — always pin the serializer.

## Verification

After applying:
1. Deploy the service
2. Create a new document via the API
3. Query the document directly in Cosmos Data Explorer
4. Confirm fields are camelCase: `userId`, `accountId`, `createdAt`, etc.

## References

- Issue: #125
- Migration plan: `.squad/decisions/inbox/turk-125-cosmos-migration-plan.md`
- Microsoft docs: [Cosmos DB Custom Serialization](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/how-to-custom-serialization)
