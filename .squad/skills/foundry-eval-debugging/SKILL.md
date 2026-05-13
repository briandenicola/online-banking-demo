# Skill: Debugging Azure AI Foundry Eval (raisvc) Failures

**When to use:** Any time the agent_framework / Azure AI Foundry "Evals" pipeline returns
a 4xx (especially 400-wrapping-403 with `componentName: "raisvc"` and
`innerError.code: "UnauthorizedUserAction"`).

**Background:** `raisvc` is the Responsible AI service backend that fronts Foundry's
content-safety + quality evaluators. It is notorious for collapsing several distinct
failure modes onto a single confusing error code (`UnauthorizedUserAction` / 403). Do
**not** assume the error means RBAC. Walk this ladder in order — each rung is cheaper
than the next to verify, and the actual cause is almost always lower than you think.

## The Diagnostic Ladder

### Rung 1 — RBAC (cheap, but rarely the cause)

Verify on the managed identity used by the calling pod:

| Role                              | Why                                              |
|-----------------------------------|--------------------------------------------------|
| Cognitive Services User           | Foundry data-plane minimum                       |
| Azure AI User                     | Project-level read                               |
| Cognitive Services OpenAI User    | OpenAI inference (chat/completions)              |
| Azure AI Project Manager          | Eval-run create on the project                   |

If all four are present (resource scope), **RBAC is not the cause**. Move on. Do not
keep adding roles — past investigations have wasted hours adding `Cognitive Services
Contributor` only to find the bug elsewhere.

### Rung 2 — Token Scope / Audience

The Foundry Python SDK (`azure.ai.projects`) hardcodes
`https://ai.azure.com/.default` for `get_openai_client()` (see
`azure/ai/projects/aio/_patch.py:166`). You generally don't choose the scope yourself.

Verify the actual JWT audience inside the pod:

```bash
kubectl exec -n <ns> deploy/<svc> -c <svc> -- python -c "
from azure.identity import DefaultAzureCredential
import base64, json
t = DefaultAzureCredential().get_token('https://ai.azure.com/.default').token
payload = t.split('.')[1] + '=' * ((4 - len(t.split('.')[1]) % 4) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
print('aud:', claims.get('aud'))
print('oid:', claims.get('oid'))
"
```

`oid` must match the managed identity principal you assigned roles to.

**Important:** any `credential.get_token(<scope>)` call your *own* code makes at
startup is purely diagnostic. `DefaultAzureCredential` caches per scope, but the SDK
issues its own token at its own scope from the same credential. Changing your warm-up
scope does not change the SDK's scope.

### Rung 3 — Eval Payload Shape (this is usually it)

`FoundryEvals.evaluate(items)` ultimately POSTs `/openai/v1/evals/{id}/runs` with a
JSONL data source. The SDK builds each row as:

```python
query_text    = " ".join(m.text for m in query_msgs    if m.role == "user"      and m.text)
response_text = " ".join(m.text for m in response_msgs if m.role == "assistant" and m.text)
```

If either is empty, raisvc rejects with the misleading 403.

**Required for evaluation:** every `EvalItem.conversation` must contain
**at least one `user` message AND one `assistant` message** with non-empty text. If
you're evaluating a prompt template you authored, you must:

1. Run the prompt through a `FoundryAgent` first (`agent.run(...)`).
2. Capture `response.text`.
3. Build the conversation as `[Message("system", [...]), Message("user", [...]), Message("assistant", [response.text])]`.

**Message construction gotcha:** `agent_framework.Message` has **no** `Message.system(...)`
or `Message.user(...)` factory methods. Use positional `Message(role, contents)` where
`contents` is a `Sequence` — wrap single strings in a list (`[my_string]`) or each
character becomes a separate `Content` object.

**EvalItem kwarg gotcha:** the kwarg is `conversation=[...]`, **not** `input=[...]`.
For ground-truth evals add `expected_output=...` (not `output=...`).

### Rung 4 — Endpoint / API Version

If the eval CREATE (`POST /openai/v1/evals`) succeeds but the eval RUN fails, the
endpoint and API version are correct. Skip this rung.

If the CREATE itself 404s or 401s, check `FOUNDRY_PROJECT_ENDPOINT` — should be
`https://<account>.services.ai.azure.com/api/projects/<project-name>` (no trailing
slash). The SDK appends `/openai/v1` automatically.

### Rung 5 — Wrapper Bugs

Run a minimal repro that bypasses your wrapper code:

```bash
kubectl exec -n <ns> deploy/<svc> -c <svc> -- python -c "
import asyncio, os
from azure.identity.aio import DefaultAzureCredential
from agent_framework_foundry import FoundryChatClient, FoundryAgent, FoundryEvals
from agent_framework._evaluation import EvalItem
from agent_framework import Message

async def main():
    cred = DefaultAzureCredential()
    endpoint = os.environ['FOUNDRY_PROJECT_ENDPOINT']
    model = os.environ['FOUNDRY_MODEL']
    client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=cred)
    agent = FoundryAgent(project_endpoint=endpoint, credential=cred,
                         agent_name='risk-assessor', agent_version='1',
                         instructions='You are a test agent. Reply with one sentence.')
    s = agent.create_session()
    r = await agent.run('Test transaction: 5 dollar coffee', session=s)
    item = EvalItem(conversation=[
        Message('system', ['You are a test agent.']),
        Message('user',   ['Test transaction: 5 dollar coffee']),
        Message('assistant', [r.text]),
    ])
    evals = FoundryEvals(client=client, evaluators=['relevance'])
    result = await evals.evaluate([item], eval_name='diag')
    print(result)

asyncio.run(main())
"
```

If this works, the bug is in your wrapper (missing turn, wrong split strategy,
empty content). If it also fails, you're back at rung 1–4.

### Rung 6 — Enable SDK Wire Logging

As a last resort, construct `AIProjectClient(..., console_logging=True)` and re-run.
The OpenAI client will log every request body. Look for:
- Empty `response` strings in the JSONL items
- Missing `query_messages` / `response_messages` arrays
- `testing_criteria` referencing evaluators your project doesn't have permissions for

## Anti-Patterns (don't do these)

- **Adding more RBAC roles when you already have the documented set.** The error code
  is misleading. Adding `Cognitive Services Contributor` doesn't help; raisvc
  short-circuits payload validation before role evaluation.
- **Pinning / unpinning the SDK in response to runtime errors.** Preview SDKs do drift
  (see `preview-sdk-pinning` skill), but a 400/403 from raisvc is almost never SDK
  drift. It's almost always your payload.
- **Treating `eval_agent.run()` as optional.** If you're evaluating a prompt
  *template* (not a captured agent transcript), you MUST run the agent first to
  produce the assistant turn. The SDK does not auto-generate the response.
- **Trusting commit messages over diffs.** A commit titled "fix(cosmos): pin
  serializer casing" once silently reverted a Foundry token scope. Always read the
  actual diff for files outside the title's scope.

## Issues to reference

- #137 — the "real" RCA after pinning failed (the assistant-turn fix).
- #126 / commit `4134138` — the Message + EvalItem API fix (necessary but not
  sufficient).
- #131 / commit `69ce049` — the original `ai.azure.com` scope fix (warm-up only).
- `.squad/skills/preview-sdk-pinning/SKILL.md` — companion skill for *real* SDK
  drift cases.

## Citations

- `src/ai-service/app/routes/api.py:run_foundry_evaluation` — canonical correct
  implementation post-fix.
- `agent_framework_foundry/_foundry_evals.py:_evaluate_via_dataset` — where the
  query/response split happens.
- `azure/ai/projects/aio/_patch.py:166` — where the SDK hardcodes
  `https://ai.azure.com/.default`.
