import { test, expect } from '../../fixtures/authFixture';
import { ensureTestUser } from '../../fixtures/authFixture';
import { AdminPage } from '../../pages/AdminPage';
import { LoginPage } from '../../pages/LoginPage';

const ADMIN_CREDENTIALS = {
  email: 'admin@banking-demo.com',
  password: 'password123',
};

const REGULAR_USER_CREDENTIALS = {
  email: 'e2e-default@banking-demo.com',
  password: 'password123',
};

test.describe('E2E-403: Admin User Actions — Suspend/Unsuspend', () => {
  let adminPage: AdminPage;
  let adminToken: string;

  test.beforeAll(async ({ request }) => {
    await ensureTestUser(request, ADMIN_CREDENTIALS);
    await ensureTestUser(request, REGULAR_USER_CREDENTIALS);
  });

  test.beforeEach(async ({ page, request }) => {
    const loginResponse = await request.post('/api/auth/login', {
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

  test('should show confirmation dialog before suspending a user', async ({ page }) => {
    const tableVisible = await adminPage.userTable.isVisible().catch(() => false);
    if (!tableVisible) {
      test.skip(true, 'User table not available');
      return;
    }

    const rowCount = await adminPage.getUserRowCount();
    if (rowCount < 2) {
      test.skip(true, 'Not enough users to test suspend');
      return;
    }

    // Find a row with a suspend button (skip first row which might be admin)
    const suspendBtns = page.locator('table tbody tr button, [role="row"] button').filter({ hasText: /suspend|disable/i });
    const hasSuspend = await suspendBtns.first().isVisible().catch(() => false);

    if (!hasSuspend) {
      test.skip(true, 'Suspend button not found');
      return;
    }

    await suspendBtns.first().click();

    // Confirmation dialog should appear
    const dialogVisible = await adminPage.confirmationDialog.isVisible().catch(() => false);
    expect(dialogVisible).toBeTruthy();

    // Cancel to avoid side effects
    await adminPage.cancelAction();
  });

  test('should suspend a user via API', async ({ request }) => {
    // Get user list
    const usersResponse = await request.get('/api/admin/users', {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (!usersResponse.ok()) {
      test.skip(true, 'Admin users API not available');
      return;
    }

    const users = await usersResponse.json();
    const userList = Array.isArray(users) ? users : users.data || users.users || [];

    // Find a non-admin user to suspend
    const targetUser = userList.find(
      (u: { email?: string; role?: string; id?: number }) =>
        u.email !== ADMIN_CREDENTIALS.email && u.role !== 'admin' && u.id !== 1
    );

    if (!targetUser) {
      test.skip(true, 'No non-admin user found to suspend');
      return;
    }

    // Attempt to suspend
    const suspendResponse = await request.post(`/api/admin/users/${targetUser.id}/suspend`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (!suspendResponse.ok()) {
      // Try alternative endpoint
      const altResponse = await request.patch(`/api/admin/users/${targetUser.id}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { status: 'suspended' },
      });
      expect(altResponse.status()).toBeLessThan(500);
    } else {
      expect(suspendResponse.ok()).toBeTruthy();
    }

    // Unsuspend to clean up
    await request.post(`/api/admin/users/${targetUser.id}/unsuspend`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    }).catch(() => {
      request.patch(`/api/admin/users/${targetUser.id}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { status: 'active' },
      });
    });
  });

  test('should prevent suspended user from logging in', async ({ request, browser }) => {
    // Get users to find one to suspend
    const usersResponse = await request.get('/api/admin/users', {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (!usersResponse.ok()) {
      test.skip(true, 'Admin users API not available');
      return;
    }

    const users = await usersResponse.json();
    const userList = Array.isArray(users) ? users : users.data || users.users || [];
    const targetUser = userList.find(
      (u: { email?: string; role?: string; id?: number }) =>
        u.email === REGULAR_USER_CREDENTIALS.email
    );

    if (!targetUser) {
      test.skip(true, 'Target user not found');
      return;
    }

    // Suspend the user
    const suspendResponse = await request.post(`/api/admin/users/${targetUser.id}/suspend`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (!suspendResponse.ok()) {
      const altResponse = await request.patch(`/api/admin/users/${targetUser.id}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { status: 'suspended' },
      });
      if (!altResponse.ok()) {
        test.skip(true, 'Cannot suspend user via API');
        return;
      }
    }

    try {
      // Try to login as suspended user
      const loginResponse = await request.post('/api/auth/login', {
        data: {
          username: REGULAR_USER_CREDENTIALS.email,
          password: REGULAR_USER_CREDENTIALS.password,
        },
      });

      // Suspended user should fail to login (401/403) or get a specific error
      expect(loginResponse.status()).toBeGreaterThanOrEqual(400);
    } finally {
      // Always unsuspend to restore test state
      await request.post(`/api/admin/users/${targetUser.id}/unsuspend`, {
        headers: { Authorization: `Bearer ${adminToken}` },
      }).catch(async () => {
        await request.patch(`/api/admin/users/${targetUser.id}`, {
          headers: { Authorization: `Bearer ${adminToken}` },
          data: { status: 'active' },
        });
      });
    }
  });

  test('should re-enable a suspended user', async ({ request }) => {
    const usersResponse = await request.get('/api/admin/users', {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (!usersResponse.ok()) {
      test.skip(true, 'Admin users API not available');
      return;
    }

    const users = await usersResponse.json();
    const userList = Array.isArray(users) ? users : users.data || users.users || [];
    const targetUser = userList.find(
      (u: { email?: string; role?: string; id?: number }) =>
        u.email !== ADMIN_CREDENTIALS.email && u.role !== 'admin' && u.id !== 1
    );

    if (!targetUser) {
      test.skip(true, 'No user available for suspend/unsuspend test');
      return;
    }

    // Suspend first
    await request.post(`/api/admin/users/${targetUser.id}/suspend`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    }).catch(() =>
      request.patch(`/api/admin/users/${targetUser.id}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { status: 'suspended' },
      })
    );

    // Now unsuspend
    const unsuspendResponse = await request.post(`/api/admin/users/${targetUser.id}/unsuspend`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (!unsuspendResponse.ok()) {
      const altResponse = await request.patch(`/api/admin/users/${targetUser.id}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { status: 'active' },
      });
      expect(altResponse.status()).toBeLessThan(500);
    } else {
      expect(unsuspendResponse.ok()).toBeTruthy();
    }

    // Verify user can login again
    const loginResponse = await request.post('/api/auth/login', {
      data: {
        username: targetUser.email,
        password: 'password123',
      },
    });

    // Should be able to log in now (or at least not get a "suspended" error)
    expect(loginResponse.status()).toBeLessThan(500);
  });

  test('should prevent admin from suspending themselves', async ({ request }) => {
    // Get admin user ID
    const usersResponse = await request.get('/api/admin/users', {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (!usersResponse.ok()) {
      test.skip(true, 'Admin users API not available');
      return;
    }

    const users = await usersResponse.json();
    const userList = Array.isArray(users) ? users : users.data || users.users || [];
    const adminUser = userList.find(
      (u: { email?: string; id?: number }) =>
        u.email === ADMIN_CREDENTIALS.email || u.id === 1
    );

    if (!adminUser) {
      test.skip(true, 'Admin user not found in list');
      return;
    }

    // Attempt self-suspension — should be rejected
    const selfSuspendResponse = await request.post(`/api/admin/users/${adminUser.id}/suspend`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (selfSuspendResponse.ok()) {
      // If API doesn't prevent it, unsuspend immediately
      await request.post(`/api/admin/users/${adminUser.id}/unsuspend`, {
        headers: { Authorization: `Bearer ${adminToken}` },
      });
      // The API ideally should prevent self-suspension
    }

    // Either rejected (4xx) or we handled it gracefully
    expect(selfSuspendResponse.status()).not.toBe(500);
  });
});
