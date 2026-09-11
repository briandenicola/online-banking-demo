import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './specs', testMatch: 'terminal-state.spec.ts',
  timeout: 40000, reporter: [['list']], use: { baseURL: 'http://127.0.0.1:8099', headless: true } });
