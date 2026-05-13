# Decision: Issue #137 — Real Root Cause of Foundry Eval 403

**Author:** Basher
**Date:** 2026-05-13
**Status:** Proposed (awaiting Brian's end-to-end verification)
**Supersedes:** the "Fix Applied" section in the issue body of #137 (which named SDK pinning as the fix — that was incomplete).

## TL;DR

The eval 403 is **not RBAC** and **not SDK contract drift**. It's an **incomplete eval payload**. The
`/api/admin/evaluate` endpoint was sending `[system, user]` conversations with no assistant turn.
Foundry's raisvc rejects eval-run creation when there's nothing to evaluate, returning a confusing
400-wrapped 403 `UnauthorizedUserAction` that *looks* like an authorization failure but is actually
"your request body is missing the response you want me to score."

## What the issue body got wrong

The issue's "Fix Applied" section claimed the cure was exact-pinning `agent-framework-core 1.2.2`,
`agent-framework-foundry 1.2.2`, `azure-ai-inference 1.0.0b9` (commit `0b6255a`). That pin shipped
and **the 403 still occurred** — which Brian confirmed. The pin was a red herring: the SDK has been
fine; the bug was always in our caller code.

Earlier RCAs in this thread also chased RBAC (Cognitive Services Contributor, Azure AI Project
Manager, etc.) — those role assignments are now in place but were not the cause either. raisvc
short-circuits payload validation **before** role evaluation, then maps the validation failure to
the catch-all `UnauthorizedUserAction` code. That's a Microsoft UX bug we have to work around.

## The real cause

`src/ai-service/app/routes/api.py:run_foundry_evaluation` constructs each `EvalItem` from a
two-message conversation:

```python
EvalItem(conversation=[
    Message("system", [request.system_prompt]),
    Message("user", [prompt]),
])
```

The Foundry SDK's `_evaluate_via_dataset` then derives:

```python
query_text    = " ".join(m.text for m in query_msgs    if m.role == "user"      and m.text)
response_text = " ".join(m.text for m in response_msgs if m.role == "assistant" and m.text)
```

With no assistant message, `response_text == ""`. The JSONL row submitted to
`POST /openai/v1/evals/{id}/runs` has an empty `response` field. raisvc's content-safety /
quality evaluators have nothing to score, raisvc rejects, and the SDK surfaces the 403.

A telltale sign in the current code: an `eval_agent = FoundryAgent(...)` is constructed and never
used. That dead variable is residue from the original implementation (commit `bd4f6a7`) which did:

```python
session = eval_agent.create_session()
response = await eval_agent.run(user_msg, session=session)
conversation = [
    Message(role="system",    contents=[request.system_prompt]),
    Message(role="user",      contents=[user_msg]),
    Message(role="assistant", contents=[str(response)]),     # <-- this turn was lost
]
```

## When and where it broke

| Commit    | Event                                                                                |
|-----------|--------------------------------------------------------------------------------------|
| `bd4f6a7` | Original eval impl in `app/main.py`. Three-turn conversation. Worked.                |
| `39dfdbe` | **The break.** "P2 Wave 1: code quality + refactoring (#114)" extracted main.py → routes/api.py and dropped the `eval_agent.run()` call + the assistant `Message`. Also broke the `Message` / `EvalItem` API. |
| `4134138` | Fixed the immediate `AttributeError: type object Message has no attribute system` and the `EvalItem` kwarg name (`input` → `conversation`). Did **not** notice the missing assistant turn. PR comment even calls out the residual 403 as "infra follow-up" — but it isn't infra. |
| `0b6255a` | Pinned SDKs. No effect on the bug.                                                   |
| `243457f` | Silent unrelated regression: reverted the warm-up token scope in `anomaly_service.py` from `ai.azure.com` back to `cognitiveservices.azure.com`. **Cosmetic only** — that token is just logged, not used by the SDK — but worth fixing for diagnostic clarity. |

## Fix shipped

**`src/ai-service/app/routes/api.py`** — restored the per-transaction agent run and the assistant
turn:

```python
session = eval_agent.create_session()
agent_response = await eval_agent.run(prompt, session=session)
assistant_text = agent_response.text or ""

eval_items.append(EvalItem(conversation=[
    Message("system",    [request.system_prompt]),
    Message("user",      [prompt]),
    Message("assistant", [assistant_text]),
]))
```

Also passed `eval_name=request.eval_name` to `evals.evaluate(...)` (it had been silently ignored).

**`src/ai-service/app/services/anomaly_service.py`** — reverted the warm-up scope to
`https://ai.azure.com/.default` to match `init_agents.py` and avoid future confusion. Functional
no-op (token is only logged) but stops the diagnostic noise.

**`pyproject.toml`** — untouched. The 1.2.2 pin stands; preview SDKs still need exact pins for the
reasons in `.squad/skills/preview-sdk-pinning/SKILL.md`.

**RBAC** — untouched. Existing role assignments are correct and sufficient.

## Verification ladder for Brian

1. Build & deploy the ai-service image (just this service, no infra).
2. From the cluster:
   ```bash
   kubectl logs -n banking-demo deploy/ai-service -c ai-service -f | grep -E '/openai/v1/evals'
   ```
3. From the UI Admin → Eval tab, run an evaluation against a small transaction set.
4. Expect: both `POST /openai/v1/evals` and `POST /openai/v1/evals/{id}/runs` return 2xx, the
   poll loop completes, and the response includes `per_evaluator` scores.
5. If still 403: capture the failing request body via `_OpenAILoggingTransport` (set
   `console_logging=True` on the AIProjectClient temporarily) and re-open.

## Recommended follow-ups

- **Behavioural test (issue worth filing):** an integration test that mocks `evals.create` /
  `evals.runs.create` and asserts the submitted JSONL has non-empty `response` per item. Would
  have caught both the 39dfdbe regression and the 4134138 incomplete fix.
- **Audit other refactor casualties:** the same `#114` refactor pass touched several services.
  Worth a sweep for other dead-variable smells where the original behaviour was lost.
- **File a Microsoft feedback item** that raisvc should distinguish "missing assistant turn" from
  "RBAC denied" instead of returning the same `UnauthorizedUserAction` code for both.

## Skill captured

`.squad/skills/foundry-eval-debugging/SKILL.md` — diagnostic ladder for raisvc 403s
(RBAC → token scope/audience → SDK payload shape → endpoint/api_version → wrapper bugs).
