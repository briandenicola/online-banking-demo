import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class BudgetPage extends BasePage {
  readonly path = '/budget';

  readonly pageTitle: Locator;
  readonly categoriesList: Locator;
  readonly categoryItems: Locator;
  readonly spendingSummary: Locator;
  readonly addBudgetButton: Locator;
  readonly editBudgetButton: Locator;
  readonly deleteBudgetButton: Locator;
  readonly budgetForm: Locator;
  readonly categoryNameInput: Locator;
  readonly budgetLimitInput: Locator;
  readonly saveButton: Locator;
  readonly cancelButton: Locator;
  readonly dateRangeFilter: Locator;
  readonly startDateInput: Locator;
  readonly endDateInput: Locator;
  readonly applyFilterButton: Locator;
  readonly emptyState: Locator;
  readonly warningAlert: Locator;
  readonly loadingIndicator: Locator;
  readonly successMessage: Locator;
  readonly errorMessage: Locator;
  readonly confirmDeleteButton: Locator;
  readonly totalSpending: Locator;

  constructor(page: Page) {
    super(page);
    this.pageTitle = page.locator('h1, h2, h4').filter({ hasText: /budget|spending/i });
    this.categoriesList = page.locator(
      '[data-testid="categories-list"], [data-testid="budget-list"], .budget-categories, .MuiList-root'
    ).first();
    this.categoryItems = page.locator(
      '[data-testid*="category-item"], [data-testid*="budget-item"], .budget-category-item'
    );
    this.spendingSummary = page.locator(
      '[data-testid="spending-summary"], .spending-summary, .budget-summary'
    ).first();
    this.addBudgetButton = page.getByRole('button', { name: /add budget|create budget|new budget/i });
    this.editBudgetButton = page.getByRole('button', { name: /edit/i });
    this.deleteBudgetButton = page.getByRole('button', { name: /delete|remove/i });
    this.budgetForm = page.locator(
      '[data-testid="budget-form"], form, [role="dialog"] form, .MuiDialog-root'
    ).first();
    this.categoryNameInput = page.locator(
      'input[name="categoryName"], input[name="name"], input[name="category"], #categoryName'
    ).first();
    this.budgetLimitInput = page.locator(
      'input[name="limit"], input[name="budgetLimit"], input[name="amount"], #budgetLimit'
    ).first();
    this.saveButton = page.getByRole('button', { name: /save|create|add/i });
    this.cancelButton = page.getByRole('button', { name: /cancel/i });
    this.dateRangeFilter = page.locator(
      '[data-testid="date-range-filter"], .date-range-filter, .MuiDateRangePicker-root'
    ).first();
    this.startDateInput = page.locator(
      'input[name="startDate"], input[type="date"]'
    ).first();
    this.endDateInput = page.locator(
      'input[name="endDate"], input[type="date"]'
    ).last();
    this.applyFilterButton = page.getByRole('button', { name: /apply|filter/i });
    this.emptyState = page.locator(
      '[data-testid="empty-state"], .empty-state, .no-data'
    ).first();
    this.warningAlert = page.locator('[role="alert"]').filter({ hasText: /warning|limit|exceed/i });
    this.loadingIndicator = page.locator('[role="progressbar"], .MuiCircularProgress-root');
    this.successMessage = page.locator('[role="alert"]').filter({ hasText: /success|saved|created|deleted/i });
    this.errorMessage = page.locator('[role="alert"]').filter({ hasText: /error|fail/i });
    this.confirmDeleteButton = page.getByRole('button', { name: /confirm|yes|delete/i }).last();
    this.totalSpending = page.locator(
      '[data-testid="total-spending"], .total-spending, .spending-total'
    ).first();
  }

  async expectLoaded(): Promise<void> {
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  async getCategoryCount(): Promise<number> {
    return this.categoryItems.count();
  }

  async getCategoryByIndex(index: number): Promise<{ name: string; limit: string; spent: string }> {
    const item = this.categoryItems.nth(index);
    const name = (await item.locator('.category-name, [data-testid*="name"], td:first-child').textContent()) || '';
    const limit = (await item.locator('.category-limit, [data-testid*="limit"], td:nth-child(2)').textContent()) || '';
    const spent = (await item.locator('.category-spent, [data-testid*="spent"], td:nth-child(3)').textContent()) || '';
    return { name: name.trim(), limit: limit.trim(), spent: spent.trim() };
  }

  async clickAddBudget(): Promise<void> {
    await this.addBudgetButton.click();
  }

  async fillBudgetForm(categoryName: string, limit: string): Promise<void> {
    await this.categoryNameInput.clear();
    await this.categoryNameInput.fill(categoryName);
    await this.budgetLimitInput.clear();
    await this.budgetLimitInput.fill(limit);
  }

  async saveBudget(): Promise<void> {
    await this.saveButton.click();
  }

  async createBudget(categoryName: string, limit: string): Promise<void> {
    await this.clickAddBudget();
    await this.fillBudgetForm(categoryName, limit);
    await this.saveBudget();
  }

  async editBudgetByIndex(index: number): Promise<void> {
    const item = this.categoryItems.nth(index);
    await item.locator('button').filter({ hasText: /edit/i }).click();
  }

  async deleteBudgetByIndex(index: number): Promise<void> {
    const item = this.categoryItems.nth(index);
    await item.locator('button').filter({ hasText: /delete|remove/i }).click();
  }

  async confirmDelete(): Promise<void> {
    await this.confirmDeleteButton.click();
  }

  async setDateRange(startDate: string, endDate: string): Promise<void> {
    await this.startDateInput.fill(startDate);
    await this.endDateInput.fill(endDate);
    const applyVisible = await this.applyFilterButton.isVisible().catch(() => false);
    if (applyVisible) {
      await this.applyFilterButton.click();
    }
  }

  async expectSuccess(): Promise<void> {
    await expect(this.successMessage).toBeVisible({ timeout: 10_000 });
  }

  async expectEmptyState(): Promise<void> {
    await expect(this.emptyState).toBeVisible({ timeout: 5_000 });
  }

  async expectWarning(): Promise<void> {
    await expect(this.warningAlert).toBeVisible({ timeout: 5_000 });
  }

  async waitForDataLoad(): Promise<void> {
    await expect(this.loadingIndicator).toBeHidden({ timeout: 10_000 });
  }
}
