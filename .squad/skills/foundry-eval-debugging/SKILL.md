# Skill: Debugging Azure AI Foundry Eval (raisvc) Failures

**When to use:** Any time the agent_framework / Azure AI Foundry "Evals" pipeline returns
a 4xx (especially 400-wrapping-403 with `componentName: "raisvc"` and
`innerError.code: "UnauthorizedUserAction"`) — **OR** any time you see a 400
`Missing required parameter: 'model'` from `client.responses.create()` in a
stack involving `agent_framework_foundry._agent._FoundryAgentChatClient`.

**Background:** `raisvc` is the Responsible AI service backend that fronts Foundry's
content-safety + quality evaluators. It is notorious for collapsing several distinct
failure modes onto a single confusing error code (`UnauthorizedUserAction` / 403). Do
**not** assume the error means RBAC. Walk this ladder in order — each rung is cheaper
than the next to verify, and the actual cause is almost always lower than you think.

## The Diagnostic Ladder

### Rung 0 — FoundryAgent constructor contract (ADDED 2026-05-14, #137 + #130)

If you see `Missing required parameter: 'model'` from `responses.create()`, OR
`FoundryAgent.__init__() got an unexpected keyword argument 'model'`, OR if a
counter/metric that depends on `agent.run()` succeeding is silently zero —
this rung first. Almost certainly a FoundryAgent call site is wrong.

`agent-framework-foundry` 1.2.x has **bidirectional signature drift** within
the same package release:

| Class                | Accepts `model=`? | How to set the model         |
|----------------------|:-----------------:|------------------------------|
| `FoundryAgent`       | ❌ NO             | `default_options={"extra_body": {"model": "<deployment>"}}` |
| `FoundryChatClient`  | ✅ YES            | `model="<deployment>"`       |
| `FoundryEvals`       | ✅ YES            | `model="<deployment>"` (or inherits from `client.model`) |
| `OpenAIChatClient`   | ✅ YES (positional) | `OpenAIChatClient("<deployment>", ...)` |

The **`extra_body`** wrapper is required because the OpenAI SDK silently
strips unknown top-level keys from `default_options` before sending.
`default_options={"model": ...}` is dropped on the floor; only fields under
`extra_body` make it into the request body.

**Verification command:**
```bash
kubectl exec -n <ns> deploy/<svc> -- python -c "
import inspect
from agent_framework_foundry import FoundryAgent, FoundryChatClient, FoundryEvals
print('Agent:',  inspect.signature(FoundryAgent.__init__))
print('Chat:',   inspect.signature(FoundryChatClient.__init__))
print('Evals:',  inspect.signature(FoundryEvals.__init__))
"
```

**Canonical correct construction:**
```python
agent = FoundryAgent(
    project_endpoint=endpoint,
    credential=credential,
    agent_name="...",
    agent_version="1",
    description="...",
    instructions=SYSTEM_PROMPT,
    default_options={"extra_body": {"model": model_deployment_name}},
)
```

**Regression guard:** Each Python service that constructs `FoundryAgent` has a
pytest class `TestFoundryAgentSignatureContract` in its tests. It greps every
`FoundryAgent(...)` call against `inspect.signature(FoundryAgent.__init__)`
and asserts the `default_options.extra_body.model` shape. If the SDK signature
changes again, those tests fail loudly in normal `pytest` — no waiting for a
pod startup error in production.

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

### Rung 7 — `FoundryAgent` constructor / `model` errors (2026-05-14 incident)

This rung covers TWO related symptoms that surface when constructing or running
`FoundryAgent` for an `agent_name`/`agent_version`-bound persistent agent.

**Symptom A — `FoundryAgent.__init__() got an unexpected keyword argument 'model'`**
at startup.

The `agent_framework_foundry==1.2.x` `FoundryAgent.__init__` is **keyword-only and
does NOT accept `model`**. There's no `**kwargs` catch-all. This trips on any code
copied from a tutorial, an older SDK, or a fix that was logically right (Responses
API requires a model) but used the wrong shape.

**Always verify against the deployed pod's installed SDK:**

```bash
kubectl exec -n <ns> deploy/<svc> -c <container> -- python -c "
import inspect
from agent_framework_foundry import FoundryAgent
print(inspect.signature(FoundryAgent.__init__))"
```

**Fix:** Remove `model=` from the constructor. The model goes elsewhere — see
Symptom B.

**Symptom B — `Error code: 400 — Missing required parameter: 'model'`** from
`POST .../openai/v1/responses` after the constructor succeeds.

The SDK's request preparer at `agent_framework_foundry/_agent.py:_FoundryAgentChatClient`
**actively pops `model` from outgoing run-options** (look for `run_options.pop("model", None)`)
because it expects the model to be configured **server-side on the Foundry agent
version**. When the server-side agent has `model=None`, the request body has no
model field and the API rejects it. The error message is misleading: it implies a
client-side parameter problem when the actual cause is a missing server-side
configuration.

**Diagnose:**

```python
# inside a working pod (any one with the SDK + workload identity)
from azure.ai.projects.aio import AIProjectClient
from azure.identity import DefaultAzureCredential
import asyncio, os

async def check(name):
    c = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/"),
                        credential=DefaultAzureCredential())
    async for v in c.agents.list_versions(agent_name=name):
        print(f"  v={v.version} model={getattr(v,'model',None)}")

asyncio.run(check("identity-verifier"))
# ⇒ if model=None, that's your bug
```

**Two fixes (preferred → workaround):**

1. **Preferred — set `model` server-side on the agent version.** The SDK is
   intentional about not sending model on every call. Update each agent's version
   definition in the Foundry portal / Terraform / IaC to pin `model="gpt-5.4-mini"`
   (or whichever deployment). All client services then "just work" with no
   special construction.

2. **Workaround — smuggle `model` through `extra_body`.** The SDK strips `model`
   from `run_options` but preserves `extra_body`:

   ```python
   FoundryAgent(
       project_endpoint=...,
       credential=...,
       agent_name="identity-verifier",
       agent_version="1",
       instructions=...,
       default_options={"extra_body": {"model": foundry_model}},
   )
   ```

   This sends `{"model": "..."}` in the request body and bypasses the strip.
   Use this when you can't change the server-side agent definition, but treat it
   as tech debt.

**Things that look like they should work but don't:**

- `default_options={"model": foundry_model}` — stripped by `pop("model")`.
- `default_options=FoundryAgentOptions(model=foundry_model)` — same; `FoundryAgentOptions`
  is a TypedDict, semantically identical to a plain dict here.
- `agent.run(..., options=ChatOptions(model=foundry_model))` — stripped.
- `agent.run(..., client_kwargs={"model": foundry_model})` — `client_kwargs`
  goes to the underlying OpenAI client constructor, not the request body, so
  `AsyncResponses.create()` then errors with "got an unexpected keyword argument
  'model_id'" (the SDK normalises the name) and the request never goes out.

**Contract test (regression guard):** see
`src/account-opening-service/tests/test_worker.py::TestFoundryAgentSignatureContract`.
It uses `inspect.signature(FoundryAgent.__init__)` against the *installed* SDK and
asserts each call site only uses supported kwargs and never `model=`. Re-runs on
every preview-SDK pin bump; will catch the next signature drift before pod
startup.

**Cross-service note:** if account-opening-worker is broken with Symptom B, every
other Python service that calls `FoundryAgent.run(...)` against the same Foundry
project is also broken — they may just be hiding it (e.g. swallowed in a
"fallback" branch). Repro from inside each pod with the diagnose snippet above
before declaring the incident scoped.

### Rung 8 — Cosmos DB SQL Data-Plane RBAC for Foundry Project SAMI (ADDED 2026-05-14)

**When this rung applies:** Any Foundry agents/threads/runs/eval API call returns
HTTP 403 with a body that names a *principal GUID* and `aka.ms/cosmos-native-rbac`.
Common form:

```
HTTP/1.1 403 Forbidden
{"code":"Forbidden","message":"Request blocked by Auth <cosmos-account>
 : Request is blocked because principal [<guid>] does not have required RBAC
 permissions to perform action [Microsoft.DocumentDB/databaseAccounts/readMetadata]
 on resource [/]. Learn more: https://aka.ms/cosmos-native-rbac."}
```

This is **Cosmos native (data-plane) RBAC**, not Azure RBAC. Adding more
`azurerm_role_assignment` entries does nothing — you need an
`azurerm_cosmosdb_sql_role_assignment` resource (or `az cosmosdb sql role
assignment create`).

**Step 1 — Identify the principal first. Always.** A Foundry deployment with BYO
Cosmos has *at least two* MIs that touch the account:

| MI                          | TF expression                                                  | When it talks to Cosmos                  |
|-----------------------------|----------------------------------------------------------------|------------------------------------------|
| Foundry **account** MSI     | `azapi_resource.this.output.identity.principalId`              | Capability host provisioning, managed PE |
| Foundry **project** SAMI    | `azapi_resource.ai_foundry_project.output.identity.principalId`| Agents data-plane proxy, threads, evals  |
| AKS workload UAMI           | `azurerm_user_assigned_identity.banking_services.principal_id` | App-tier SDK calls                       |

```bash
az ad sp show --id <guid> --query "{name:displayName,appId:appId}" -o json
```

A `displayName` ending in `…/projects/<name>` is the project SAMI; just the
account name is the account MSI.

**Step 2 — Grant data-plane role.**
Role: `Cosmos DB Built-in Data Contributor`, id `00000000-0000-0000-0000-000000000002`.
This includes `Microsoft.DocumentDB/databaseAccounts/readMetadata` plus
container R/W.

Terraform (canonical):
```hcl
resource "azurerm_cosmosdb_sql_role_assignment" "<name>" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = <principal_id>
  scope               = azurerm_cosmosdb_account.main.id
}
```

Out-of-band CLI fix (when TF state has unrelated drift you can't apply through):
```bash
az cosmosdb sql role assignment create \
  --account-name <cosmos> --resource-group <rg> \
  --scope "/" --principal-id <guid> \
  --role-definition-id 00000000-0000-0000-0000-000000000002
```
The next clean `terraform apply` then reconciles (the resource imports cleanly).

**Step 3 — Wire up wait.** If you also create the capability host or run agent
provisioning right after the role assignment, add it to the
`time_sleep.wait_*_rbac.depends_on` list. Cosmos data-plane RBAC is fast (seconds)
but the existing 90s wait absorbs it.

**Why control-plane roles aren't enough:** `Cosmos DB Account Reader` and
`Cosmos DB Operator` are ARM roles — they let you manage the account *resource*
but they grant ZERO data-plane access. Foundry agents authenticate to Cosmos's
data-plane endpoint, which only honors `sqlRoleAssignments`.

**Citation:** https://learn.microsoft.com/azure/cosmos-db/how-to-setup-rbac#built-in-role-definitions

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

### Rung 9 — Response Serialization + Polling Termination (ADDED 2026-05-14)

**When this rung applies:** KeyNotFoundException or missing fields when parsing Foundry eval responses, OR when evals report "ok" but have zero results / incomplete status.

**Two related bugs:**

#### A. FastAPI Serialization of SDK Objects

When returning an `EvalResults` object (from `agent_framework_foundry.FoundryEvals.evaluate()`) directly from a FastAPI endpoint, only `__dict__` attributes are serialized to JSON. `@property` methods are NOT included.

**EvalResults has:**
- Instance attributes: `provider`, `eval_id`, `run_id`, `status`, `result_counts` (dict), `report_url`, `error`, `per_evaluator` (dict), `items` (list), `sub_results` (dict)
- Properties (NOT serialized): `total`, `passed`, `failed`, `all_passed`

If client code expects top-level `total`, `passed`, `failed`, `all_passed` fields, it will hit KeyNotFoundException / missing field errors.

**Fix:** Always flatten SDK objects into explicit dicts matching the expected contract:
```python
return {
    "total": results.total,           # property → top-level field
    "passed": results.passed,         # property → top-level field
    "failed": results.failed,         # property → top-level field
    "all_passed": results.all_passed, # property → top-level field
    "per_evaluator": results.per_evaluator,  # dict attribute
    "eval_id": results.eval_id,
    "run_id": results.run_id,
    "status": results.status,
    "items": [...]  # manually flatten items too if needed
}
```

**Never** return the SDK object directly and expect properties to be serialized.

#### B. Polling Termination Check

The Foundry SDK's `_poll_eval_run` polls until `run.status in ("completed", "failed", "canceled")` OR timeout (default 180s). If timeout fires, it returns `status="timeout"`. If the eval fails, it returns `status="failed"`.

**Always check `results.status == "completed"` before reporting success.** If status is anything else (`in_progress`, `timeout`, `failed`, `canceled`), the eval did NOT complete successfully. Log the incomplete status and raise an error with the status + error message:

```python
if results.status not in ("completed",):
    logger.error(
        "foundry.eval.invoke.incomplete",
        status=results.status,
        n_results=results.total,
        error=results.error,
    )
    raise HTTPException(
        status_code=500,
        detail=f"Evaluation did not complete (status: {results.status}): {results.error or 'unknown'}"
    )
```

**Zero-result completed evals:** A status of `"completed"` with `total == 0` is valid (all items errored or empty input). Surface as a warning, not an error.

**Citation:** `src/ai-service/app/routes/api.py:run_foundry_evaluation` (lines 441-494, post-fix), `src/prompt-eval-service/Services/EvaluationService.cs` (lines 121-162, post-fix).

### Rung 10 — Empty Assistant Response Data Loss (ADDED 2026-05-15)

**When this rung applies:** Foundry receives `data_source.source.content: []` (empty array) despite logs showing `n_test_inputs: N` where N > 0. The eval completes with `status="completed"` but `total=0`.

**Root cause:** The SDK's `_evaluate_via_dataset` method builds JSONL rows from `EvalItem.conversation` using:

```python
query_text = " ".join(m.text for m in query_msgs if m.role == "user" and m.text).strip()
response_text = " ".join(m.text for m in response_msgs if m.role == "assistant" and m.text).strip()
```

The filter condition `if m.role == "assistant" and m.text` drops messages where `.text` is falsy (empty string, None). If you construct:

```python
assistant_text = agent_response.text or ""  # WRONG: "" is falsy
Message("assistant", [assistant_text])
```

...and `agent_response.text` is `None` or `""`, the message is created but the SDK's filter silently drops it. The resulting JSONL row has `response: ""`, which fails Foundry's schema validation and is excluded from the dataset. If ALL rows are dropped this way, Foundry receives an empty dataset.

**Fix:** Always use a non-empty sentinel value if the agent returns empty text:

```python
assistant_text = agent_response.text or "(no response)"  # CORRECT: non-empty fallback
Message("assistant", [assistant_text])
```

This ensures the message passes the SDK's `and m.text` filter and Foundry receives valid data.

**Diagnostic steps:**
1. Check logs for `n_test_inputs > 0` but `n_eval_items == 0` or missing — means items were collected but lost before SDK call
2. Add debug logging RIGHT BEFORE `evals.evaluate(items)`:
   ```python
   logger.debug("sample_item", conversation=[{"role": m.role, "text_length": len(m.text)} for m in items[0].conversation])
   ```
3. If all messages show `text_length > 0` but Foundry still sees empty content, the bug is in the SDK call signature (wrong kwarg name)
4. If any message shows `text_length == 0`, that's the data loss — fix the sentinel value

**Citations:**
- `src/ai-service/app/routes/api.py:399-403` — sentinel value fix + explanatory comment
- `agent_framework_foundry/_foundry_evals.py:680-681` — SDK filter that drops empty messages
- Issue: Brian's feedback "we need to understand WHY eval came back with 0 result counts" (2026-05-15)


---

### Rung 11 — Foundry Backend Dataset Discard (ADDED 2026-05-15, REVISED 2026-05-15c)

**When this rung applies**: After confirming Rung 10's sentinel fix is deployed and `n_eval_items > 0`, Foundry STILL returns `content: []` and `total: 0`. HTTP debug logs show the SDK sent valid content in the POST request, and Foundry's 201 response **echoed the content back**, but subsequent GET polls show `content: []`.

**Symptom timeline**:
1. POST `/evals/.../runs` with `content: [N items]` where N > 0
2. Foundry responds 201 Created with body showing `content: [N items]` (same array)
3. First GET poll (1-5s later) returns `content: []`
4. Run stuck in `status: "in_progress"` with `total: 0` until SDK timeout (180s)

**Root cause (REVISED)**: **SDK version regression / missing agent_reference metadata**. Foundry's backend requires `agent_reference` in the request body for proper dataset persistence. This field is **missing in agent-framework-foundry 1.2.2** but **added in 1.3.0** (released 2026-05-08, issue #5582 fix).

**Observed on SDK 1.2.2**:
- Foundry accepts the inline `file_content` dataset but fails to persist it as the expected asset (metadata shows `"expected_inline_dataset_id": "azureai://.../data/eval-data-.../versions/1"`)
- The backend clears the content array instead of transitioning the run to "failed", leaving it in perpetual "in_progress"
- HTTP logs show valid SDK POST body, but missing `agent_reference` field prevents proper processing

**Possible additional triggers** (if still fails on 1.3.0):
- Response field contains JSON-as-string; evaluators (coherence, fluency, relevance) may reject structured data during validation
- Backend asset persistence failure (RBAC issue, quota limit, service regression)
- Known Foundry bug with inline datasets in certain configurations

**Diagnostic steps**:
1. **Check SDK version first**: `pip list | grep agent-framework-foundry`
   - If 1.2.2 or earlier → upgrade to 1.3.0+ (see fix below)
   - If already 1.3.0+ → proceed with Foundry-side diagnostics
2. Enable HTTP debug logging (use `app.telemetry.foundry_http_debug` context manager)
3. Capture the POST request body and 201 response body
4. Check for `agent_reference` field in POST body — if missing and SDK <1.3.0, that's the bug
5. If present: Check metadata field for `"expected_inline_dataset_id"` — if present, Foundry is trying to create a dataset asset
6. Verify RBAC: Foundry project SAMI needs `Storage Blob Data Contributor` on the project storage account

**FIX (SDK 1.2.2 → 1.3.0)**: Update `pyproject.toml` with proper version constraint:

```diff
- agent-framework-core = "1.2.2"
- agent-framework-foundry = "1.2.2"
+ agent-framework-core = "^1.3.0"
+ agent-framework-foundry = "^1.3.0"
```

**Why this fixes it**: 1.3.0 adds `_build_agent_reference()` function and injects `agent_reference: {name, type, version}` in the request body for non-preview calls (SDK issue #5582). Foundry's backend needs this metadata to properly persist inline datasets.

**Why the bug happened**: Commit fe0b20c (2026-05-14) used bare `"1.2.2"` instead of `"^1.2.2"` or `"==1.2.2"`. Poetry/pip treats bare versions as **minimum constraints** (`>=1.2.2`), so:
- Local dev with `pip install .` resolved to 1.3.0 (latest)
- Cluster from cached image had 1.2.2
- No poetry.lock to enforce consistency

**Additional mitigation options** (if still fails on 1.3.0+):
1. **File Azure support ticket**: Include correlation_id, eval_id, run_id, and timeline from debug logs
2. **Test response format workaround**: Change system_prompt to return plain text instead of JSON-as-string to see if Foundry's evaluators reject structured responses
3. **Switch eval path**: Use trace-based eval (`evaluate_traces`) or target-based eval (`evaluate_foundry_target`) instead of dataset-based eval — both avoid inline `file_content`

**Workaround example** (plain-text response):
```python
# Before (JSON response — may trigger Foundry validation rejection):
instructions = "Classify the transaction. Respond with JSON: {\"category\": \"...\", \"confidence\": 0.9}"

# After (plain-text response):
instructions = "Classify the transaction. Respond with: 'Category: <name>, Confidence: <0.0-1.0>, Reasoning: <explanation>'"
```

If switching to plain text fixes it, confirms Foundry's coherence/fluency evaluators reject JSON-serialized responses during async validation.

**Citations**:
- `.squad/decisions/inbox/basher-eval-sdk-bisect.md` — SDK version constraint fix + 1.3.0 upgrade rationale
- `.squad/agents/basher/history.md` Session 2026-05-15c — SDK bisect investigation
- `.squad/decisions/inbox/basher-eval-foundry-backend-bug.md` — Original RCA with HTTP logs (SDK 1.2.2)
- Foundry HTTP logs correlation_id: `0dfe381709664089a1d3b4e409300a1a` (eval run `evalrun_a0e9fd3868bb43f583f8ee481115118b`, SDK 1.2.2)
- PyPI releases: 1.2.2 (2026-04-29), 1.3.0 (2026-05-08 00:09)
- SDK issue #5582: agent_reference injection fix

**Precedence**: If you encounter empty datasets, check Rung 10 (our bug) FIRST. Then check SDK version (Rung 11). Only escalate to Foundry support if SDK 1.3.0+ still fails and HTTP logs prove we sent valid data with agent_reference.
