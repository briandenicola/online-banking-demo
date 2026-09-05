# Decision: the co-sign queue's seniority bar is derived from policy, never written in code

**Author:** Turk (Backend Dev)
**Date:** 2026-09-05
**Branch:** `squad/332-phase3-supervisor`
**Status:** proposed — informational; closes a latent magic-number in the supervisor queue

## What happened

The "approvals awaiting a supervisor co-signature" queue (`ApprovalScope.AwaitingSupervisor`)
filters on a seniority bar: an approval appears only if its next unfilled slot demands a signer at
least that senior. Both repositories used to compute this as `awaitingSeniority >= 2`. That `2` is
a **seniority integer in code** — precisely the class of literal Brian forbids — and worse, it is a
*duplicate* of a fact that already has one ratified home: the seniority of `supervisor` in
`src/user-service/config/role-hierarchy.yaml`, reached via `rungs.L2.cosignerRoles`.

The failure mode is the quiet one. The day someone renumbers seniorities in `role-hierarchy.yaml`,
or points `L2.cosignerRoles` at a different role, the hardcoded `2` keeps the old value and the
queue silently shows the wrong population — either leaking approvals to under-senior reviewers or
hiding them from the right ones. Nothing would fail; the number would just be wrong.

## The ruling

`ApprovalService.ResolveAwaitingSeniority` fills the bar from the **live policy** before the query
reaches the repository:

```csharp
var cosignerRoles = policy.Rung(Rung.L2).CosignerRoles;
return query with { AwaitingSeniorityAtLeast = policy.MinimumSeniorityAmong(cosignerRoles) };
```

- No integer is written in code. The bar tracks `rungs.L2.cosignerRoles` through the ratified
  hierarchy — one source, the same one every signature slot already reads.
- It is **scoped**: only the `AwaitingSupervisor` scope acquires a bar. A "mine" listing that grew
  a seniority filter would hide a banker's own approvals, so the other scopes must stay bar-less.
- It is **fail-closed at two layers**. If `cosignerRoles` is empty the policy **loader refuses to
  start** ("an empty list is a slot with no bar, not a slot with a default bar"), and should a
  policy ever reach the service with an empty set another way, `MinimumSeniorityAmong` throws
  rather than returning `0` — a bar of 0 is one every authenticated principal clears.
- The repository itself **throws** if an `AwaitingSupervisor` query arrives with the bar still
  null, rather than guessing a literal. Three fail-closed gates, no silent default anywhere.

## How it's proven (and the tamper)

New suite `src/authority-service.UnitTests/SupervisorQueueSeniorityTests.cs` (5 tests) uses a
recording repository to observe the RESOLVED query the service hands down — so the assertion is on
the derived value, not on downstream filtering that could mask a wrong bar:

- shipped policy resolves the bar to `2` (supervisor), and to `policy.MinimumSeniorityAmong(...)`;
- moving `cosignerRoles: [supervisor]` → `[banker]` drops the bar to **1** — the test that would
  catch a reverted derivation;
- an explicit caller-supplied bar is left untouched;
- non-supervisor scopes acquire **no** bar;
- emptying `cosignerRoles` is refused at policy **load** (fail-closed at startup).

**Tamper record:** I replaced the derivation with a literal `AwaitingSeniorityAtLeast = 2`.
`Bar_follows_the_policy_when_the_cosigner_role_changes` failed (expected 1, got 2). Reverted;
all 5 green. (Note for the next agent: the revert used `mv`, which restored an older mtime than the
cached build — the test kept failing until I `touch`ed the file to force a rebuild. Same stale-cache
gotcha as the Python `.pyc` one in my history.)
