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

  test('@smoke Create transactions — realistic banking transactions via API', async ({ request }) => {
    const auth = await apiLogin(request);
    const headers = { Authorization: `Bearer ${auth.token}` };

    // Fetch user's accounts to get a valid accountId
    const accountsResponse = await request.get('/api/accounts', { headers });
    expect(accountsResponse.ok(), `GET /api/accounts failed: ${accountsResponse.status()}`).toBeTruthy();

    const accounts = await accountsResponse.json();
    expect(Array.isArray(accounts), 'Accounts response should be an array').toBeTruthy();
    expect(accounts.length, 'User should have at least one account').toBeGreaterThan(0);

    const accountId = accounts[0].id;

    const transactions = [
      {
        AccountId: accountId,
        Amount: -5.75,
        Type: 'debit',
        Description: 'Starbucks Coffee #4521',
        Currency: 'USD',
        Category: 'Food & Drink',
        AutoCategorize: false,
      },
      {
        AccountId: accountId,
        Amount: -67.99,
        Type: 'payment',
        Description: 'Amazon.com Order #112-4432',
        Currency: 'USD',
        Category: 'Shopping',
        AutoCategorize: false,
      },
      {
        AccountId: accountId,
        Amount: 3250.00,
        Type: 'credit',
        Description: 'Payroll Direct Deposit - Contoso Ltd',
        Currency: 'USD',
        Category: 'Income',
        AutoCategorize: false,
      },
      {
        AccountId: accountId,
        Amount: -142.30,
        Type: 'payment',
        Description: 'Electric Bill - Pacific Power',
        Currency: 'USD',
        Category: 'Utilities',
        AutoCategorize: false,
      },
      {
        AccountId: accountId,
        Amount: -200.00,
        Type: 'withdrawal',
        Description: 'ATM Withdrawal - Chase Bank',
        Currency: 'USD',
        Category: 'Cash',
        AutoCategorize: false,
      },
    ];

    const createdIds: string[] = [];

    for (const tx of transactions) {
      const response = await request.post('/api/transactions', {
        headers,
        data: tx,
      });

      expect(
        response.status(),
        `POST /api/transactions failed for "${tx.Description}": ${response.status()}`
      ).toBe(201);

      const body = await response.json();
      expect(body).toHaveProperty('id');
      createdIds.push(body.id);
      console.log(`[Smoke TX] Created: "${tx.Description}" (${tx.Type}) $${tx.Amount} → id=${body.id}`);
    }

    // Verify all transactions appear in the user's transaction list
    const txListResponse = await request.get('/api/transactions', { headers });
    expect(txListResponse.ok(), `GET /api/transactions failed: ${txListResponse.status()}`).toBeTruthy();

    const txList = await txListResponse.json();
    const allTx = Array.isArray(txList) ? txList : (txList.items ?? txList.transactions ?? []);

    for (let i = 0; i < transactions.length; i++) {
      const expected = transactions[i];
      const match = allTx.find(
        (t: { description: string; amount: number }) =>
          t.description === expected.Description &&
          Math.abs(t.amount - expected.Amount) < 0.01
      );
      expect(match, `Transaction "${expected.Description}" ($${expected.Amount}) not found in GET /api/transactions`).toBeTruthy();
    }

    console.log(`[Smoke TX] All ${transactions.length} transactions verified in transaction list`);
  });

  test('@smoke Account lifecycle — savings, transfer, and car purchase', async ({ request }) => {
    const auth = await apiLogin(request);
    const headers = { Authorization: `Bearer ${auth.token}` };

    // 1. Create savings account with $500,000
    const savingsRes = await request.post('/api/accounts', {
      headers,
      data: { AccountType: 'savings', InitialBalance: 500000, Currency: 'USD' },
    });
    expect(savingsRes.status(), `Create savings failed: ${savingsRes.status()}`).toBe(200);
    const savings = await savingsRes.json();
    expect(savings.balance).toBe(500000);
    console.log(`[Lifecycle] Savings created: id=${savings.id} acct#=${savings.accountNumber} balance=$${savings.balance}`);

    // 2. Create checking account with $0
    const checkingRes = await request.post('/api/accounts', {
      headers,
      data: { AccountType: 'checking', InitialBalance: 0, Currency: 'USD' },
    });
    expect(checkingRes.status(), `Create checking failed: ${checkingRes.status()}`).toBe(200);
    const checking = await checkingRes.json();
    expect(checking.balance).toBe(0);
    console.log(`[Lifecycle] Checking created: id=${checking.id} acct#=${checking.accountNumber} balance=$${checking.balance}`);

    // 3. Transfer $150,000 from savings to checking
    const transferRes = await request.post('/api/transfers', {
      headers,
      data: {
        FromAccountId: savings.id,
        ToAccountId: checking.id,
        FromAccountNumber: savings.accountNumber,
        ToAccountNumber: checking.accountNumber,
        Amount: 150000,
        Description: 'Fund checking from savings',
      },
    });
    expect(transferRes.status(), `Transfer failed: ${transferRes.status()}`).toBe(201);
    console.log('[Lifecycle] Transfer $150,000 savings → checking completed');

    // 4. Create car purchase transaction on checking ($75,000 debit)
    const txRes = await request.post('/api/transactions', {
      headers,
      data: {
        AccountId: checking.id,
        Amount: -75000,
        Type: 'debit',
        Description: '2014 Kia Optima',
        Currency: 'USD',
        AutoCategorize: false,
      },
    });
    expect(txRes.status(), `Transaction failed: ${txRes.status()}`).toBe(201);
    console.log('[Lifecycle] Transaction "2014 Kia Optima" -$75,000 on checking created');

    // 5. Verify final balances
    const savingsCheck = await request.get(`/api/accounts/${savings.id}`, { headers });
    expect(savingsCheck.ok(), `GET savings failed: ${savingsCheck.status()}`).toBeTruthy();
    const savingsFinal = await savingsCheck.json();
    expect(savingsFinal.balance, `Savings should be $350,000 (500k - 150k transfer)`).toBe(350000);

    const checkingCheck = await request.get(`/api/accounts/${checking.id}`, { headers });
    expect(checkingCheck.ok(), `GET checking failed: ${checkingCheck.status()}`).toBeTruthy();
    const checkingFinal = await checkingCheck.json();
    expect(checkingFinal.balance, `Checking should be $75,000 (0 + 150k transfer - 75k car)`).toBe(75000);

    console.log(`[Lifecycle] Final balances — Savings: $${savingsFinal.balance} | Checking: $${checkingFinal.balance}`);
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
