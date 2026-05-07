import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class LoginPage extends BasePage {
  readonly path = '/login';

  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly submitButton: Locator;
  readonly errorMessage: Locator;

  constructor(page: Page) {
    super(page);
    this.emailInput = page.getByRole('textbox', { name: /email/i });
    this.passwordInput = page.getByLabel(/password/i);
    this.submitButton = page.getByRole('button', { name: /login|sign in/i });
    this.errorMessage = page.locator('[role="alert"]');
  }

  async login(email: string, password: string): Promise<void> {
    await this.emailInput.fill(email);
    await this.passwordInput.fill(password);
    await this.submitButton.click();
  }

  async expectError(message?: string): Promise<void> {
    await expect(this.errorMessage).toBeVisible();
    if (message) {
      await expect(this.errorMessage).toContainText(message);
    }
  }

  async expectNavigatedToDashboard(): Promise<void> {
    // Dashboard is at root '/' — there is no '/dashboard' route
    await this.page.waitForURL(/\/(?:\?.*)?$/, { timeout: 10_000 });
    await expect(this.page.getByRole('heading', { level: 4 }).first()).toBeVisible({ timeout: 10_000 });
  }
}
