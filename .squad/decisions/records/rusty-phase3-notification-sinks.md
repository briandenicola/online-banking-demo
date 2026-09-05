# Decision — Phase 3 out-of-band notification sinks

**Author:** Rusty (platform/infra) · **Date:** 2026-09-04 · **Epic:** #332 Phase 3 §5.6

## What shipped

`INotificationSink` in `authority-service` with config-selected implementations
(`src/authority-service/Services/NotificationSink.cs`):

- **`redis-stream`** (default, working local impl) — publishes the notification envelope onto a
  Redis Stream, reusing the audit connection multiplexer.
- **`webhook`** — POSTs the envelope to a configured URL (Teams/Slack in a live demo). Inert,
  and says so once at startup, when no URL is configured.
- **`email`** — logging stub so the interface exists and a real transport is not a refactor later.
- **`composite`** — fans out to every configured sink and isolates their failures from each other.
- **`null`** — used when notifications are disabled or no Redis exists; records for tests.

Selection and every endpoint are configuration (`Notifications:*`, env `Notifications__*`); there
is **no hardcoded URL, stream name or address** in the code. An unconfigured optional sink is
inert, never defaulted to a guessed endpoint.

Fired fire-and-forget from `ApprovalService.SignAsync` when a signature lands but the card stays
pending awaiting a co-signature (the §1.3 "Awaiting supervisor co-signature" beat). It **never
gates state** (I-1/I-6): the firing is wrapped, every sink swallows its own transport failure,
and a total notification failure is logged and ignored — the approval is the system of record.

## Ruling 1 — the redis-stream sink publishes to a DEDICATED stream, not `banking-events`

Epic §5.6 says the redis-stream sink publishes "to the existing banking events stream." I default
it instead to a dedicated key **`copilot-notifications`** (configurable via
`Notifications:RedisStreamKey`; set it to `banking-events` to merge them).

Why deviate from the literal wording:

1. `banking-events` is the **audited** vocabulary. `RedisAuditPublisher` enforces a closed set of
   eleven PascalCase event types and throws on anything else; the Go `event-processor` switches on
   those exact names. A notification is neither — it is transient, fire-and-forget, and explicitly
   "never gates state." Putting it on the audit bus either forces it into that closed enum (making
   a UI ping an audit event) or lands it in the consumer's `default:` branch as a
   published-but-unaudited unknown — the precise Phase 1 gap I flagged for
   `InsufficientFundsAttempt` / `UserRegistered`.
2. A notification failure must never look like a missing audit record. Separate streams keep
   "did we ping a supervisor" and "is the audit trail complete" as two independent questions.

This is the same "read the consumer, not the doc" basis on which `RoleGranted` was shipped
PascalCase over the epic's dotted form. The consumer side (surfacing the ping to a supervisor's
SSE session) is Turk's harness work; my contract is the envelope shape + the stream key.

## Ruling 2 — the payload names the KIND of signer, never WHO

`SupervisorNotification` / its envelope carry `awaitingSeniority`, `pendingSlotOrdinal`,
`requiredRung` — and deliberately **no** `cosignerId` / `assignee` / `reviewerId`. A test asserts
the envelope contains no such field. Naming a co-signer is exactly the `cosignerId` pointer that
epic §5.2.2 ruled out on security grounds (a banker picking their own reviewer). The notification
is a property of the work, not of a person, all the way onto the wire.

## Ruling 3 — authority-service was missing its Redis wiring in the kustomize base (fixed)

While wiring the sink I found `deploy/kustomize/base/authority-service.yaml` set **no**
`Redis__ConnectionString` at all. In-cluster the service therefore fell back to
`NullAuditPublisher` — **audit events (§5.7) were silently not published in AKS**, and the new
redis-stream notification sink would have been inert for the same reason. Both are no-ops that
pass every probe and look healthy. Added `Redis__ConnectionString` from the existing
`banking-secrets/redis-connection-string` (the same secret `event-processor` consumes), which
fixes the audit gap and enables the notification sink together. This is Phase 1/2 deployment debt
in my lane — "it validated" and "it published" were different claims again (Phase 2 lesson 19).

## Verification (PROVED vs BELIEVED)

- **PROVED:** `authority-service` builds; 207/207 authority tests pass including 8 new
  `NotificationSinkTests` (co-signer-free envelope, composite failure isolation, webhook inert
  without URL, sink-list parsing, non-audit default stream). `docker compose config`,
  `kubectl kustomize`, `terraform validate/fmt` all clean; the rendered ConfigMap and authority
  Deployment carry the new keys.
- **BELIEVED / UNPROVEN:** no Docker daemon and no live Redis/Azure here, so an actual
  `StreamAddAsync` to Redis and an end-to-end "supervisor's second browser receives the ping" were
  not exercised. The firing point and the transport are unit-tested with fakes only.
