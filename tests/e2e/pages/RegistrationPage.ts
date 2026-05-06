import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class RegistrationPage extends BasePage {
  readonly path = '/register';

  readonly firstNameInput: Locator;
  readonly lastNameInput: Locator;
  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly confirmPasswordInput: Locator;
  readonly submitButton: Locator;
  readonly errorMessage: Locator;
  readonly loginLink: Locator;

  constructor(page: Page) {
    super(page);
    this.firstNameInput = page.getByRole('textbox', { name: /first name/i });
    this.lastNameInput = page.getByRole('textbox', { name: /last name/i });
    this.emailInput = page.getByRole('textbox', { name: /email/i });
    this.passwordInput = page.getByLabel(/^password$/i);
    this.confirmPasswordInput = page.getByLabel(/confirm password/i);
    this.submitButton = page.getByRole('button', { name: /register|sign up|create account/i });
    this.errorMessage = page.locator('[role="alert"], .error-message, .MuiAlert-message');
    this.loginLink = page.getByRole('link', { name: /login|sign in/i });
  }

  async register(
    firstName: string,
    lastName: string,
    email: string,
    password: string,
    confirmPassword: string
  ): Promise<void> {
    await this.firstNameInput.fill(firstName);
    await this.lastNameInput.fill(lastName);
    await this.emailInput.fill(email);
    await this.passwordInput.fill(password);
    await this.confirmPasswordInput.fill(confirmPassword);
    await this.submitButton.click();
  }

  async expectError(message?: string): Promise<void> {
    await expect(this.errorMessage).toBeVisible();
    if (message) {
      await expect(this.errorMessage).toContainText(message);
    }
  }

  async expectNavigatedToLogin(): Promise<void> {
    await this.page.waitForURL('**/login', { timeout: 10_000 });
  }

  async getValidationError(fieldName: string): Promise<string | null> {
    const field = this.page.locator(`[aria-label*="${fieldName}"] ~ .MuiFormHelperText-root, [name="${fieldName}"] ~ .MuiFormHelperText-root`);
    const isVisible = await field.isVisible();
    return isVisible ? await field.textContent() : null;
  }
}
