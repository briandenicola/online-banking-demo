import { defineConfig } from '@playwright/test';

/**
 * No `webServer`: the stack must be started by hand with the STREAM_MODE that
 * selects the outcome under test, because one server process serves one mode.
 *
 *   STREAM_MODE=refused-run|answer-run python3 tests/e2e/support/fake_copilot_stack.py \
 *     src/ui-app/build 8097 src/ui-app/src/api/__tests__/bankerApprovalsWire.fixture.json
 */
export default defineConfig({
  testDir: './specs',
  testMatch: 'run-outcomes.spec.ts',
  timeout: 40000,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8097', headless: true },
});
