import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class AccountsPage extends BasePage {
  readonly path = '/accounts';

  readonly pageTitle: Locator;
  readonly accountsTable: Locator;
  readonly accountRows: Locator;
  readonly addAccountButton: Locator;
  readonly loadingIndicator: Locator;
  readonly successAlert: Locator;

  constructor(page: Page) {
    super(page);
    this.pageTitle = page.locator('h1, h2, h4').filter({ hasText: /accounts/i });
    this.accountsTable = page.locator('table, [data-testid="accounts-table"]');
    this.accountRows = page.locator('tbody tr, [data-testid*="account-row"]');
    this.addAccountButton = page.getByRole('button', { name: /add account/i });
    this.loadingIndicator = page.locator('[role="progressbar"], .MuiCircularProgress-root');
    this.successAlert = page.locator('[role="alert"]').filter({ hasText: /success/i });
  }

  async expectLoaded(): Promise<void> {
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
    await expect(this.accountsTable).toBeVisible();
  }

  async getAccountCount(): Promise<number> {
    return this.accountRows.count();
  }

  async getAccountByIndex(index: number): Promise<{
    name: string;
    number: string;
    type: string;
    balance: string;
  }> {
    const row = this.accountRows.nth(index);
    const cells = row.locator('td');
    
    return {
      name: await cells.nth(0).textContent() || '',
      number: await cells.nth(1).textContent() || '',
      type: await cells.nth(2).textContent() || '',
      balance: await cells.nth(3).textContent() || '',
    };
  }

  async clickAccountByName(accountName: string): Promise<void> {
    await this.accountRows.filter({ hasText: accountName }).first().click();
  }

  async waitForAccountsToLoad(): Promise<void> {
    await expect(this.accountRows.first()).toBeVisible({ timeout: 10_000 });
  }
}
