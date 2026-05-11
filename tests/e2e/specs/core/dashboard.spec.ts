import { test, expect } from '../../fixtures/authFixture';
import { DashboardPage } from '../../pages/DashboardPage';
import { AccountsPage } from '../../pages/AccountsPage';

test.describe('E2E-205: Dashboard Load & Account Display', () => {
  let dashboardPage: DashboardPage;
  let accountsPage: AccountsPage;

  test.beforeEach(async ({ authenticatedPage }) => {
    dashboardPage = new DashboardPage(authenticatedPage);
    accountsPage = new AccountsPage(authenticatedPage);
  });

  test('@smoke should load dashboard successfully after authentication', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    expect(authenticatedPage.url()).toMatch(/\/(\?.*)?$/);
  });

  test('should display welcome message on dashboard', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    await expect(dashboardPage.welcomeMessage.first()).toBeVisible();
    const welcomeText = await dashboardPage.welcomeMessage.first().textContent();
    expect(welcomeText).toBeTruthy();
  });

  test('@smoke should display accounts list on dashboard', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    const accountCount = await dashboardPage.getAccountCount();
    expect(accountCount).toBeGreaterThan(0);
  });

  test('should show account cards with balances', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    const accountsList = dashboardPage.accountsList;
    await expect(accountsList).toBeVisible();

    const accountCards = accountsList.locator('li, [data-testid*="account"]').first();
    await expect(accountCards).toBeVisible();

    const accountText = await accountCards.textContent();
    expect(accountText).toMatch(/\$|account|balance/i);
  });

  test('should display navigation links', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    const navLinks = dashboardPage.navLinks;
    const linkCount = await navLinks.count();
    expect(linkCount).toBeGreaterThan(0);
  });

  test('should display logout button', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    // Logout is behind the avatar menu dropdown
    await dashboardPage.userMenuButton.click();
    await expect(dashboardPage.logoutButton).toBeVisible();
  });

  test('should navigate to accounts page from dashboard', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    await dashboardPage.navigateTo('accounts');

    await authenticatedPage.waitForURL('**/accounts', { timeout: 10_000 });
    expect(await authenticatedPage.url()).toContain('/accounts');
  });

  test('should render account information correctly', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const accountCount = await accountsPage.getAccountCount();
    expect(accountCount).toBeGreaterThan(0);

    const firstAccount = await accountsPage.getAccountByIndex(0);
    expect(firstAccount.name).toBeTruthy();
    expect(firstAccount.number).toBeTruthy();
    expect(firstAccount.balance).toMatch(/\$/);
  });

  test('should display multiple accounts if user has them', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const accountCount = await accountsPage.getAccountCount();
    
    if (accountCount > 1) {
      const firstAccount = await accountsPage.getAccountByIndex(0);
      const secondAccount = await accountsPage.getAccountByIndex(1);
      
      expect(firstAccount.name).not.toBe(secondAccount.name);
    } else {
      expect(accountCount).toBeGreaterThan(0);
    }
  });

  test('should show proper account types', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const firstAccount = await accountsPage.getAccountByIndex(0);
    expect(firstAccount.type).toMatch(/checking|savings|credit/i);
  });

  test('should format balances correctly', async ({ authenticatedPage }) => {
    await accountsPage.navigate();
    await accountsPage.expectLoaded();

    const firstAccount = await accountsPage.getAccountByIndex(0);
    expect(firstAccount.balance).toMatch(/\$\d+(\.\d{2})?/);
  });

  test('should maintain authentication state on dashboard', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();
  });
});
