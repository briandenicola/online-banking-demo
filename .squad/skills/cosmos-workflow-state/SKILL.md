# Skill: Cosmos-backed Workflow State with Per-Stage Idempotency

**When to use:** Any multi-stage backend workflow (KYC pipeline, transaction reconciliation,
multi-step provisioning) that runs across Redis-stream consumers and needs:
- A persistent record of every stage transition (success **and** failure)
- Resume-from-failed-stage without rerunning earlier work
- Safe replay of any single stage (idempotency at Redis, Cosmos, and external-API layers)
- A status read-path the UI can poll cheaply

## Anti-pattern (what to avoid)

Splitting the workflow run into a separate `*-runs` container "for cleanliness" when an
existing per-entity Cosmos doc already holds the form data, audit trail, and per-stage
results. You'll end up doing cross-container reads for every UI poll, double-writing on
every stage, and inviting casing/serialization drift across two repository classes.
**Extend the existing doc** unless you have a hard reason (e.g., different TTL, different
RU class).

## Pattern

### 1. Doc shape — additive fields on the existing entity

```ts
{
  // existing fields stay untouched (id, status, formData, agentResults, auditTrail)

  lastError?: {
    stage: StageName;        // failed stage
    code: string;            // classified error code, NOT raw exception text
    message: string;         // human-safe summary
    retryable: boolean;      // false ⇒ UI hides retry
    occurredAt: string;
    attempt: number;
    correlationId?: string;  // upstream request-id for support tickets
  };
  stageAttempts?: Record<StageName, number>;
  failedStage?: StageName;   // mirror of lastError.stage for query filters
}
```

Keep status enum exhaustive: include both `failed` (recoverable terminal) and an
explicit per-stage in-progress value for every stage (so "currently running stage X" is
truthful in the UI, not inferred from "last completed was X-1").

### 2. Idempotency key shape: `{entityId}:{stage}:{attempt}`

This single key drives three layers of dedup:

| Layer | Mechanism |
|---|---|
| Redis stream | Consumer maintains `processed:{group}:{key}` SET, 24h TTL. Short-circuit `process_one` on hit, `xack`, drop. |
| Cosmos `agentResults` | `add_agent_result` does upsert-by-`idempotencyKey`: replace existing entry if key matches; append otherwise. Re-runs overwrite `failed → completed` cleanly. |
| External API (Foundry, payment provider, etc.) | Use the same key as the agent name / request idempotency-key header. |

`attempt` lives on the doc as `stageAttempts[stage]`. Resubmit increments it **before**
publishing the event ⇒ each manual retry produces a fresh key (genuine retry) but
accidental redelivery with the same key is dropped.

### 3. Failure path is part of the consumer base class — not per-agent

```python
# in AgentConsumer.process_one
try:
    await self.process_event(event_data)
except Exception as exc:
    last_error = self._classify(exc)  # maps exception → (code, retryable)
    self._repository.set_failure(
        application_id=event_data.get(self.ID_FIELD),
        last_error=last_error,
        failed_stage=self.STAGE_NAME,
    )
    await publish_event(self.redis, "stage_failed", {...})
    await self.redis.xack(self.stream_name, self.consumer_group, message_id)
    return  # CRITICAL: ack failures so they don't get redelivered;
            # let the user-driven /resubmit endpoint drive retry
```

Each agent subclass declares `STAGE_NAME` and `_classify(exc)`. `_classify` should
return well-known codes (`"foundry_403"`, `"cus_timeout"`, `"network_error"`,
`"validation_error"`, `"unknown"`) — never raw exception messages, which leak stack
internals to the UI.

### 4. Resubmit endpoint contract

```
POST /api/<entity>/{id}/resubmit
- Requires: status == failed
- Computes: stage = lastError.stage; attempt = ++stageAttempts[stage]
- Atomic-ish: clear lastError, transition status back to stage, bump attempt
- Synthesizes the upstream event (mapping table: stage → trigger event type)
- Publishes with idempotencyKey = "{id}:{stage}:{attempt}"
- Returns 202 with { resumedFromStage, attempt }
```

### 5. UI read-path: cheap dedicated `/status` endpoint

Don't make the UI poll the full entity doc (which carries form data, full audit trail,
all agent reasoning). Add a thin projection endpoint that returns only what the customer
status screen needs: `{ id, status, stages[], lastError, customerOutcome, updatedAt }`.
Polling at 2 s × 60 s = 30 reads × ~5 RU = ~150 RU per workflow — comfortable.

Stop polling on terminal status (success, failure, decline). The UI's terminal-status
list must include the new `failed` value or polling becomes infinite.

### 6. Migration: forward-only

Default the new fields to empty in the Pydantic model. Old docs missing
`stageAttempts`/`lastError` validate cleanly. No backfill job. The first agent to touch
an old doc post-deploy starts behaving correctly. Old `agentResults` entries lacking
idempotency keys co-exist with new keyed entries — upsert-by-key only matches when both
sides have keys.

## Tests to cover

- Replay same Redis message twice → exactly one `agentResults` entry.
- Inject failure mid-workflow → `status == "failed"`, `lastError` populated.
- POST /resubmit on non-failed status → 409.
- POST /resubmit happy path → bumps attempt, transitions status, completes downstream.
- e2e: submit → kill upstream service → status flips → restart upstream → /resubmit → completion.

## Reference implementation

To be created in this repo by Basher per `.squad/decisions/inbox/danny-135-136-unified-plan.md`:
- `src/account-opening-service/app/cosmos_repository.py` — `set_failure`, `clear_failure_and_increment_attempt`, upsert-by-key in `add_agent_result`
- `src/account-opening-service/app/consumer.py` — uniform failure-persist + ack
- `src/account-opening-service/app/routes/api.py` — `POST /resubmit`, `GET /status`

## Companion skills

- `redis-stream-consumer-resilience` — for the `XAUTOCLAIM` reaper that handles
  crashed-pod scenarios this skill doesn't cover.
- `api-projection` — for the read-side `project_<entity>()` helper that derives the
  UI-facing `stages[]` shape from the storage-shape `agentResults[]`.
- `cosmos-casing-audit` — run this skill on any new fields you add to the doc to
  prevent serializer casing drift.
