import { test as base, expect, APIRequestContext, Page } from '@playwright/test';

export interface AuthCredentials {
  email: string;
  password: string;
}

export interface AuthState {
  token: string;
  email: string;
  role: string;
}

export const DEFAULT_USER: AuthCredentials = {
  email: 'e2e-default@banking-demo.com',
  password: 'password123',
};

/**
 * Ensures a test user exists by registering via the API.
 * Ignores 409 (already exists) since that means the user is already registered.
 */
export async function ensureTestUser(
  request: APIRequestContext,
  credentials: AuthCredentials = DEFAULT_USER
): Promise<void> {
  await request.post('/api/users/register', {
    data: {
      username: credentials.email,
      email: credentials.email,
      firstName: 'E2E',
      lastName: 'Test',
      password: credentials.password,
    },
  });
  // Ignore response — 201 (created) or 409 (already exists) are both fine
}

/**
 * Authenticates via the API and returns a JWT token.
 * Registers the user first if they don't exist.
 */
export async function apiLogin(
  request: APIRequestContext,
  credentials: AuthCredentials = DEFAULT_USER
): Promise<AuthState> {
  // Ensure the user is registered before attempting login
  await ensureTestUser(request, credentials);

  const response = await request.post('/api/users/login', {
    data: {
      username: credentials.email,
      password: credentials.password,
    },
  });

  expect(response.ok(), `Login failed: ${response.status()}`).toBeTruthy();

  const body = await response.json();
  const token = body.token ?? body.accessToken ?? body.jwt;

  if (!token) {
    throw new Error(`No token in login response: ${JSON.stringify(body)}`);
  }

  return { token, email: credentials.email, role: body.role ?? 'user' };
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
    // Inject auth state into localStorage before navigating.
    // The app reads 'auth_token', 'auth_email', and 'auth_role' from localStorage.
    await page.addInitScript(({ token, email, role }: { token: string; email: string; role: string }) => {
      window.localStorage.setItem('auth_token', token);
      window.localStorage.setItem('auth_email', email);
      window.localStorage.setItem('auth_role', role);
    }, { token: authState.token, email: authState.email, role: authState.role });
    await use(page);
  },
});

export { expect } from '@playwright/test';
