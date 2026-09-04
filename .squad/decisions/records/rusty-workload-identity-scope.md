---
date: 2026-09-04
author: Rusty (Platform/Infra)
status: proposed
component: infra/identity
issue: 336
---

# Per-service workload identity — the pattern is established, the migration is not

## What

`authority-service` now has its own managed identity, its own Kubernetes service
account (`authority-workload-identity`), its own federated credential, and Cosmos
data-plane role assignments **scoped to the two authority containers** rather
than to the whole account. See `infra/cloud/identity-authority.tf`.

Every other service still shares `banking-services-mi` with account-scoped Cosmos
Data Contributor.

## Why only one service

Two reasons, and the second is the real one:

1. Re-identifying nine services in the same change is a large blast radius for a
   Phase 1 that has an unrelated exit criterion.
2. **The shared identity cannot simply be narrowed.** It currently holds
   account-scoped Cosmos Data Contributor because nine services share it; scoping
   it down requires knowing, per service, exactly which containers it touches.
   That is an audit, not a Terraform edit. Starting the new service narrow costs
   nothing; narrowing the old one is the actual work.

## What remains of #336

- Eight services still share one identity: user, account, transaction, transfer,
  ai, budget, chatbot, account-opening, plus event-processor and
  prompt-eval-service.
- The shared identity's Cosmos role assignment is still **account-scoped**. Until
  that is split, any pod using `banking-workload-identity` can read and write
  `copilot-approvals` directly. The authority-service identity is a positive
  control (it proves *who wrote*), not yet a negative one (it does not prevent
  others writing).
- A NetworkPolicy restricting `copilot-approvals` traffic does not help — Cosmos
  is reached over a private endpoint shared by the whole namespace.

**Honest assessment:** §4.4 layer 1 is now a control *for authority-service's own
identity*, and still a convention *for everyone else's access to the approval
store*. Closing that gap is the remaining bulk of #336 and should be sequenced
before anyone claims the approval store is isolated.

## Ask

Danny to confirm the incremental approach (one service at a time, narrow-on-
creation, audit-then-narrow for existing) rather than a big-bang re-identity, and
to decide whether the shared identity's account-scoped Cosmos grant is a Phase 1
blocker or a Phase 3 item alongside #334.
