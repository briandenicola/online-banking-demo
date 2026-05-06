import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class DashboardPage extends BasePage {
  readonly path = '/dashboard';

  readonly welcomeMessage: Locator;
  readonly accountsList: Locator;
  readonly navLinks: Locator;
  readonly logoutButton: Locator;

  constructor(page: Page) {
    super(page);
    this.welcomeMessage = page.locator('h1, h2, [data-testid="welcome"]');
    this.accountsList = page.locator('[data-testid="accounts-list"], .accounts-list, .MuiList-root');
    this.navLinks = page.locator('nav a, [role="navigation"] a');
    this.logoutButton = page.getByRole('button', { name: /logout|sign out/i });
  }

  async expectLoaded(): Promise<void> {
    await expect(this.welcomeMessage.first()).toBeVisible({ timeout: 10_000 });
  }

  async getAccountCount(): Promise<number> {
    const items = this.accountsList.locator('li, [data-testid*="account"]');
    return items.count();
  }

  async navigateTo(route: string): Promise<void> {
    await this.navLinks.filter({ hasText: new RegExp(route, 'i') }).first().click();
  }

  async logout(): Promise<void> {
    await this.logoutButton.click();
  }
}
