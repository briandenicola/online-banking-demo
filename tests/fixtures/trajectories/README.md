# Banker Copilot golden trajectories

These are static, committed traces from the **banker-copilot-service** only. Each directory has
`trace.json` (the service's `GET /api/copilot/runs/{runId}/trace` response) and `expected.json`
(the scenario labels and outcome contract). They are not synthetic examples: `_capture/capture.py`
drives the real FastAPI application with `TestClient` in-process, a deterministic assessor, and
in-process downstream doubles, then writes the returned persisted envelopes.

Run the invariant check with:

```bash
python tests/fixtures/trajectories/verify.py
```

## Schema and invariants

`trace.json` preserves the service response and its envelope frames: top-level `runId`,
`frameCount`, `traceDegraded`, and `frames`. Every frame carries `id`, `seq`, `runId`,
`sessionId`, `kind`, `ts`, and object `payload`. Verification requires gapless per-run `seq`,
monotonic server timestamps, known event kinds, stable tool `traceId`, non-empty tool `spanId`,
and the current `model.call` deployment/latency/token fields when a model-call frame exists.
`expected.json` has exactly `scenario`, `actionId`, `requiredRung`, `terminalStatus`, and non-empty
`labels`.

To add a trajectory, add a scenario to `_capture/capture.py`, capture it through `TestClient`,
inspect the resulting event kinds, commit both generated JSON files, and run `verify.py`. Do not
hand-edit or hand-fabricate `trace.json`; regenerate it from the service. Keep volatile IDs and
server timestamps as captured so the fixture remains evidence of the actual envelope.

## Scope rationale

This corpus is deliberately banker-copilot-only. Issue **#140** was closed `not planned`, while
**#364** established the escalation-ladder and independent-supervisor trace work that these
fixtures exercise. Coverage for `chatbot-service` and `ai-service` is deferred: those services
have different contracts and must not be represented by a copied banker-copilot trace.

The five scenarios cover an L1 flagged-transaction resolution, an L2 escalation, account-opening
review, adversarial/prompt-injection resistance, and supervisor fanout with multiple reads and a
second opinion.
