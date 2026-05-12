import { expect, Page, APIRequestContext } from '@playwright/test';

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
      // Accept expectedStatus or 401 (service is alive but requires auth)
      if (response.status === expectedStatus || response.status === 401) {
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
  const requiredServices = [
    { name: 'gateway', path: '/api/users/health' },
    { name: 'accounts', path: '/api/accounts/health' },
    { name: 'transactions', path: '/api/transactions/health' },
  ];

  const optionalServices = [
    { name: 'account-opening', path: '/api/account-opening/applications' },
  ];

  // Required services must be healthy
  await Promise.all(
    requiredServices.map((svc) =>
      waitForService({
        url: `${baseURL}${svc.path}`,
        timeout: 60_000,
      })
    )
  );

  // Optional services — log but don't block
  await Promise.allSettled(
    optionalServices.map(async (svc) => {
      try {
        await waitForService({
          url: `${baseURL}${svc.path}`,
          timeout: 15_000,
        });
      } catch {
        console.log(`[waitForAllServices] Optional service "${svc.name}" not available — tests will degrade gracefully`);
      }
    })
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

/**
 * Ensures the demo user exists by registering via the API.
 * Ignores 409 (already exists). Call in test.beforeAll for UI-based login tests.
 */
export async function ensureDefaultUser(
  request: APIRequestContext,
  email = 'e2e-default@banking-demo.com',
  password = 'password123'
): Promise<void> {
  await request.post('/api/users/register', {
    data: {
      username: email,
      email,
      firstName: 'Demo',
      lastName: 'User',
      password,
    },
  });
  // Ignore response — 201 (created) or 409 (already exists) are both fine
}
