---
skill: dotnet-foundry-httpclient-timeout
category: dotnet
tags: [httpclient, foundry, timeout, ai-service]
created: 2026-05-14
last_verified: 2026-05-14
---

# Skill: Configure HttpClient Timeouts for Foundry/AI Operations

## Problem Pattern

.NET services calling long-running AI/Foundry endpoints timeout with:
```
The request was canceled due to the configured HttpClient.Timeout of 100 seconds elapsing.
```

**Symptom:** Client-side cancellation while server-side work continues successfully. The "100 seconds" in the error message is the .NET default `HttpClient.Timeout`.

## Root Cause

Using `_httpClientFactory.CreateClient()` with no name parameter creates an HttpClient with .NET's default 100-second timeout. Foundry evaluation runs (and other AI operations) can take 3-10 minutes.

## Solution Pattern

### 1. Register named HttpClients in Program.cs/Startup.cs

```csharp
using Microsoft.Extensions.DependencyInjection;

// Short timeout for quick CRUD operations
builder.Services.AddHttpClient("AiService", client =>
{
    var aiServiceUrl = builder.Configuration["AI_SERVICE_URL"] ?? "http://ai-service:80";
    client.BaseAddress = new Uri(aiServiceUrl);
    client.Timeout = TimeSpan.FromSeconds(30);  // Quick ops: 30s
});

// Long timeout for Foundry evaluation calls
builder.Services.AddHttpClient("AiServiceEval", client =>
{
    var aiServiceUrl = builder.Configuration["AI_SERVICE_URL"] ?? "http://ai-service:80";
    client.BaseAddress = new Uri(aiServiceUrl);
    client.Timeout = TimeSpan.FromMinutes(10);  // AI/Foundry ops: 10min (600s)
});
```

**Rationale for 10 minutes:**
- Matches ai-service's `x-stainless-read-timeout: 600` for Foundry SDK
- Allows margin for multi-item operations (e.g., 10 transactions × 30s/tx = 5min baseline)
- Prevents premature cancellation while allowing eventual timeout for real hangs

### 2. Use the appropriate named client in services

```csharp
using System.Net.Http;
using System.Net.Http.Headers;

public class EvaluationService
{
    private readonly IHttpClientFactory _httpClientFactory;
    
    public EvaluationService(IHttpClientFactory httpClientFactory)
    {
        _httpClientFactory = httpClientFactory;
    }
    
    // ❌ NEVER DO THIS (defaults to 100s timeout)
    // var client = _httpClientFactory.CreateClient();
    
    // ✅ For quick operations (transaction fetch, health checks)
    public async Task<List<Transaction>> FetchTransactionsAsync(string bearerToken)
    {
        var client = _httpClientFactory.CreateClient("AiService");
        client.DefaultRequestHeaders.Authorization = 
            new AuthenticationHeaderValue("Bearer", bearerToken);
        var response = await client.GetAsync("/api/admin/transactions");
        // ...
    }
    
    // ✅ For long-running AI/Foundry operations (evaluations, document analysis)
    public async Task ExecuteEvaluationAsync(string bearerToken)
    {
        var client = _httpClientFactory.CreateClient("AiServiceEval");
        client.DefaultRequestHeaders.Authorization = 
            new AuthenticationHeaderValue("Bearer", bearerToken);
        var response = await client.PostAsync("/api/admin/evaluate", content);
        // ...
    }
}
```

### 3. Validation check

Before merging any .NET service changes, grep for unnamed CreateClient calls:

```bash
# Should return ZERO matches in production code
rg 'CreateClient\(\)' src/*/Services/ src/*/Controllers/

# If matches found, verify they're NOT calling AI/Foundry endpoints
# If they ARE, switch to a named client with appropriate timeout
```

## When to Use Each Timeout

| Operation Type | Named Client | Timeout | Examples |
|---|---|---|---|
| Quick CRUD | `"AiService"` | 30s | Transaction fetch, health checks, user lookup |
| AI/Foundry ops | `"AiServiceEval"` | 10min | Foundry evals, document analysis, multi-item scoring |
| Foundry polling loops | `"AiServiceEval"` | 10min overall + per-call timeout | Long-poll with iteration timeout |

## Special Case: Polling Loops

If implementing a polling loop (e.g., checking eval status), prefer:
- **Per-HTTP-call timeout:** 30s (via named client)
- **Overall deadline:** 10 minutes via `CancellationToken` linked to a timer

```csharp
using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(10));
var client = _httpClientFactory.CreateClient("AiService");  // 30s per-call timeout

while (!cts.Token.IsCancellationRequested)
{
    var response = await client.GetAsync($"/api/evals/{evalId}/status", cts.Token);
    if (response.IsSuccessStatusCode)
    {
        var status = await response.Content.ReadFromJsonAsync<EvalStatus>();
        if (status.IsComplete) return status;
    }
    await Task.Delay(5000, cts.Token);  // Poll every 5s
}
```

**Do NOT use `HttpClient.Timeout` as the overall deadline** — it applies per-call, not to the entire loop.

## Diagnostic: Detecting This Issue

**Log signatures:**
- .NET service logs: `TaskCanceledException: The request was canceled due to the configured HttpClient.Timeout of 100 seconds elapsing`
- Downstream service (ai-service) logs: Successful 200 OK responses well past the 100s mark
- Foundry/backend logs: Operation still `in_progress` and healthy

**Quick check:**
```bash
# Search for CreateClient() with no args
rg 'CreateClient\(\)' src/

# Search for default timeout errors in logs
rg 'HttpClient.Timeout of 100 seconds' logs/
```

## Testing the Fix

After implementing:
1. Trigger a long-running eval (10+ transactions)
2. Monitor client-side logs — should NOT see TaskCanceledException before ~10min
3. Monitor server-side logs — should see request complete successfully
4. Verify UI shows completed eval results, not timeout error

## References

- Example implementation: `src/prompt-eval-service/Program.cs:85-92`
- Example usage: `src/prompt-eval-service/Services/EvaluationService.cs:84`
- ai-service Foundry timeout: `src/ai-service/app/services/foundry_client.py` (Stainless SDK `timeout=600`)
- .NET HttpClient docs: https://learn.microsoft.com/en-us/dotnet/api/system.net.http.httpclient.timeout

## Related Skills

- `foundry-managed-vnet` — Foundry connectivity and private endpoint setup
- `dotnet-httpclient-auth` — Passing bearer tokens via HttpClient headers (if exists)
