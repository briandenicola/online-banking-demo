---
name: "dotnet-package-upgrade-triage"
description: "How to diagnose and fix .NET package major-version upgrade breaks from Dependabot"
domain: "backend, dotnet, dependencies"
confidence: "high"
source: "earned (2026-05-14, Microsoft.OpenApi 2.x migration)"
---

## Context

When Dependabot upgrades .NET packages (especially Swashbuckle, ASP.NET Core, Azure SDKs), major version bumps often include breaking changes:
- Namespace consolidation or reorganization
- API signature changes (new required parameters, removed properties)
- Helper types replacing manual patterns
- Transitive dependency upgrades with their own breaking changes

This skill provides a systematic triage process to isolate, understand, and fix these breaks efficiently.

## Patterns

### 1. Isolate the Specific Break

When build fails after Dependabot PR merge:
- **Read the error carefully.** CS0234 (namespace doesn't exist) vs CS0117 (member doesn't exist) vs CS7036 (missing parameter) indicate different classes of breaks.
- **Identify the package.** Check `Directory.Packages.props` (central package management) or `*.csproj` for version changes.
- **Trace transitive deps:** Use `dotnet nuget why <project> <package>` to understand dependency chains. A Swashbuckle upgrade may pull in Microsoft.OpenApi 2.x.

### 2. Create Throwaway Test Project

Before bulk-editing production code:
```bash
cd /tmp && mkdir test_pkg && cd test_pkg
cat > test.csproj << 'EOF'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net9.0</TargetFramework>
    <OutputType>Exe</OutputType>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Swashbuckle.AspNetCore" Version="10.1.7" />
  </ItemGroup>
</Project>
EOF
```

Try the old pattern first to confirm it fails. Then iterate on new patterns until build succeeds.

### 3. Find Official Migration Guidance

**Check in order:**
1. **Package release notes** — GitHub releases page for the package
2. **Migration guide** — Look for `docs/migration` or `MIGRATION.md` in repo
3. **Source code examples** — Check `test/` or `samples/` directories in the package's GitHub repo
4. **Web search** — Use exact package name + version + "breaking changes" or "migration"

**Example:**
```bash
git clone --depth 1 --branch v10.1.7 https://github.com/domaindrivendev/Swashbuckle.AspNetCore.git
grep -r "AddSecurityDefinition" test/ --include="*.cs" -A 10
```

Look for how the **official tests** use the new API.

### 4. Verify New Pattern with Test Build

In your throwaway project, test the complete pattern:
```csharp
using Microsoft.OpenApi;  // Changed from Microsoft.OpenApi.Models

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "Test" });
    c.AddSecurityRequirement(doc => new OpenApiSecurityRequirement
    {
        { new OpenApiSecuritySchemeReference("Bearer", doc), [] }
    });
});
```

Run `dotnet build`. If it succeeds, you've validated the fix.

### 5. Grep All Usages Before Bulk Edit

Before applying fixes to production code:
```bash
cd /path/to/repo
grep -r "Microsoft\.OpenApi\.Models" src/ --include="*.cs"
```

This shows:
- How many files are affected
- Whether the pattern is consistent or has variations
- Any edge cases (e.g., some services using fully-qualified names)

### 6. Apply Fixes Consistently

Use the `edit` tool to make surgical changes:
- Change `using` statements first
- Change type references next
- Update API calls last (AddSecurityRequirement, etc.)
- Keep changes minimal — only fix what's broken

### 7. Build One Service First

Pick one affected service and build it:
```bash
cd src/user-service && dotnet build -c Release 2>&1 | tail -30
```

This catches:
- If your fix worked for the namespace issue
- Other build errors you didn't anticipate
- Package restore issues (separate from code fixes)

### 8. Document for Future Reference

Update agent history with:
- The breaking change discovered
- The fix pattern (before/after code)
- Verification method used
- Files modified

Write a decision document explaining:
- What changed (root cause)
- Why this approach was chosen
- How to handle similar breaks in future

## Examples

### Microsoft.OpenApi 1.x → 2.x (Swashbuckle 6.x → 10.x)

**Break:** `Microsoft.OpenApi.Models` namespace removed.

**Fix:**
```csharp
// BEFORE (Microsoft.OpenApi 1.x)
using Microsoft.OpenApi.Models;
c.AddSecurityRequirement(new OpenApiSecurityRequirement
{
    {
        new OpenApiSecurityScheme 
        { 
            Reference = new OpenApiReference 
            { 
                Id = "Bearer", 
                Type = ReferenceType.SecurityScheme 
            } 
        },
        Array.Empty<string>()
    }
});

// AFTER (Microsoft.OpenApi 2.x)
using Microsoft.OpenApi;
c.AddSecurityRequirement(doc => new OpenApiSecurityRequirement
{
    {
        new OpenApiSecuritySchemeReference("Bearer", doc),
        []
    }
});
```

**Key Changes:**
1. Namespace: `Microsoft.OpenApi.Models.*` → `Microsoft.OpenApi.*`
2. Helper type: `OpenApiSecuritySchemeReference` replaces manual `OpenApiSecurityScheme { Reference = ... }`
3. Lambda: `AddSecurityRequirement` now requires `Func<OpenApiDocument, ...>` to pass document context
4. Collection type: Dictionary value changed from `string[]` to `List<string>` (use `[]` collection expression)

## Anti-Patterns

❌ **Don't guess the fix** — Create a test project to validate before bulk editing production code.

❌ **Don't fix blindly** — If the build error is a namespace issue but there are also NuGet restore errors, the code fix may be correct even if the build still fails. Separate concerns.

❌ **Don't ignore other errors** — After fixing the primary issue, note any secondary build errors for follow-up (but don't fix them in the same pass if they're unrelated).

❌ **Don't pin back without trying forward** — Reverting to an older package version should be a last resort. Most breaking changes have straightforward migration paths.

❌ **Don't trust AI-generated migration guides** — Web search results may be outdated or wrong. Always verify with official source code or test projects.

## Troubleshooting

**"Package version not found" during restore:**
- The version Dependabot specified may not exist yet (preview versions, future releases)
- Check NuGet.org for actual latest stable version
- This is a **package version issue**, not a code fix issue — defer to separate triage pass

**"Type still not found after namespace change":**
- Verify the type exists in the new version: `strings ~/.nuget/packages/<package>/<version>/lib/<tfm>/<assembly>.dll | grep <TypeName>`
- The type may have been renamed or removed entirely — check migration guide

**"Lambda required but wasn't before":**
- API may now need runtime context (like `OpenApiDocument` for references)
- Look at official examples for the new signature

**"Build succeeds in test project but fails in production":**
- Central package management (`Directory.Packages.props`) may pin a transitive dep to an incompatible version
- Run `dotnet nuget why <project> <package>` to trace the conflict
