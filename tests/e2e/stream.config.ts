import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './specs',
  testMatch: 'stream-lifecycle.spec.ts',
  timeout: 60000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8098', headless: true },
});
