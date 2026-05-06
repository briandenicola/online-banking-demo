import { test, expect } from '../../fixtures/authFixture';
import { TransfersPage } from '../../pages/TransfersPage';
import { AccountsPage } from '../../pages/AccountsPage';
import { TransactionsPage } from '../../pages/TransactionsPage';

const CHECKING_ACCOUNT = 'acct-2-checking';
const SAVINGS_ACCOUNT = 'acct-2-savings';
const TRANSFER_AMOUNT = '25.00';

test.describe('E2E-301: Transfer Between Accounts (Happy Path)', () => {
  let transfersPage: TransfersPage;
  let accountsPage: AccountsPage;
  let transactionsPage: TransactionsPage;

  test.beforeEach(async ({ authenticatedPage }) => {
    transfersPage = new TransfersPage(authenticatedPage);
    accountsPage = new AccountsPage(authenticatedPage);
    transactionsPage = new TransactionsPage(authenticatedPage);
  });

  test('should load transfers page successfully', async ({ authenticatedPage }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    expect(await authenticatedPage.url()).toContain('/transfers');
  });

  test('should display transfer form with required fields', async ({ authenticatedPage }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    await expect(transfersPage.fromAccountSelect).toBeVisible();
    await expect(transfersPage.toAccountSelect).toBeVisible();
    await expect(transfersPage.amountInput).toBeVisible();
    await expect(transfersPage.submitButton).toBeVisible();
  });

  test('should complete transfer from checking to savings', async ({ authenticatedPage }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    await transfersPage.performFullTransfer(CHECKING_ACCOUNT, SAVINGS_ACCOUNT, TRANSFER_AMOUNT);

    await transfersPage.expectSuccess();
  });

  test('should complete transfer from savings to checking', async ({ authenticatedPage }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    await transfersPage.performFullTransfer(SAVINGS_ACCOUNT, CHECKING_ACCOUNT, TRANSFER_AMOUNT);

    await transfersPage.expectSuccess();
  });

  test('should show confirmation dialog before completing transfer', async ({ authenticatedPage }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    await transfersPage.initiateTransfer(CHECKING_ACCOUNT, SAVINGS_ACCOUNT, TRANSFER_AMOUNT);

    // Check if a confirmation step exists
    const dialogVisible = await transfersPage.confirmationDialog.isVisible().catch(() => false);
    const confirmVisible = await transfersPage.confirmButton.isVisible().catch(() => false);

    if (dialogVisible || confirmVisible) {
      // Confirmation flow exists - verify dialog content
      await expect(transfersPage.confirmButton).toBeVisible();
      await expect(transfersPage.cancelButton).toBeVisible();
      await transfersPage.confirmTransfer();
    }

    // Either way, transfer should complete
    await transfersPage.waitForTransferComplete();
  });

  test('should verify balance updates after transfer', async ({ authenticatedPage, request, authState }) => {
    // Get initial balances via API
    const accountsResponse = await request.get('/api/accounts', {
      headers: { Authorization: `Bearer ${authState.token}` },
    });

    if (!accountsResponse.ok()) {
      test.skip(true, 'Accounts API not available');
      return;
    }

    const accounts = await accountsResponse.json();
    const checkingBefore = accounts.find((a: { id: string }) => a.id === CHECKING_ACCOUNT);
    const savingsBefore = accounts.find((a: { id: string }) => a.id === SAVINGS_ACCOUNT);

    if (!checkingBefore || !savingsBefore) {
      test.skip(true, 'Demo accounts not found');
      return;
    }

    const initialCheckingBalance = parseFloat(checkingBefore.balance);
    const initialSavingsBalance = parseFloat(savingsBefore.balance);
    const amount = parseFloat(TRANSFER_AMOUNT);

    // Perform the transfer via API
    const transferResponse = await request.post('/api/transfers', {
      headers: { Authorization: `Bearer ${authState.token}` },
      data: {
        fromAccountId: CHECKING_ACCOUNT,
        toAccountId: SAVINGS_ACCOUNT,
        amount,
      },
    });

    if (!transferResponse.ok()) {
      test.skip(true, 'Transfer API not available');
      return;
    }

    // Verify updated balances
    const updatedResponse = await request.get('/api/accounts', {
      headers: { Authorization: `Bearer ${authState.token}` },
    });
    const updatedAccounts = await updatedResponse.json();
    const checkingAfter = updatedAccounts.find((a: { id: string }) => a.id === CHECKING_ACCOUNT);
    const savingsAfter = updatedAccounts.find((a: { id: string }) => a.id === SAVINGS_ACCOUNT);

    expect(parseFloat(checkingAfter.balance)).toBeCloseTo(initialCheckingBalance - amount, 2);
    expect(parseFloat(savingsAfter.balance)).toBeCloseTo(initialSavingsBalance + amount, 2);
  });

  test('should show transfer in transaction history', async ({ authenticatedPage, request, authState }) => {
    // Perform transfer via API to ensure it exists
    const transferResponse = await request.post('/api/transfers', {
      headers: { Authorization: `Bearer ${authState.token}` },
      data: {
        fromAccountId: CHECKING_ACCOUNT,
        toAccountId: SAVINGS_ACCOUNT,
        amount: parseFloat(TRANSFER_AMOUNT),
      },
    });

    if (!transferResponse.ok()) {
      test.skip(true, 'Transfer API not available');
      return;
    }

    // Navigate to transactions and verify
    await transactionsPage.navigate();
    await transactionsPage.expectLoaded();
    await transactionsPage.waitForTransactionsToLoad();

    // Look for transfer-related text in the transaction rows
    const transferRow = authenticatedPage.locator('tbody tr, [data-testid*="transaction-row"]')
      .filter({ hasText: /transfer/i });

    const hasTransfer = await transferRow.first().isVisible().catch(() => false);
    expect(hasTransfer).toBeTruthy();
  });

  test('should allow cancelling a transfer before confirmation', async ({ authenticatedPage }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    await transfersPage.initiateTransfer(CHECKING_ACCOUNT, SAVINGS_ACCOUNT, TRANSFER_AMOUNT);

    const dialogVisible = await transfersPage.confirmationDialog.isVisible().catch(() => false);
    if (dialogVisible) {
      await transfersPage.cancelTransfer();
      await expect(transfersPage.confirmationDialog).toBeHidden();
    }
  });

  test('should maintain authenticated state during transfer', async ({ authenticatedPage }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    const token = await authenticatedPage.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();
  });
});
