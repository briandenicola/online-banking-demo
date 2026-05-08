import { Page, Locator } from '@playwright/test';

export abstract class BasePage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  abstract readonly path: string;

  async navigate(): Promise<void> {
    // SPA auth race condition: on every full page load, React's useState
    // initializes user as null. The useEffect that restores user from
    // localStorage runs AFTER the first render, by which time the
    // unauthenticated router has already caught the path and redirected
    // to /login → /. This affects ALL paths except / (which ends up in
    // the right place after the redirect cycle).
    //
    // Fix: for non-root paths, load / first to establish auth state,
    // then use pushState + popstate to trigger React Router's
    // client-side navigation without a full page reload.
    if (this.path !== '/') {
      await this.page.goto('/');
      await this.page.waitForLoadState('networkidle');
      // Client-side navigate via React Router (avoids full page reload)
      await this.page.evaluate((path) => {
        window.history.pushState({}, '', path);
        window.dispatchEvent(new PopStateEvent('popstate'));
      }, this.path);
      await this.page.waitForLoadState('networkidle');
    } else {
      await this.page.goto(this.path);
    }
  }

  async waitForReady(): Promise<void> {
    await this.page.waitForLoadState('domcontentloaded');
  }

  async getTitle(): Promise<string> {
    return this.page.title();
  }

  async isVisible(locator: Locator): Promise<boolean> {
    return locator.isVisible();
  }

  async getCurrentURL(): Promise<string> {
    return this.page.url();
  }
}
