# Decision — Banker Copilot: surface feature flags & comparison methodology

**From:** Linus (Frontend Dev)
**Date:** 2026-09-04
**Branch:** `squad/332-banker-copilot`
**Epic:** #332 Banker Copilot — Phase 5 (revised)
**Status:** implemented in `src/ui-app/`, proposed for ratification
**Supersedes:** the "phased retirement" fate column in `docs/design/banker-copilot-ui.md` §1.3

---

## Ruling this implements

Brian, 2026-09-04: *"instead of Phase 5 being retirement, i want to keep the tabs around for now
to compare and contrast how the experience. let's put a feature flag into the code to show/hide
the pages."*

Phase 5 changes from **admin tab retirement** to **coexistence**. Danny is amending the epic in
parallel; this document covers only the frontend.

---

## D1. Flag mechanism — five layers, first match wins

`ui-app` had exactly one frontend config idiom before today: `REACT_APP_DEMO_MODE` in
`pages/Login.tsx`, a CRA build-time env var. It is kept as a layer rather than replaced, with two
runtime layers added above it.

| # | Layer | Scope | Changed by | Survives |
|---|---|---|---|---|
| 1 | URL `?ff=bankerCopilot:on,classicAdminTabs:off` | one tab | sharing a link | tab close |
| 2 | `localStorage` | one browser | in-app toggle | reload |
| 3 | `window.__RUNTIME_CONFIG__` (`public/runtime-config.js`) | deployment | remounting the file | redeploy |
| 4 | `REACT_APP_FF_<UPPER_SNAKE>` | image | rebuild | rebuild |
| 5 | `FLAG_DEFINITIONS[].defaultValue` | code | a PR | — |

URL overrides mirror to **sessionStorage**, not localStorage: a link someone sends you must not
permanently reconfigure your browser.

## D2. Runtime, not build-time — with one caveat stated plainly

**Decision: runtime-toggleable**, as Brian leaned. Flipping the switch in the user menu re-renders
immediately — no rebuild, no redeploy, not even a reload. Switching surfaces live in front of an
audience works.

`runtime-config.js` is a **`.js` file loaded synchronously in `<head>`**, not a fetched
`config.json`. A fetch is async and would guarantee a flash of the wrong surface on every boot,
which is unacceptable for a flag whose only job is deciding which surface you see.

**Caveat, stated because it will otherwise be misunderstood:** layers 1–2 are *per-browser*. A
mid-demo flip changes your browser, not the deployment. Changing what a new visitor sees still
requires remounting layer 3. That is the correct split — a presenter should not be able to
reconfigure everyone's app by clicking a switch — but "runtime-toggleable" is true at two
different scopes and it is worth being precise about which one you mean.

## D3. Scope and defaults

**Global default per deployment, per-browser override.** No server-side per-user flag store; the
per-browser override *is* the assignment mechanism for the comparison.

| Flag | Default today | Default once Phase 2 lands |
|---|---|---|
| `classicAdminTabs` | `true` | **`true` — unchanged, and unchanged at Phase 5 too.** |
| `bankerCopilot` | `false` | **`true`** |
| `comparisonInstrumentation` | `true` | `true` |

`bankerCopilot` is false today only because the harness does not exist; a nav item pointing at an
empty route is worse than no nav item. It flips with Phase 2 so **both** surfaces are visible by
default — a comparison you have to opt into is a comparison nobody runs.

**Retiring the classic tabs is no longer a scheduled event.** It requires an explicit ruling
supported by the data in D5, not the passage of a phase.

The scheduled change is encoded as a `plannedDefaultChange` field on the flag definition, rendered
in the toggle panel, and asserted in a unit test. Three redundant reminders is proportionate for a
deferred default change, which is exactly the kind of decision that gets forgotten.

## D4. This is a PRESENTATION toggle, NOT a security control — and yes, hiding refuses routes

Stated in a module-level comment in `featureFlags.ts`, in the UI copy on the refusal notice, and in
design doc §10.5.

Every flag value comes from the browser: a query param, a `localStorage` entry, or a
world-readable JS file served to anonymous visitors. All three are user-controlled.

- Hiding a nav item hides a nav item. The destination is neither unreachable nor unauthorised.
- Refusing a route removes a React screen. **It does not remove the HTTP API behind it.**
- Turning a flag off protects nothing; turning it on grants nothing.

**Does hiding also refuse the route? Yes.** Flag-off hides the nav *and* refuses to render the
route. The reason is **experimental hygiene, not security**: a participant who wanders onto the
disabled surface mid-task contaminates the measurement.

The refusal screen is deliberately **loud and reversible** — it names the flag, says plainly that
this is a display setting rather than a permission check, and offers a button that turns the
surface back on. An authorisation failure would never hand you a button that fixes it. That
asymmetry is the design.

Both admin routes remain wrapped in `isAdmin` *in addition to* the flag. The two gates do
different jobs; the code says so at the point of use.

## D5. The comparison — pre-registered, and losable

Full methodology in design doc §11; implementation in `src/ui-app/src/telemetry/comparison.ts`.

**Metric directionality is encoded in code, not in a chart config.** Epic §9 risk 1 says a
*falling* time-to-sign is a defect, not adoption. That inverts the normal reading of a latency
metric, so every metric carries a `direction`, including a value named `lowerIsSuspicious`:

- `contextSwitchCount` — lower is better. **The core claim** ("tab-hunting across 7 tabs").
- `taskDurationMs`, `interactionCount` — lower is better.
- `signatureDwellMs`, `signaturesPerHour` — **lower is SUSPICIOUS.** Never presented as wins.
- `evidenceOpenRate` — higher is better (a proxy, not truth).
- `denialRate` — **neutral**, deliberately targetless.
- `reversalRate` — lower is better. The only outcome-quality metric in the set.

**Fair-comparison rules:** shared task set with identical `taskKey` across surfaces;
counterbalanced order per participant; metrics and tasks pre-registered before the harness exists;
blind outcome scoring for `reversalRate`; medians not means; no p-values at demo sample sizes.

**Anti-rigging measures, named because the person most likely to bias this is me:** the task set
deliberately includes `review-flagged-txn`, which is Classic Admin's *best* case (single tab, no
tab-hunting to remove) so the comparison can be lost; `taskDurationMs` is wall-clock and includes
agent latency; an agent-driven trace update is **not** a context switch; and
`exportComparisonData()` embeds `interpretationWarnings` in the payload so caveats travel with the
numbers.

**Committed falsifiers.** Any of these should stop the retirement conversation regardless of what
`taskDurationMs` did:

- `contextSwitchCount` does not fall materially → the core claim is wrong.
- `signatureDwellMs` falls or `signaturesPerHour` rises → **we built approval fatigue.**
- `reversalRate` rises → faster, worse decisions.
- `denialRate` collapses toward zero → the human step has stopped functioning.

---

## Absorbed corrections (no dissent)

- **`ApprovalState` is `proposed → pending → signed → executed`**, with `denied` the single
  terminal rejection carrying `terminalReason` of `HUMAN_DENIED | POLICY_RUNG_ESCALATED |
  PAYLOAD_SUPERSEDED | TTL_EXPIRED`. No `expired`, no `void`. Reconciled throughout the design
  doc and in `comparison.ts`.
- **`cosignerId` deleted.** The UI renders **"awaiting a supervisor"**, never "assigned to you",
  and shows no prospective-signer name, avatar, or picker anywhere. Naming a co-signer at proposal
  time would let a banker choose their own reviewer — the exact self-dealing L2 exists to prevent.
  Worth flagging to everyone: presentation can reintroduce a field the data model deliberately
  omits, so this needs watching in review, not just in types.

---

## Asks

### → Rusty (infra)

The app works with **no mount at all** (layer 5 supplies safe defaults), so this is an enhancement,
not a prerequisite. When convenient, mount `runtime-config.js` so deployment-level defaults can be
set without a rebuild:

```yaml
# docker-compose.yml — ui-app service
volumes:
  - ./infra/local/runtime-config.js:/usr/share/nginx/html/runtime-config.js:ro
```

```yaml
# deploy/kustomize/base/ui-app.yaml
volumeMounts:
  - name: runtime-config
    mountPath: /usr/share/nginx/html/runtime-config.js
    subPath: runtime-config.js
volumes:
  - name: runtime-config
    configMap:
      name: ui-app-runtime-config
```

The mounted file must set `window.__RUNTIME_CONFIG__ = { featureFlags: { ... } }`. Contents are
world-readable to anonymous visitors — **no secrets, ever**. `src/ui-app/public/runtime-config.js`
is the documented template.

Separately: thank you for the `proxy_buffering off` SSE block — that was the exact gap I flagged
in the design spike, and without it the "live" trace would have arrived as one lump.

### → Turk (backend)

One open contract item, unchanged from the design spike: I renamed the stream event
`approval.voided` → **`approval.terminal`**, carrying `state` and `terminalReason`. An event named
for a `void` state would reintroduce through the wire protocol the exact distinction §5.1.1
collapsed. This is a proposal, not a ratified contract — please confirm or counter.

### → Danny (spec)

Design doc §1.3 is rewritten for coexistence and §10/§11 are new; the epic's Phase 5 amendment and
this should agree. Two items that are arguably yours rather than mine:

1. **Who rules on retirement, and against what threshold?** I have committed falsifiers (D5) but
   deliberately not a success bar. Setting the bar after seeing the data is how this exercise
   produces a foregone conclusion.
2. **Comparison participants.** The methodology assumes a facilitated session with several people
   doing each task on both surfaces. If the realistic sample is two people, the honest output is
   qualitative findings plus directional numbers, and the doc should say so rather than implying a
   study we cannot run.

---

## Status of the build — honest limits

**Works:** flag resolution across all five layers; nav gating; route refusal; the mid-demo toggle
panel; comparison recorder with per-surface medians and embedded interpretation warnings;
`tsc --noEmit` clean; production build succeeds; **27 new tests pass**.

**Does not work yet, and should not be claimed:**

- **The comparison recorder has no call sites.** It is complete and tested but nothing calls it.
  Instrumenting Classic Admin alone before the harness exists produces a baseline nobody can
  check; both surfaces should be instrumented in one pass with identical counting rules.
- **No exporter.** Data is buffered in `sessionStorage` and exported by hand, so it dies with the
  tab. Fine for a facilitated session, wrong for passive collection over days. A backend contract
  for this is not mine to design.
- **`signaturesPerHour` and `reversalRate` are defined but not computed** — the first needs a
  session-duration denominator, the second needs joining to reversal events that do not exist yet.
- `/copilot` is a deliberate placeholder. It exists so the flag gates something real.

**Pre-existing, untouched by this work:** 13 tests fail in `AgentPipeline.test.tsx` and
`DocumentUpload.test.tsx` (verified by stashing this work and re-running on a clean tree —
identical failures), and a `react-hooks/exhaustive-deps` warning in
`components/account-opening/ApplicationStatus.tsx` (lines 115, 136) fails `CI=true` builds. Both
predate this branch and are outside this change's scope, but the eslint warning will block CI for
whoever adds a workflow.
