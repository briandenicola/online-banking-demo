# 2026-09-04T13:49:00Z — Banker Copilot epic ideation

**Session:** Banker Copilot epic ideation  
**Requested by:** Brian Denicola  
**Date:** 2026-09-04  

## Outcome: SUCCESS

### Converged Invariants

1. **Agents never approve.** All write/mutating actions carry a human signature. No L0 auto-execute tier. This earlier draft tier was SUPERSEDED.
2. **Authority ladder** (L1/L2/L3):
   - L1: acting banker signs
   - L2: supervisor agent produces independent second opinion; human supervisor co-signs (separation of duties)
   - L3: outside the harness; agent may not even propose
3. **Dynamic escalators** push UP only (self-dealing, bulk, velocity, low confidence, policy exception, high-risk customer, anomalous session).
4. **Configuration-driven thresholds**, never hardcoded.
5. **Approval durable objects** (proposed → pending → signed/denied/expired); TTL expiry = denied.
6. **Payload-hash signing** (RFC 8785 JCS); re-plan voids old signature.
7. **No blanket approve-all**; batch approval capped, single action type, under threshold, never L2.
8. **Delegated banker identity** plus explicit capability allowlist; Azure AI Foundry Agent Service runtime.
9. **Agentic/trajectory evaluation deferred.**

### Design Artifacts

- **Architecture:** Service topology enforces invariants (banker-copilot-service Python/FastAPI + authority-service .NET); four-layer bypass prevention; TTL lazy + sweeper, not destructive Cosmos TTL.
- **Backend:** Declarative policy YAML; 18 real actions; escalator monotonicity structural; approval store `/actorId` partition; payload hash with money-as-decimal strings + slot ordinality.
- **Frontend:** Three-pane work surface (task queue / trace / canvas); SSE over fetch + bearer auth; anti-fatigue mechanisms (dwell timers, batch caps, spot checks, meter); L2 disagreement as flagship screen.

### Critical Cross-Cutting Findings

1. **Single shared JWT audience** across all services (`banking-demo`) means no way to express service-to-service authorization boundaries. **Remediation:** introduce second `banking-copilot` audience for harness; requires splitting shared `banking-workload-identity` KSA for per-service mesh policy.
2. **nginx configs lack `proxy_buffering off`** (infra/local/gateway.nginx.conf, ui-app.nginx.conf). Without it, SSE trace streaming silently batches and "live" trace is a lie. **Highest-risk non-frontend dependency; needs owner now.**

### Escalations to Brian

Policy-version handling, JWT role model, L2 demo logistics, denial reasons, step-up auth substitute.

### Sequencing

Build against flagged transactions first (simplest, available today). Loans become showcase once #140 lands.
