---
date: 2026-09-15
author: Copilot (Orchestrator)
status: decided
component: prompt-eval-service, banker-copilot-service
issue: 376
---

# Custom trajectory scorer, not `azure-ai-evaluation`

#376 asked for a spike before choosing between `azure-ai-evaluation`'s agent-trajectory
evaluators and a custom scorer built directly against the `CopilotEventEnvelope` schema. Decided
directly instead of spiking, because the shape of the required scorers already answers the
question without needing a throwaway prototype.

## Why custom wins here

Every scorer #376 lists is a structural read or diff against fields the trace already carries,
not a semantic-quality judgment an LLM-as-judge evaluator is built for:

- **Escalation correctness** — direct compare of the run's terminal rung against the fixture's
  `expectedEscalationRung`. No judgment involved.
- **Evidence completeness** — a set-equality check between `evidence_progress`'s
  `requiredEvidenceToolIds`/`satisfiedRequiredEvidenceToolIds` (already split apart by #366) and
  the fixture's `expectedEvidenceSet`.
- **Tool selection** — ordered-sequence diff against `expectedToolSequence`, cross-checked against
  the manifest's zero-write enforcement (a structural, not semantic, check).
- **Supervisor independence** — reading whether `fanout.py`'s second-opinion frames re-derive
  independently or literally repeat the primary's `propose_action` payload.
- **Fan-out efficiency** — arithmetic over the `model.call` token telemetry #374 added.
- **Injection resistance** — same tool-sequence/evidence-set diff as above, applied to the
  adversarial fixture; still structural.

Only **recommendation quality** (comparing the final rationale prose to a human ground truth) is
plausibly better served by an LLM judge, and `azure-ai-evaluation` is not required to get one —
that single scorer can call the same model client the rest of the service already uses.

Bringing in `azure-ai-evaluation` for this would mean building an adapter from
`CopilotEventEnvelope` into whatever shape its trajectory evaluators expect, maintaining a new
dependency, and still writing every one of the domain-specific scorers above ourselves, because
`azure-ai-evaluation`'s built-in evaluators do not know this service's escalation ladder, evidence
model, or zero-write manifest. The adapter buys nothing for six of the seven scorers.

## What this means for #376

The scoring harness is a plain Python module inside (or callable by) `prompt-eval-service`,
operating directly on `trace.json` shape (the same shape #375's fixtures already use) and
producing per-run scores plus the escalation confusion matrix. No new dependency added.

## Revisit if

A future scorer is added that is genuinely a semantic-quality judgment at scale (e.g., grading
free-text rationale against many graders, not one-off comparison) — at that point,
`azure-ai-evaluation`'s LLM-judge evaluators become worth a real spike.
