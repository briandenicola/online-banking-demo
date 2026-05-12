# 006: Smart Account Opening — Multi-Agent KYC Pipeline

## Problem Statement

The online banking demo currently lacks a realistic account opening flow. New users are created via direct API calls (`POST /api/users/register`), but real-world banks require:

1. **Document verification** — Photo ID and proof of address must be uploaded and validated
2. **Identity cross-reference** — Extracted document data must match application form fields
3. **Compliance screening** — KYC (Know Your Customer) checks against risk rules and regulatory requirements
4. **Human-in-the-loop review** — Flagged applications must route to admin review queue
5. **Audit trail** — Every decision must be logged with reasoning for compliance

The application needs a multi-agent AI pipeline that orchestrates document extraction, identity verification, compliance screening, and automated provisioning — showcasing Azure AI Content Understanding, Foundry agents, and agent-to-agent coordination via Redis Streams.

## Goal

Build a **Smart Account Opening** feature with a multi-agent KYC pipeline that automates document processing, identity verification, and compliance checks. Applications that pass all checks are auto-approved; flagged applications route to the existing admin panel for human review. The feature demonstrates:

- **Azure AI Content Understanding** for document analysis and data extraction
- **Multi-agent orchestration** via Redis Streams (event-driven coordination)
- **Microsoft Agent Framework** for identity verification, compliance, and provisioning agents
- **Real-time UI** showing pipeline progress through each agent stage
- **Human-in-the-loop** admin review for flagged applications
- **Full audit trail** for regulatory compliance

## Requirements

### R1: Account Opening Service (Python/FastAPI)

**Decision: Python/FastAPI** — Aligns with existing AI-heavy services (ai-service, chatbot-service, budget-service). Python ecosystem has stronger Azure AI Content Understanding SDK support and matches the team's AI service patterns.

- New service: `account-opening-service` on port **8004**
- FastAPI with `azure-ai-projects>=2.1.0`, `azure-ai-documentintelligence`, `azure-storage-blob`, `agent-framework-foundry`
- Endpoints:
  - `POST /api/account-opening/applications` — Submit application with form data
  - `POST /api/account-opening/applications/{id}/documents` — Upload ID/proof of address (returns Azure Blob SAS URLs)
  - `GET /api/account-opening/applications/{id}` — Get application status and agent progress
  - `GET /api/account-opening/applications/{id}/audit` — Get full audit trail (admin only)
  - `GET /api/account-opening/applications` — List applications (admin only)
  - `PATCH /api/account-opening/applications/{id}/review` — Admin approve/reject (admin only)
- JWT authentication (admin role required for admin endpoints)
- Workload Identity for Azure Blob Storage, Content Understanding, and Foundry

### R2: Document Upload & Storage

- Application submission creates:
  - `account-applications` Cosmos DB container entry with state: `submitted`
  - Azure Blob Storage staging area: `account-opening-documents/{applicationId}/`
- User uploads documents (photo ID, proof of address) to Blob Storage via SAS URLs
- Document metadata stored in application record: `{ type: 'photo_id', blobUrl: '...', uploadedAt: '...' }`
- Uploaded documents trigger `document_uploaded` event to `account-opening-events` Redis Stream

### R3: Multi-Agent Pipeline — Event-Driven Orchestration

Four agents coordinate via Redis Streams:

#### Agent 1: Document Extraction Agent
- **Trigger:** `document_uploaded` event
- **Technology:** Azure AI Content Understanding (Document Intelligence)
- **Function:** Analyze uploaded documents, extract structured data (name, DOB, address, expiry, document number)
- **Output:** Publishes `document_extracted` event with structured data to `account-opening-events` stream
- **State transition:** `submitted` → `document_extraction`

#### Agent 2: Identity Verification Agent
- **Trigger:** `document_extracted` event (subscribes to stream)
- **Technology:** Microsoft Agent Framework (`agent-framework-foundry`) with GPT-5.4-mini
- **Function:** Cross-reference extracted data against application form, flag mismatches (name variations, expired ID, address discrepancies)
- **Output:** Publishes `identity_verified` event with `{ verified: true/false, confidence: 0.0-1.0, flags: [...] }` to stream
- **State transition:** `document_extraction` → `identity_verification`

#### Agent 3: Compliance/KYC Agent
- **Trigger:** `identity_verified` event (subscribes to stream)
- **Technology:** Microsoft Agent Framework (`agent-framework-foundry`) with GPT-5.4-mini
- **Function:** Evaluate risk tier based on:
  - Identity verification confidence score
  - Application data (income, employment, account type)
  - Compliance rules (jurisdiction requirements, age verification)
  - Simulated sanctions/PEP screening (mock data for demo)
- **Output:** Publishes `compliance_checked` event with `{ kycStatus: 'approved'|'review'|'rejected', riskTier: 'low'|'medium'|'high', reasoning: '...' }` to stream
- **State transition:** `identity_verification` → `compliance_check`

#### Agent 4: Account Provisioning Agent (Orchestrator)
- **Trigger:** `compliance_checked` event (subscribes to stream)
- **Technology:** Microsoft Agent Framework (`agent-framework-foundry`) with GPT-5.4-mini
- **Function:** Aggregates results from all agents and makes final decision:
  - **Auto-approve:** If `identity_verified=true` AND `kycStatus='approved'` AND `riskTier='low'`
    - Creates user via `POST http://user-service:8080/api/auth/register`
    - Creates account via `POST http://account-service:8080/api/accounts`
    - Sends welcome notification (mock for demo)
  - **Route to review:** If any flags exist OR `kycStatus='review'` OR `riskTier='medium'|'high'`
    - Adds to admin review queue (Cosmos DB flagged applications list)
  - **Auto-reject:** If `identity_verified=false` OR `kycStatus='rejected'`
    - Notifies user with rejection reason
- **Output:** Publishes `application_decision` event with final outcome
- **State transition:** `compliance_check` → `approved`|`rejected`|`pending_review`

**Orchestration Pattern:**
- Agents communicate asynchronously via Redis Streams (`account-opening-events`)
- Each agent subscribes to relevant events, processes, and publishes results
- Orchestrator (Agent 4) aggregates results and makes final decision
- No direct HTTP calls between agents — pure event-driven coordination
- Application state machine tracks progress through pipeline

### R4: Cosmos DB Container

New container: `account-applications`

**Schema:**
```json
{
  "id": "app-uuid",
  "userId": "usr-uuid",  // null until approved
  "accountId": "acc-uuid",  // null until approved
  "status": "submitted|document_extraction|identity_verification|compliance_check|approved|rejected|pending_review",
  "formData": {
    "firstName": "John",
    "lastName": "Doe",
    "dateOfBirth": "1990-01-01",
    "address": "123 Main St",
    "email": "john@example.com",
    "phone": "+1234567890",
    "employment": "Software Engineer",
    "annualIncome": 75000,
    "accountType": "checking"
  },
  "documents": [
    {
      "type": "photo_id",
      "blobUrl": "https://...",
      "uploadedAt": "2026-05-11T10:00:00Z",
      "extractedData": {
        "name": "John Doe",
        "dob": "1990-01-01",
        "documentNumber": "DL123456",
        "expiryDate": "2028-01-01"
      }
    },
    {
      "type": "proof_of_address",
      "blobUrl": "https://...",
      "uploadedAt": "2026-05-11T10:05:00Z",
      "extractedData": {
        "address": "123 Main St, City, State 12345"
      }
    }
  ],
  "agentResults": {
    "documentExtraction": { "status": "completed", "timestamp": "...", "data": {...} },
    "identityVerification": { "verified": true, "confidence": 0.95, "flags": [], "timestamp": "..." },
    "complianceCheck": { "kycStatus": "approved", "riskTier": "low", "reasoning": "...", "timestamp": "..." },
    "provisioning": { "decision": "approved", "userId": "usr-123", "accountId": "acc-456", "timestamp": "..." }
  },
  "auditTrail": [
    { "timestamp": "...", "agent": "document-extraction", "action": "extracted", "details": {...} },
    { "timestamp": "...", "agent": "identity-verification", "action": "verified", "details": {...} },
    ...
  ],
  "reviewedBy": "admin-user-id",  // null if not reviewed
  "reviewedAt": "2026-05-11T12:00:00Z",
  "reviewNotes": "Application approved after manual document review",
  "createdAt": "2026-05-11T09:00:00Z",
  "updatedAt": "2026-05-11T12:00:00Z"
}
```

**Partition key:** `/userId` (null until approved, use `id` for submitted applications)

### R5: Azure AI Content Understanding Integration

- **Resource:** Azure AI Document Intelligence (Content Understanding)
- **SDK:** `azure-ai-documentintelligence` Python package
- **Authentication:** Workload Identity via `DefaultAzureCredential`
- **Model:** `prebuilt-idDocument` for photo ID, `prebuilt-layout` for proof of address
- **Extraction:**
  - Photo ID: Name, DOB, document number, expiry date, address (if present)
  - Proof of address: Address, document date (utility bill, bank statement)
- **Error handling:** If extraction fails (poor image quality, unsupported format), flag for human review

### R6: Redis Streams Event Schema

**Stream:** `account-opening-events`

**Event types:**
1. `document_uploaded` — `{ applicationId, documentType, blobUrl }`
2. `document_extracted` — `{ applicationId, documentType, extractedData: {...}, confidence }`
3. `identity_verified` — `{ applicationId, verified, confidence, flags: [...], reasoning }`
4. `compliance_checked` — `{ applicationId, kycStatus, riskTier, reasoning }`
5. `application_decision` — `{ applicationId, decision, userId, accountId, reasoning }`

**Consumer groups:**
- `document-extraction-group` — Agent 1 consumes `document_uploaded`
- `identity-verification-group` — Agent 2 consumes `document_extracted`
- `compliance-group` — Agent 3 consumes `identity_verified`
- `provisioning-group` — Agent 4 consumes `compliance_checked`

### R7: Real-Time Progress UI

New page: `AccountOpeningPage.tsx` (route: `/account-opening`)

**User Flow:**
1. User clicks "Open New Account" from dashboard
2. Form wizard collects application data (personal info, employment, income)
3. User uploads documents (photo ID, proof of address)
4. Real-time progress indicator shows each agent's status:
   - ✓ Document Extraction — Completed
   - ⏳ Identity Verification — In Progress
   - ⏸ Compliance Check — Pending
   - ⏸ Account Provisioning — Pending
5. Final outcome displayed: "Application Approved!" or "Under Review" or "Application Rejected"

**Components:**
- `ApplicationForm.tsx` — Multi-step form (personal info → documents → review)
- `DocumentUpload.tsx` — Drag-and-drop file upload with preview
- `AgentPipeline.tsx` — Visual progress indicator (stepper with agent status)
- `ApplicationStatus.tsx` — Real-time polling of application status (WebSocket future enhancement)

**Polling pattern:** `GET /api/account-opening/applications/{id}` every 2 seconds during pipeline execution

### R8: Admin Review Queue

Extend existing Admin page (`AdminPage.tsx`) with new tab: **"Account Applications"**

**Features:**
- List all applications with status filter (all/pending_review/approved/rejected)
- Sort by date, risk tier, status
- Click application → detail view showing:
  - Application form data
  - Uploaded documents (thumbnail previews, click to view full)
  - Extracted data comparison table (form vs. documents)
  - Agent results (identity verification confidence, compliance reasoning)
  - Full audit trail
- Admin actions:
  - Approve → creates user + account via `PATCH /api/account-opening/applications/{id}/review`
  - Reject → marks application as rejected with notes
  - Request more info → flags for applicant follow-up (Phase 2)

### R9: Audit Trail & Compliance

Every agent action logged to `auditTrail` array in Cosmos DB:

```json
{
  "timestamp": "2026-05-11T10:15:23Z",
  "agent": "identity-verification",
  "action": "verified",
  "details": {
    "extractedName": "John Doe",
    "formName": "John Doe",
    "match": true,
    "confidence": 0.95,
    "model": "gpt-5.4-mini",
    "reasoning": "Name matches exactly, DOB matches, address matches with minor formatting differences"
  }
}
```

**Compliance requirements:**
- Immutable audit trail (append-only)
- Every decision includes agent reasoning (no black-box decisions)
- Document retention: 7 years (Azure Blob Storage lifecycle policy)
- PII handling: Encryption at rest (Cosmos DB + Blob Storage default)

### R10: Terraform Infrastructure

**New resources:**
1. **Azure Blob Storage Account** (Standard LRS)
   - Container: `account-opening-documents`
   - Lifecycle policy: Delete blobs after 7 years
   - Private endpoint (no public access)
2. **Azure AI Document Intelligence** (Content Understanding)
   - SKU: S0 (Standard)
   - Private endpoint
3. **Cosmos DB Container** (use existing database)
   - Container name: `account-applications`
   - Partition key: `/userId`
   - Throughput: 400 RU/s autoscale
4. **Managed Identity Role Assignments**
   - `account-opening-workload-identity` with roles:
     - `Storage Blob Data Contributor` (Blob Storage)
     - `Cognitive Services User` (Document Intelligence)
     - `Cosmos DB Built-in Data Contributor` (Cosmos DB)
     - `Cognitive Services OpenAI User` (Foundry)
5. **AKS Federated Identity Credential**
   - ServiceAccount: `account-opening-sa`
   - Namespace: `banking`

## Architecture

```
User (React UI)
    │
    ├─▶ POST /api/account-opening/applications
    │     (submit form data)
    │
    ├─▶ POST /api/account-opening/applications/{id}/documents
    │     (upload documents to Azure Blob via SAS URL)
    │     └─▶ Publishes: document_uploaded
    │
    └─▶ GET /api/account-opening/applications/{id}
          (poll status every 2s)

Redis Streams: account-opening-events
    │
    ├─▶ Agent 1: Document Extraction
    │     Consumes: document_uploaded
    │     Azure AI Content Understanding → extract name/DOB/address
    │     Publishes: document_extracted
    │     State: submitted → document_extraction
    │
    ├─▶ Agent 2: Identity Verification (Foundry GPT-5.4-mini)
    │     Consumes: document_extracted
    │     Compare extracted data vs. form data
    │     Publishes: identity_verified (confidence, flags)
    │     State: document_extraction → identity_verification
    │
    ├─▶ Agent 3: Compliance/KYC (Foundry GPT-5.4-mini)
    │     Consumes: identity_verified
    │     Risk assessment, compliance rules
    │     Publishes: compliance_checked (kycStatus, riskTier)
    │     State: identity_verification → compliance_check
    │
    └─▶ Agent 4: Account Provisioning (Orchestrator, Foundry GPT-5.4-mini)
          Consumes: compliance_checked
          Decision logic:
            ├─▶ Auto-approve → POST user-service, account-service
            ├─▶ Route to review → Add to admin queue
            └─▶ Auto-reject → Notify user
          Publishes: application_decision
          State: compliance_check → approved|rejected|pending_review

Cosmos DB: account-applications
    └─▶ Full application state + audit trail

Admin UI (AdminPage.tsx → "Account Applications" tab)
    ├─▶ List applications (status filter, sort)
    ├─▶ View application details + agent results
    └─▶ PATCH /api/account-opening/applications/{id}/review
          (approve/reject flagged applications)
```

## Non-Goals

- **Real-world sanctions/PEP screening** — Simulated with mock data for demo (Phase 2: integrate with third-party KYC APIs)
- **Document fraud detection** — Azure AI Document Intelligence provides extraction only; fraud detection requires advanced models (Phase 2)
- **WebSocket real-time updates** — Using polling (2s interval) for MVP; WebSocket streaming can be added later
- **Biometric verification** — No liveness detection or facial recognition (requires specialized SDKs)
- **Automated prompt deployment** — Admins manually adjust agent prompts via config (prompt-eval-service integration in Phase 2)
- **Red teaming** — Security testing via `azure-ai-evaluation` red team capabilities deferred to Phase 2

## Existing Infrastructure

- **Redis Streams:** Already provisioned and used by ai-service for transaction events (`banking-events` stream)
- **Cosmos DB:** Existing database `leading-terrier-26956-cosmos` — add new container
- **Foundry endpoint:** `FOUNDRY_PROJECT_ENDPOINT` already configured (chatbot-service uses it)
- **Model:** `gpt-5.4-mini` already deployed and accessible
- **Workload Identity:** Pattern established for all Python services (chatbot, ai-service, budget-service)
- **Istio routing:** `/api/account-opening` route will be added to VirtualService
- **JWT authentication:** Existing middleware validates JWT; admin role already implemented
- **Admin panel:** Existing `AdminPage.tsx` — add new tab for applications

## Phase 2: FabricIQ Data Agent Integration

After MVP, integrate **Microsoft Fabric Data Agent** for business analytics over application data:

**Use cases:**
1. **Application conversion analytics** — "What percentage of applications are auto-approved vs. flagged for review?"
2. **Risk tier distribution** — "Show me the breakdown of low/medium/high risk applications by income bracket"
3. **Document quality trends** — "What's the average extraction confidence score by document type?"
4. **Agent performance monitoring** — "Track identity verification false positive rates over time"

**Implementation:**
- Create Fabric workspace with semantic model over `account-applications` Cosmos DB container
- Build Data Agent using Microsoft Fabric + agent-framework
- Expose via MCP server for interoperability with other AI agents
- Add analytics tab to admin UI with natural language query interface

**Benefits:**
- Natural language queries over application data (no SQL required)
- Proactive insights (e.g., "High rejection rate spike detected — investigate compliance agent")
- Integration with Power BI for executive dashboards

## API Contracts

### POST /api/account-opening/applications

**Request:**
```json
{
  "firstName": "John",
  "lastName": "Doe",
  "dateOfBirth": "1990-01-01",
  "email": "john@example.com",
  "phone": "+1234567890",
  "address": "123 Main St, City, State 12345",
  "employment": "Software Engineer",
  "annualIncome": 75000,
  "accountType": "checking"
}
```

**Response (201):**
```json
{
  "applicationId": "app-uuid",
  "status": "submitted",
  "uploadUrls": {
    "photoId": "https://blob.../sas-token",
    "proofOfAddress": "https://blob.../sas-token"
  },
  "expiresAt": "2026-05-11T11:00:00Z"
}
```

### POST /api/account-opening/applications/{id}/documents

**Request (multipart/form-data):**
```
documentType: "photo_id" | "proof_of_address"
file: <binary>
```

**Response (200):**
```json
{
  "applicationId": "app-uuid",
  "documentType": "photo_id",
  "blobUrl": "https://blob.../document.jpg",
  "status": "uploaded"
}
```

### GET /api/account-opening/applications/{id}

**Response (200):**
```json
{
  "applicationId": "app-uuid",
  "status": "identity_verification",
  "formData": { "firstName": "John", ... },
  "documents": [
    { "type": "photo_id", "blobUrl": "...", "uploadedAt": "..." }
  ],
  "agentProgress": {
    "documentExtraction": { "status": "completed", "timestamp": "..." },
    "identityVerification": { "status": "in_progress", "timestamp": "..." },
    "complianceCheck": { "status": "pending" },
    "provisioning": { "status": "pending" }
  },
  "decision": null,
  "createdAt": "2026-05-11T09:00:00Z",
  "updatedAt": "2026-05-11T10:15:00Z"
}
```

### PATCH /api/account-opening/applications/{id}/review (Admin only)

**Request:**
```json
{
  "action": "approve" | "reject",
  "notes": "Application approved after manual document review"
}
```

**Response (200):**
```json
{
  "applicationId": "app-uuid",
  "status": "approved",
  "userId": "usr-123",
  "accountId": "acc-456",
  "reviewedBy": "admin-user-id",
  "reviewedAt": "2026-05-11T12:00:00Z"
}
```

## Dependencies

### Python Packages (account-opening-service)
- `fastapi` — Web framework
- `azure-ai-projects>=2.1.0` — Foundry agent framework
- `azure-ai-documentintelligence` — Content Understanding SDK
- `azure-storage-blob` — Blob Storage SDK
- `azure-cosmos` — Cosmos DB SDK
- `azure-identity` — Workload Identity authentication
- `redis` — Redis Streams client
- `agent-framework-foundry` — Microsoft Agent Framework
- `pydantic` — Data validation

### Infrastructure
- Azure Blob Storage (Standard LRS)
- Azure AI Document Intelligence (S0)
- Cosmos DB container (existing database)
- Managed Identity + Federated Credential
- Istio VirtualService route

### Dependent Services
- `user-service` — User creation on approval
- `account-service` — Account creation on approval
- `ai-service` — Pattern reference for Redis Streams integration

## Success Metrics

- **Auto-approval rate:** >70% of applications auto-approved without human review
- **False positive rate:** <10% of auto-approved applications flagged retroactively
- **Pipeline latency:** 95th percentile <30 seconds from upload to decision
- **Document extraction accuracy:** >95% confidence on structured fields (name, DOB, address)
- **Admin review efficiency:** 50% reduction in manual data entry (pre-filled from extraction)

## Security & Privacy

- **PII encryption:** Cosmos DB + Blob Storage encrypted at rest (Azure platform default)
- **Access control:** JWT authentication, admin role required for review endpoints
- **Audit trail:** Immutable log of all agent decisions with reasoning
- **Document retention:** 7-year lifecycle policy (regulatory compliance)
- **Private endpoints:** No public access to Blob Storage or Document Intelligence
- **SAS token expiry:** 1-hour time-bound upload URLs
- **No cross-user data access:** Application queries filtered by userId or admin role

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Document extraction failure** | User stuck in pipeline | Graceful degradation: flag for manual review, retry logic with exponential backoff |
| **Agent hallucination** | Incorrect identity verification | Structured output (JSON mode), confidence thresholds (reject if <0.8), human review for edge cases |
| **Redis Stream lag** | Delayed pipeline execution | Consumer group tracking, dead-letter queue for failed events, monitoring/alerting on lag |
| **Blob Storage outage** | Documents not accessible | Retry logic, fallback to admin manual upload, status page notification |
| **Compliance drift** | Regulatory violations | Periodic compliance rule reviews, A/B testing via prompt-eval-service, red teaming (Phase 2) |

## Testing Strategy

1. **Unit tests:** Agent logic (identity verification, compliance rules), event handlers
2. **Integration tests:** End-to-end pipeline (submit → upload → agents → decision)
3. **Mock data:** Synthetic applications with known outcomes (auto-approve, flag for review, reject)
4. **Document fixtures:** Sample IDs (driver's license, passport), utility bills for extraction testing
5. **Load testing:** Concurrent applications (Redis Streams scalability)
6. **Adversarial testing:** Poor quality documents, mismatched data, edge cases (Phase 2: red teaming)

## Rollout Plan

1. **Phase 1 (MVP):** Core pipeline (4 agents, document upload, admin review) — 3 sprints
2. **Phase 2:** FabricIQ Data Agent for analytics, red teaming, prompt evaluation integration — 2 sprints
3. **Phase 3:** WebSocket real-time updates, fraud detection models, third-party KYC API integration — 3 sprints

---

**References:**
- [Future AI Capabilities — Multi-Agent Orchestration](../../docs/future-ai-capabilities.md#1-multi-agent-orchestration)
- [Spec 002: AI-Powered Anomaly Detection](../002-ai-anomaly-detection/spec.md)
- [Spec 005: AI Admin Portal](../005-ai-admin-portal/spec.md)
