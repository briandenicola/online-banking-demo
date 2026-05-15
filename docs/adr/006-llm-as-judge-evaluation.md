# ADR-006: LLM-as-Judge for Prompt Evaluations over Foundry's Hosted Evals (raisvc)

**Status**: Accepted
**Date**: 2026-05
**Author**: Brian De Nicola

## Context

The prompt-eval-service (admin UI) lets operators run named evaluators (Coherence, Fluency, Relevance, etc.) against a candidate prompt and a transaction sample, then stores per-evaluator scores in Cosmos DB for A/B comparison.

The original implementation called Azure AI Foundry's hosted evaluation API (`FoundryEvals.evaluate()` / `raisvc`) from `ai-service` `POST /api/admin/evaluate`. This wraps OpenAI's `/v1/evals` REST surface and submits an inline JSONL dataset, which the Foundry control plane writes to a service-managed blob container before fanning evaluator workers out to score it.

Once the Foundry account was placed inside a Managed VNet (with public network access disabled and private endpoints fronting Storage / Cosmos / AI Search — see [001-azure-private-endpoints]), every eval submission silently regressed:

- The control plane returned `created` and a real `eval_id` / `run_id`
- `status` stayed `in_progress` forever
- `result_counts` stayed `{passed: 0, failed: 0, total: 0}`
- `output_items` stayed empty
- No error surfaced anywhere — the run looked perfectly healthy

After working through the diagnostic ladder in `.squad/skills/foundry-eval-debugging/SKILL.md` (capability host, agent identity RBAC, model deployment, network injections, private DNS, outbound rules), the actual root cause turned out to be a **service-side bug in Foundry's eval backend**: `raisvc` cannot write the inline JSONL dataset to private-endpoint-only blob storage when the Foundry account is in a Managed VNet. The team's prior investigation captured this as "Rung -1 — VNET Empty Dataset Bug" with a pending Microsoft support ticket and no expected ETA.

We needed evaluations to keep working in production without rolling back the private-endpoint posture (issue #145).

## Decision

Replace the `FoundryEvals` integration in `ai-service` with an **LLM-as-judge** evaluation pipeline composed of two `FoundryAgent` instances:

1. **Candidate agent** — runs the prompt under test against the supplied transaction
2. **Judge agent** — receives the candidate's response and a structured rubric describing each evaluator (Coherence, Fluency, Relevance, …) and returns a JSON object of `{evaluator: {score: 1-5, passed: bool, reason: str}}`

The judge runs against the same `gpt-5.4-mini` deployment the rest of the platform uses, through the same `FoundryChatClient` plumbing, so the eval path stays inside the Managed VNet and depends only on agent inference (which works) — never on `raisvc` or hosted dataset upload (which doesn't).

### Reasons

1. **Unblocks #145 with no infra change** — Agent inference is the one Foundry surface that does work in the Managed VNet. Switching evals to the same surface inherits that working state.
2. **No client churn** — `prompt-eval-service` (.NET) and the React admin UI consume the same response shape from `/api/admin/evaluate` (`total`, `passed`, `failed`, `all_passed`, `per_evaluator`, `items[].scores`, `eval_id`, `run_id`, `status`). Synthetic IDs are issued as `local-llm-judge-{uuid}` so existing storage and lookup flows are unchanged.
3. **No bespoke infra** — Reuses the existing Foundry agent deployment and workload identity. No additional resource provisioning or RBAC.
4. **Debuggable in-cluster** — The same code path is reachable from the `eval-debug` Pod (see `src/ai-service/app/eval_debug.py`), so on-call can iterate on prompts/judge rubrics interactively without redeploying.
5. **Forward-compatible** — When Microsoft fixes the `raisvc` Managed VNet bug, swapping back to `FoundryEvals.evaluate()` is a single function-body change. The endpoint contract and consumers stay the same.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Keep `FoundryEvals` and wait for MS fix** | Zero engineering work; "real" Foundry eval lineage in portal | Production feature stays broken indefinitely; no eta; ships failing UX |
| **Disable public network access exception for the Foundry account** | Would unblock `raisvc` blob writes | Violates the private-endpoint posture established in 001-azure-private-endpoints; weakens security model for one feature |
| **Run evals out-of-band via a one-shot Azure ML job** | Offloads judge to a separate compute | Heavy: requires AML workspace + compute + scheduling; doesn't fit the synchronous admin-UI workflow |
| **Move evals to a third-party platform (Braintrust, Langfuse, etc.)** | Mature eval tooling, dashboards | New SaaS dependency, data-residency concerns, additional secrets/auth, does not survive a private-VNet deployment without further work |

## Consequences

### Positive

- `/api/admin/evaluate` works end-to-end in the Managed VNet. Issue #145 closed.
- Judge rubric lives in code (`_build_judge_instructions`, `_evaluator_description` in `src/ai-service/app/routes/api.py`) — easy to version, review, and unit test (`tests/test_llm_judge.py`).
- New evaluators are added by extending the rubric, not by waiting on Foundry to publish a built-in evaluator.
- The `eval-debug` Pod (`deploy/kustomize/base/eval-debug.yaml`) calls the same helpers used in production, so debugger output stays faithful to prod behavior.

### Negative

- Scores no longer come from Microsoft-published evaluator metrics — they're driven by our own judge prompt. Numerical comparisons against historical `FoundryEvals` runs are not apples-to-apples.
- Two LLM calls per evaluation item (candidate + judge) doubles token spend versus a single `raisvc` invocation.
- Eval results are not visible in the Foundry portal's "Evaluations" pane — they live only in Cosmos DB (`evaluation-runs` container).

### Operational

- Production endpoint: `POST /api/admin/evaluate` in `ai-service`
- Implementation: `run_foundry_evaluation` in `src/ai-service/app/routes/api.py`
- Helpers: `_build_judge_instructions`, `_evaluator_description`, `_build_judge_user_prompt`, `_parse_judge_scores`
- Tests: `src/ai-service/tests/test_llm_judge.py` (12 tests)
- Interactive debugger: `kubectl exec -it -n banking-demo deploy/eval-debug -- python -m app.eval_debug`
- Threshold: judge score ≥ 3 (on a 1–5 scale) ⇒ `passed = true`; the parser also accepts an explicit `passed` boolean from the judge if present.

[001-azure-private-endpoints]: ../../specs/001-azure-private-endpoints/
