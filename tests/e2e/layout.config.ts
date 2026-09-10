import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './specs',
  testMatch: 'layout-copilot.spec.ts',
  timeout: 30000,
  fullyParallel: true,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8099', headless: true },
});
