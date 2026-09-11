import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
const raw = JSON.parse(fs.readFileSync(path.resolve(__dirname,
  '../../../src/ui-app/src/api/__tests__/bankerApprovalsWire.fixture.json'), 'utf8'));
// Brian's exact case: window closed, but the service has NOT swept it — still pending,
// still callerMaySign: true.
const items = raw.items.map((i: any) => ({ ...i, status: 'pending', callerMaySign: true,
  expiresAt: new Date(Date.now() - 5 * 60_000).toISOString() }));
test.use({ viewport: { width: 1550, height: 780 } });
test('a lapsed record offers no signing language', async ({ page }) => {
  await page.route('**/api/**', async (route: any) => {
    const url = route.request().url();
    if (url.includes('/authority/approvals')) {
      const scope = new URL(url).searchParams.get('scope');
      const list = scope === 'awaiting-me' ? [] : items;
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ count: list.length, items: list }) });
    }
    if (url.match(/\/sessions$/) && route.request().method() === 'POST')
      return route.fulfill({ status: 201, contentType: 'application/json',
        body: JSON.stringify({ sessionId: 's1', status: 'open' }) });
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token');
    localStorage.setItem('auth_email', 'banker@banking-demo.com');
    localStorage.setItem('auth_role', 'banker');
  });
  await page.goto('http://127.0.0.1:8099/copilot');
  await page.waitForSelector('[data-comparison-region="command"]', { timeout: 15000 });
  await page.waitForTimeout(1500);
  const body = await page.locator('body').innerText();
  console.log('HEADER:', body.split('\n').find((l) => /SIGNATURE WINDOW CLOSED|SIGNATURE REQUIRED/.test(l)));
  console.log('NOTE:', body.split('\n').find((l) => l.includes('Nobody signed before')));
  console.log('DISCLOSURE KEPT:', /what was proposed/i.test(body), '| WHY block:', /WHY THIS IS/.test(body));
  expect(body).not.toMatch(/only signature needed/i);
  expect(body).not.toMatch(/goes ahead once you sign/i);
  expect(body).not.toContain('SIGNATURE REQUIRED');
  expect(body).toContain('SIGNATURE WINDOW CLOSED');
  expect(body).toMatch(/what was proposed/i);
  await expect(page.getByRole('button', { name: /^Sign — / })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Deny$/ })).toHaveCount(0);
});

test('a fully signed record offers no verb at all, but keeps its disclosure', async ({ page }) => {
  // Brian signed live at 4:16:45 PM and the card still offered a red, enabled Deny. The server
  // rejects that with a 409 (ApprovalService.cs:452-455), so the click could only ever have
  // produced an error for something the UI invited him to do.
  const signed = raw.items
    .filter((i: any) => i.status === 'signed')
    .map((i: any) => ({ ...i, expiresAt: new Date(Date.now() + 45 * 60_000).toISOString() }));
  expect(signed.length).toBeGreaterThan(0);

  await page.route('**/api/**', async (route: any) => {
    const url = route.request().url();
    if (url.includes('/authority/approvals')) {
      const scope = new URL(url).searchParams.get('scope');
      const list = scope === 'awaiting-me' ? [] : signed;
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ count: list.length, items: list }) });
    }
    if (url.match(/\/sessions$/) && route.request().method() === 'POST')
      return route.fulfill({ status: 201, contentType: 'application/json',
        body: JSON.stringify({ sessionId: 's1', status: 'open' }) });
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token');
    localStorage.setItem('auth_email', 'banker@banking-demo.com');
    localStorage.setItem('auth_role', 'banker');
  });
  await page.goto('http://127.0.0.1:8099/copilot');
  await page.waitForSelector('[data-comparison-region="command"]', { timeout: 15000 });
  await page.waitForTimeout(1500);

  // The signed record lives under DONE TODAY and is never auto-selected, so it must be opened
  // explicitly. Asserting on an unrendered card is how a terminal-state test passes vacuously.
  // A signed-but-unexecuted record buckets under RUNNING (it is awaiting execution), not
  // DONE TODAY — verified by dumping the queue rather than assuming.
  await page.getByRole('button', { name: /^Running/i }).click();
  await page.waitForTimeout(400);
  const row = page.getByRole('button', { name: /Post a balance adjustment/i }).first();
  await expect(row).toBeVisible({ timeout: 5000 });
  await row.click();
  await page.waitForTimeout(800);
  await expect(page.getByText(/what was proposed/i).first()).toBeVisible({ timeout: 5000 });

  const body = await page.locator('body').innerText();
  console.log('HEADER:', body.split('\n').find((l) => /FULLY SIGNED|SIGNATURE REQUIRED/.test(l)));
  console.log('NOTE:', body.split('\n').find((l) => l.includes('Every signature')));
  console.log('SIGNATURES KEPT:', /signature/i.test(body), '| WHY block:', /WHY THIS IS/.test(body));

  // No verb may be offered when acting cannot change the record.
  await expect(page.getByRole('button', { name: /^Deny$/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Confirm denial$/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Sign — / })).toHaveCount(0);
  expect(body).not.toContain('SIGNATURE REQUIRED');
  expect(body).toMatch(/what was proposed/i);
});
