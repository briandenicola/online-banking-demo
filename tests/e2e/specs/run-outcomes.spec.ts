/**
 * The two free-text run outcomes, in a real browser.
 *
 * These exist because the unit suite has twice reported success on this surface
 * while the deployed UI was broken — once because jsdom silently swallowed every
 * stream frame, and once because an absence assertion passed on a card that
 * never rendered. Both new outcomes arrive purely over the wire, so the only
 * honest check is a real client parsing real SSE bytes.
 *
 * The deployed backend does not yet carry Turk's planner, so this runs against
 * `support/fake_copilot_stack.py`, whose frames are copied from `loop.py`'s
 * refusal and answer branches rather than invented.
 *
 * Run: STREAM_MODE=refused-run python3 tests/e2e/support/fake_copilot_stack.py \
 *        src/ui-app/build 8097 src/ui-app/src/api/__tests__/bankerApprovalsWire.fixture.json
 *      npx playwright test --config outcomes.config.ts
 */
import { test, expect, Page } from '@playwright/test';

const BASE = 'http://127.0.0.1:8097';

async function boot(page: Page) {
  await page.route('**/runtime-config.js', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `window.__RUNTIME_CONFIG__ = { featureFlags: { copilotHarness: true, classicAdminTabs: true } };`,
    })
  );
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token');
    localStorage.setItem('auth_email', 'banker@banking-demo.com');
    localStorage.setItem('auth_role', 'banker');
  });
  await page.goto(`${BASE}/copilot`);
  await page.waitForSelector('[data-comparison-region="command"]', { timeout: 20000 });
}

const MODE = process.env.STREAM_MODE || 'refused-run';

test.describe('a refused free-text run', () => {
  test.skip(MODE !== 'refused-run', 'requires the stack in refused-run mode');

  test('states the refusal instead of looking like a short completed run', async ({ page }) => {
    await boot(page);

    // Positive first. An absence assertion on a pane that never rendered passes
    // trivially, which is exactly how an earlier terminal-state test went green
    // while asserting nothing.
    const notice = page.getByRole('note', { name: /this run was refused/i });
    await expect(notice).toBeVisible({ timeout: 15000 });

    await expect(notice).toContainText(/the details are incomplete/i);
    await expect(notice).toContainText(/direction of the adjustment was not stated/i);
    await expect(notice).toContainText(/nothing was signed and nothing was executed/i);

    // The banker is given the next move, not just a failure.
    await expect(notice).toContainText(/credit or debit/i);
  });

  test('offers nothing to sign, because nothing was proposed', async ({ page }) => {
    await boot(page);
    await expect(page.getByRole('note', { name: /this run was refused/i })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByRole('button', { name: /^Sign — / })).toHaveCount(0);
  });
});

test.describe('a read-only answer run', () => {
  test.skip(MODE !== 'answer-run', 'requires the stack in answer-run mode');

  test('renders the answer as prose, not as the JSON dump it fell back to', async ({ page }) => {
    await boot(page);

    await expect(
      page.getByText(/dominated by a single large payroll credit/i)
    ).toBeVisible({ timeout: 15000 });

    await expect(page.getByText(/One offshore wire is flagged for review/i)).toBeVisible();

    // The register the approval card's NO VERDICT block already uses.
    await expect(page.getByText(/could not be established from the evidence/i)).toBeVisible();
    await expect(
      page.getByText(/whether the offshore wire was pre-notified/i)
    ).toBeVisible();

    // Said out loud rather than inferred from an absent approval dock.
    await expect(
      page.getByText(/nothing was proposed and there is nothing to sign/i)
    ).toBeVisible();

    // The JSON fallback would have put the raw field names on screen.
    await expect(page.getByText(/"citedEvidenceIds"/)).toHaveCount(0);
  });

  test('the new planner steps read as sense, and the timing is the run\u2019s own', async ({ page }) => {
    await boot(page);
    await expect(page.getByText(/dominated by a single large payroll credit/i)).toBeVisible({
      timeout: 15000,
    });

    // The new phases are visible to a banker rather than hidden idle time. These
    // titles are SERVER-authored; the client renders them verbatim by design, so
    // this asserts what is shipped rather than a client-side rewording.
    await expect(page.getByText('Interpret objective')).toBeVisible();
    await expect(page.getByText('Answer from evidence')).toBeVisible();

    // A real free-text run takes seconds. The old inert path finished in 241ms of
    // doing nothing, and the pane once showed "181s and still counting" for it.
    // 7.4s is what `run.done` reported, so that is what must be on screen.
    await expect(page.getByText(/2 steps · 7s/)).toBeVisible();
  });
});
