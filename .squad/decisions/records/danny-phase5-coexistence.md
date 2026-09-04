---
date: 2026-09-04
author: Danny (Lead/Architect)
status: ratified
component: epic/banker-copilot
issue: 332
ruled_by: Brian Denicola
---

# Phase 5 is coexistence and comparison, not admin tab retirement

## Ruling

**Brian, 2026-09-04:** *"instead of Phase 5 being retirement. i want to keep the tabs around for
now to compare and contrast how the experience. let's put a feature flag into the code to
show/hide the pages"*

Phase 5 is rewritten as §8.5 of `docs/epics/banker-copilot.md`. The admin tabs stay; a runtime
feature flag shows/hides them.

## 1. This is a strength, and the epic now says so

The document has asserted since §1 that intent→plan→tools→artifact beats eight admin tabs.
**Until now that was rhetoric.** Retiring the tabs would have made the claim permanently
unfalsifiable, because the alternative would no longer exist to lose to. Keeping both makes it
testable, and Phase 5 stops being a deletion task and becomes **the only phase that produces
evidence**.

The bigger win is a **control group for §9 risk 1** — approval fatigue, which I still believe is
the real threat model here. The defence has always been "the harness must produce *fewer, better*
approvals," and "fewer than what?" had no answer. Now it does: fewer than the mutating clicks the
same banker makes doing the same work through the tabs. Added a measurement table (time to
complete, mutating actions, time-to-sign trend, context switches, read fan-out per customer,
after-the-fact reversals) with, for each, **the reading that would worry me** — because a metric
without a stated failure threshold is decoration.

**Committed in the doc to publishing unflattering results.** A demo that cannot lose is not a
demonstration. If the harness generates more signature events than the tabs generated clicks, we
have made the problem worse, and the phase built to find that out is the cheapest place to learn
it.

## 2. The honest tension, stated plainly

Keeping the tabs keeps **a write path that does not traverse the authority ladder**. A banker can
lock an account by clicking a tab: no policy evaluation, no rung, no payload hash, no signature.

**This does not violate I-1.** The invariant is that *agents* never approve. A human clicking an
admin tab is a human acting directly — no agent, no delegated identity, nothing proposing
anything. That is the situation the ladder constrains agents *into*, not one it was built to
prevent. The ladder governs agent-originated state change; direct human administration was never
in scope.

**What it does mean** is that *"every mutating action carries a policy-evaluated signature"* is
false, and no part of this epic may claim it. The true, narrower, still-valuable claim is: *every
action an agent originates carries a human signature bound to a payload hash, evaluated against a
versioned policy.* Phase 5 must not blur those. If we ever want the strong claim, the route is to
put the tabs through the broker too — a real option, and explicitly not what was ruled today.

## 3. Audit asymmetry — KNOWN AND ACCEPTED (amended same day)

> **Ruling (Brian, 2026-09-04):** *"since this is demo, i'm okay with that gap."*

My first draft of this record made audit parity between the tabs and the broker path a **hard
Phase 5 blocker** and filed #337 to enforce it. **Brian overruled that within the hour, and he is
right.** Retrofitting equivalent audit emission across the legacy admin surface is real work in
service of a control nobody exercises in a demo, and it is not what this epic is for. Parity is
**out of Phase 5 scope.** What remains is the documentation, not the implementation.

**The gap, verified and stated exactly (2026-09-04, `src/user-service/Services/UserService.cs`):**
the service publishes from exactly two paths — `PublishUserRegisteredEvent` and
`PublishRoleGrantedEvent`. `LockUserAsync`, `UnlockUserAsync`, `DeleteUserAsync` and
reset-password emit **nothing**. Those four *are* the admin tabs' entire mutating surface. So the
same operation is fully evidenced through the Copilot and invisible through the tab.

**Recorded as an accepted caveat, not an open risk — the distinction is the point.** An accepted
caveat is a decision; an open risk is a debt someone will feel obliged to pay down. It is written
into §8.5.3 dated and attributed alongside the other rulings, and deliberately **kept out of the
§9 risk register**, which is for things still undecided. **#337 is closed as accepted** rather
than left open, for the same reason — a closed issue with the reasoning attached is something a
maintainer can reopen deliberately.

**What we may therefore not claim.** Now an acceptance criterion:

- ~~"Every mutating action in this system is audited."~~ False. Four are not.
- ~~"The flag compares two equally governed surfaces."~~ False. It compares a governed surface
  against an ungoverned one. **The §8.5.1 comparison is about experience — time, clicks, context
  switches, approval volume — not about governance**, and the exit criterion no longer compares
  audit records.

The honest line, and the better demo line anyway: *the harness makes agent-originated change
attributable; the tabs never did, and turning the flag off does not make them so.*

**The sharpest cost, named rather than buried:** a banker who does L3 work through a tab has done
break-glass work and leaves **no record of it**. `user.delete` — the one action an agent may not
even *propose* — is on the tab path the least evidenced operation in the system. That sits next
to the caveat in §8.5.4, not inside it.

**Knock-on I had to fix, and it is the interesting part.** §8.5.5 originally argued that audit
parity was what made a *presentation-only* flag safe: it does not matter which surface a write
came from if both are equally attributable. **That argument evaporated with this ruling**, so I
rewrote the justification rather than leaving a dangling one. The honest version is narrower and
still sufficient: **the flag adds no exposure that did not already exist.** Those routes are
reachable and role-authorized today, before this epic; hiding navigation neither grants nor
removes access. The flag changes what a banker *sees*, never what a banker *may do*. And it is
now **more** important that nobody calls it a control, because unlike the earlier framing there
is no compensating control behind it either — a reader who mistook it for a boundary would be
wrong twice over.

**If this ever leaves demo status.** The four writes publish audited events at parity with the
existing `RoleGranted` shape (same stream, single-field XADD, PascalCase `eventType`, actor/
action/target), plus `case` arms in `event-processor`. **The reason it would become urgent is not
completeness — it is that an unaudited surface beside a governed one is an incentive:** under
heavy approval load the rational move becomes *"just use the other UI,"* and the ladder degrades
into an opt-in. In a demo nobody is under load, so the incentive is inert. In production it would
not be. That is the whole argument; no plan needed until then.

### 3.1 The published-but-unaudited check — noted only, per ruling

Rusty fixed two event types published to `banking-events` that fell through `event-processor`'s
`default:` branch (`UserRegistered`, `InsufficientFundsAttempt`). Asked whether any admin tab
write is in that same set.

**It is not, and the answer is unusually clean.** The tabs' complete mutating surface is three
call sites in `AdminUserManagementTab.tsx` — `DELETE /admin/users/{id}`,
`PUT /admin/users/{id}/{lock|unlock}`, `PUT /admin/users/{id}/reset-password`. Every other admin
tab (`AdminEvalTab`, `AdminChatbotPromptTab`, `AdminFoundryStatusTab`, `AdminLoginAuditTab`) is
**read-only**. All four writes are in the **never-published** set, not the published-but-unaudited
set — so Rusty's fix class does not overlap with them and extending his work would not have
reached them. **No action.**

## 4. Break-glass is a property of the action, not of the URL

The old plan made `/admin` the break-glass console for L3. With the tabs always present, that
definition collapses into "the other UI" and the L3 boundary becomes a navigation choice.

L3 is unchanged: deletes, role promotion, adverse action, and edits to the harness's own policy
stay outside the harness, with `agent_may_propose: false`. **That property belongs to the action,
not the surface, and no flag state alters it.** So: the tabs are not the break-glass console —
the L3 *actions* are break-glass, wherever performed. What distinguishes break-glass from
ordinary tab use is the evidence it generates (mandatory operator reason, elevated-severity
event, out-of-band notification, every occurrence reviewed), not which page hosts the button. A
banker who does L3 work through a tab has done break-glass work and the record must say so.

## 5. Flag semantics — decided

| Question | Ruling | Why |
|---|---|---|
| Runtime vs build-time | **Runtime**, config-served, no rebuild | The value is flipping mid-demo. Build-time makes it a tale of two deployments |
| Scope | **Per-user, global default** | A/B measurement needs two cohorts *at once*; global-only compares across time and confounds the result |
| Default | **Tabs ON** | Nothing that exists today may vanish because a flag failed to load |
| Config unreachable | **Tabs render** | Fail toward the status quo; a blank admin surface is a worse outage than a redundant one |
| Refuses routes? | **No — navigation only** | See below |

**NORMATIVE: presentation toggle, NOT a security control.** A hidden-but-reachable route is a UI
convention; the API behind it is unchanged, still authenticated, still role-authorized, still
reachable by typing the URL. If anyone reasons about "the tabs are hidden" as a control they will
be wrong, in the component where being wrong about a control costs most.

This is precisely why §3 is not optional: **audit parity is what makes it safe for the flag to be
merely presentational.** It does not matter which surface a write came from if both are equally
attributable. *Take the flag away and the audit still holds; take the audit away and the flag is
a fig leaf.* Making it refuse routes would also destroy its purpose — you cannot A/B two
experiences if one 403s, and a flag that is *sometimes* a control is worse than one that never
is, because it teaches people to trust it.

## 6. Knock-on effects

**§9 risk 14 (`AdminPage.tsx` used by demo scripts and Playwright) — largely defused**, rewritten
rather than deleted. Residual: the suite must run in **both** flag states, and specs that
navigate by clicking a tab link break when the flag is off (address routes directly). Because the
default is tabs-ON, an unmodified suite keeps passing, so it degrades from a migration to a
coverage gap.

**A new risk replaces it, and it is the one I would actually watch:** with retirement off the
table, **nothing now forces the Copilot surface to reach parity with the tabs.** Coexistence
removes the deadline that would have exposed a missing capability. "Saved views covering each
existing tab's job" (§8.5.6) is the mitigation and it is the easiest thing on the list to quietly
skip.

**§7.1 #140 seam — the supersession HOLDS and does not soften to "available behind the flag."**
It looks inconsistent, so the epic now states the reconciling rule:

- The **admin tabs already exist** and are already exercised. Keeping them costs a flag and buys
  a control group. There is a real comparison to be had.
- The **#140 decision panel does not exist yet.** Keeping it behind a flag means *building* a
  second review surface in order to hide it — speculative duplication of **the highest-risk
  surface we have, the one where a human signs.** Two places to sign a loan decision is two code
  paths that must both enforce the ladder, against a seam (§7.1) whose entire security property
  is that there is exactly one broker-only endpoint.

**The rule: coexistence applies to what already exists, not to what has not been built.** Retiring
working software to prove a point was the thing Brian's ruling corrected; declining to build a
second signing surface is not the same act. If Copilot-based loan review proves worse, build the
panel *then*, with evidence. **A follow-up comment on #140 is warranted** to confirm the boundary
did not move, since Turk may hear "coexistence" and reasonably infer that it did.

## 7. Assignments

- **Linus** — runtime flag scaffolding in `ui-app`, per-user with global default, tabs-ON
  default, fail-open. Navigation only; do not gate routes. Constraints in §8.5.5; coordinate via
  `docs/design/banker-copilot-ui.md`. I did not touch `src/ui-app/`.
- **Turk** — **no audit-parity work.** #337 is closed as accepted; do not build tab-side audit
  emission. Still do not build a #140 decision panel; the supersession stands.
- **Rusty** — **no follow-on work here.** Your `event-processor` coverage was the consumer half of
  a problem the tabs do not have (§3.1); the four admin writes are never-published, not
  published-but-unaudited, and by ruling they stay that way.
- **Me** — follow-up comment on #140 confirming the Phase 2 boundary is unchanged.
