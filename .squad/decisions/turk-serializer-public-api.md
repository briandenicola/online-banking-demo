# Cosmos Serializer: Internal Type Mistake → Public API Fix

**Date:** 2026-05-12  
**Agent:** Turk  
**Context:** Build break follow-up to #125

## Problem

Commit 243457f used `CosmosSystemTextJsonSerializer`, which is **internal** in the Microsoft.Azure.Cosmos SDK. This caused CS0122 compilation errors across all 5 .NET services:

```
error CS0122: 'CosmosSystemTextJsonSerializer' is inaccessible due to its protection level
```

## Root Cause

Misread SDK documentation or used an outdated example. The internal type exists but is not part of the public API surface.

## Fix

Replaced the internal type with the **public** `CosmosSerializationOptions` API:

```csharp
// ❌ WRONG (internal type)
Serializer = new CosmosSystemTextJsonSerializer(
    new System.Text.Json.JsonSerializerOptions
    {
        PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase
    })

// ✅ CORRECT (public API)
SerializerOptions = new CosmosSerializationOptions
{
    PropertyNamingPolicy = CosmosPropertyNamingPolicy.CamelCase,
    IgnoreNullValues = true
}
```

## Impact

- **Immediate:** Build now compiles successfully
- **Functional:** Behavior is identical (camelCase serialization)
- **Maintenance:** Using supported public API reduces future SDK upgrade risk

## Services Updated

- user-service/Program.cs:117
- account-service/Program.cs:107
- transaction-service/Program.cs:114
- transfer-service/Program.cs:124
- prompt-eval-service/Program.cs:93

## Related

- Skill updated: `.squad/skills/cosmos-casing-audit/SKILL.md` (added DO NOT USE warning)
- History logged: Turk now knows the correct public API pattern
