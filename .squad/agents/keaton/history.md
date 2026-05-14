# Keaton — History

## Learnings

### 2026-05-14 — Issue #132 investigation (Cosmos vs Redis hydration drift)

- **Dual-store architecture is the root issue:** Cosmos is write-once at tx creation; Redis is write-once at AI scoring. Nothing reconciles them. The transaction-service GET path reads only Cosmos, so AI results are invisible to the standard API.
- **scored-tx key indirection:** The `scored-tx:{uuid}` keys use a random UUID, not the original transaction ID. The `transactionId` is a field inside the JSON payload. This means you can't do a direct MGET by tx ID without a secondary index. This was a design choice in anomaly_service.py that makes the BFF join harder than it needs to be.
- **Admin-only gating in Transactions.tsx:** The UI overlay that reads `/admin/transactions` is gated behind `isAdmin`. This means regular users NEVER see scored data, even though the merge logic exists. This was likely an oversight — the endpoint is admin-only on the ai-service side too.
- **Replay endpoint is functional:** `POST /api/admin/replay-events` in transaction-service re-publishes all Cosmos tx to the Redis Stream. This is the backfill mechanism — it causes ai-service to re-score. Already tested in #123.
- **Transaction model has no riskScore:** The Cosmos `Transaction` model (`Models/Transaction.cs`) has `Category` but no `riskScore` at all. The UI `Transaction` interface expects `riskScore?: number` but it's always null from Cosmos.
- **StackExchange.Redis already in transaction-service:** The service uses Redis for event publishing via `IEventPublisher`. The connection/DI is already wired. Adding a read path should reuse this.
