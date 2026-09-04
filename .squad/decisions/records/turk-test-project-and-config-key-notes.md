---
date: 2026-09-04
author: Turk (Backend)
status: proposed
component: authority-service, tests
issue: 332
---

# Two test-project names, and the config keys that changed under me

Three small things I decided unilaterally and want on the record rather than discovered later.

## 1. `authority-service.UnitTests`, not `authority-service.Tests`

`src/authority-service.Tests/` already existed when I started — someone else's in-flight
spec-oracle work. Rather than merge into a project I do not own and risk trampling it, my unit
tests live in **`src/authority-service.UnitTests/`** (94 tests, all passing).

Two test projects against one service is not a state to leave things in. Someone should fold them
together once the spec-oracle work lands; I did not do it because deleting or restructuring
another agent's project mid-flight is exactly the kind of "helpful" change that loses work.

## 2. Denial config keys are `Denial__Reason*`, not `DENIAL_REASON_*`

My own earlier history entry promised `DENIAL_REASON_MIN_LENGTH` and friends in the manifests.
The implementation reads `Denial:ReasonMinLength` etc., which binds from `Denial__ReasonMinLength`
— the standard .NET double-underscore form, consistent with every other key in these services
(`Jwt__Key`, `CosmosDb__Endpoint`). I used the `Denial__` form and added those keys to
`deploy/kustomize/base/configmap.yaml`. Flagging because the earlier note is now wrong and
someone may go looking for the screaming-snake names.

`ReasonMaxRepeatUnit` is **8**, not the 4 I first wrote. At 4, with `ReasonMinDistinctChars` at 5,
the repeated-unit rule is mathematically unreachable — any repeat of a ≤4-character unit has ≤4
distinct characters, so the distinct-characters rule always fires first. A validation rule that
cannot fire is worse than an absent one: it reports enforcement it does not perform.

## 3. `Approval__SigningKey` needs a secret Rusty owns

The service **refuses to start** if `Approval__SigningKey` is absent or equal to `Jwt__Key`. A
bearer token must never be sufficient to forge an approval signature, and since issue #334 has
every service sharing one symmetric JWT key, "equal to the JWT key" would mean any service in the
mesh can mint approvals.

`deploy/kustomize/base/authority-service.yaml` therefore references
`secretKeyRef: { name: banking-secrets, key: authority-signing-key }`. **That key does not exist
yet.** Rusty owns Key Vault / the secret provider class — until it is created, the pod will
CrashLoopBackOff, which is the correct behaviour but will look like my bug.

Docker Compose supplies a local default and works today.
