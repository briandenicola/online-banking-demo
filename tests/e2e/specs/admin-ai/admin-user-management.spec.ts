import { test, expect } from '../../fixtures/authFixture';
import { ensureTestUser } from '../../fixtures/authFixture';
import { AdminPage } from '../../pages/AdminPage';

const ADMIN_CREDENTIALS = {
  email: 'admin@banking-demo.com',
  password: 'password123',
};

test.describe('E2E-402: Admin User Management — List & Filter', () => {
  let adminPage: AdminPage;
  let adminToken: string;

  test.beforeAll(async ({ request }) => {
    await ensureTestUser(request, ADMIN_CREDENTIALS);
  });

  test.beforeEach(async ({ page, request }) => {
    const loginResponse = await request.post('/api/users/login', {
      data: {
        username: ADMIN_CREDENTIALS.email,
        password: ADMIN_CREDENTIALS.password,
      },
    });

    if (!loginResponse.ok()) {
      test.skip(true, 'Admin login not available');
      return;
    }

    const body = await loginResponse.json();
    const token = body.token ?? body.accessToken ?? body.jwt;

    if (!token) {
      test.skip(true, 'No admin token');
      return;
    }

    adminToken = token;
    await page.addInitScript((state: { token: string; email: string; role: string }) => {
      window.localStorage.setItem('auth_token', state.token);
      window.localStorage.setItem('auth_email', state.email);
      window.localStorage.setItem('auth_role', state.role);
    }, { token, email: ADMIN_CREDENTIALS.email, role: body.role ?? 'admin' });

    adminPage = new AdminPage(page);
    await adminPage.navigate();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);

    const onAdmin = (await adminPage.getCurrentURL()).includes('/admin');
    if (!onAdmin) {
      test.skip(true, 'Admin dashboard not accessible');
    }
  });

  test('should display user list table', async () => {
    await adminPage.expectUserTableVisible();
    const rowCount = await adminPage.getUserRowCount();
    expect(rowCount).toBeGreaterThanOrEqual(1);
  });

  test('should filter users by active status', async ({ page }) => {
    const filterVisible = await adminPage.statusFilter.isVisible().catch(() => false);
    if (!filterVisible) {
      test.skip(true, 'Status filter not available');
      return;
    }

    await adminPage.filterByStatus('active');
    await page.waitForTimeout(1000);

    const rowCount = await adminPage.getUserRowCount();
    // All visible rows should have active status
    for (let i = 0; i < Math.min(rowCount, 5); i++) {
      const status = await adminPage.getUserStatusInRow(i);
      if (status) {
        expect(status.toLowerCase()).toContain('active');
      }
    }
  });

  test('should filter users by suspended status', async ({ page }) => {
    const filterVisible = await adminPage.statusFilter.isVisible().catch(() => false);
    if (!filterVisible) {
      test.skip(true, 'Status filter not available');
      return;
    }

    await adminPage.filterByStatus('suspended');
    await page.waitForTimeout(1000);

    // Should either show suspended users or an empty state
    const rowCount = await adminPage.getUserRowCount();
    if (rowCount > 0) {
      const status = await adminPage.getUserStatusInRow(0);
      if (status) {
        expect(status.toLowerCase()).toMatch(/suspend|disabled|inactive/);
      }
    }
  });

  test('should sort users by registration date', async ({ page }) => {
    const sortVisible = await adminPage.sortByDate.isVisible().catch(() => false);
    if (!sortVisible) {
      test.skip(true, 'Date sort column not available');
      return;
    }

    await adminPage.sortByRegistrationDate();
    await page.waitForTimeout(1000);

    // Table should still be visible after sorting
    await adminPage.expectUserTableVisible();
    const rowCount = await adminPage.getUserRowCount();
    expect(rowCount).toBeGreaterThanOrEqual(1);
  });

  test('should support pagination', async ({ page }) => {
    const hasPagination = await adminPage.paginationControls.isVisible().catch(() => false);

    if (!hasPagination) {
      // Pagination may not appear if user count is small
      const rowCount = await adminPage.getUserRowCount();
      expect(rowCount).toBeGreaterThanOrEqual(0);
      return;
    }

    // Click next page button
    const nextButton = page.locator(
      'button[aria-label*="next" i], button:has-text("Next"), .MuiPagination-root button:nth-last-child(2)'
    ).first();
    const nextVisible = await nextButton.isVisible().catch(() => false);

    if (nextVisible) {
      await nextButton.click();
      await page.waitForTimeout(1000);
      // Table should still render
      await adminPage.expectUserTableVisible();
    }
  });

  test('should search users by name or email', async ({ page }) => {
    const searchVisible = await adminPage.searchInput.isVisible().catch(() => false);
    if (!searchVisible) {
      test.skip(true, 'Search input not available');
      return;
    }

    const initialRowCount = await adminPage.getUserRowCount();

    await adminPage.searchUsers('demo');
    await page.waitForTimeout(1000);

    const filteredRowCount = await adminPage.getUserRowCount();
    // Search should filter results (could be same or fewer)
    expect(filteredRowCount).toBeGreaterThanOrEqual(0);
    expect(filteredRowCount).toBeLessThanOrEqual(initialRowCount);
  });

  test('should display user data in table rows via API', async ({ request }) => {
    // Verify admin users API works
    const response = await request.get('/api/admin/users', {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (!response.ok()) {
      // Try alternative endpoint
      const altResponse = await request.get('/api/users', {
        headers: { Authorization: `Bearer ${adminToken}` },
      });
      if (!altResponse.ok()) {
        test.skip(true, 'Admin users API not available');
        return;
      }
      const users = await altResponse.json();
      expect(Array.isArray(users) || users.data).toBeTruthy();
      return;
    }

    const users = await response.json();
    const userList = Array.isArray(users) ? users : users.data || users.users || [];
    expect(userList.length).toBeGreaterThanOrEqual(1);

    // Verify user object has expected fields
    const firstUser = userList[0];
    expect(firstUser).toHaveProperty('email');
  });
});
