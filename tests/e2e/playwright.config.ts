import { defineConfig, devices } from '@playwright/test';

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: './specs',
  // These run against a locally-served static build plus a hand-started fake
  // stack, each on its own port and its own config, not against the deployed
  // BASE_URL this config targets. Collecting them here fails the shared suite
  // with ECONNREFUSED.
  //   layout-copilot           -> layout.config.ts        (8099)
  //   stream-lifecycle         -> stream.config.ts        (8098)
  //   run-outcomes             -> outcomes.config.ts      (8097, STREAM_MODE)
  //   refusal-disclosure-*     -> disclosure.config.ts    (8096, STREAM_MODE)
  testIgnore: [
    '**/layout-copilot.spec.ts',
    '**/stream-lifecycle.spec.ts',
    '**/run-outcomes.spec.ts',
    '**/refusal-disclosure-assertion.spec.ts',
  ],
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: isCI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
    actionTimeout: 15_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: 'smoke',
      grep: /@smoke/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
  ],
  outputDir: './test-results',
});
