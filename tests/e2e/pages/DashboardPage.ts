import { Page, Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class DashboardPage extends BasePage {
  readonly path = '/';

  readonly welcomeMessage: Locator;
  readonly accountsList: Locator;
  readonly navLinks: Locator;
  readonly logoutButton: Locator;
  readonly userMenuButton: Locator;

  constructor(page: Page) {
    super(page);
    this.welcomeMessage = page.locator('h1, h2, h4, [data-testid="welcome"]');
    this.accountsList = page.locator('[data-testid="accounts-list"], .accounts-list, .MuiList-root');
    this.navLinks = page.locator('nav a, [role="navigation"] a');
    this.logoutButton = page.getByRole('menuitem', { name: /logout|sign out/i });
    // User avatar button (shows first letter of user's name)
    this.userMenuButton = page.locator('header button').last();
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
    await this.userMenuButton.click();
    await this.logoutButton.click();
  }
}
