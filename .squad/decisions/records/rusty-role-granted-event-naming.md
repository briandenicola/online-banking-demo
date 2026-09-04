---
date: 2026-09-04
author: Rusty (Platform/Infra)
status: proposed
component: epic/banker-copilot
issue: 335
---

# `RoleGranted` — the role-grant audit event name diverges from the epic

## What

Epic §5.8.3 states: *"Every promotion emits `authority.role.granted` onto the audit
stream."*

I implemented it as **`RoleGranted`** (PascalCase) instead, published by
`user-service` onto `banking-events` in the standard `payload`-envelope form, and
added a matching case to the Go consumer.

## Why

`authority.role.granted` cannot work as written, and would have failed silently
rather than loudly:

1. **Every event already on `banking-events` is PascalCase.** Verified against
   the producers, not the docs: `TransactionCreated`, `InsufficientFundsAttempt`
   (transaction-service), `TransferInitiated` (transfer-service),
   `UserRegistered` (user-service). Turk's design §7.2 also specifies PascalCase
   for all eleven authority events (`ApprovalSigned`, `PolicyReloaded`, …).
   `authority.role.granted` would have been the only dotted name on the stream.

2. **The Go consumer switches on exact string equality.** A dotted name would
   land in the `default:` branch and log as `"Audit Unknown event type"` — i.e.
   the one event whose entire purpose is to prove a role grant was audited would
   have been the one event that was not. That is exactly the #335 failure mode,
   reintroduced by a naming slip.

3. **The dotted form reads like a policy action id, not an event.** Action ids in
   this epic are `<domain>.<entity>.<verb>` (`user.role.promote` is the L3 action
   id). Using the same shape for an audit event invites confusing the *action a
   policy governs* with the *record that it happened*.

## Impact if rejected

Trivial to reverse: one constant in `src/user-service/Constants.cs`, one `case`
in `src/event-processor/main.go`, one entry in the Go audit-coverage test. No
consumers depend on it yet.

## Ask

Danny to either ratify `RoleGranted` and correct epic §5.8.3, or rule the other
way and accept that the dotted form needs the Go consumer to grow a second
matching strategy.
