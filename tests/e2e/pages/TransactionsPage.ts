import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class TransactionsPage extends BasePage {
  readonly path = '/transactions';

  readonly pageTitle: Locator;
  readonly transactionsTable: Locator;
  readonly transactionRows: Locator;
  readonly addTransactionButton: Locator;
  readonly loadingIndicator: Locator;
  readonly errorAlert: Locator;
  readonly paginationControls: Locator;

  constructor(page: Page) {
    super(page);
    this.pageTitle = page.locator('h1, h2, h4').filter({ hasText: /transactions/i });
    this.transactionsTable = page.locator('table, [data-testid="transactions-table"]');
    this.transactionRows = page.locator('tbody tr, [data-testid*="transaction-row"]');
    this.addTransactionButton = page.getByRole('button', { name: /add transaction/i });
    this.loadingIndicator = page.locator('[role="progressbar"], .MuiCircularProgress-root');
    this.errorAlert = page.locator('[role="alert"]');
    this.paginationControls = page.locator('[role="navigation"], .MuiPagination-root');
  }

  async expectLoaded(): Promise<void> {
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
    await expect(this.transactionsTable).toBeVisible();
  }

  async getTransactionCount(): Promise<number> {
    return this.transactionRows.count();
  }

  async getTransactionByIndex(index: number): Promise<{
    date: string;
    description: string;
    amount: string;
  }> {
    const row = this.transactionRows.nth(index);
    const cells = row.locator('td');
    
    return {
      date: await cells.nth(0).textContent() || '',
      description: await cells.nth(1).textContent() || '',
      amount: await cells.nth(2).textContent() || '',
    };
  }

  async waitForTransactionsToLoad(): Promise<void> {
    await expect(this.loadingIndicator).toBeHidden({ timeout: 10_000 });
    // Wait for either transaction rows to appear or the table to be ready
    // (the user may have no transactions)
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  async clickPaginationNext(): Promise<void> {
    await this.page.getByRole('button', { name: /next/i }).click();
  }

  async clickPaginationPrevious(): Promise<void> {
    await this.page.getByRole('button', { name: /previous/i }).click();
  }
}
