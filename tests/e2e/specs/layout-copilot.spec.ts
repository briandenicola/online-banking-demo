/**
 * Layout verification in a real browser at Brian's reported viewport.
 *
 * jsdom cannot answer the questions that matter here — it has no layout engine,
 * so "is the command bar inside the viewport" is unanswerable there. This drives
 * real Chromium, stubs the API so the surface has content, and MEASURES.
 *
 * Run: npx playwright test layout-copilot.spec.ts --config=layout.config.ts
 */
import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = 'http://127.0.0.1:8099';

const fixturePath = path.join(
  __dirname,
  '../../../src/ui-app/src/api/__tests__/bankerApprovalsWire.fixture.json'
);
const approvals = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));

// The fixture was seeded in September and its signing windows have since closed. The card now
// (correctly) suppresses every signing affordance on a lapsed record, so a stale fixture would
// silently turn the attestation assertions below into tests of the closed state instead. Re-date
// the windows so these tests keep testing what they claim to test.
approvals.items = approvals.items.map((item: any) => ({
  ...item,
  createdAt: new Date(Date.now() - 60_000).toISOString(),
  expiresAt: new Date(Date.now() + 45 * 60_000).toISOString(),
}));

async function boot(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    if (url.includes('/authority/approvals')) {
      const scope = new URL(url).searchParams.get('scope');
      const items = scope === 'awaiting-me' ? [] : approvals.items;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: items.length, items }),
      });
    }
    if (url.match(/\/sessions$/) && route.request().method() === 'POST') {
      // The real service answers 201 with a session id. A bare `{}` trips the
      // client's sessionId guard and puts an error toast on screen, which then
      // reads as a layout bug that is not one.
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ sessionId: 'sess_layout_1', status: 'open' }),
      });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });

  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token');
    localStorage.setItem('auth_email', 'banker@securebank.test');
    localStorage.setItem('auth_role', 'banker');
  });

  await page.goto(`${BASE}/copilot`);
  await page.waitForSelector('[data-comparison-region="command"]', { timeout: 15000 });
}

/** Brian's window, plus a range of shapes the surface must survive. */
const VIEWPORTS = [
  { name: 'brian-wide-short', width: 1550, height: 780 },
  { name: 'laptop-short', width: 1280, height: 720 },
  { name: 'very-short', width: 1440, height: 640 },
  { name: 'tall-desktop', width: 1920, height: 1080 },
  { name: 'mid-width', width: 1100, height: 800 },
];

for (const vp of VIEWPORTS) {
  test.describe(`${vp.name} (${vp.width}x${vp.height})`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test('the command bar is fully inside the viewport', async ({ page }) => {
      await boot(page);
      const bar = page.locator('[data-comparison-region="command"]');
      const box = await bar.boundingBox();
      expect(box).not.toBeNull();
      // Top and BOTTOM must both be on screen. The bug was a visible top edge
      // with the input and Start button clipped below the fold.
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(vp.height + 1);
    });

    test('the Start button and the input are clickable, not occluded', async ({ page }) => {
      await boot(page);
      const input = page.getByLabel(/describe the task/i);
      await expect(input).toBeVisible();

      const box = await input.boundingBox();
      expect(box).not.toBeNull();

      // Whatever paints at the input's centre must be the input itself. This is
      // what catches an overlay (footer, z-index) sitting on top of it.
      const centre = { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 };
      const topmostIsInput = await page.evaluate(({ x, y }) => {
        const el = document.elementFromPoint(x, y);
        return Boolean(el && (el.tagName === 'INPUT' || el.closest('.MuiInputBase-root')));
      }, centre);
      expect(topmostIsInput).toBe(true);

      // Typing must reach it, which also proves nothing swallows the click.
      await input.click();
      await input.fill('review the flagged wires');
      await expect(page.getByRole('button', { name: /^start$/i })).toBeEnabled();
    });

    test('no marketing footer steals vertical room from the console', async ({ page }) => {
      await boot(page);
      await expect(page.locator('footer')).toHaveCount(0);
      await expect(page.getByText(/FDIC Insured/i)).toHaveCount(0);
    });

    test('the page does not scroll — the surface fits the window', async ({ page }) => {
      await boot(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollHeight - window.innerHeight
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });

    test('with no run, the centre pane holds the selected approval', async ({ page }) => {
      await boot(page);
      const queue = await page.locator('[data-comparison-region="queue"]').boundingBox();
      const trace = await page.locator('[data-comparison-region="trace"]').boundingBox();

      // The artifact pane shows what a RUN produced. With no run it would be one
      // sentence occupying a third of the surface, so it is not mounted.
      await expect(page.locator('[data-comparison-region="artifact"]')).toHaveCount(0);

      const detail = page.locator('[data-testid="approval-detail-pane"]');
      await expect(detail).toBeVisible();

      expect(trace).not.toBeNull();
      expect(trace!.width).toBeGreaterThan(80);
      expect(trace!.height).toBeGreaterThan(80);
      expect(trace!.x + trace!.width).toBeLessThanOrEqual(vp.width + 1);

      // The point of the change: the approval is no longer in a ~340px column.
      const box = await detail.boundingBox();
      expect(box!.width).toBeGreaterThan(400);

      // The queue collapses into a drawer only below md.
      if (vp.width >= 900) {
        expect(queue).not.toBeNull();
        expect(queue!.width).toBeGreaterThan(180);
      }
    });

    test('the approval keeps its rung, hash and signature slots in the centre', async ({
      page,
    }) => {
      await boot(page);
      const detail = page.locator('[data-testid="approval-detail-pane"]');
      // §7.1 depends on rung + payload hash being visible; the signature slots
      // are what make dual control legible. None may be dropped by the move.
      await expect(detail).toContainText(/L2/);
      await expect(detail).toContainText(/signer/i);
      await expect(detail.getByText(/[0-9a-f]{6,}/i).first()).toBeVisible();
    });

    test('the queue actually rendered its seven items', async ({ page }) => {
      await boot(page);
      if (vp.width < 900) test.skip();
      const queue = page.locator('[data-comparison-region="queue"]');
      await expect(queue.getByRole('button', { name: /needs you/i })).toContainText('7');
    });
  });
}

/**
 * A run with REAL trace content.
 *
 * This closes a gap I flagged as unverified last round: `TracePane`'s
 * `minHeight` was changed from 200 to 0 to let it shrink, and until now it had
 * only ever been measured EMPTY. An empty pane cannot demonstrate that a full
 * one still fits.
 *
 * The SSE stream is stubbed at the network boundary. `copilotStream.ts` is not
 * modified or mocked — there is a live SSE fault behind it that Turk owns.
 */
function streamBody(runId: string): string {
  const frames = [
    { kind: 'run.started', seq: 1, runId, payload: { title: 'Review flagged wires', intent: 'review the flagged wires from overnight', startedAt: new Date().toISOString() } },
    { kind: 'plan.proposed', seq: 2, runId, payload: { version: 1, steps: [
      { id: 's1', title: 'Assemble the evidence bundle', status: 'pending' },
      { id: 's2', title: 'Score each wire against policy', status: 'pending' },
      { id: 's3', title: 'Draft the supervisor memo', status: 'pending' },
    ] } },
    { kind: 'step.started', seq: 3, runId, payload: { stepId: 's1', index: 0, title: 'Assemble the evidence bundle' } },
    { kind: 'step.completed', seq: 4, runId, payload: { stepId: 's1', durationMs: 1730, summary: 'Bundle assembled from 4 overnight wires.' } },
  ];
  return frames.map((f) => `event: ${f.kind}\ndata: ${JSON.stringify(f)}\n\n`).join('');
}

async function bootWithRun(page: Page) {
  const runId = 'run_layout_1';
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    const method = route.request().method();

    if (url.includes('/authority/approvals')) {
      const scope = new URL(url).searchParams.get('scope');
      const items = scope === 'awaiting-me' ? [] : approvals.items;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: items.length, items }) });
    }
    if (url.includes('/stream')) {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: streamBody(runId) });
    }
    if (url.match(/\/sessions$/) && method === 'POST') {
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ sessionId: 'sess_layout_1' }) });
    }
    if (url.includes('/runs') && method === 'POST') {
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ runId }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });

  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token');
    localStorage.setItem('auth_email', 'banker@securebank.test');
    localStorage.setItem('auth_role', 'banker');
  });

  await page.goto(`${BASE}/copilot`);
  await page.waitForSelector('[data-comparison-region="command"]', { timeout: 15000 });
  await page.getByRole('textbox', { name: /describe the task/i }).fill('review the flagged wires from overnight');
  await page.getByRole('button', { name: /^start$/i }).click();
}

/**
 * Run-active coverage at two shapes deliberately.
 *
 * 1550x780 is Brian's window and takes the `sideBySide` (row) branch. 1000x900
 * takes the OTHER branch — not `wide`, not `shortViewport`, not `narrow` — so
 * trace and artifact stack VERTICALLY with both panes populated. That is the
 * combination the `TracePane` `minHeight: 200 -> 0` change affects most, and it
 * had no coverage at all.
 */
for (const rvp of [
  { name: 'row mode', width: 1550, height: 780 },
  { name: 'column mode', width: 1000, height: 900 },
]) {
test.describe(`a run owns the centre pane (${rvp.name} ${rvp.width}x${rvp.height})`, () => {
  test.use({ viewport: { width: rvp.width, height: rvp.height } });

  test('the trace takes the centre and the approval moves to the labelled dock', async ({ page }) => {
    await bootWithRun(page);
    const trace = page.locator('[data-comparison-region="trace"]');
    await expect(trace).toContainText(/Review flagged wires|Assemble the evidence bundle/, { timeout: 10000 });

    // The trace must not be displaced by the approval detail.
    await expect(page.locator('[data-testid="approval-detail-pane"]')).toHaveCount(0);
    // ...and the approval must not vanish: it is docked, and it says so.
    const artifact = page.locator('[data-comparison-region="artifact"]');
    await expect(artifact).toBeVisible();
    await expect(artifact).toContainText(/Selected approval/i);
  });

  test('the command bar survives a populated trace', async ({ page }) => {
    await bootWithRun(page);
    await expect(page.locator('[data-comparison-region="trace"]')).toContainText(
      /Review flagged wires|Assemble the evidence bundle/,
      { timeout: 10000 }
    );
    // Both panes must be real and on screen in BOTH branches.
    for (const sel of ['[data-comparison-region="trace"]', '[data-comparison-region="artifact"]']) {
      const box = await page.locator(sel).boundingBox();
      expect(box, sel).not.toBeNull();
      expect(box!.height, sel).toBeGreaterThan(60);
      expect(box!.y + box!.height, sel).toBeLessThanOrEqual(rvp.height + 1);
      expect(box!.x + box!.width, sel).toBeLessThanOrEqual(rvp.width + 1);
    }
    const bar = await page.locator('[data-comparison-region="command"]').boundingBox();
    expect(bar!.y + bar!.height).toBeLessThanOrEqual(rvp.height + 1);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollHeight - window.innerHeight
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

}

/**
 * Narrow widths — the drawer mode I could not verify last round.
 */
for (const vp of [
  { name: 'small-laptop', width: 1000, height: 800 },
  { name: 'tablet', width: 860, height: 780 },
  { name: 'phone-ish', width: 420, height: 780 },
]) {
  test.describe(`${vp.name} (${vp.width}x${vp.height})`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test('the command bar is fully inside the viewport', async ({ page }) => {
      await boot(page);
      const bar = await page.locator('[data-comparison-region="command"]').boundingBox();
      expect(bar).not.toBeNull();
      expect(bar!.y + bar!.height).toBeLessThanOrEqual(vp.height + 1);
      expect(bar!.x + bar!.width).toBeLessThanOrEqual(vp.width + 1);
    });

    test('the page does not scroll', async ({ page }) => {
      await boot(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollHeight - window.innerHeight
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });

    test('the approval is readable and nothing is clipped horizontally', async ({ page }) => {
      await boot(page);
      const detail = page.locator('[data-testid="approval-detail-pane"]');
      await expect(detail).toBeVisible();
      const box = await detail.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(-1);
      expect(box!.x + box!.width).toBeLessThanOrEqual(vp.width + 1);
      expect(box!.height).toBeGreaterThan(80);
    });
  });
}


/**
 * Regression guard for a bug that ONLY appears with real content.
 *
 * Each pane is the sole child of a `display: flex` Region. Without `flexGrow`
 * its width is content-based, so the trace pane rendered 426px inside a 750px
 * region as soon as a run replaced its long empty-state paragraph with short
 * step labels — a 324px dead gap. Measuring the empty pane could never catch it.
 */
test.describe('panes fill the space they are given (1550x780)', () => {
  test.use({ viewport: { width: 1550, height: 780 } });

  test('with a run, trace and artifact panes both fill their regions', async ({ page }) => {
    await bootWithRun(page);
    await expect(page.locator('[data-comparison-region="trace"]')).toContainText(
      /Assemble the evidence bundle/,
      { timeout: 10000 }
    );
    const fill = await page.evaluate(() => {
      const measure = (sel: string) => {
        const region = document.querySelector(sel) as HTMLElement | null;
        const paper = region ? (region.querySelector('section') as HTMLElement | null) : null;
        if (!region || !paper) return null;
        return {
          region: Math.round(region.getBoundingClientRect().width),
          paper: Math.round(paper.getBoundingClientRect().width),
        };
      };
      return {
        trace: measure('[data-comparison-region="trace"]'),
        artifact: measure('[data-comparison-region="artifact"]'),
        queue: measure('[data-comparison-region="queue"]'),
      };
    });
    for (const [name, m] of Object.entries(fill)) {
      expect(m, name).not.toBeNull();
      // Allow a pixel of rounding, nothing more. 426-of-750 must never recur.
      expect(m!.region - m!.paper, name).toBeLessThanOrEqual(2);
    }
  });

  test('the run trace renders numbered steps, not NaN', async ({ page }) => {
    await bootWithRun(page);
    const trace = page.locator('[data-comparison-region="trace"]');
    await expect(trace).toContainText(/Assemble the evidence bundle/, { timeout: 10000 });
    await expect(trace).not.toContainText('NaN');
  });

  test('the signing attestation reads correctly in the right dock too', async ({ page }) => {
    // The card renders in two placements now — the centre pane with no run, and
    // this dock while a run owns the centre. The attestation must be true and
    // unclipped in both, and it must never revive the copy that told a signer
    // their signature counted because they were not themselves.
    await bootWithRun(page);
    const dock = page.locator('[data-comparison-region="artifact"]');
    await expect(dock).toContainText(/Signing as/i, { timeout: 10000 });
    await expect(dock).not.toContainText(/independent supervisor co-signature/i);
    await expect(dock).not.toContainText(/different identity from the requester/i);

    // The banner must not spill out of the narrower column.
    const overflow = await page.evaluate(() => {
      const region = document.querySelector('[data-comparison-region="artifact"]') as HTMLElement;
      const alert = region?.querySelector('.MuiAlert-root') as HTMLElement;
      if (!region || !alert) return null;
      const r = region.getBoundingClientRect();
      const a = alert.getBoundingClientRect();
      return Math.round(a.right - r.right);
    });
    expect(overflow).not.toBeNull();
    expect(overflow!).toBeLessThanOrEqual(1);
  });
});

/**
 * Found while fixing the signing gate: the error toast was anchored bottom-centre
 * at z-index 1400, landing squarely on the command bar. That is the same defect
 * Brian reported for the marketing footer, and it became far easier to hit once
 * errors could surface on mount. This pins the toast away from the input.
 */
test.describe('an error toast does not occlude the command bar (1550x780)', () => {
  test.use({ viewport: { width: 1550, height: 780 } });

  test('the input stays the topmost element while an error is showing', async ({ page }) => {
    await page.route('**/api/**', async (route) => {
      const url = route.request().url();
      if (url.includes('/authority/approvals')) {
        const scope = new URL(url).searchParams.get('scope');
        const items = scope === 'awaiting-me' ? [] : approvals.items;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ count: items.length, items }),
        });
      }
      // Force the failure path: no session, so the error surfaces on mount.
      if (url.match(/\/sessions$/)) return route.fulfill({ status: 503, body: '' });
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    });
    await page.addInitScript(() => {
      localStorage.setItem('auth_token', 'test-token');
      localStorage.setItem('auth_email', 'banker@securebank.test');
      localStorage.setItem('auth_role', 'banker');
    });
    await page.goto(`${BASE}/copilot`);
    await page.waitForSelector('[data-comparison-region="command"]');

    // The error must actually be on screen, or this proves nothing.
    const toast = page.locator('.MuiSnackbar-root');
    await expect(toast).toBeVisible();

    const input = page.getByLabel(/describe the task/i);
    const box = await input.boundingBox();
    const topmostIsInput = await page.evaluate(({ x, y }) => {
      const el = document.elementFromPoint(x, y);
      return Boolean(el && (el.tagName === 'INPUT' || el.closest('.MuiInputBase-root')));
    }, { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 });
    expect(topmostIsInput).toBe(true);
  });
});
