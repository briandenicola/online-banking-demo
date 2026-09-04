# Decision: the role model has one source, and this service is not it

**Author:** Turk (Backend Dev)
**Date:** 2026-09-04
**Branch:** `squad/332-banker-copilot`
**Status:** proposed — needs Danny to ratify item 3, and Rusty to confirm item 5

## What happened

`config/authority-policy.yaml` carried its own claim-to-seniority map. It disagreed with
`src/user-service/config/role-hierarchy.yaml` — the ratified model — in the two worst directions
simultaneously:

1. `banker.claimValues` listed `user` and `User`. The hierarchy gives `user` seniority 0 and
   describes it as *"Customer. No harness access at all."* My file promoted that same claim to
   seniority 1, so **a retail customer's token satisfied an L1 signature slot.**
2. `admin` was declared at seniority 3 — above supervisor — and listed in `L2.cosignerRoles`.
   §5.8 puts `admin` at 0, implying neither banker nor supervisor. So **one admin identity could
   fill both L2 slots** and dual control evaporated, with every existing test still green.

Both files were internally coherent. Rusty's tests lock `admin` out of banking authority and they
passed, because they test *his* file. Nothing compared the two. That is the whole lesson: this is
Danny's duplication rule one layer down, and the duplicated thing was the definition of who is
allowed to sign.

I also found the same class in two more places while auditing:

3. Cross-role claim aliases `manager`/`Manager` → `supervisor` and `administrator` → `admin`.
   Neither alias exists in the ratified hierarchy; each was a promotion granted by this file alone.
4. `capabilityScopes` listed `admin` on **every** scope including `transactions.read` and
   `identity.read`, making the platform role a superset for data access as well as for signing.
5. A `supervisor_seniority` threshold (default 2, env `POLICY_SUPERVISOR_SENIORITY`) supplied the
   L2 co-signature bar. That is the role model restated a *third* time, and being env-overridable
   it let an operator lower dual control to peer level by setting a number — no role file touched,
   no trace in the role model, no test failure.

## Decisions

**1. Seniority is consumed, never declared.** The loader reads `role-hierarchy.yaml` and stamps
seniority onto the resolved policy. Declaring `seniority:` under a signer role is now a startup
error, not an ignored key — an ignored key means the operator reads a number that is not in force.
Because the stamped value lands on the resolved document, `policyVersion` covers it: a change to
the hierarchy is a genuine ruleset change and moves the version, which is correct.

**2. A claim may only denote its own role.** Every `claimValue` must be a case variant of the
signer role's own name. This kills `user` → banker and both aliases structurally, rather than
relying on anyone noticing the next one.

**3. L3 is authority *outside* the ladder, not seniority *within* it — and they are now different
concepts.** Brian asked whether one `seniority` integer could carry both. It cannot, and trying to
make it is exactly what produced bug 2: to let `admin` act at L3, someone gave it a number, and a
number that beats supervisor's beats supervisor's *everywhere*, including at the L2 co-sign check.
So L3 now declares `outOfHarness: true` and `platformRoles: [admin]` with empty `signerRoles`, and
the loader rejects any in-harness rung listing a role with banking seniority < 1. **`admin` keeps
its L3 standing and loses everything else.** *This is the item I most want Danny to look at.*

**4. The L2 bar is derived, not tuned.** `defaults.supervisorSeniority` is retired and now a hard
loader error (rejected, not ignored — same reasoning as `distinctIdentities`). The co-signer bar is
computed as the minimum banking seniority among `rungs.L2.cosignerRoles`.

**5. The requester must hold banking standing.** Proposing was open to any authenticated principal.
A customer could therefore put an entry in a supervisor's queue that reads as though a banker had
raised it. `ProposeAsync` now requires the actor to clear the first slot's bar. Verified live: both
a `user` token and an `admin` token get 403 on propose.

## What Rusty needs to know

`role-hierarchy.yaml` is now a **runtime dependency of authority-service**. It is baked into the
image (`COPY src/user-service/config/role-hierarchy.yaml`) and pointed at by `ROLE_HIERARCHY_PATH`;
docker-compose mounts the same file read-only. If it is ever served from a ConfigMap, it must be
**the same object user-service reads** — two ConfigMaps with the same content is the bug we just
fixed, wearing a hat. Adding a role to the hierarchy is safe; changing an existing role's seniority
changes `policyVersion` and, by §5.3.2, re-evaluates every outstanding approval.

## What Livingston needs to know

Four of his fixture-driven tests and two of his role-model tests now fail, and I have deliberately
not edited his project:

- `TestPolicies/descending-escalators.yaml` declares `defaults.supervisorSeniority` (retired) and
  `signerRoles.*.seniority` (now rejected). Both need removing for the fixture to load.
- `ProductionRoleModelTests` asserts `admin` is a signer role with ascending seniority. That
  assertion encoded the vulnerable model; under §5.8 it should now assert the opposite.

His F-9 (`RaiseBy` overflow), F-1 (silent escalator grammar drift) and F-2 (stored-hash tautology)
are addressed. F-3 was already covered — `moneyFields ⊄ hashFields` was a loader error already, and
there is now a test saying so out loud.
