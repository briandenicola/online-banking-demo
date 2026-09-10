---
date: 2026-09-10T20:47:00Z
session_type: integrated team session
epic: 332 (Banker Copilot agentic harness)
branch: 332-beta
duration: multi-agent, 18:00Z–20:47Z
---

# Session Log — Copilot UI and Authority Fixes

## Arc

A live UI walkthrough exposed a chain of real defects. Starting with a blank task queue, each layer uncovered a deeper issue in the client, server, and policy engine.

## Defects Found & Fixed

1. **Doubled `/api/api` prefix** (Linus) — Client library was double-prefixing all URLs. Task queue was completely inaccessible (404). Fixed by consolidating `apiPath()` source of truth.

2. **SSE header stall** (Turk + Rusty diagnostics) — Stream opened but status line withheld for 15 seconds on cold starts. Root cause: `stream_session` awaited `runs.await_next_run` before the handler returned, blocking `http.response.start`. Fixed by removing pre-flight await and letting `_events()` loop handle the wait after streaming begins.

3. **Client reconnect storm** (Linus) — Stream close ignored terminal frame marker and attempted infinite reconnect. Fixed by checking frame's `terminal` field before re-establishing connection.

4. **Approval card in engine vocabulary** (Linus + Danny) — User-facing copy branched on rung, escalators, and slot indices instead of banker-centric language. Fixed by rewriting copy around approval state and what signers actually need to decide.

5. **Evidence findings discarded** (Linus) — Evidence `findings` field was stripped during client-side wire mapping. Fixed by preserving the field through `toEvidence()`.

6. **Reason template rendering failures** (Turk) — Policy escalator reason templates rendered unresolved `{placeholder}` text. Fixed by resolving known tokens (`{actual}`, `{threshold}`) from policy and omitting sentences with unresolved placeholders.

7. **Free-text planner path is inert** (Turk discovery + Brian's directive) — UI command bar accepted free-text objectives but backend never invoked the model to select an action. Planner returned empty runs with no evidence or proposals. Brian ruled this must be fixed in epic #332 — the harness must demonstrate model-driven action selection, not just model-driven assessment of pre-selected actions.

## Architectural Changes

- **Centre pane ownership** (Danny's ruling): Run owns the centre pane when active; when idle, centre shows the selected approval. Smallest change that allocates screen space to what the banker clicked.
- **Session-on-mount** (Linus): Page loads now open a session and SSE stream immediately, so the queue is usable without triggering an agent run first. Trade: creates one session per page load (distinguishable server-side).
- **Counter-proposal model** (Turk, per Danny's A+B ruling): Bankers can counter-propose via `context.supersedes`; escalator fires at L2 with no `raiseBy` to match Brian's demo path.

## Testing & Verification

- **Backend:** 414 Python, 150 unit, 224 integration tests passed
- **Frontend:** 489 passed, 13 pre-existing (account-opening), 52/52 Playwright E2E
- **Demo:** 10/10 seeded dataset groups validated
- **Live:** All defects reproduced and verified fixed before deployment

## Work Pending

- Turk's SSE fix requires live deployment for wall-clock verification through Istio
- Livingston's 32-case agreement measurement (permission withheld; awaits queue clear)
- Two architectural questions for Danny (compliance footer, queue bucket semantics)

## Discoveries

- Pre-existing latent defect: SSE ordering was broken on cold paths, only triggered by pod restart clearing in-process `RunStreamRegistry`
- Cord-code issue: Reconnect logic had no terminal-frame awareness, turning clean stream closure into a loop
- Free-text path was building for months without anyone noticing it doesn't call the model

## Next Steps (Epic #332)

1. Deploy Turk's backend fixes + Linus's frontend fixes
2. Measure live SSE first-byte latency
3. Run 32-case agreement suite (if queue clear)
4. Resolve Danny's open questions (footer compliance, bucket semantics)
5. Implement free-text action planner (remaining work to close Brian's scope ruling)
