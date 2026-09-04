---
date: 2026-05-12
author: Linus (Frontend)
status: proposed
component: ui-app/copilot
issue: 332
phase: 2
---

# Phase 2 UI: the flag default flips, the comparison gets instrumented on both surfaces, and one
# endpoint I invented needs Turk's confirmation

## 1. The `bankerCopilot` flag default flips to `true`

Phase 1 encoded the flip as a typed `plannedDefaultChange` with a stated condition: *"when
/copilot renders a real harness rather than a placeholder."* That condition is now met — three
panes, a live trace over SSE, an approval card that shows the payload hash and gates the Sign
action. So the flip happens, in `featureFlags.ts` and `public/runtime-config.js` alike, and the
test that asserted "harness hidden today" is rewritten rather than deleted.

I want to be explicit that I considered *not* flipping it. The argument against is that
`banker-copilot-service` does not exist yet, so on a fresh environment the route opens and the
stream fails to connect. The argument for won, on two grounds:

1. **The surface degrades honestly.** With no service, the stream status reads *Disconnected*, the
   trace pane says the run continues on the server, and — critically — **signing is disabled**,
   because signing against a payload we cannot confirm is current is precisely the risk the payload
   hash exists to prevent. An empty harness is legible. It is not a broken page.
2. **A comparison you have to opt into is a comparison nobody runs.** Coexistence is the whole
   point of Phase 5 as re-scoped. If Classic Admin is on by default and the harness is not, the
   comparison data will be collected almost entirely from people who went looking for the harness —
   which is not a sample, it is a fan club.

**The flag remains a presentation toggle and not a security control.** It gates a route. Every
authority decision behind that route is made by `authority-service`, which has never heard of the
flag and would reject an ineligible signer whatever the frontend rendered. I have kept saying this
in comments because the failure mode — someone later treating the flag as an access control — is
silent, and Phase 1 already lost hours to a privilege escalation that lived in a seam nobody was
looking at.

## 2. Both surfaces are instrumented, in one pass, by one component

This is the Phase 1 carry-over discharged. The recorder had no call sites because I deliberately
refused to instrument the harness before Classic Admin existed to compare it against: whichever
surface you wire up while you are excited about it gets the careful counting, and the other gets
whatever you remember later. A "3.2× fewer interactions" number produced that way is marketing.

What I did instead of writing the rules twice: **the rules are written once**, in
`components/comparison/TaskMeasurementBar.tsx`, and both surfaces are wrapped in that same
component. Counting is done by delegated DOM events over the wrapped subtree. **Neither surface
contains a single call to the recorder** — `AdminPage.tsx` gained one attribute per tab, and
`CopilotHarness.tsx` one per pane, and nothing else.

That is a structural guarantee rather than a promise. It is not possible to instrument one surface
more finely than the other, because there is no counting code in either surface to add to. A test
asserts it mechanically.

The counting rules, stated so they can be argued with rather than discovered later:

- **Interaction** — one activation of an interactive element. Scrolling counts on neither surface.
  Typing counts once per *field*, not per keystroke; per-keystroke counting would make the harness
  lose by construction on a metric that means nothing, because the harness has a text command bar
  and Classic has forms.
- **Context switch** — the interacted element's declared region differs from the last one. A tab in
  Classic, a pane in the harness. A region is a place you must move your attention to; neither
  surface gets to draw the boundary more flatteringly than the other.
- **Evidence open** — activation of anything carrying `data-comparison-evidence`.
- **Decision** — reported explicitly, because only the surface knows dwell time and whether
  evidence was opened before signing.

`lowerIsSuspicious` on `signatureDwellMs` is untouched and remains pre-registered. It was written
down before any data existed precisely so a falling time-to-sign could not be reinterpreted as
efficiency afterwards. **Instrumentation existing is not a result.** Nobody should quote a number
from this until facilitated sessions have actually happened.

## 3. I invented a resync endpoint, then found Turk's real one — and it corrected a modelling error

The harness must recover when it detects a `seq` gap it cannot close from its buffer. I rebuild by
fetching the persisted envelopes and replaying them through **the same reducer** the live path uses,
which is the only recovery that cannot produce a state the live path could not have produced.

I initially assumed `GET /api/copilot/sessions/{sessionId}/events`. Turk's service landed in
parallel while I was working, so I read it rather than shipping the guess. The real endpoint is:

```
GET /api/copilot/runs/{runId}/trace  →  { runId, frameCount, traceDegraded, frames[] }
```

**A run is not a session, and that is the part worth recording.** `seq` is *run-scoped* — a session
with three runs has three independently replayable traces, not one. My session-scoped assumption
would have rebuilt one run's trace from another run's frames on every resync, and the result would
have looked plausible: a trace, in order, with the wrong contents. I have re-keyed gap detection,
the resync path, and the stream's `onResyncRequired` callback to carry the run id, and the client
now sends `?runId=` when attaching.

Two further things adopted from the real contract:

- **`traceDegraded` is propagated, not swallowed.** If the server could not persist every frame, the
  trace stays flagged INCOMPLETE even though the resync "succeeded". A recovered trace with holes is
  still a trace with holes, and the one thing this surface must never do is present one as a
  complete record to someone deciding whether to sign against it.
- **Starting a run is a separate call from opening a session.** A session is a container; the planner
  only moves on `POST /sessions/{id}/runs`. The UI opens the stream first and then starts the run —
  Turk's `await_next_run` handles that ordering deliberately, so attach-then-dispatch is the
  supported path rather than a race I am getting away with.

This is also a small vindication of the anti-duplication rule from §8.0: `/runs/{id}/trace` is the
same endpoint eval replay (#333) reads. One trace, one reader, no second definition to drift.

## 4. The wire contract does not match the design doc, and the wire won

I read `authority-service/Controllers/ApprovalsController.cs` rather than trusting the docs, as
asked. They disagree. The doc describes `opinions[]` and `signatures[]`; the service actually emits
`agentAssessment`, `signatureSlots`, `callerMaySign`/`callerMaySignReason`, `payloadHash` plus a
server-computed `payloadHashShort`, `policyVersion`, and structured `firedEscalators`.

The service is frozen and correct; the doc is stale. I mapped the real shape in exactly one place
(`api/authorityWire.ts`, `toApproval()`) so there is a single seam to fix when the doc catches up.
Two things there are deliberate and worth flagging:

- **`callerMaySign` is never inferred client-side.** Separation of duties is decided by the service
  holding the signing key. The client mirrors the answer so the banker learns the rule instead of
  discovering it as a 403, and mirrors `callerMaySignReason` so the rule is explained.
- **An unknown status, or a `denied` without a `terminalReason`, logs an error rather than being
  coerced into something renderable.** A silently mis-rendered terminal state is how a
  policy-driven void starts looking like a colleague rejecting your work.

`POST /execute` returning **409 `policy_rung_escalated`** is translated into that terminal reason
with its optional `replacement`, never into a generic failure.

## 5. Two corrections verified, not just assumed

- **Lifecycle** is `proposed → pending → signed → executed`, with `denied` the single terminal
  rejection state carrying one of four `terminalReason` values. No `expired`, no `void`. All four
  render as **distinct copy**, each leading with whether anything was executed, and three of them
  carry a `blameless` flag because a banker told "Denied" for a TTL expiry will go and ask a
  colleague why they rejected it. A test asserts the four are distinct and that none of the
  non-human causes renders as a bare "Denied".
- **`cosignerId` does not exist**, and the UI does not reintroduce it by another route. An unfilled
  slot renders a **rule** — "Awaiting a supervisor — must be a different person" — derived from the
  slot's own `minSeniority` and `mustDifferFrom`. Never a name, never "assigned to you". A test
  asserts no unfilled slot carries an identity.

## 6. What I did not build, and why

- **No batch approval, and no "Approve All" anywhere.** L1-only batching is Phase 3. Epic §9 risk #1
  is right that approval fatigue, not prompt injection, is the real threat: if a banker signs 40
  cards an hour, "human in the loop" is theatre and we have built a slower autonomous system with a
  liability shield.
- **The session meter pauses; it does not block.** A hard block gets worked around with a second
  browser tab, and the workaround is worse than the behaviour. Making the rate visible to the person
  producing it is most of the effect.
- **The undo window is config only.** Post-signature undo for reversible actions needs a
  service-side cancellation contract that does not exist. Rendering an Undo button that cannot
  actually stop execution would be a lie told at the worst possible moment.
