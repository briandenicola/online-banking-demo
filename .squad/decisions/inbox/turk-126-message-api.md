# Decision Drop — Turk — Issue #126: ai-service `/api/admin/evaluate` 500

**Date:** 2026-05-13
**Author:** Turk (Backend Dev — Python/FastAPI)
**Status:** Implemented on `squad/p2-wave-3`
**Scope:** `src/ai-service/app/routes/api.py` (single hunk, lines 363–371)

## Problem

`POST /api/admin/evaluate` in ai-service returned HTTP 500 with:

```
AttributeError: type object 'Message' has no attribute 'system'
```

The Foundry-evals admin endpoint was completely unusable — the Prompt Eval admin UI page could not run any evaluation.

## Root cause

Two cumulative API misuses against the `agent_framework` SDK:

1. **`Message.system(...)` / `Message.user(...)` do not exist.** The class exposes
   only `from_dict`, `from_json`, `text`, `to_dict`, `to_json` as public
   helpers. Construction is positional:
   ```
   Message(role: 'RoleLiteral | str',
           contents: 'Sequence[Content | str | Mapping[str, Any]] | None' = None,
           ...)
   ```
2. **`EvalItem(input=[...], output="")` uses wrong kwargs.** Real signature:
   ```
   EvalItem(conversation: list[Message],
            tools=None, context=None,
            expected_output=None, expected_tool_calls=None,
            split_strategy=None)
   ```
   Without this second fix, the endpoint would have flipped from
   `AttributeError` to `TypeError: EvalItem.__init__() got an unexpected
   keyword argument 'input'` — same 500, different message.

Verified by introspecting the live pod with
`kubectl exec ... python -c "import inspect; ..."`.

## Fix

```python
eval_items.append(
    EvalItem(
        conversation=[
            Message("system", [request.system_prompt]),
            Message("user",   [prompt]),
        ],
    )
)
```

Note: `contents` is a `Sequence`, so a single string MUST be list-wrapped —
otherwise Python iterates the string and produces one `TextContent` per
character (verified: a 22-char prompt yielded 22 content parts).

## Other call sites checked

`grep -rn 'Message\.(system|user|assistant)\(' src/ai-service/` — only the two
sites in `api.py:366-367` matched. No other Python service uses the
`agent_framework` `Message` type. Safe.

## Verification

- ✅ `task cloud:build:ai-service` — clean build, image pushed.
- ✅ `task cloud:deploy` — rolling restart succeeded; `ai-service` Ready.
- ✅ Live in-pod construction test: `Message("system", [text])` + `EvalItem(conversation=[...])` both succeed and round-trip.
- ✅ Live HTTPS POST to `/api/admin/evaluate` with admin JWT — request now passes
  request validation and reaches the Foundry evaluator. **The original
  `AttributeError` is gone.**

## Follow-up (NOT in this fix — out of Backend scope)

The endpoint now surfaces a *different* error from the Foundry evaluator
backend itself:

```
openai.BadRequestError: 400 - {'error': {'code': 'UserError',
  'message': 'The action cannnot be finished with reason
             Response status code does not indicate success: 403 (Forbidden).',
  'innerError': {'code': 'UnauthorizedUserAction'},
  'componentName': 'raisvc', ...}}
```

That is an Azure AI Foundry **RBAC / role-assignment issue** on the
project's evaluator/`raisvc` plane — not a Python bug. Recommend a separate
issue for **Danny** (architecture / Terraform owner) to grant the workload
identity the appropriate role on the AI Foundry project's evaluation
service. This decision drop closes #126 (the Python-side bug); the 403 is a
new infra ticket.

## Files changed

- `src/ai-service/app/routes/api.py` — −4/+3 lines, single hunk.
