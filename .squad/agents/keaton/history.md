# Keaton — History

## Learnings

### 2026-05-14 — Issue #132 investigation (Cosmos vs Redis hydration drift)

- **Dual-store architecture is the root issue:** Cosmos is write-once at tx creation; Redis is write-once at AI scoring. Nothing reconciles them. The transaction-service GET path reads only Cosmos, so AI results are invisible to the standard API.
- **scored-tx key indirection:** The `scored-tx:{uuid}` keys use a random UUID, not the original transaction ID. The `transactionId` is a field inside the JSON payload. This means you can't do a direct MGET by tx ID without a secondary index. This was a design choice in anomaly_service.py that makes the BFF join harder than it needs to be.
- **Admin-only gating in Transactions.tsx:** The UI overlay that reads `/admin/transactions` is gated behind `isAdmin`. This means regular users NEVER see scored data, even though the merge logic exists. This was likely an oversight — the endpoint is admin-only on the ai-service side too.
- **Replay endpoint is functional:** `POST /api/admin/replay-events` in transaction-service re-publishes all Cosmos tx to the Redis Stream. This is the backfill mechanism — it causes ai-service to re-score. Already tested in #123.
- **Transaction model has no riskScore:** The Cosmos `Transaction` model (`Models/Transaction.cs`) has `Category` but no `riskScore` at all. The UI `Transaction` interface expects `riskScore?: number` but it's always null from Cosmos.
- **StackExchange.Redis already in transaction-service:** The service uses Redis for event publishing via `IEventPublisher`. The connection/DI is already wired. Adding a read path should reuse this.

---

**2026-05-14 16:57 Scribe:** Heads-up: #141 filed — Foundry Managed VNet migration plan from Danny. See decisions.md for context.

---

### 2026-05-14 — Eval timeout fix (Foundry long-poll HttpClient issue)

- **Root cause:** `EvaluationService.cs:83` used `_httpClientFactory.CreateClient()` with NO name parameter, which creates an HttpClient with the .NET default timeout of exactly 100 seconds. This client POSTs to ai-service's `/api/admin/evaluate`, which synchronously waits for Foundry's `evals.evaluate()` call—these can take 3-5+ minutes.
- **The symptom signature:** The error message "The request was canceled due to the configured HttpClient.Timeout of 100 seconds elapsing" is the canonical .NET 5+ `HttpClient` TaskCanceledException message. That exact phrasing (with "100 seconds") is a dead giveaway for the default timeout.
- **Named vs unnamed HttpClient:** `Program.cs:78-83` registered a named "AiService" client with 30s timeout, but `ExecuteFoundryEvaluationAsync` didn't use it. Meanwhile, `FetchTransactionsAsync:221` DID use the named client for quick transaction fetches. The eval call was the only place using an unnamed/default client.
- **Fix pattern:** Added a second named client "AiServiceEval" with `Timeout = TimeSpan.FromMinutes(10)` (600s) matching ai-service's Stainless `x-stainless-read-timeout: 600` for Foundry SDK calls. Updated `ExecuteFoundryEvaluationAsync` to use `CreateClient("AiServiceEval")` instead of `CreateClient()`.
- **Where else this could bite us:** Any .NET service calling a long-running endpoint should use named HttpClients with explicit timeouts. Grep for `CreateClient()` with no args in any service that talks to ai-service, account-opening-service, or any Python/FastAPI service doing AI work. Default 100s timeout is too short for Foundry/OpenAI operations.
- **Files changed:**
  - `src/prompt-eval-service/Program.cs:85-92` — added `AddHttpClient("AiServiceEval", ...)` with 10min timeout
  - `src/prompt-eval-service/Services/EvaluationService.cs:84` — changed `CreateClient()` → `CreateClient("AiServiceEval")`

---

**2026-05-14 Scribe note:** Companion pattern for long-running operations: When handling `agent_framework.EvalResults` objects in the evaluation response, use `.total` (not `len()`), `.passed`, `.failed` properties. The SDK doesn't implement `__len__()`. See decisions.md "EvalResults Access Pattern — Use `.total`, Not `len()`" for details and impact on ai-service consumers.
