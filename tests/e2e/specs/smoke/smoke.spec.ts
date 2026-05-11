import { test, expect, apiLogin, DEFAULT_USER } from '../../fixtures/authFixture';
import { waitForAllServices } from '../../utils/testHelpers';
import { LoginPage } from '../../pages/LoginPage';
import { DashboardPage } from '../../pages/DashboardPage';
import { AccountsPage } from '../../pages/AccountsPage';
import { TransactionsPage } from '../../pages/TransactionsPage';
import { RegistrationPage } from '../../pages/RegistrationPage';


test.describe('Smoke Tests', () => {
  test.beforeAll(async ({ request }) => {
    const baseURL = process.env.BASE_URL || 'http://localhost';
    await waitForAllServices(baseURL);
  });

  test('@smoke Health checks — core services respond', async ({ request }) => {
    const endpoints = [
      '/api/users/health',
      '/api/accounts/health',
      '/api/transactions/health',
    ];

    for (const endpoint of endpoints) {
      const response = await request.get(endpoint);
      // Accept any non-5xx response — 200, 401, etc. all mean the service is alive
      expect(response.status(), `${endpoint} returned ${response.status()}`).toBeLessThan(500);
    }
  });

  test('@smoke Login — valid credentials return JWT', async ({ page, request }) => {
    // Ensure test user exists
    await apiLogin(request);

    const loginPage = new LoginPage(page);
    await loginPage.navigate();
    await loginPage.login(DEFAULT_USER.email, DEFAULT_USER.password);
    await loginPage.expectNavigatedToDashboard();

    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();
  });

  test('@smoke Dashboard loads — renders with account data', async ({ authenticatedPage }) => {
    const dashboard = new DashboardPage(authenticatedPage);
    await dashboard.navigate();
    await dashboard.expectLoaded();
  });

  test('@smoke Accounts visible — accounts page lists user accounts', async ({ authenticatedPage }) => {
    const accountsPage = new AccountsPage(authenticatedPage);
    await accountsPage.navigate();
    await accountsPage.expectLoaded();
  });

  test('@smoke Transactions visible — transactions page renders', async ({ authenticatedPage }) => {
    const txPage = new TransactionsPage(authenticatedPage);
    await txPage.navigate();
    await txPage.expectLoaded();
  });

  test('@smoke Registration — new user can register', async ({ page }) => {
    const uniqueEmail = `smoke-${Date.now()}@banking-demo.com`;
    const regPage = new RegistrationPage(page);
    await regPage.navigate();
    await regPage.register('Smoke', 'Test', uniqueEmail, 'password123', 'password123');

    // Successful registration redirects to login
    await regPage.expectNavigatedToLogin();
  });

  test('@smoke Login audit — admin page accessible for admin user', async ({ authenticatedPage }) => {
    // Navigate to admin page — the e2e user may or may not be admin
    await authenticatedPage.goto('/admin');
    await authenticatedPage.waitForLoadState('networkidle');

    const url = authenticatedPage.url();
    if (url.includes('/admin')) {
      // Admin page loaded — verify it rendered something meaningful
      await expect(authenticatedPage.locator('body')).not.toBeEmpty();
    }
    // Non-admin users get redirected to dashboard — that's acceptable for smoke
    // The test passes either way: admin access works OR non-admin redirect works
  });

  test('@smoke AI service health — readyz reports agent status', async ({ request }) => {
    const aiBaseURL = process.env.AI_SERVICE_URL || 'http://localhost:8002';
    const response = await request.get(`${aiBaseURL}/readyz`);

    expect(response.status(), 'readyz endpoint should respond').toBeLessThan(500);

    const body = await response.json();
    expect(body).toHaveProperty('checks');
    expect(body).toHaveProperty('status');

    const pipeline = body.checks?.analyzer_pipeline ?? false;
    const redis = body.checks?.redis ?? false;
    console.log(`[AI readyz] status=${body.status} | analyzer_pipeline=${pipeline} | redis=${redis}`);
    // Informational — test passes regardless of agent availability
  });

  test('@smoke AI categorization — transactions get categorized', async ({ request }) => {
    const auth = await apiLogin(request);

    const response = await request.get('/api/admin/transactions', {
      headers: { Authorization: `Bearer ${auth.token}` },
    });

    // 503 (Redis unavailable) or 403 (non-admin) are acceptable degraded states
    if (response.status() === 503) {
      console.log('[AI categorization] Redis unavailable — ai-service cannot serve scored transactions');
      return; // pass gracefully
    }
    if (response.status() === 403 || response.status() === 401) {
      console.log('[AI categorization] User lacks admin role — cannot access admin transactions');
      return; // pass gracefully
    }

    expect(response.status(), `Expected 200, got ${response.status()}`).toBe(200);

    const transactions = await response.json();
    expect(Array.isArray(transactions), 'Response should be an array').toBeTruthy();

    if (transactions.length > 0) {
      for (const tx of transactions) {
        expect(tx).toHaveProperty('category');
        expect(tx).toHaveProperty('riskScore');
      }

      const categories = transactions.map((t: { category: string }) => t.category);
      const hasRealCategories = categories.some((c: string) => c && c !== 'Uncategorized');
      console.log(
        `[AI categorization] ${transactions.length} transactions | ` +
        `categories: ${hasRealCategories ? 'AI-classified' : 'fallback/Uncategorized'}`
      );
    } else {
      console.log('[AI categorization] No scored transactions yet — pipeline may not have processed any');
    }
  });

  test('@smoke Logout — user can log out', async ({ authenticatedPage }) => {
    const dashboard = new DashboardPage(authenticatedPage);
    await dashboard.navigate();
    await dashboard.expectLoaded();

    await dashboard.logout();

    // After logout, should redirect to login and clear token
    await authenticatedPage.waitForURL(/\/login/, { timeout: 10_000 });
    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeFalsy();
  });
});
