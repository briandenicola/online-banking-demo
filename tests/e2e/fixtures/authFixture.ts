import { test as base, expect, APIRequestContext, Page } from '@playwright/test';

export interface AuthCredentials {
  email: string;
  password: string;
}

export interface AuthState {
  token: string;
  email: string;
}

export const DEFAULT_USER: AuthCredentials = {
  email: 'demo@banking-demo.com',
  password: 'password123',
};

/**
 * Authenticates via the API and returns a JWT token.
 */
export async function apiLogin(
  request: APIRequestContext,
  credentials: AuthCredentials = DEFAULT_USER
): Promise<AuthState> {
  const response = await request.post('/api/users/login', {
    data: {
      email: credentials.email,
      password: credentials.password,
    },
  });

  expect(response.ok(), `Login failed: ${response.status()}`).toBeTruthy();

  const body = await response.json();
  const token = body.token ?? body.accessToken ?? body.jwt;

  if (!token) {
    throw new Error(`No token in login response: ${JSON.stringify(body)}`);
  }

  return { token, email: credentials.email };
}

/**
 * Extended test fixture that provides authenticated state.
 */
export const test = base.extend<{
  authState: AuthState;
  authenticatedPage: Page;
}>({
  authState: async ({ request }, use) => {
    const state = await apiLogin(request);
    await use(state);
  },

  authenticatedPage: async ({ page, authState }, use) => {
    // Inject token into localStorage before navigating
    await page.addInitScript((token: string) => {
      window.localStorage.setItem('token', token);
    }, authState.token);
    await use(page);
  },
});

export { expect } from '@playwright/test';
