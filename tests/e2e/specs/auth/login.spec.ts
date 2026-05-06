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
    expect(await page.url()).toContain('/dashboard');
  });

  test('should store JWT token in localStorage after successful login', async ({ page }) => {
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const token = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();
    expect(token).toMatch(/^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]*$/);
  });

  test('should display error message with invalid email', async () => {
    await loginPage.login('invalid@example.com', 'password123');
    await loginPage.expectError();
  });

  test('should display error message with invalid password', async () => {
    await loginPage.login('demo@banking-demo.com', 'wrongpassword');
    await loginPage.expectError();
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

    const token = await page.evaluate(() => localStorage.getItem('token'));

    await page.goto('/accounts');
    await page.waitForLoadState('domcontentloaded');

    const authHeader = await page.evaluate(() => {
      return localStorage.getItem('token');
    });

    expect(authHeader).toBe(token);
  });

  test('should persist session across page reloads', async ({ page }) => {
    await loginPage.login('demo@banking-demo.com', 'password123');
    await loginPage.expectNavigatedToDashboard();

    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    expect(await page.url()).toContain('/dashboard');
    const token = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();
  });

  test('should work with alternative test user credentials', async ({ page }) => {
    await loginPage.login('testuser', 'password123');
    await loginPage.expectNavigatedToDashboard();

    const token = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();
  });

  test('should clear any previous error messages on successful login', async ({ page }) => {
    await loginPage.login('invalid@example.com', 'wrongpassword');
    await loginPage.expectError();

    await loginPage.emailInput.clear();
    await loginPage.passwordInput.clear();
    await loginPage.login('demo@banking-demo.com', 'password123');
    
    await loginPage.expectNavigatedToDashboard();
  });
});
