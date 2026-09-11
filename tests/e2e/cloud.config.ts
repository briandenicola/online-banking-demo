import { defineConfig } from '@playwright/test';

/**
 * The ONLY Playwright config that talks to the deployed system.
 *
 * Everything else under tests/e2e drives `support/fake_copilot_stack.py` on
 * localhost. Those suites are fast, deterministic and safe to run in CI, and
 * this file must not change that: the cloud specs live in their own `cloud/`
 * directory because `playwright.config.ts` globs `./specs` and would otherwise
 * collect them, quietly making the offline suite depend on network access.
 *
 * THE GATE IS A THROW, NOT A SKIP.
 *
 * `run-outcomes.spec.ts` gates its modes with `test.skip(...)`, which is right
 * there — the other mode genuinely cannot run. It is wrong here. A skipped
 * collection reports "0 failed" and exits 0, which reads as a pass, and tonight
 * has repeatedly cost us hours precisely because a green run meant nothing had
 * been checked. An ungated invocation of this config therefore fails loudly
 * before a single browser starts.
 *
 * Run:
 *   BANKER_COPILOT_CLOUD_E2E=1 npx playwright test --config cloud.config.ts
 *
 * Optional:
 *   CLOUD_BASE_URL=https://...        override the target host
 *   DEMO_SEED_PASSWORD=...            override `credentials.passwordDefault`
 *                                     from config/demo-dataset.json
 */

const GATE = 'BANKER_COPILOT_CLOUD_E2E';

if (process.env[GATE] !== '1') {
  throw new Error(
    `\n${GATE} is not set to "1".\n\n` +
      'This config drives the DEPLOYED system: it signs in with real demo\n' +
      'credentials, runs real model-backed plans and creates real approval\n' +
      'records. It is deliberately impossible to run by accident, and it\n' +
      'deliberately does not degrade into an empty, green, meaningless run.\n\n' +
      `  ${GATE}=1 npx playwright test --config cloud.config.ts\n`
  );
}

const CLOUD_BASE_URL =
  process.env.CLOUD_BASE_URL || 'https://onlinebankingdemo.bjdazure.tech';

export default defineConfig({
  testDir: './cloud',
  // A live planner run against a real model took 2.5s (refusal) to ~70s (a full
  // propose path) when measured on 2026-09-10. The ceiling is generous because
  // the honest failure for a slow model is a slow pass, not a flake.
  timeout: 6 * 60 * 1000,
  expect: { timeout: 15000 },
  // One worker, no parallelism: these runs mutate a shared demo tenant's
  // approval queue, and two concurrent runs make the "what did MY run create"
  // delta ambiguous.
  workers: 1,
  fullyParallel: false,
  // No retries. A retry here would hide exactly the intermittent cloud faults
  // this suite exists to surface — `planner_model_unavailable` was observed on
  // one run of a prompt that succeeded on the next.
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: CLOUD_BASE_URL,
    headless: true,
    trace: 'retain-on-failure',
  },
});
