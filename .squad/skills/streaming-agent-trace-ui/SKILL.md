# Skill: Streaming Agent Trace UI (SSE-over-fetch + external store + coalesced aria-live)

## When to use

Any React surface that renders a **long-running server-side agent run** as it happens:
plan steps, tool calls, nested subagent fan-out, artifacts. Symptoms that you need this:

- You reached for `EventSource` and then discovered you cannot attach an `Authorization` header.
- The trace "goes live" only when the run finishes (everything arrives in one lump).
- Every incoming event calls `setState`, and a 300-node tree drops frames.
- You put `aria-live="polite"` on the trace container and a screen reader now narrates
  several hundred tool calls.
- A pending human approval silently mutated underneath the person about to sign it.

Reference design: `docs/design/banker-copilot-ui.md`.

## 1. Transport — SSE over `fetch`, not `EventSource`, not WebSocket

Native `EventSource` cannot set request headers. In this repo the bearer token lives in
`localStorage` and is attached by an axios interceptor (`src/ui-app/src/api/client.ts`), so
`EventSource` forces `?token=...` into the URL — which lands in nginx access logs, browser
history, and APM spans. Use `fetch` + `ReadableStream` + a small SSE frame parser:

```ts
const res = await fetch('/api/copilot/runs/stream', {
  method: 'POST',                                  // intent rides the opening request
  headers: {
    Authorization: `Bearer ${localStorage.getItem('auth_token')}`,
    Accept: 'text/event-stream',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ intent, lastSeq }),
  signal: abortController.signal,                  // real cancellation
});
const reader = res.body!.getReader();              // parse `id:`/`event:`/`data:` frames
```

Prefer this over WebSocket when traffic is overwhelmingly server→client and the rare
client→server actions are **high-stakes and discrete** (approve, sign, cancel). Those want
ordinary `POST` semantics: HTTP status codes, idempotency keys, retry, and — critically — reuse
of the existing axios interceptors (401 redirect, error normalisation via `api/errors.ts`).
Signing a high-value action over a fire-and-forget socket frame with no status code is a trap.

## 2. Infra gotcha that silently kills the whole feature

**nginx buffers by default.** If the proxy in front of your stream lacks these, the client sees
nothing until the run ends and the "live" trace is a lie:

```nginx
location /api/copilot/ {
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    chunked_transfer_encoding on;
}
```

Check `infra/local/gateway.nginx.conf` **and** the cloud ingress. Assign this an owner at design
time — it is invisible in local dev if you happen to bypass the gateway, and it surfaces during
integration week when it is expensive.

## 3. Event envelope — discriminated union with a monotonic `seq`

```ts
interface Envelope<K extends Kind, P> {
  id: string;
  seq: number;      // monotonic + gapless PER RUN — basis for dedupe, ordering, resume
  runId: string;
  kind: K;
  ts: string;       // SERVER clock; never trust the client clock for TTLs
  payload: P;
}
type AgentEvent = Envelope<'step.started', StepStarted> | Envelope<'tool.completed', ...> | ...;
```

Discriminating on `kind` in a union makes the reducer exhaustively type-checked: a new
server-side event kind without a client handler becomes a **compile error**, not a silent no-op.
That is the main reason to bother with the envelope type at all.

Rules:
- `seq <= lastSeq` → **drop** (reconnects legitimately replay).
- All reducer ops **idempotent** — upsert by node id, never push-append. Belt and braces.
- `seq > lastSeq + 1` → **gap**. Buffer (capped), request replay from `lastSeq`, drain when
  contiguous. Can't close it in ~5s → full snapshot refetch and hard reset.
  **Never render a known-incomplete trace as if it were complete.**
- Suppress entry animations while draining a resume (`isDraining` flag), or a reconnect produces
  a 200-node flash cascade.
- Heartbeat every ~15s; two missed → `degraded` → force reconnect. Without it, a half-open TCP
  connection is visually identical to "the agent is thinking" — the worst possible ambiguity.

## 4. Never let a dead stream look like a live one

- On non-`live` status, **running nodes stop pulsing and go static.** A pulse is a promise of
  liveness; it must not lie.
- Banner states the truth: *"Reconnecting — the run continues on the server."*
- **Disable any consequential action button while disconnected**, tooltip:
  *"Reconnecting — cannot verify this is still the current payload."* This is the TOCTOU window;
  don't let the UI reopen what the backend's payload-hash design closed.

## 5. Rendering performance — external store, not React state

At 50–200 events/sec, `setState`-per-event is a re-render storm. Pattern (no new dependency):

1. `dispatch(event)` mutates a plain object graph **outside** React.
2. Events land in a pending buffer; a single `requestAnimationFrame` tick applies them and bumps
   version counters — a burst of 40 events in 16ms produces **one** render pass. Skip the frame
   entirely when the tab is hidden.
3. **Per-node version counters.** Each node component subscribes to its own id via
   `useSyncExternalStore`, so a tool call completing inside step 3 re-renders step 3's subtree,
   not the run.
4. Narrow selector hooks only (`useTraceNode(id)`, `useApproval(id)`, `useStreamStatus()`). No
   component subscribes to whole state.
5. **One shared 1s ticker** broadcasting "now" to every countdown/elapsed timer. Twenty
   independent `setInterval`s across twenty rows is a classic own-goal.
6. Virtualise only above ~200 visible nodes — below that, `React.memo` beats the virtualiser's
   bookkeeping. Measure first.

`useSyncExternalStore` is in React 18+, is tearing-safe under concurrent rendering, and is the
React-blessed way to do exactly this. Don't add Redux/Zustand for one surface.

## 6. Pure reducer buys you a demo mode

Keep the reducer a pure `(state, event) => state`. You get:
- the entire event protocol testable with no network (feed a fixture array, assert the tree);
- a **deterministic fixture player** (`?demo=<id>`) that replays a recorded run with real timing.

Build the fixture player in week one. Never demo a streaming agentic system on a conference
network without it.

## 7. `aria-live` for a high-frequency trace — the part everyone gets wrong

Naive `aria-live="polite"` on the trace container announces every tool call and timer tick. The
screen-reader user turns it off, which is strictly worse than never having it.

**Rule: the visual region and the announced region are different regions.**

- Trace tree: `aria-live="off"`, `aria-busy="true"` while running, `role="tree"` /
  `role="treeitem"` with `aria-expanded` / `aria-level` / `aria-setsize` / `aria-posinset`.
  Explorable on demand, never auto-announced.
- Separate **visually-hidden** live region: `aria-live="polite"` `aria-atomic="true"`, fed
  **coalesced ~2500ms plan-level summaries** — one sentence per window
  ("Step 3 of 5, Underwrite, running. Four specialist agents started."). Never individual tool
  calls. Never timer ticks.
- `assertive` reserved for a tiny fixed set of genuinely interrupting events (e.g. approval
  required, approval voided, agent disagreement). Nothing else earns it.
- Countdowns: `role="timer"`, `aria-hidden` on the ticking digits, **discrete** announcements at
  5:00 / 1:00 / 0:30, plus a static text alternative ("Expires at 09:24 AM").
- `aria-busy="false"` + one polite summary on completion ("Run complete in 47 seconds, 12 steps").
- Never steal focus on an incoming event — announce instead. Yanking focus mid-read is how
  someone acts on the wrong item.
- `prefers-reduced-motion` disables stagger/flash/pulse; every status carries a glyph **and** a
  label so state is never conveyed by animation or colour alone.

## 8. Trace-tree UX details that are load-bearing

- **Ghost future steps at ~40% opacity.** Seeing the plan's shape before execution is what makes
  a re-plan legible — and it's the visual everyone remembers.
- **Never silently swap the list on re-plan.** Superseded steps strike through and collapse into
  a `Superseded (n)` group; new steps slide in with a one-shot highlight; stamp an inline
  `plan revised · v2 · "<reason>"` divider. Vanishing steps destroy trust.
- **Release follow-the-tail autoscroll on any user scroll-up**, offer a `↓ N new` pill. (The
  unconditional `scrollIntoView` in `src/ui-app/src/pages/Chat.tsx` is the anti-pattern.)
- Cap visual nesting at depth 3; flatten deeper behind a disclosure.
- A **proportional-width Gantt strip** (flexbox + percentage widths) makes parallel subagent work
  visibly parallel. Trivially cheap, disproportionately impressive.

## Related

- `docs/design/banker-copilot-ui.md` — full design, including the approval/dual-control UX.
- `.squad/skills/api-error-rendering/SKILL.md` — error normalisation for the non-streaming calls.
- `src/ui-app/src/components/account-opening/ApplicationStages.tsx` — the non-streaming ancestor
  of the trace node; reuse its status vocabulary, not its horizontal `Stepper` layout.
