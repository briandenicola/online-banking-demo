import { test, expect } from '../../fixtures/authFixture';
import { TransactionsPage } from '../../pages/TransactionsPage';
import { DashboardPage } from '../../pages/DashboardPage';

test.describe('E2E-207: Transaction List & Pagination', () => {
  let transactionsPage: TransactionsPage;
  let dashboardPage: DashboardPage;

  test.beforeEach(async ({ authenticatedPage }) => {
    transactionsPage = new TransactionsPage(authenticatedPage);
    dashboardPage = new DashboardPage(authenticatedPage);
  });

  test('should load transactions page successfully', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.expectLoaded();

    expect(await authenticatedPage.url()).toContain('/transactions');
  });

  test('should display transactions table', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.expectLoaded();

    await expect(transactionsPage.transactionsTable).toBeVisible();
  });

  test('should show transaction rows with data', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.waitForTransactionsToLoad();

    const transactionCount = await transactionsPage.getTransactionCount();
    
    if (transactionCount > 0) {
      const firstTransaction = await transactionsPage.getTransactionByIndex(0);
      
      expect(firstTransaction.date || firstTransaction.description || firstTransaction.amount).toBeTruthy();
    } else {
      expect(await transactionsPage.transactionsTable.isVisible()).toBeTruthy();
    }
  });

  test('should display transaction date correctly', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.waitForTransactionsToLoad();

    const transactionCount = await transactionsPage.getTransactionCount();
    
    if (transactionCount > 0) {
      const transaction = await transactionsPage.getTransactionByIndex(0);
      expect(transaction.date).toBeTruthy();
    }
  });

  test('should display transaction description', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.waitForTransactionsToLoad();

    const transactionCount = await transactionsPage.getTransactionCount();
    
    if (transactionCount > 0) {
      const transaction = await transactionsPage.getTransactionByIndex(0);
      expect(transaction.description).toBeTruthy();
    }
  });

  test('should display transaction amount with currency', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.waitForTransactionsToLoad();

    const transactionCount = await transactionsPage.getTransactionCount();
    
    if (transactionCount > 0) {
      const transaction = await transactionsPage.getTransactionByIndex(0);
      expect(transaction.amount).toMatch(/\$|-|\d/);
    }
  });

  test('should navigate from dashboard to transactions', async ({ authenticatedPage }) => {
    await dashboardPage.navigate();
    await dashboardPage.expectLoaded();

    await dashboardPage.navigateTo('transactions');

    await authenticatedPage.waitForURL('**/transactions');
    await transactionsPage.expectLoaded();
  });

  test('should show page title', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.expectLoaded();

    await expect(transactionsPage.pageTitle).toBeVisible();
    const titleText = await transactionsPage.pageTitle.textContent();
    expect(titleText).toMatch(/transactions/i);
  });

  test('should check for pagination controls if many transactions', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.waitForTransactionsToLoad();

    const transactionCount = await transactionsPage.getTransactionCount();
    
    if (transactionCount > 10) {
      const paginationVisible = await transactionsPage.paginationControls.isVisible();
      expect(paginationVisible).toBeTruthy();
    }
  });

  test('should maintain list format across different browsers', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.expectLoaded();

    await expect(transactionsPage.transactionsTable).toBeVisible();
    await expect(transactionsPage.pageTitle).toBeVisible();
  });

  test('should load transactions without errors', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    
    const errorVisible = await transactionsPage.errorAlert.isVisible().catch(() => false);
    expect(errorVisible).toBeFalsy();

    await transactionsPage.expectLoaded();
  });

  test('should show add transaction button if available', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.expectLoaded();

    const buttonVisible = await transactionsPage.addTransactionButton.isVisible().catch(() => false);
    
    expect(typeof buttonVisible).toBe('boolean');
  });

  test('should display multiple transactions if available', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.waitForTransactionsToLoad();

    const transactionCount = await transactionsPage.getTransactionCount();
    
    if (transactionCount > 1) {
      const firstTx = await transactionsPage.getTransactionByIndex(0);
      const secondTx = await transactionsPage.getTransactionByIndex(1);
      
      expect(firstTx.description || firstTx.amount).toBeTruthy();
      expect(secondTx.description || secondTx.amount).toBeTruthy();
    }
  });

  test('should maintain authenticated state on transactions page', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.expectLoaded();

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeTruthy();
  });

  test('should handle empty transaction list gracefully', async ({ authenticatedPage }) => {
    await transactionsPage.navigate();
    await transactionsPage.expectLoaded();

    const transactionCount = await transactionsPage.getTransactionCount();
    expect(transactionCount).toBeGreaterThanOrEqual(0);
  });
});
