# Coordinated Implementation Plan: Issues #135 + #136

**Date:** 2026-05-XX  
**Author:** Danny (Lead/Architect)  
**Branch:** `squad/135-136-account-opening-state-machine`  
**Status:** Awaiting Brian's review before implementation  

---

## 1. Decision: Schema Location

**Decision:** Extend the existing `account-applications` container document — do NOT create a new `account-opening-runs` container.

**Rationale:**
- The `cosmos-workflow-state` skill explicitly warns against splitting into a separate `*-runs` container:
  > "You'll end up doing cross-container reads for every UI poll, double-writing on every stage, and inviting casing/serialization drift across two repository classes."
- The existing `ApplicationResponse` model already holds `formData`, `agentResults[]`, `auditTrail[]`, and `documents[]` — all of which are workflow state.
- Adding `lastError`, `stageAttempts`, and `failedStage` fields to the same document keeps the read-path as a single point read (`container.read_item(item=id, partition_key=id)`).
- Cosmos partition key convention (from existing repo): PK = `/id` (application's own ID). This is already the pattern used by `CosmosDBApplicationRepository.get()`.

**Partition Key:** `/id` (unchanged — application document is its own partition key).

---

## 2. Cosmos Schema — Extended ApplicationResponse

```python
# Additive fields on ApplicationResponse (models/__init__.py)
class LastError(BaseModel):
    stage: str                      # e.g., "document_extraction"
    code: str                       # classified error code, NOT raw exception
    message: str                    # human-safe summary
    retryable: bool                 # false → UI hides Retry button
    occurredAt: datetime
    attempt: int
    correlationId: str | None = None

class ApplicationResponse(BaseModel):
    # --- Existing fields ---
    id: str
    status: ApplicationStatus
    createdAt: datetime
    updatedAt: datetime
    formData: dict[str, Any]
    documents: list[DocumentMetadata] = Field(default_factory=list)
    agentResults: list[AgentResult] = Field(default_factory=list)
    auditTrail: list[AuditEntry] = Field(default_factory=list)
    
    # --- New fields for #135 ---
    lastError: LastError | None = None
    stageAttempts: dict[str, int] = Field(default_factory=dict)  # stage → attempt count
    failedStage: str | None = None  # mirror of lastError.stage for query filters
    
    # --- New fields for #136 ---
    customerOutcome: str | None = None        # "approved" | "declined" | "needs_review"
    customerExplanation: str | None = None    # AI-generated customer-tone text
    customerExplanationGeneratedAt: datetime | None = None

# ApplicationStatus enum extension
class ApplicationStatus(str, Enum):
    submitted = "submitted"
    document_extraction = "document_extraction"
    identity_verification = "identity_verification"
    compliance_check = "compliance_check"
    approved = "approved"
    rejected = "rejected"
    pending_review = "pending_review"
    failed = "failed"  # NEW: recoverable terminal state
```

**JSON Shape (Cosmos document):**

```json
{
  "id": "abc123",
  "userId": "user-456",
  "status": "failed",
  "createdAt": "2026-05-14T10:00:00Z",
  "updatedAt": "2026-05-14T10:05:00Z",
  "formData": { "firstName": "Alice", "lastName": "Smith", ... },
  "documents": [...],
  "agentResults": [
    {
      "agentName": "document-extraction",
      "status": "completed",
      "confidence": 0.9,
      "findings": {...},
      "timestamp": "2026-05-14T10:01:00Z",
      "idempotencyKey": "abc123:document_extraction:1"
    },
    {
      "agentName": "identity-verification",
      "status": "failed",
      "confidence": 0.0,
      "findings": {},
      "timestamp": "2026-05-14T10:03:00Z",
      "idempotencyKey": "abc123:identity_verification:1"
    }
  ],
  "auditTrail": [...],
  "lastError": {
    "stage": "identity_verification",
    "code": "foundry_timeout",
    "message": "The identity verification service is temporarily unavailable. You can retry this step.",
    "retryable": true,
    "occurredAt": "2026-05-14T10:03:00Z",
    "attempt": 1,
    "correlationId": "req-789"
  },
  "stageAttempts": {
    "document_extraction": 1,
    "identity_verification": 1
  },
  "failedStage": "identity_verification",
  "customerOutcome": null,
  "customerExplanation": null,
  "customerExplanationGeneratedAt": null
}
```

---

## 3. Stage State Machine Diagram

```
                    ┌─────────────────────────────────────────────────────────────┐
                    │                                                             │
                    │  Any stage can fail → transition to "failed"                │
                    │  From "failed", POST /resubmit → resume from failedStage    │
                    │                                                             │
                    └─────────────────────────────────────────────────────────────┘

┌───────────┐     ┌───────────────────┐     ┌───────────────────────┐     ┌─────────────────┐
│ submitted │────▶│ document_extraction│────▶│ identity_verification │────▶│ compliance_check│
└───────────┘     └─────────┬──────────┘     └──────────┬────────────┘     └────────┬────────┘
                            │                           │                           │
                            │                           │                           │
                            ▼                           ▼                           ▼
                       ┌────────┐                  ┌────────┐                  ┌────────┐
                       │ failed │                  │ failed │                  │ failed │
                       └───┬────┘                  └───┬────┘                  └───┬────┘
                           │                           │                           │
                           │ POST /resubmit            │ POST /resubmit            │ POST /resubmit
                           │                           │                           │
                           ▼                           ▼                           ▼
                    ┌─────────────────┐         ┌─────────────────────┐    ┌─────────────────┐
                    │ doc_extraction  │         │ identity_verification│    │ compliance_check│
                    │ (resume)        │         │ (resume)             │    │ (resume)        │
                    └─────────────────┘         └─────────────────────┘    └─────────────────┘

                                                                                    │
                                                                                    ▼
                                                      ┌─────────────────────────────────────────┐
                                                      │                                         │
                                            ┌─────────┴───────────┬───────────────────┐         │
                                            ▼                     ▼                   ▼         │
                                      ┌──────────┐         ┌───────────┐        ┌────────────┐ │
                                      │ approved │         │ rejected  │        │pending_rev │◀┘
                                      └──────────┘         └───────────┘        └────────────┘
                                            │                     │                   │
                                            │                     │                   │
                                            └─────────────────────┴───────────────────┘
                                                                  │
                                                                  ▼
                                                    ┌──────────────────────────┐
                                                    │ Generate customerExplan  │
                                                    │ (one-shot, terminal only)│
                                                    └──────────────────────────┘

VALID_TRANSITIONS (state_machine.py addition):
- Any in-progress stage → "failed" (on exception in consumer)
- "failed" → resume from failedStage (via /resubmit endpoint only)
- Terminal states: approved, rejected, pending_review, failed
- Note: "failed" is recoverable via /resubmit; others are final
```

---

## 4. Idempotency Strategy

### Key Shape: `{applicationId}:{stage}:{attempt}`

Examples:
- `abc123:document_extraction:1`
- `abc123:identity_verification:2` (after one retry)

### Three-Layer Dedup (per cosmos-workflow-state skill)

| Layer | Mechanism | Implementation |
|-------|-----------|----------------|
| **Redis stream** | Consumer maintains `processed:{group}:{key}` SET, 24h TTL | In `AgentConsumer.process_one()`: check SET before processing; add to SET after success |
| **Cosmos agentResults** | `add_agent_result()` upserts by `idempotencyKey` | If result with same key exists, replace it (allows failed→completed transition cleanly) |
| **External API (Foundry)** | Use idempotency key as Foundry session ID prefix | `FoundryAgent.create_session(session_id=f"{idem_key}-session")` |

### Where Keys Are Stored and Checked

```python
# AgentConsumer base class (consumer.py)
class AgentConsumer(abc.ABC):
    STAGE_NAME: str  # Each consumer subclass sets this
    
    def _derive_idempotency_key(self, application_id: str, attempt: int) -> str:
        return f"{application_id}:{self.STAGE_NAME}:{attempt}"
    
    async def _is_already_processed(self, key: str) -> bool:
        return await self.redis.sismember(f"processed:{self.consumer_group}:{key}", key)
    
    async def _mark_processed(self, key: str) -> None:
        await self.redis.sadd(f"processed:{self.consumer_group}:{key}", key)
        await self.redis.expire(f"processed:{self.consumer_group}:{key}", 86400)  # 24h TTL
```

### Resubmit Increments Attempt

The `/resubmit` endpoint increments `stageAttempts[stage]` **before** publishing the resume event. This ensures each manual retry gets a fresh idempotency key, while accidental redelivery of the same message is dropped.

---

## 5. API Contracts

### 5.1 New Endpoint: POST `/api/account-opening/{applicationId}/resubmit`

**Auth:** Requires authenticated user (owner) OR admin role.

**Request:** Empty body (no payload needed)

**Pre-conditions:**
- Application status MUST be `"failed"`
- `lastError.retryable` MUST be `true`

**Response (202 Accepted):**
```json
{
  "applicationId": "abc123",
  "resumedFromStage": "identity_verification",
  "attempt": 2,
  "status": "identity_verification",
  "message": "Application resumed from identity_verification stage."
}
```

**Error Responses:**
- `404`: Application not found
- `403`: Not owner and not admin
- `409 Conflict`: Application status is not `"failed"`
- `422`: `lastError.retryable` is `false` — cannot retry

**Implementation Logic:**
1. Load application from Cosmos
2. Validate status == "failed" and lastError.retryable == true
3. Compute: `stage = lastError.stage`, `attempt = stageAttempts[stage] + 1`
4. Atomic update: clear `lastError`, set `failedStage = None`, bump `stageAttempts[stage]`, set `status` back to `stage`
5. Publish resume event with `idempotencyKey = "{applicationId}:{stage}:{attempt}"`
6. Return 202

### 5.2 New Endpoint: GET `/api/account-opening/{applicationId}/status`

**Auth:** Requires authenticated user (owner) OR admin role.

**Purpose:** Thin projection endpoint for customer UI polling. Returns only what the status screen needs — NOT the full document with formData and audit trail.

**Response (200 OK):**
```json
{
  "id": "abc123",
  "status": "identity_verification",
  "stages": [
    { "name": "Document Extraction", "status": "completed", "confidence": 0.9 },
    { "name": "Identity Verification", "status": "in_progress" },
    { "name": "Compliance Check", "status": "pending" },
    { "name": "Provisioning", "status": "pending" }
  ],
  "lastError": null,
  "customerOutcome": null,
  "customerExplanation": null,
  "updatedAt": "2026-05-14T10:03:00Z"
}
```

**For terminal states with explanation:**
```json
{
  "id": "abc123",
  "status": "rejected",
  "stages": [...],
  "lastError": null,
  "customerOutcome": "declined",
  "customerExplanation": "Based on our review, we're unable to open an account at this time. The identity verification step identified some discrepancies in the documents provided. You may reapply with updated documentation.",
  "updatedAt": "2026-05-14T10:10:00Z"
}
```

**Polling Cadence:** UI polls at 2-second intervals until terminal status. Stop polling on: `approved`, `rejected`, `pending_review`, `failed`.

---

## 6. Worker Changes (worker.py + agent consumers)

### 6.1 Mutation Points That Must Persist

Each consumer's `process_event()` method has these mutation points:

| Consumer | Stage | Mutation Points |
|----------|-------|-----------------|
| DocumentExtractionConsumer | document_extraction | `state_machine.transition()`, `agentResults.append()`, `repository.update()` |
| IdentityVerificationConsumer | identity_verification | `state_machine.transition()`, `agentResults.append()`, `repository.update()` |
| ComplianceCheckConsumer | compliance_check | `state_machine.transition()`, `agentResults.append()`, `repository.update()` |
| ProvisioningConsumer | provisioning | `state_machine.transition()`, `agentResults.append()`, account creation calls, `repository.update()` |

### 6.2 Try/Except Blocks That Must Record lastError

The failure path should be centralized in `AgentConsumer` base class (per skill guidance):

```python
# consumer.py — AgentConsumer.process_one() (modified)
async def process_one(self) -> int:
    messages = await self.redis.xreadgroup(...)
    for message_id, fields in entries:
        event_data = self._decode_fields(fields)
        application_id = event_data.get("data", {}).get("applicationId")
        
        # Derive idempotency key
        application = self._repository.get(application_id)
        if not application:
            continue
        attempt = application.stageAttempts.get(self.STAGE_NAME, 0) + 1
        idem_key = self._derive_idempotency_key(application_id, attempt)
        
        # Redis dedup check
        if await self._is_already_processed(idem_key):
            await self.redis.xack(self.stream_name, self.consumer_group, message_id)
            continue
        
        try:
            await self.process_event(event_data, idempotency_key=idem_key)
            await self._mark_processed(idem_key)
        except Exception as exc:
            # Classify and persist failure
            last_error = self._classify(exc)
            self._repository.set_failure(
                application_id=application_id,
                last_error=last_error,
                failed_stage=self.STAGE_NAME,
                attempt=attempt,
            )
            await publish_event(self.redis, "stage_failed", {
                "applicationId": application_id,
                "stage": self.STAGE_NAME,
                "error": last_error,
            })
        
        # ACK regardless — don't redeliver; let /resubmit drive retry
        await self.redis.xack(self.stream_name, self.consumer_group, message_id)
```

### 6.3 Error Classification

Each consumer subclass defines `STAGE_NAME` and optionally overrides `_classify()`:

```python
# Base implementation in AgentConsumer
def _classify(self, exc: Exception) -> LastError:
    """Maps exception → (code, message, retryable). Override in subclass for specifics."""
    if "timeout" in str(exc).lower():
        return LastError(code="timeout", message="Service temporarily unavailable", retryable=True, ...)
    if "403" in str(exc) or "401" in str(exc):
        return LastError(code="auth_error", message="Authentication error", retryable=False, ...)
    if isinstance(exc, ValueError):
        return LastError(code="validation_error", message="Invalid data", retryable=False, ...)
    return LastError(code="unknown", message="An error occurred", retryable=True, ...)
```

---

## 7. UI Plan

### 7.1 Admin Component Reuse Strategy

The `AdminApplicationsTab` already:
- Polls applications list
- Renders stages via `renderStages(application.stages)`
- Shows risk tier, status chips

**Customer screen reuse:** Extract the `AgentPipeline` + status rendering into a shared component that both admin and customer screens use. The customer version hides:
- Admin actions (Approve/Reject buttons)
- Raw reasoning text (engineering language)

Instead, customer version shows:
- `customerExplanation` (friendly text) on terminal status
- Retry button when `status === "failed"` and `lastError.retryable === true`

### 7.2 Polling vs SSE Recommendation

**Recommendation: Polling at 2-second intervals.**

Rationale:
- SSE adds infrastructure complexity (connection management, reconnect logic)
- Workflow takes 10-30 seconds typically; 15 polls × 2s = 30s coverage
- Cosmos RU cost is minimal: 2 RU × 15 polls = ~30 RU per workflow
- Stop polling on terminal status (existing logic in ApplicationStatus.tsx)

### 7.3 Customer Status Screen Component Shape

```tsx
// New component: CustomerApplicationStatus.tsx
interface CustomerStatusProps {
  applicationId: string;
}

const CustomerApplicationStatus: React.FC<CustomerStatusProps> = ({ applicationId }) => {
  const { data, loading, error, refetch } = useApplicationStatus(applicationId);
  
  // Poll until terminal
  usePolling(refetch, 2000, isTerminal(data?.status));
  
  return (
    <Card>
      <CardContent>
        <Typography variant="h5">Application Status</Typography>
        
        {/* Stage progress (reused from AgentPipeline) */}
        <AgentPipeline stages={data?.stages ?? []} />
        
        {/* Error state with Retry */}
        {data?.status === 'failed' && data?.lastError?.retryable && (
          <Alert severity="warning" action={
            <Button onClick={handleResubmit}>Retry</Button>
          }>
            {data.lastError.message}
          </Alert>
        )}
        
        {/* Terminal state with customer explanation */}
        {isTerminal(data?.status) && data?.customerExplanation && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="h6">
              {data.customerOutcome === 'approved' ? '🎉 Welcome!' : 'Application Update'}
            </Typography>
            <Typography>{data.customerExplanation}</Typography>
          </Box>
        )}
        
        {/* Collapsible stage breakdown */}
        <Accordion>
          <AccordionSummary>View Processing Details</AccordionSummary>
          <AccordionDetails>
            {data?.stages?.map(stage => (
              <StageDetail key={stage.name} stage={stage} />
            ))}
          </AccordionDetails>
        </Accordion>
      </CardContent>
    </Card>
  );
};
```

### 7.4 Where Customer-Tone Explanation Gets Generated and Stored

**Generation:** One-shot at finalization (when workflow reaches terminal state)  
**Storage:** On the application document as `customerExplanation` + `customerExplanationGeneratedAt`  
**Not regenerated on each view** — UI reads the stored text

---

## 8. AI Explanation Generation

### 8.1 Which Service Generates the Customer-Tone Text

**Decision:** `account-opening-service` worker generates the explanation in the `ProvisioningConsumer` (or a new finalization step) when the workflow reaches a terminal state.

**Rationale:**
- Keeps all workflow logic in one service
- Avoids adding cross-service HTTP call to chatbot-service
- The provisioning agent already has access to all context (formData, agentResults, decision)

### 8.2 Prompt Template Approach

Store the prompt template in the codebase (not Cosmos `prompt-templates` container) since it's workflow-specific:

```python
CUSTOMER_EXPLANATION_PROMPT = """
You are writing a customer-facing message for a bank account application.

Application outcome: {outcome}  # approved | rejected | pending_review
Risk assessment: {risk_tier}
Identity verified: {identity_verified}
Compliance flags: {flags}

Write a 2-3 sentence explanation for the customer that:
1. Uses friendly, plain English (no banking jargon)
2. Explains what happens next
3. If declined, provides an actionable suggestion without revealing internal assessment details
4. Never mentions specific risk scores, internal flags, or compliance codes

For approved: Welcome them and explain account activation.
For declined: Be empathetic, don't blame them, suggest next steps.
For pending review: Explain the timeline and that someone will be in touch.

Return ONLY the explanation text, no JSON wrapper.
"""
```

### 8.3 Storage on Run Document

```python
# In ProvisioningConsumer or new FinalizationConsumer
async def _generate_customer_explanation(self, application, decision: str) -> str:
    # Gather context
    context = {
        "outcome": decision,
        "risk_tier": self._extract_risk_tier(application),
        "identity_verified": self._extract_identity_result(application),
        "flags": self._extract_flags(application),
    }
    
    # Generate via Foundry
    prompt = CUSTOMER_EXPLANATION_PROMPT.format(**context)
    response = await self._agent.run(prompt, session=self._agent.create_session())
    
    return str(response).strip()

# After decision is made, persist explanation
application.customerOutcome = decision  # "approved" | "declined" | "needs_review"
application.customerExplanation = await self._generate_customer_explanation(application, decision)
application.customerExplanationGeneratedAt = datetime.now(timezone.utc)
self._repository.update(application)
```

---

## 9. Work Breakdown

### Phase 1: Backend Foundation (Basher) — ~2 days

| # | Task | Dependencies | Parallelizable |
|---|------|--------------|----------------|
| 1.1 | Extend `ApplicationResponse` model with `lastError`, `stageAttempts`, `failedStage`, `customerOutcome`, `customerExplanation`, `customerExplanationGeneratedAt` | None | ✅ |
| 1.2 | Add `"failed"` to `ApplicationStatus` enum | 1.1 | ✅ |
| 1.3 | Update `state_machine.py` with failed state transitions | 1.2 | ✅ |
| 1.4 | Add `set_failure()`, `clear_failure_and_increment_attempt()` to `CosmosDBApplicationRepository` | 1.1 | ✅ |
| 1.5 | Refactor `AgentConsumer` base class with idempotency + failure persistence | 1.4 | ❌ Blocks 1.6-1.9 |
| 1.6 | Update `DocumentExtractionConsumer` with `STAGE_NAME`, error classification | 1.5 | ✅ |
| 1.7 | Update `IdentityVerificationConsumer` with `STAGE_NAME`, error classification | 1.5 | ✅ |
| 1.8 | Update `ComplianceCheckConsumer` with `STAGE_NAME`, error classification | 1.5 | ✅ |
| 1.9 | Update `ProvisioningConsumer` with `STAGE_NAME`, error classification, customer explanation generation | 1.5 | ✅ |
| 1.10 | Add `POST /api/account-opening/{applicationId}/resubmit` endpoint | 1.4, 1.3 | ✅ |
| 1.11 | Add `GET /api/account-opening/{applicationId}/status` projection endpoint | 1.1 | ✅ |
| 1.12 | Update `projection.py` to include new fields in status projection | 1.11 | ✅ |

### Phase 2: UI Implementation (Linus) — ~2 days

| # | Task | Dependencies | Parallelizable |
|---|------|--------------|----------------|
| 2.1 | Add `failed` to `ApplicationStatus` type in `accountOpening.ts` | 1.2 deployed | ✅ |
| 2.2 | Add `resubmitApplication()` API call | 1.10 deployed | ✅ |
| 2.3 | Add `getApplicationStatus()` API call (thin projection) | 1.11 deployed | ✅ |
| 2.4 | Create `CustomerApplicationStatus.tsx` component | 2.1, 2.2, 2.3 | ❌ |
| 2.5 | Add Retry button to customer status screen when `status === "failed"` | 2.4 | ✅ |
| 2.6 | Add customer explanation rendering on terminal status | 2.4 | ✅ |
| 2.7 | Add collapsible per-stage breakdown | 2.4 | ✅ |
| 2.8 | Update `AccountOpeningPage.tsx` to use new status component | 2.4 | ✅ |
| 2.9 | Update `ApplicationStatus.tsx` to handle `failed` state | 2.1 | ✅ |

### Phase 3: E2E Tests (Livingston) — ~1 day

| # | Task | Dependencies | Parallelizable |
|---|------|--------------|----------------|
| 3.1 | E2E: Submit → stage failure → status shows failed with Retry button | 2.8 deployed | ❌ |
| 3.2 | E2E: Retry → workflow resumes → completes | 3.1 | ❌ |
| 3.3 | E2E: Terminal approved → customer explanation displayed | 2.8 deployed | ✅ |
| 3.4 | E2E: Terminal rejected → customer explanation displayed | 2.8 deployed | ✅ |
| 3.5 | Unit test: Idempotency — replay same Redis message → single agentResult entry | 1.5 | ✅ |
| 3.6 | Unit test: POST /resubmit on non-failed status → 409 | 1.10 | ✅ |

---

## 10. Out-of-Scope Reaffirmation

Per issues #135 and #136 scope:

| Excluded | Reason |
|----------|--------|
| Dapr/Temporal workflow engine | Both issues explicitly state "no Dapr/Temporal" |
| Automatic retry (exponential backoff) | #135 specifies "resubmit-on-error" is user-driven, not auto |
| Email/SMS notifications | Not mentioned in either issue |
| Admin override of non-retryable failures | Not in scope — admin can only approve/reject pending_review |
| Partial stage completion / checkpointing | Full-stage atomicity only |
| Real-time WebSocket/SSE push | Polling is sufficient per analysis |

---

## 11. Risks / Open Questions for Brian

### Open Questions

1. **Customer explanation tone review:** Should Brian review the prompt template before deployment, or is the implementation free to iterate?

2. **Failed state visibility to admin:** Should admin see failed applications in a separate tab, or mixed with pending_review? Current plan: mixed (filter by status).

3. **Retry limit:** Should there be a maximum retry count before auto-transitioning to a non-retryable terminal state? Current plan: unlimited retries (no cap).

4. **Explanation storage TTL:** Should customer explanations be trimmed after account activation (data minimization)? Current plan: persisted indefinitely.

### Risks

| Risk | Mitigation |
|------|------------|
| Foundry timeout during explanation generation delays terminal state persistence | Generate explanation asynchronously after persisting terminal status; UI shows generic message until explanation populated |
| Redis SET for idempotency keys grows unbounded | 24h TTL on SET keys; workflow completes in minutes, not days |
| Cosmos OR-pattern casing drift (per cosmos-casing-audit skill) | All new fields use camelCase; pin serializer in Python repo |

---

## Approval

**Awaiting Brian's sign-off before implementation begins.**

- [ ] Schema design approved
- [ ] API contracts approved
- [ ] Customer explanation prompt template approved
- [ ] Retry limit decision (unlimited OK? or cap at N?)
- [ ] Work breakdown prioritization confirmed

---

*Plan authored by Danny (Lead/Architect) — 2026-05-XX*
