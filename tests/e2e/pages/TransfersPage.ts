import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class TransfersPage extends BasePage {
  readonly path = '/transfers';

  readonly pageTitle: Locator;
  readonly fromAccountSelect: Locator;
  readonly toAccountSelect: Locator;
  readonly amountInput: Locator;
  readonly submitButton: Locator;
  readonly confirmButton: Locator;
  readonly cancelButton: Locator;
  readonly successMessage: Locator;
  readonly errorMessage: Locator;
  readonly loadingIndicator: Locator;
  readonly confirmationDialog: Locator;
  readonly balanceDisplay: Locator;

  constructor(page: Page) {
    super(page);
    this.pageTitle = page.locator('h1, h2, h4').filter({ hasText: /transfer/i });
    // MUI TextField with select prop renders as a div with role="combobox", not a native <select>
    this.fromAccountSelect = page.getByLabel(/from account/i);
    this.toAccountSelect = page.getByLabel(/to account/i);
    this.amountInput = page.getByLabel(/amount/i);
    this.submitButton = page.getByRole('button', { name: /transfer|submit|send/i });
    this.confirmButton = page.getByRole('button', { name: /confirm|yes/i });
    this.cancelButton = page.getByRole('button', { name: /cancel|no/i });
    this.successMessage = page.locator('[role="alert"]').filter({ hasText: /success|completed/i });
    this.errorMessage = page.locator('[role="alert"]').filter({ hasText: /error|fail|insufficient|invalid/i });
    this.loadingIndicator = page.locator('[role="progressbar"], .MuiCircularProgress-root');
    this.confirmationDialog = page.locator('[role="dialog"], .MuiDialog-root');
    this.balanceDisplay = page.locator('[data-testid*="balance"], .balance');
  }

  async expectLoaded(): Promise<void> {
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  async selectFromAccount(accountId: string): Promise<void> {
    await this.fromAccountSelect.selectOption({ value: accountId }).catch(async () => {
      // Fallback for MUI Select components
      await this.fromAccountSelect.click();
      await this.page.locator(`[data-value="${accountId}"], li`).filter({ hasText: new RegExp(accountId, 'i') }).first().click();
    });
  }

  async selectToAccount(accountId: string): Promise<void> {
    await this.toAccountSelect.selectOption({ value: accountId }).catch(async () => {
      await this.toAccountSelect.click();
      await this.page.locator(`[data-value="${accountId}"], li`).filter({ hasText: new RegExp(accountId, 'i') }).first().click();
    });
  }

  async enterAmount(amount: string): Promise<void> {
    await this.amountInput.clear();
    await this.amountInput.fill(amount);
  }

  async submitTransfer(): Promise<void> {
    await this.submitButton.click();
  }

  async confirmTransfer(): Promise<void> {
    await this.confirmButton.click();
  }

  async cancelTransfer(): Promise<void> {
    await this.cancelButton.click();
  }

  async initiateTransfer(fromAccountId: string, toAccountId: string, amount: string): Promise<void> {
    await this.selectFromAccount(fromAccountId);
    await this.selectToAccount(toAccountId);
    await this.enterAmount(amount);
    await this.submitTransfer();
  }

  async expectSuccess(): Promise<void> {
    await expect(this.successMessage).toBeVisible({ timeout: 10_000 });
  }

  async expectError(errorText?: string): Promise<void> {
    if (errorText) {
      await expect(
        this.page.locator('[role="alert"], .MuiAlert-root, .error, [data-testid*="error"]')
          .filter({ hasText: new RegExp(errorText, 'i') })
      ).toBeVisible({ timeout: 10_000 });
    } else {
      await expect(this.errorMessage).toBeVisible({ timeout: 10_000 });
    }
  }

  async expectValidationError(): Promise<void> {
    await expect(
      this.page.locator('.MuiFormHelperText-root, [role="alert"], .error-message, .Mui-error')
        .first()
    ).toBeVisible({ timeout: 5_000 });
  }

  async getFieldValidationMessage(fieldName: string): Promise<string> {
    const field = this.page.locator(`[name="${fieldName}"], #${fieldName}`).first();
    const helperText = field.locator('~ .MuiFormHelperText-root, + .error-message');
    return (await helperText.textContent()) || '';
  }

  async waitForTransferComplete(): Promise<void> {
    await expect(this.loadingIndicator).toBeHidden({ timeout: 15_000 });
  }

  async performFullTransfer(fromAccountId: string, toAccountId: string, amount: string): Promise<void> {
    await this.initiateTransfer(fromAccountId, toAccountId, amount);
    // Handle confirmation dialog if present
    const dialogVisible = await this.confirmationDialog.isVisible().catch(() => false);
    if (dialogVisible) {
      await this.confirmTransfer();
    }
    await this.waitForTransferComplete();
  }
}
