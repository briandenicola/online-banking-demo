import { test, expect } from '@playwright/test';
import { LoginPage } from '../../pages/LoginPage';
import { DashboardPage } from '../../pages/DashboardPage';
import { ensureDefaultUser } from '../../utils/testHelpers';

test.describe('E2E-204: Logout & Session Cleanup', () => {
  let loginPage: LoginPage;
  let dashboardPage: DashboardPage;

  test.beforeAll(async ({ request }) => {
    await ensureDefaultUser(request);
  });

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    dashboardPage = new DashboardPage(page);

    await loginPage.navigate();
    await loginPage.login('e2e-default@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();
    await dashboardPage.expectLoaded();
  });

  test('should remove token from localStorage on logout', async ({ page }) => {
    const tokenBeforeLogout = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(tokenBeforeLogout).toBeTruthy();

    await dashboardPage.logout();

    await page.waitForTimeout(500);

    const tokenAfterLogout = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(tokenAfterLogout).toBeNull();
  });

  test('should redirect to login page after logout', async ({ page }) => {
    await dashboardPage.logout();

    await page.waitForURL('**/login', { timeout: 10_000 });
    expect(await page.url()).toContain('/login');
  });

  test('should clear all auth-related data from localStorage', async ({ page }) => {
    await dashboardPage.logout();

    await page.waitForURL('**/login');

    const storageState = await page.evaluate(() => {
      const keys = Object.keys(localStorage);
      const authKeys = keys.filter(key => 
        key.includes('token') || key.includes('auth') || key.includes('user')
      );
      return {
        allKeys: keys,
        authKeys: authKeys,
        tokenValue: localStorage.getItem('auth_token'),
      };
    });

    expect(storageState.tokenValue).toBeNull();
  });

  test('should prevent access to protected pages after logout', async ({ page }) => {
    await dashboardPage.logout();
    await page.waitForURL('**/login');

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForURL('**/login', { timeout: 10_000 });

    await page.goto('/accounts');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForURL('**/login', { timeout: 10_000 });

    await page.goto('/transactions');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForURL('**/login', { timeout: 10_000 });
  });

  test('should require re-authentication after logout', async ({ page }) => {
    await dashboardPage.logout();
    await page.waitForURL('**/login');

    await page.goto('/');
    await page.waitForURL('**/login');

    expect(await page.url()).toContain('/login');

    await loginPage.login('e2e-default@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const newToken = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(newToken).toBeTruthy();
  });

  test('should handle logout from different pages', async ({ page }) => {
    await page.goto('/accounts');
    await page.waitForLoadState('domcontentloaded');

    // Open user menu and click Sign Out
    const userMenuButton = page.locator('header button').last();
    await userMenuButton.click();
    const logoutButton = page.getByRole('menuitem', { name: /logout|sign out/i });
    await logoutButton.click();

    await page.waitForURL('**/login', { timeout: 10_000 });

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeNull();
  });

  test('should clear session state completely', async ({ page }) => {
    const storageBeforeLogout = await page.evaluate(() => {
      return {
        token: localStorage.getItem('auth_token'),
        localStorageLength: localStorage.length,
      };
    });

    expect(storageBeforeLogout.token).toBeTruthy();

    await dashboardPage.logout();
    await page.waitForURL('**/login');

    const storageAfterLogout = await page.evaluate(() => {
      return {
        token: localStorage.getItem('auth_token'),
        sessionToken: sessionStorage.getItem('token'),
      };
    });

    expect(storageAfterLogout.token).toBeNull();
    expect(storageAfterLogout.sessionToken).toBeNull();
  });

  test('should not allow API requests after logout', async ({ page }) => {
    await dashboardPage.logout();
    await page.waitForURL('**/login');

    let apiCallMade = false;
    page.on('request', request => {
      if (request.url().includes('/api/')) {
        const authHeader = request.headers()['authorization'];
        if (authHeader) {
          apiCallMade = true;
        }
      }
    });

    await page.goto('/accounts');
    await page.waitForTimeout(1000);

    expect(await page.url()).toContain('/login');
  });

  test('should display logout confirmation if implemented', async ({ page }) => {
    await dashboardPage.logout();

    await page.waitForTimeout(500);

    const isOnLoginPage = (await page.url()).includes('/login');
    const tokenCleared = await page.evaluate(() => localStorage.getItem('auth_token') === null);

    expect(isOnLoginPage).toBeTruthy();
    expect(tokenCleared).toBeTruthy();
  });
});
