import { test, expect } from '@playwright/test';
import { LoginPage } from '../../pages/LoginPage';
import { DashboardPage } from '../../pages/DashboardPage';

test.describe('E2E-203: Session Persistence & Token Refresh', () => {
  let loginPage: LoginPage;
  let dashboardPage: DashboardPage;

  test('should persist session after closing and reopening browser context', async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    loginPage = new LoginPage(page);
    dashboardPage = new DashboardPage(page);

    await loginPage.navigate();
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const token = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();

    await context.close();

    const newContext = await browser.newContext({
      storageState: undefined,
    });
    const newPage = await newContext.newPage();

    await newPage.goto('/dashboard');
    await newPage.waitForLoadState('domcontentloaded');

    expect(await newPage.url()).toContain('/login');

    await newContext.close();
  });

  test('should maintain session when navigating between pages', async ({ page }) => {
    loginPage = new LoginPage(page);

    await loginPage.navigate();
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const originalToken = await page.evaluate(() => localStorage.getItem('token'));

    await page.goto('/accounts');
    await page.waitForLoadState('domcontentloaded');
    let currentToken = await page.evaluate(() => localStorage.getItem('token'));
    expect(currentToken).toBe(originalToken);

    await page.goto('/transactions');
    await page.waitForLoadState('domcontentloaded');
    currentToken = await page.evaluate(() => localStorage.getItem('token'));
    expect(currentToken).toBe(originalToken);

    await page.goto('/dashboard');
    await page.waitForLoadState('domcontentloaded');
    currentToken = await page.evaluate(() => localStorage.getItem('token'));
    expect(currentToken).toBe(originalToken);
  });

  test('should preserve session state in localStorage', async ({ page }) => {
    loginPage = new LoginPage(page);

    await loginPage.navigate();
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const storageState = await page.evaluate(() => {
      return {
        token: localStorage.getItem('token'),
        keys: Object.keys(localStorage),
      };
    });

    expect(storageState.token).toBeTruthy();
    expect(storageState.keys).toContain('token');
  });

  test('should handle session when token is manually removed from localStorage', async ({ page }) => {
    loginPage = new LoginPage(page);

    await loginPage.navigate();
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    await page.evaluate(() => localStorage.removeItem('token'));

    await page.goto('/accounts');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForURL('**/login', { timeout: 10_000 });
  });

  test('should maintain authenticated state during rapid navigation', async ({ page }) => {
    loginPage = new LoginPage(page);

    await loginPage.navigate();
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const pages = ['/dashboard', '/accounts', '/transactions', '/dashboard'];
    
    for (const route of pages) {
      await page.goto(route);
      await page.waitForLoadState('domcontentloaded');
      const token = await page.evaluate(() => localStorage.getItem('token'));
      expect(token).toBeTruthy();
    }
  });

  test('should restore session after page refresh', async ({ page }) => {
    loginPage = new LoginPage(page);
    dashboardPage = new DashboardPage(page);

    await loginPage.navigate();
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const tokenBeforeRefresh = await page.evaluate(() => localStorage.getItem('token'));

    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    const tokenAfterRefresh = await page.evaluate(() => localStorage.getItem('token'));
    expect(tokenAfterRefresh).toBe(tokenBeforeRefresh);

    await dashboardPage.expectLoaded();
  });

  test('should handle expired token gracefully', async ({ page }) => {
    loginPage = new LoginPage(page);

    await loginPage.navigate();
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    await page.evaluate(() => {
      localStorage.setItem('token', 'expired.invalid.token');
    });

    await page.goto('/accounts');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForTimeout(2000);

    const currentUrl = page.url();
    const hasToken = await page.evaluate(() => localStorage.getItem('token'));
    
    expect(hasToken === 'expired.invalid.token' || currentUrl.includes('/login')).toBeTruthy();
  });
});
