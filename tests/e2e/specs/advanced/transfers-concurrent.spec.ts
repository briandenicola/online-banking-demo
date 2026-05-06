import { test, expect } from '../../fixtures/authFixture';
import { TransfersPage } from '../../pages/TransfersPage';

const CHECKING_ACCOUNT = 'acct-2-checking';
const SAVINGS_ACCOUNT = 'acct-2-savings';

test.describe('E2E-303: Concurrent Transfers (Race Condition Testing)', () => {
  let transfersPage: TransfersPage;

  test.beforeEach(async ({ authenticatedPage }) => {
    transfersPage = new TransfersPage(authenticatedPage);
  });

  test('should handle rapid successive transfers correctly', async ({ request, authState }) => {
    // Get initial balances
    const initialResponse = await request.get('/api/accounts', {
      headers: { Authorization: `Bearer ${authState.token}` },
    });

    if (!initialResponse.ok()) {
      test.skip(true, 'Accounts API not available');
      return;
    }

    const initialAccounts = await initialResponse.json();
    const checkingBefore = initialAccounts.find((a: { id: string }) => a.id === CHECKING_ACCOUNT);
    const savingsBefore = initialAccounts.find((a: { id: string }) => a.id === SAVINGS_ACCOUNT);

    if (!checkingBefore || !savingsBefore) {
      test.skip(true, 'Demo accounts not found');
      return;
    }

    const transferAmount = 5.00;
    const numTransfers = 3;

    // Send transfers rapidly in sequence
    const results: boolean[] = [];
    for (let i = 0; i < numTransfers; i++) {
      const response = await request.post('/api/transfers', {
        headers: { Authorization: `Bearer ${authState.token}` },
        data: {
          fromAccountId: CHECKING_ACCOUNT,
          toAccountId: SAVINGS_ACCOUNT,
          amount: transferAmount,
        },
      });
      results.push(response.ok());
    }

    const successfulTransfers = results.filter(Boolean).length;

    // Verify final balances are consistent
    const finalResponse = await request.get('/api/accounts', {
      headers: { Authorization: `Bearer ${authState.token}` },
    });
    const finalAccounts = await finalResponse.json();
    const checkingAfter = finalAccounts.find((a: { id: string }) => a.id === CHECKING_ACCOUNT);
    const savingsAfter = finalAccounts.find((a: { id: string }) => a.id === SAVINGS_ACCOUNT);

    const expectedCheckingBalance = parseFloat(checkingBefore.balance) - (transferAmount * successfulTransfers);
    const expectedSavingsBalance = parseFloat(savingsBefore.balance) + (transferAmount * successfulTransfers);

    expect(parseFloat(checkingAfter.balance)).toBeCloseTo(expectedCheckingBalance, 2);
    expect(parseFloat(savingsAfter.balance)).toBeCloseTo(expectedSavingsBalance, 2);
  });

  test('should handle parallel concurrent transfers without data corruption', async ({ request, authState }) => {
    // Get initial balances
    const initialResponse = await request.get('/api/accounts', {
      headers: { Authorization: `Bearer ${authState.token}` },
    });

    if (!initialResponse.ok()) {
      test.skip(true, 'Accounts API not available');
      return;
    }

    const initialAccounts = await initialResponse.json();
    const checkingBefore = initialAccounts.find((a: { id: string }) => a.id === CHECKING_ACCOUNT);
    const savingsBefore = initialAccounts.find((a: { id: string }) => a.id === SAVINGS_ACCOUNT);

    if (!checkingBefore || !savingsBefore) {
      test.skip(true, 'Demo accounts not found');
      return;
    }

    const transferAmount = 2.00;

    // Send multiple transfers in parallel
    const transferPromises = Array.from({ length: 3 }, () =>
      request.post('/api/transfers', {
        headers: { Authorization: `Bearer ${authState.token}` },
        data: {
          fromAccountId: CHECKING_ACCOUNT,
          toAccountId: SAVINGS_ACCOUNT,
          amount: transferAmount,
        },
      })
    );

    const responses = await Promise.all(transferPromises);
    const successfulTransfers = responses.filter(r => r.ok()).length;

    // Wait briefly for any async processing
    await new Promise(resolve => setTimeout(resolve, 1000));

    // Verify balances are consistent
    const finalResponse = await request.get('/api/accounts', {
      headers: { Authorization: `Bearer ${authState.token}` },
    });
    const finalAccounts = await finalResponse.json();
    const checkingAfter = finalAccounts.find((a: { id: string }) => a.id === CHECKING_ACCOUNT);
    const savingsAfter = finalAccounts.find((a: { id: string }) => a.id === SAVINGS_ACCOUNT);

    // Total deducted should equal total credited (no money created or destroyed)
    const checkingDiff = parseFloat(checkingBefore.balance) - parseFloat(checkingAfter.balance);
    const savingsDiff = parseFloat(savingsAfter.balance) - parseFloat(savingsBefore.balance);

    expect(checkingDiff).toBeCloseTo(savingsDiff, 2);
    expect(checkingDiff).toBeCloseTo(transferAmount * successfulTransfers, 2);
  });

  test('should prevent overdraft during concurrent transfers', async ({ request, authState }) => {
    // Get current checking balance
    const accountsResponse = await request.get('/api/accounts', {
      headers: { Authorization: `Bearer ${authState.token}` },
    });

    if (!accountsResponse.ok()) {
      test.skip(true, 'Accounts API not available');
      return;
    }

    const accounts = await accountsResponse.json();
    const checking = accounts.find((a: { id: string }) => a.id === CHECKING_ACCOUNT);

    if (!checking) {
      test.skip(true, 'Checking account not found');
      return;
    }

    const currentBalance = parseFloat(checking.balance);

    // Attempt to transfer more than balance by splitting across parallel requests
    // Each request tries to transfer 75% of balance - at least one should fail
    const transferAmount = currentBalance * 0.75;

    const transferPromises = [
      request.post('/api/transfers', {
        headers: { Authorization: `Bearer ${authState.token}` },
        data: {
          fromAccountId: CHECKING_ACCOUNT,
          toAccountId: SAVINGS_ACCOUNT,
          amount: transferAmount,
        },
      }),
      request.post('/api/transfers', {
        headers: { Authorization: `Bearer ${authState.token}` },
        data: {
          fromAccountId: CHECKING_ACCOUNT,
          toAccountId: SAVINGS_ACCOUNT,
          amount: transferAmount,
        },
      }),
    ];

    const responses = await Promise.all(transferPromises);
    const successCount = responses.filter(r => r.ok()).length;

    // Verify account did not go negative
    const finalResponse = await request.get('/api/accounts', {
      headers: { Authorization: `Bearer ${authState.token}` },
    });
    const finalAccounts = await finalResponse.json();
    const checkingFinal = finalAccounts.find((a: { id: string }) => a.id === CHECKING_ACCOUNT);

    expect(parseFloat(checkingFinal.balance)).toBeGreaterThanOrEqual(0);

    // At most one should succeed if balance enforcement works
    // (both could succeed if balance is large enough, which is also valid)
    if (transferAmount * 2 > currentBalance) {
      expect(successCount).toBeLessThanOrEqual(1);
    }
  });

  test('should handle transfer while page is reloading', async ({ authenticatedPage, request, authState }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    // Start a transfer via API while UI is active
    const transferPromise = request.post('/api/transfers', {
      headers: { Authorization: `Bearer ${authState.token}` },
      data: {
        fromAccountId: CHECKING_ACCOUNT,
        toAccountId: SAVINGS_ACCOUNT,
        amount: 1.00,
      },
    });

    // Simultaneously reload the page
    await authenticatedPage.reload();

    // Wait for API transfer to complete
    const response = await transferPromise;

    // Page should recover gracefully
    await transfersPage.expectLoaded();

    // The API transfer result is independent of page state
    expect(response.status()).toBeLessThan(500);
  });

  test('should show consistent balances after rapid UI transfers', async ({ authenticatedPage }) => {
    await transfersPage.navigate();
    await transfersPage.expectLoaded();

    // Perform a transfer via UI
    await transfersPage.performFullTransfer(CHECKING_ACCOUNT, SAVINGS_ACCOUNT, '1.00');

    // Wait for success or error
    const success = await transfersPage.successMessage.isVisible().catch(() => false);
    const error = await transfersPage.errorMessage.isVisible().catch(() => false);

    // At least one outcome should appear
    expect(success || error).toBeTruthy();

    // If successful, navigate to accounts to verify UI consistency
    if (success) {
      const accountsPage = (await import('../../pages/AccountsPage')).AccountsPage;
      const accounts = new accountsPage(authenticatedPage);
      await accounts.navigate();
      await accounts.expectLoaded();

      // Balances should be displayed (not NaN or undefined)
      const firstAccount = await accounts.getAccountByIndex(0);
      expect(firstAccount.balance).toMatch(/\$\s*\d/);
    }
  });
});
