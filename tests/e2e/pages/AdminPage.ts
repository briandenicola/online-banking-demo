import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class AdminPage extends BasePage {
  readonly path = '/admin';

  readonly pageTitle: Locator;
  readonly statsCards: Locator;
  readonly userCountCard: Locator;
  readonly totalTransactionsCard: Locator;
  readonly userTable: Locator;
  readonly userTableRows: Locator;
  readonly searchInput: Locator;
  readonly statusFilter: Locator;
  readonly sortByDate: Locator;
  readonly paginationControls: Locator;
  readonly suspendButton: Locator;
  readonly unsuspendButton: Locator;
  readonly confirmationDialog: Locator;
  readonly confirmButton: Locator;
  readonly cancelButton: Locator;
  readonly forbiddenMessage: Locator;
  readonly loadingIndicator: Locator;
  readonly adminNavLink: Locator;

  constructor(page: Page) {
    super(page);
    this.pageTitle = page.locator('h1, h2, h4').filter({ hasText: /admin/i });
    this.statsCards = page.locator(
      '[data-testid*="stats"], .stats-card, .MuiCard-root, [data-testid*="metric"]'
    );
    this.userCountCard = page.locator(
      '[data-testid="user-count"], [data-testid*="users-card"]'
    ).first();
    this.totalTransactionsCard = page.locator(
      '[data-testid="total-transactions"], [data-testid*="transactions-card"]'
    ).first();
    this.userTable = page.locator(
      'table, [data-testid="user-table"], [role="grid"], .MuiTable-root, .MuiDataGrid-root'
    ).first();
    this.userTableRows = page.locator(
      'table tbody tr, [role="row"]:not([role="row"]:first-child), .MuiTableRow-root'
    );
    this.searchInput = page.locator(
      'input[placeholder*="search" i], input[name="search"], [data-testid="user-search"], input[type="search"]'
    ).first();
    this.statusFilter = page.locator(
      'select[name="status"], [data-testid="status-filter"], [aria-label*="status" i]'
    ).first();
    this.sortByDate = page.locator(
      'th:has-text("date"), th:has-text("registered"), button:has-text("date"), [data-testid*="sort-date"]'
    ).first();
    this.paginationControls = page.locator(
      '.MuiPagination-root, [data-testid="pagination"], nav[aria-label="pagination"], .MuiTablePagination-root'
    ).first();
    this.suspendButton = page.getByRole('button', { name: /suspend|disable|deactivate/i });
    this.unsuspendButton = page.getByRole('button', { name: /unsuspend|enable|activate|restore/i });
    this.confirmationDialog = page.locator('[role="dialog"], .MuiDialog-root');
    this.confirmButton = page.getByRole('button', { name: /confirm|yes|proceed/i });
    this.cancelButton = page.locator('[role="dialog"] button').filter({ hasText: /cancel|no/i });
    this.forbiddenMessage = page.locator(
      '[data-testid="forbidden"], [role="alert"]'
    ).filter({ hasText: /forbidden|unauthorized|access denied|not authorized/i });
    this.loadingIndicator = page.locator('[role="progressbar"], .MuiCircularProgress-root');
    this.adminNavLink = page.locator(
      'a[href*="admin"], [data-testid="admin-link"], nav a:has-text("Admin"), li:has-text("Admin")'
    ).first();
  }

  async expectLoaded(): Promise<void> {
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  async expectForbidden(): Promise<void> {
    const hasForbidden = await this.forbiddenMessage.isVisible().catch(() => false);
    const urlRedirected = !(await this.getCurrentURL()).includes('/admin');
    expect(hasForbidden || urlRedirected).toBeTruthy();
  }

  async expectStatsVisible(): Promise<void> {
    await expect(this.statsCards.first()).toBeVisible({ timeout: 10_000 });
  }

  async expectUserTableVisible(): Promise<void> {
    await expect(this.userTable).toBeVisible({ timeout: 10_000 });
  }

  async getUserRowCount(): Promise<number> {
    await this.userTable.waitFor({ state: 'visible', timeout: 10_000 });
    return this.userTableRows.count();
  }

  async searchUsers(query: string): Promise<void> {
    await this.searchInput.clear();
    await this.searchInput.fill(query);
    await this.page.waitForTimeout(500);
  }

  async filterByStatus(status: 'active' | 'suspended' | 'all'): Promise<void> {
    await this.statusFilter.selectOption({ value: status }).catch(async () => {
      await this.statusFilter.click();
      await this.page.locator(`[data-value="${status}"], li`).filter({ hasText: new RegExp(status, 'i') }).first().click();
    });
    await this.page.waitForTimeout(500);
  }

  async sortByRegistrationDate(): Promise<void> {
    await this.sortByDate.click();
    await this.page.waitForTimeout(500);
  }

  async suspendUser(rowIndex: number): Promise<void> {
    const row = this.userTableRows.nth(rowIndex);
    const suspendBtn = row.locator('button').filter({ hasText: /suspend|disable/i });
    await suspendBtn.click();
  }

  async unsuspendUser(rowIndex: number): Promise<void> {
    const row = this.userTableRows.nth(rowIndex);
    const unsuspendBtn = row.locator('button').filter({ hasText: /unsuspend|enable|activate/i });
    await unsuspendBtn.click();
  }

  async confirmAction(): Promise<void> {
    await expect(this.confirmationDialog).toBeVisible({ timeout: 5_000 });
    await this.confirmButton.click();
  }

  async cancelAction(): Promise<void> {
    await expect(this.confirmationDialog).toBeVisible({ timeout: 5_000 });
    await this.cancelButton.click();
  }

  async isAdminNavVisible(): Promise<boolean> {
    return this.adminNavLink.isVisible().catch(() => false);
  }

  async getUserStatusInRow(rowIndex: number): Promise<string> {
    const row = this.userTableRows.nth(rowIndex);
    const statusCell = row.locator('td, [role="cell"]').filter({ hasText: /active|suspended|disabled/i });
    return (await statusCell.textContent()) || '';
  }
}
