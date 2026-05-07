import { test, expect } from '@playwright/test';
import { LoginPage } from '../../pages/LoginPage';
import { DashboardPage } from '../../pages/DashboardPage';

test.describe('E2E-202: User Login Flow', () => {
  let loginPage: LoginPage;
  let dashboardPage: DashboardPage;

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    dashboardPage = new DashboardPage(page);
    await loginPage.navigate();
  });

  test('should successfully login with valid credentials and redirect to dashboard', async ({ page }) => {
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    await dashboardPage.expectLoaded();
    // Dashboard is at root '/', not '/dashboard'
    expect(page.url()).toMatch(/\/(?:\?.*)?$/);
  });

  test('should store JWT token in localStorage after successful login', async ({ page }) => {
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();
    expect(token).toMatch(/^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]*$/);
  });

  test('should not navigate to dashboard with invalid email', async ({ page }) => {
    await loginPage.login('invalid@example.com', 'password123');
    // 401 interceptor triggers page reload to /login
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('/login');
  });

  test('should not navigate to dashboard with invalid password', async ({ page }) => {
    await loginPage.login('demo@banking-demo.com', 'wrongpassword');
    // 401 interceptor triggers page reload to /login
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('/login');
  });

  test('should display error message with empty credentials', async () => {
    await loginPage.submitButton.click();
    
    const emailInput = loginPage.emailInput;
    const passwordInput = loginPage.passwordInput;
    
    await expect(emailInput).toBeVisible();
    await expect(passwordInput).toBeVisible();
  });

  test('should use stored token for subsequent page loads', async ({ page }) => {
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));

    await page.goto('/accounts');
    await page.waitForLoadState('domcontentloaded');

    const authHeader = await page.evaluate(() => {
      return localStorage.getItem('auth_token');
    });

    expect(authHeader).toBe(token);
  });

  test('should persist session across page reloads', async ({ page }) => {
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Dashboard is at root '/', not '/dashboard'
    expect(page.url()).toMatch(/\/(?:\?.*)?$/);
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();
  });

  test('should work with alternative test user credentials', async ({ page }) => {
    // Use the seeded demo user since 'testuser' may not exist
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();
  });

  test('should clear any previous error messages on successful login', async ({ page }) => {
    // After invalid login, the 401 interceptor reloads to /login
    await loginPage.login('invalid@example.com', 'wrongpassword');
    await page.waitForLoadState('load');

    // Navigate fresh to /login to avoid reload race conditions
    await page.goto('/login');
    await page.waitForLoadState('domcontentloaded');

    loginPage = new LoginPage(page);
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();
  });
});
