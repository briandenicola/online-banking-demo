import { expect, Page } from '@playwright/test';

export interface HealthCheckOptions {
  url: string;
  timeout?: number;
  interval?: number;
  expectedStatus?: number;
}

/**
 * Polls a URL until it returns the expected status code.
 * Use before test suites to ensure services are healthy.
 */
export async function waitForService(options: HealthCheckOptions): Promise<void> {
  const { url, timeout = 30_000, interval = 1_000, expectedStatus = 200 } = options;
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.status === expectedStatus) {
        return;
      }
    } catch {
      // Service not ready yet
    }
    await new Promise((resolve) => setTimeout(resolve, interval));
  }

  throw new Error(`Service at ${url} did not become healthy within ${timeout}ms`);
}

/**
 * Waits for all core banking services to be healthy.
 */
export async function waitForAllServices(baseURL: string): Promise<void> {
  const services = [
    { name: 'gateway', path: '/api/users/health' },
    { name: 'accounts', path: '/api/accounts/health' },
    { name: 'transactions', path: '/api/transactions/health' },
  ];

  await Promise.all(
    services.map((svc) =>
      waitForService({
        url: `${baseURL}${svc.path}`,
        timeout: 60_000,
      })
    )
  );
}

/**
 * Waits for a page to reach a stable state (network idle + DOM loaded).
 */
export async function waitForPageReady(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForLoadState('networkidle');
}

/**
 * Retries an async action until it succeeds or timeout is reached.
 */
export async function retry<T>(
  fn: () => Promise<T>,
  options: { timeout?: number; interval?: number } = {}
): Promise<T> {
  const { timeout = 10_000, interval = 500 } = options;
  const deadline = Date.now() + timeout;

  let lastError: Error | undefined;
  while (Date.now() < deadline) {
    try {
      return await fn();
    } catch (e) {
      lastError = e as Error;
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
  }

  throw lastError ?? new Error(`Retry timed out after ${timeout}ms`);
}
