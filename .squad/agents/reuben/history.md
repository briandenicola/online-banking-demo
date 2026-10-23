# Reuben — History

## Project Context
- **Project:** online-banking-demo
- **User:** Brian
- **Stack:** .NET 10/C#, Python/FastAPI, React/TypeScript, Cosmos DB, Redis, Docker Compose, Azure AKS
- **Joined:** 2026-09-17
- **Focus:** Deterministic controls, authority boundaries, canonicalization, source binding, and reconciliation

## Core Context
- Banker Copilot agents may propose and recommend but may not author authoritative decisions.
- `authority-service` owns the deterministic loan decision-control boundary for #382.
- POL-001..010 remain provisional until independently reviewed and ratified.
- Full canonical synthetic snapshots plus digests are persisted for the demo.
- A reconciliation mismatch invalidates the approval and requires a new proposal.
- Loan execution remains disabled until #383 provides durable workflow and idempotency rails.
- Reviewer rejection lockout applies: Reuben joined to independently revise Turk's rejected first #382 slice.

## Learnings
