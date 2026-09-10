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
    // Measured: 15 pre-fix, 3 post-fix, over the same 12s window.
    console.log(`completed-run stream requests in 12s: ${streamRequests.length}`);
    expect(streamRequests.length).toBeLessThanOrEqual(6);

    // And the trace must not claim the agent is still working. The run reached `run.done`.
    await expect(page.getByText(/the agent is still running on the server/i)).toHaveCount(0);
  });
});
