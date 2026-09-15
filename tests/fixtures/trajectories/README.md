# Banker Copilot trajectory fixtures

These five committed fixtures are real responses captured from the FastAPI banker-copilot service by
`_capture/capture.py` and `TestClient`. Each scenario directory contains the untouched service
response `trace.json` and a hand-reviewed `expected.json` contract. Do not hand-fabricate or edit a
`trace.json`; add or change a scenario in the capture script and rerun the capture instead.

Run the verifier from the repository root:

```bash
python tests/fixtures/trajectories/verify.py
```

## Exact `expected.json` schema

The object has exactly these keys:

```json
{
  "scenario": "scenario-directory-name",
  "expectedToolSequence": ["tool_name_in_completed-order"],
  "expectedEvidenceSet": ["required-evidence-tool-id"],
  "expectedEscalationRung": "L1",
  "groundTruth": {
    "recommendation": "approve",
    "rationale": "One or two policy-semantic sentences."
  }
}
```

`expectedToolSequence` is the ordered list of completed tool names, including the final
`propose_action`. `expectedEvidenceSet` is the set of required evidence tool IDs, and must be fully
satisfied in the final `evidence_progress` frame. `expectedEscalationRung` is `L1` or `L2`.
`groundTruth.recommendation` is `approve`, `deny`, or `escalate`; the verifier requires L1 fixtures
to use `approve` and L2 fixtures to use `escalate` for this corpus. The rationale must explain the
policy outcome in one or two sentences.

The verifier imports `app.events.envelope` and also checks the full trace response shape, required
payload fields for every emitted event kind, known kinds, one-run/session identity, gapless and
monotonic `seq`/server `ts`, per-call tool `traceId`/`spanId`, and `model.call` telemetry. It adds
scenario assertions for L1/L2 behavior, bounded prompt-injection resistance, and supervisor fanout.

## Addition workflow and scope

1. Add the scenario to `_capture/capture.py` and its deterministic downstream doubles.
2. Capture through `TestClient`; commit the returned `trace.json` unchanged.
3. Add the exact six-key contract above, then run `verify.py`.
4. Run the full banker-copilot pytest suite before committing.

This corpus records the Banker Copilot boundary: issue **#140 is `not_planned`**, while **#364 is
the escalation-ladder** and independent-supervisor scope represented by the L2 fixtures. Coverage for
`chatbot-service` and `ai-service` is deferred; their distinct contracts must not be represented by a
copied banker-copilot trace.
