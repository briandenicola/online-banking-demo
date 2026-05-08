import { test, expect } from '../../fixtures/authFixture';
import { AccountsPage } from '../../pages/AccountsPage';
import { DashboardPage } from '../../pages/DashboardPage';

test.describe('E2E-206: View Account Details', () => {
  let accountsPage: AccountsPage;
  let dashboardPage: DashboardPage;

  test.beforeEach(async ({ authenticatedPage }) => {
    accountsPage = new AccountsPage(authenticatedPage);
    dashboardPage = new DashboardPage(authenticatedPage);
  });

  test('should load accounts page successfully', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    expect(await authenticatedPage.url()).toContain('/accounts');
  });

  test('should display all user accounts', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const accountCount = await accountsPage.getAccountCount();
    expect(accountCount).toBeGreaterThan(0);
  });

  test('should show account details in table format', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    await expect(accountsPage.accountsTable).toBeVisible();
    await expect(accountsPage.accountRows.first()).toBeVisible();
  });

  test('should display account name, number, type, and balance', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const account = await accountsPage.getAccountByIndex(0);
    
    expect(account.name).toBeTruthy();
    expect(account.number).toBeTruthy();
    expect(account.type).toBeTruthy();
    expect(account.balance).toMatch(/\$/);
  });

  test('should show correct account types', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const account = await accountsPage.getAccountByIndex(0);
    expect(account.type).toMatch(/checking|savings|credit|investment/i);
  });

  test('should format account numbers correctly', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const account = await accountsPage.getAccountByIndex(0);
    expect(account.number).toMatch(/\d+/);
  });

  test('should display balances with currency formatting', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const account = await accountsPage.getAccountByIndex(0);
    expect(account.balance).toMatch(/\$\s*\d+(\.\d{2})?/);
  });

  test('should click on account row to view details', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const firstAccount = await accountsPage.getAccountByIndex(0);
    
    await accountsPage.clickAccountByName(firstAccount.name);
    
    await authenticatedPage.waitForTimeout(1000);
  });

  test('should navigate from dashboard to accounts', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    await dashboardPage.navigateTo('accounts');

    await authenticatedPage.waitForURL('**/accounts');
    await accountsPage.expectLoaded();
  });

  test('should show add account button', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    await expect(accountsPage.addAccountButton).toBeVisible();
  });

  test('should maintain authenticated state on accounts page', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();
  });

  test('should handle accounts with different balance types', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const accountCount = await accountsPage.getAccountCount();
    
    for (let i = 0; i < Math.min(accountCount, 3); i++) {
      const account = await accountsPage.getAccountByIndex(i);
      expect(account.balance).toMatch(/\$/);
    }
  });

  test('should show page title', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    await expect(accountsPage.pageTitle).toBeVisible();
    const titleText = await accountsPage.pageTitle.textContent();
    expect(titleText).toMatch(/accounts/i);
  });
});
