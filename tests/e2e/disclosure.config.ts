import { defineConfig } from '@playwright/test';

/**
 * No `webServer`: one stack process serves one STREAM_MODE, and this suite needs
 * three. Start the mode under test by hand.
 *
 *   STREAM_MODE=leaky-refusal|suppressed-refusal|model-unavailable \
 *     python3 tests/e2e/support/fake_copilot_stack.py src/ui-app/build 8096 \
 *     src/ui-app/src/api/__tests__/bankerApprovalsWire.fixture.json
 */
export default defineConfig({
  testDir: './specs',
  testMatch: 'refusal-disclosure-assertion.spec.ts',
  timeout: 40000,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8096', headless: true },
});
