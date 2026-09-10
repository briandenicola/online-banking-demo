/**
 * SSE lifecycle verification in a real browser, against a REAL held-open stream.
 *
 * WHY THIS CANNOT BE A UNIT TEST
 * -----------------------------
 * Both defects this spec covers are emergent over TIME and over the WIRE:
 *  - a healthy idle stream that is wrongly declared degraded 30s in, because the
 *    server's heartbeat carries no `seq` and the envelope parser dropped it before
 *    it could pet the watchdog;
 *  - a reconnect STORM (Brian counted 24 identical requests) after a run finishes.
 * A jest test asserting `streamStatus` transitions reproduces neither. Playwright's
 * `route.fulfill` cannot help either — it delivers a body and closes, which a correct
 * SSE client reads as a disconnect. Only a real server can hold a stream open, so
 * `support/fake_copilot_stack.py` serves the built SPA and a genuine `text/event-stream`.
 *
 * FIDELITY IS THE WHOLE POINT. The stub's heartbeat is byte-for-byte what
 * `sessions.py::_heartbeat_frame` emits — `event: heartbeat` + `data: {"serverTs": ...}`,
 * with NO `seq` and NO `id:`. It previously sent a `seq`, which the client could parse,
 * and that single unfaithful field is why the Phase 3 gate spec passed green while the
 * heartbeat-drop bug was live in production.
 *
 * Run: STREAM_MODE=healthy npx playwright test stream-lifecycle.spec.ts --config=stream.config.ts
 */
import { test, expect, Page } from '@playwright/test';

const BASE = 'http://127.0.0.1:8098';

/**
 * Squeeze the client's timers so the watchdog window fits in a test.
 *
 * `heartbeatIntervalMs * missedHeartbeatsBeforeDegraded` is the watchdog. At the shipped
 * 15000 x 2 this test would need 30s of wall clock; at 3000 x 2 it needs 6s and exercises
 * exactly the same code path. The stub heartbeats every 2s, comfortably inside the window,
 * so a client that HANDLES heartbeats stays live and one that DROPS them degrades.
 */
async function boot(page: Page) {
  // `public/runtime-config.js` assigns `window.__RUNTIME_CONFIG__` outright, so an
  // `addInitScript` that sets it first is simply overwritten — an earlier version of this
  // spec did exactly that, left the shipped 30s watchdog in place, waited 12s and "passed"
  // against the unfixed client. Override the CONFIG FILE, which is how a deployment tunes
  // these values anyway.
  await page.route('**/runtime-config.js', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `window.__RUNTIME_CONFIG__ = { featureFlags: { copilotHarness: true, classicAdminTabs: true }, copilot: { heartbeatIntervalMs: 3000, missedHeartbeatsBeforeDegraded: 2 } };`,
    })
  );
  // The wire fixture is pinned to a real seeding run whose signing windows closed at
  // 21:06Z. Now that the card enforces the window, a lapsed fixture silently converts an
  // open-card test into a closed-card test: `Sign` is absent, and the failure looks like a
  // gate regression when it is the fixture being honestly out of date. Re-date the windows
  // relative to now so the spec keeps asserting what it was written to assert.
  await page.route('**/authority/approvals*', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const items = (body.items || []).map((item: Record<string, unknown>) => ({
      ...item,
      createdAt: new Date(Date.now() - 60_000).toISOString(),
      expiresAt: new Date(Date.now() + 45 * 60_000).toISOString(),
    }));
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...body, items }),
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token');
    localStorage.setItem('auth_email', 'banker@banking-demo.com');
    localStorage.setItem('auth_role', 'banker');
  });
  await page.goto(`${BASE}/copilot`);
  await page.waitForSelector('[data-comparison-region="command"]', { timeout: 20000 });

  // Prove the override landed. A silently-ignored config is how the previous version of this
  // spec passed against a live bug.
  const hb = await page.evaluate(
    () => (window as unknown as { __RUNTIME_CONFIG__?: { copilot?: { heartbeatIntervalMs?: number } } })
      .__RUNTIME_CONFIG__?.copilot?.heartbeatIntervalMs
  );
  expect(hb).toBe(3000);
}

const MODE = process.env.STREAM_MODE || 'healthy';

test.describe('SSE lifecycle', () => {
  test.skip(MODE !== 'healthy', 'requires the stack in healthy mode');

  /**
   * Sampling ONCE is not good enough here, and an earlier version of this spec proved it by
   * passing against the unfixed client. The pre-fix failure mode is a FLAP: the watchdog
   * fires, status goes `degraded`, the client aborts and reconnects, and it is back to `Live`
   * within a few hundred milliseconds. A single assertion after the window lands in the `Live`
   * phase and reports all-clear on a client that is disabling signing every few seconds.
   * Sample continuously and judge the whole window.
   */
  async function sampleStatus(page: Page, ms: number): Promise<string[]> {
    const seen: string[] = [];
    const until = Date.now() + ms;
    while (Date.now() < until) {
      const label = await page.locator('[role="status"]').first().textContent();
      if (label && seen[seen.length - 1] !== label) seen.push(label);
      await page.waitForTimeout(200);
    }
    return seen;
  }

  test('a healthy idle stream is still signable after the watchdog window', async ({ page }) => {
    await boot(page);

    await expect(page.getByText(/^Live$/).first()).toBeVisible({ timeout: 10000 });

    // Past heartbeatIntervalMs * missedHeartbeatsBeforeDegraded (6s here, 30s shipped) with
    // nothing but heartbeats on the wire. Before the fix the watchdog fired here, status went
    // `degraded`, and EVERY card in the queue became Deny-only on a connection that was never
    // broken. This is Brian's cold-load symptom, reproduced.
    const observed = await sampleStatus(page, 12000);

    expect(observed).toEqual(['Live']);
  });

  test('the signing gate opens honestly once the stream is verified live', async ({ page }) => {
    // The gate itself is UNTOUCHED — `canSignUnderStream` still accepts only `live`/`resumed`.
    // What changed is that a healthy stream is now allowed to REACH those states and stay
    // there. This asserts the gate passes on its own terms, not that it was bypassed: the
    // dwell timer still has to elapse first, which is deliberate friction, not the gate.
    await boot(page);
    await expect(page.getByText(/^Live$/).first()).toBeVisible({ timeout: 10000 });

    await page.getByText('Post a balance adjustment').first().click();

    // Target the CARD's sign button specifically. `/sign/i` also matches the batch group's
    // "Sign 2 items" and every queue row whose accessible name contains "DENIED", and an
    // earlier version of this test passed in 525ms against one of those — the dwell-gated
    // button it was supposed to be watching was still disabled at the time.
    const sign = page.getByRole('button', { name: /^Sign — / }).first();

    // Disabled first, and honestly so: the L2 dwell is 25s of deliberate friction. If this
    // is ever enabled immediately, the dwell has been lost, not the gate fixed.
    await expect(sign).toBeDisabled();
    await expect(sign).toHaveText(/enabled in \d+:\d+/);

    // Then it opens on its own terms, because the stream is genuinely live.
    await expect(sign).toBeEnabled({ timeout: 40000 });

    // And the banner that was telling Brian signing was disabled must be gone.
    await expect(page.getByText(/Live updates are interrupted/i)).toHaveCount(0);
  });

  test('a held-open healthy stream is opened exactly once', async ({ page }) => {
    const streamRequests: string[] = [];
    await page.route('**/stream*', async (route) => {
      streamRequests.push(route.request().url());
      await route.continue();
    });

    await boot(page);
    await page.waitForTimeout(12000);

    // One connection, held open. Any reconnect here is the watchdog killing a healthy stream,
    // which is what produced Brian's 24 identical requests once a run was in play.
    console.log(`healthy stream requests in 12s: ${streamRequests.length}`);
    expect(streamRequests.length).toBe(1);
  });
});

test.describe('after a run has finished', () => {
  test.skip(MODE !== 'completed-run', 'requires STREAM_MODE=completed-run');

  /**
   * The server CANNOT hold a session-scoped stream open once that session's latest run has
   * finished: `runs.latest_for_session` returns the closed run and `_events()` ends with
   * `if stream.closed and queue.empty(): return`. So every reattach is 200-then-EOF.
   *
   * The client's job is therefore NOT to keep the stream alive — it cannot — but to stop
   * hammering, stop re-dispatching the finished run's frames, and stop claiming a liveness
   * it does not have. Restoring live updates for this case is a SERVER change and is Turk's.
   */
  test('a finished run is consumed once and does not trigger a reconnect storm', async ({
    page,
  }) => {
    const streamRequests: string[] = [];
    await page.route('**/stream*', async (route) => {
      streamRequests.push(route.request().url());
      await route.continue();
    });

    await boot(page);
    await page.waitForTimeout(12000);

    // Pre-fix this was unbounded: `attempt` was reset on `response.ok`, so a 200-then-EOF
    // loop reconnected on the base delay forever.
    // Measured over the same 12s window: 15 with no fix, 5 with backoff only, 1 now. The
    // threshold is 1 — the initial attach and nothing after it. A cap of 6 would have let the
    // backoff-only behaviour pass, and that is exactly what cost Brian 213 requests.
    console.log(`completed-run stream requests in 12s: ${streamRequests.length}`);
    expect(streamRequests.length).toBe(1);

    // And the trace must not claim the agent is still working. The run reached `run.done`.
    await expect(page.getByText(/the agent is still running on the server/i)).toHaveCount(0);

    // The banner must state the outcome, not a contradiction. It previously read
    // "This run is completed. Reconnecting for live updates — nothing further is expected
    // for this run." — a sentence written to describe the storm rather than stop it.
    await expect(page.getByText(/Reconnecting for live updates/i)).toHaveCount(0);
    await expect(
      page.getByText(/Live updates have stopped because there is nothing left to send/i)
    ).toBeVisible();

    // THE INFERENCE I HAVE NOT PROVEN UNTIL NOW. Stopping the reconnect settles the status
    // at `closed`, and `canSignUnderStream` accepts only `live`/`resumed`. So a banker on a
    // finished run cannot sign. My claim was that this is NOT a regression — the gate was
    // already shut in that state, because the pre-fix reattach delivered nothing but
    // already-consumed frames, which the replay filter drops without ever promoting the
    // status. Assert the honest consequence rather than leaving it as reasoning.
    //
    // Target the QUEUE ROW by its rung chip. `getByText('Post a balance adjustment')` matches
    // the batch group's "Review 2 together" toggle first, and clicking that collapses a
    // group instead of selecting a card — which is precisely how the first version of this
    // assertion failed. Assert something POSITIVE about the rendered card before asserting
    // any absence, or an absence passes trivially on a card that never rendered.
    await page.getByRole('button', { name: /Post a balance adjustment L1 · one signer/ }).first().click();
    await expect(page.getByText(/You are signing/i).first()).toBeVisible();

    // The record is open — it keeps its Sign button and its disclosure. What it must not do
    // is offer an ENABLED one on a stream that is no longer live. If this ever enables, the
    // gate has been weakened, not fixed.
    await expect(page.getByRole('button', { name: /^Sign — / }).first()).toBeDisabled();
  });
});
