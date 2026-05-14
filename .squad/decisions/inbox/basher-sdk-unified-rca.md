# RCA: #137 + #130 — Unified Foundry SDK Signature Fix

**Author:** Basher
**Date:** 2026-05-14
**Branch:** `squad/p2-wave-3`
**Issues:** #137 (eval failures), #130 (multi-pod counter / "AI Calls Today" = 0)
**Status:** ✅ Fixed and verified in production pod

## Linked Symptoms

| # | Where | Error | Was attributed to |
|---|---|---|---|
| A | account-opening-worker startup | `FoundryAgent.__init__() got an unexpected keyword argument 'model'` (after d120834) → `Missing required parameter: 'model'` (after first fix attempt) | "FoundryAgent signature drift" |
| B | ai-service `/api/admin/evaluate` | `openai.BadRequestError: Missing required parameter: 'model'` from `responses.create()` | "Eval payload bug" |
| C | UI Admin → "AI Calls Today" stuck at 0 | (no error — silent zero) | "Counter not wired" |

All three were the **same root cause**: every `FoundryAgent(...)` constructor
in the codebase was either passing `model=` (which the SDK rejects) or omitting
the model entirely (in which case the underlying `responses.create()` 400s).
Fixing each construction site fixes all three symptoms.

## Root Cause

`agent-framework-foundry==1.2.2` ships with this signature:

```python
FoundryAgent(
    *, project_endpoint, agent_name, agent_version, credential,
    project_client, allow_preview, tools, context_providers, middleware,
    client_type, env_file_path, env_file_encoding, id, name, description,
    instructions, default_options, ...
)   # ← NO `model=`
```

`FoundryAgent` does **not** take `model=`. To put the model deployment name
into the request body that `_FoundryAgentChatClient.responses.create(...)`
sends to Foundry, callers must use:

```python
default_options={"extra_body": {"model": "<deployment>"}}
```

The `extra_body` wrapper is required because the OpenAI client strips unknown
top-level options before sending; only fields under `extra_body` survive.

`FoundryChatClient` and `FoundryEvals` (sister classes in the same package) do
accept top-level `model=`. So in the same SDK release, two adjacent classes
have **opposite** model conventions — bidirectional signature drift.

## Why C was downstream of B (and why the issue looked like 3 separate bugs)

The cross-replica counter (`ai:metrics:calls:{YYYY-MM-DD}` in Redis) is
incremented only on the **success path** of `FoundryRiskAnalyzer.analyze`,
after `_parse_response()` returns. When `self._agent.run(...)` raises (because
of the missing-model 400), the outer `except Exception` returns a fallback
`RiskAssessment(flags=["ai_unavailable"])` and skips the increment. The
counter stayed at 0 because every AI call was 400'ing — not because the
counter logic (which is correct) was broken.

## Files Changed

- `src/account-opening-service/app/worker.py` — connectivity check FoundryAgent
- `src/account-opening-service/app/agents/identity_verification.py`
- `src/account-opening-service/app/agents/compliance_check.py`
- `src/account-opening-service/app/agents/provisioning.py`
- `src/account-opening-service/tests/test_worker.py` — new `TestFoundryAgentSignatureContract`
- `src/ai-service/app/services/anomaly_service.py` — risk_agent + categorizer_agent
- `src/ai-service/app/routes/api.py` — eval_agent
- `src/ai-service/tests/test_detection.py` — new `TestFoundryAgentSignatureContract`
- `.squad/skills/foundry-eval-debugging/SKILL.md` — added Rung 0 (FoundryAgent contract check)

## SDK Versions in Deployed Image at Fix Time

```text
agent-framework-core      1.2.2
agent-framework-foundry   1.2.2
agent-framework-openai    1.2.2
azure-ai-projects         2.1.0
azure-ai-inference        1.0.0b9
openai                    2.36.0
```

Pin guard CI (`.github/workflows/preview-sdk-pin-guard.yml`) is intact and
correct — pins did not drift. The bug was at the call sites.

## Verification (production pod, 2026-05-14 ~01:57Z)

**A.** account-opening-worker:
```text
HTTP Request: POST .../openai/v1/responses "HTTP/1.1 200 OK"
{"event": "Foundry connectivity verified", "logger": "account-opening-worker"}
```

**B.** ai-service in-pod repro using the new eval_agent construction:
```text
agent.run OK, response_len= 18    # ← was 400 "Missing required parameter: 'model'"
```

**C.** ai-service in-pod risk_agent + counter:
```text
counter BEFORE: 0
analyze returned: riskScore=0.03 explanation='Routine small purchase…' flags=[]
counter AFTER:  1
```

## Prevention

1. **Pytest contract tests** (this PR) — both services now have a
   `TestFoundryAgentSignatureContract` class that:
   - Reads `inspect.signature(FoundryAgent.__init__)` from the installed SDK
   - Greps every `FoundryAgent(...)` call in the service's source
   - Asserts no unsupported kwargs (catches `model=` regression)
   - Asserts every call passes `default_options={"extra_body": {"model": ...}}`

   These run in normal pytest, no special harness.

2. **Skill update** — `.squad/skills/foundry-eval-debugging/SKILL.md` now has a
   "Rung 0: FoundryAgent constructor contract" section that runs first.

3. **Pin guard already in place** for preview SDK pyproject pins (#137 prior
   work) — unchanged and still correct.

## Remaining Concerns

- The standalone `FoundryEvals` test path (the in-pod repro that exercises
  `evals.create` + `evals.runs.create`) still produces a `componentName:
  raisvc` 400/403 with my minimal "5 dollar coffee" input. That is **not** a
  blocker for #137 — it's the older eval payload validation issue documented
  in the `foundry-eval-debugging` skill (Rung 3). The actual ai-service
  `/api/admin/evaluate` endpoint, which sends a complete system+user+assistant
  conversation per the skill's prescription, should now succeed end-to-end
  because `eval_agent.run()` now returns. If raisvc rejects production eval
  runs, treat it as a separate ticket and walk the eval-debugging skill.

- `azure-ai-contentunderstanding = "*"` in account-opening-service pyproject
  is still unpinned; flagged in prior history but kept out of this PR's scope.

## Bundling

Single commit on `squad/p2-wave-3`. No infra/Terraform changes. No image-tag
changes (still `:latest`).
