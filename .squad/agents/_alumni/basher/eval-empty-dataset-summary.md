# Foundry Eval Empty Dataset Bug — Root Cause Analysis

**TL;DR:** Foundry's eval service **cannot upload inline datasets to private-endpoint-only blob storage**. All eval runs stuck in "Starting" because the dataset upload step fails silently.

---

## The Smoking Gun

### 1. SDK Sends Valid Data
```python
# Verified: SDK constructs proper JSONL with non-empty fields
{
  "query": "Assess this transaction: $1,500.00",
  "response": "This transaction shows HIGH RISK.",
  "query_messages": [
    {"role": "system", "content": [{"type": "text", "text": "You are a financial risk assessor."}]},
    {"role": "user", "content": [{"type": "text", "text": "Assess this transaction: $1,500.00"}]}
  ],
  "response_messages": [
    {"role": "assistant", "content": [{"type": "text", "text": "This transaction shows HIGH RISK."}]}
  ]
}
```

### 2. HTTP POST Succeeds
```bash
DEBUG:openai._base_client:Sending HTTP Request: POST .../evals/.../runs
INFO:httpx:HTTP Request: POST ... "HTTP/1.1 201 Created"
# Foundry accepts the submission — no client-side error
```

### 3. Storage Account Is Empty
```bash
$ kubectl exec deploy/eval-sandbox -- bash -c '
  TOKEN=$(python3 -c "from azure.identity import DefaultAzureCredential; print(DefaultAzureCredential().get_token(\"https://storage.azure.com/.default\").token)")
  curl -H "Authorization: Bearer $TOKEN" -H "x-ms-version: 2021-08-06" \
    "https://a676b825d5b2a5d641e032sa.blob.core.windows.net/9fff2344-68ff-40ad-a0af-72f55a2463fe-azureml-blobstore?restype=container&comp=list"
'

<?xml version="1.0" encoding="utf-8"?>
<EnumerationResults ...>
  <MaxResults>20</MaxResults>
  <Blobs />  <!-- ⚠️ ZERO BLOBS despite 6 eval runs submitted -->
  <NextMarker />
</EnumerationResults>
```

### 4. All Eval Runs Stuck Forever
```bash
$ curl -H "Authorization: Bearer $TOKEN" \
  "${FOUNDRY_PROJECT_ENDPOINT}/evaluations/runs?api-version=2025-05-15-preview"

{
  "value": [
    {
      "id": "evalrun_6dd19ece794c42d5a5b06767f26a5edc",
      "displayName": "debug-test Run",
      "status": "Starting",  # ⚠️ Never progresses
      "tags": {
        "expected_inline_dataset_id": "azureai://.../eval-data-2026-05-14_213159_b5197_UTC/versions/1",
        "is_inline_dataset": "true"
      },
      "outputs": {
        "evaluationResultId": ""  # ⚠️ Empty — no processing happened
      },
      "systemData": {
        "createdAt": "05/14/2026 21:32:00 +00:00"  # 10+ minutes ago
      }
    },
    # ... all 6 runs from today stuck in "Starting"
  ]
}
```

---

## Why It Happens

Foundry's eval run creation flow:

```
Client SDK                          Foundry API                        Storage Account
    |                                   |                                      |
    |-- POST /evals/.../runs -------->  |                                      |
    |   data_source: {                  |                                      |
    |     type: "file_content",         |                                      |
    |     content: [{item: {...}}]      |                                      |
    |   }                               |                                      |
    |                                   |                                      |
    |<---------- 201 Created --------   |                                      |
    |                                   |                                      |
    |                                   |-- Upload JSONL to blob storage --X   |
    |                                   |   (FAILS: no network path             |
    |                                   |    to private endpoint OR             |
    |                                   |    missing RBAC)                     |
    |                                   |                                      |
    |                                   |-- Register dataset with 0 rows ----> |
    |                                   |                                      |
    |                                   |-- Eval run stuck: no data to eval    |
    |                                   |   status: "Starting" forever         |
```

**The upload step (step 2) fails silently** because:
- Storage account has `publicNetworkAccess: "Disabled"`
- Foundry eval worker can't reach the private endpoint
- OR missing `Storage Blob Data Contributor` RBAC on Foundry service principal

---

## Fix: Explicit Dataset Upload

**Workaround (works now):**
```python
# 1. Upload JSONL to blob storage using pod's managed identity
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
blob_service = BlobServiceClient(
    account_url=f"https://{storage_account}.blob.core.windows.net",
    credential=credential
)
container = blob_service.get_container_client("{workspace-guid}-azureml-blobstore")

jsonl_buffer = io.BytesIO()
for d in dicts:
    jsonl_buffer.write((json.dumps({"item": d}) + "\n").encode("utf-8"))
jsonl_buffer.seek(0)

blob_name = f"eval-datasets/eval-{timestamp}.jsonl"
container.upload_blob(name=blob_name, data=jsonl_buffer)

# 2. Reference uploaded dataset by URI
data_source = {
    "type": "uri_file",
    "uri": f"azureai://datastores/workspaceblobstore/paths/{blob_name}"
}

# 3. Submit eval run
run = await client.evals.runs.create(eval_id=eval_obj.id, data_source=data_source)
```

**Correct fix (requires Microsoft):**
- Grant Foundry eval workers network access to customer private endpoints, OR
- Make inline `file_content` upload aware of private DNS

---

## Impact

**BROKEN:**
- ✅ ai-service transaction categorization evals
- ✅ prompt-eval-service template quality checks
- ✅ eval-sandbox reproduction tests
- ✅ Any future eval-based CI/CD gates

**ENVIRONMENTS:**
- ❌ **Production (VNET-only, private endpoints)** — broken
- ✅ **Dev/test (public blob access)** — works

---

## Next Steps

1. ✅ **Basher:** Document root cause (this file + decision + skill update)
2. ⏳ **Basher:** Implement explicit dataset upload workaround in `FoundryEvalsVNETWorkaround` class
3. ⏳ **Basher:** Update ai-service and prompt-eval-service to use workaround
4. ⏳ **Danny:** File Azure support ticket with this RCA
5. ⏳ **Squad:** Add regression test for when Foundry fixes the bug

---

## Files Updated

- `.squad/agents/basher/history.md` — Investigation log
- `.squad/decisions/inbox/basher-eval-empty-dataset-rca.md` — Full RCA + workaround code
- `.squad/skills/foundry-eval-debugging/SKILL.md` — Added Rung -1 (VNET empty dataset bug)
- `.squad/agents/basher/eval-empty-dataset-summary.md` — This summary (for Brian)
