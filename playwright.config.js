const { defineConfig } = require('playwright/test');

const python = process.env.E2E_PYTHON || 'python';
const browserChannel = process.env.PLAYWRIGHT_CHANNEL || undefined;

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:5010',
    channel: browserChannel,
    trace: 'retain-on-failure',
  },
  webServer: process.env.E2E_BASE_URL ? undefined : {
    command: `"${python}" scripts/run_e2e_server.py`,
    url: 'http://127.0.0.1:5010/healthz',
    reuseExistingServer: false,
    timeout: 120000,
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 800 } } },
    { name: 'mobile', use: { viewport: { width: 360, height: 780 }, isMobile: true } },
  ],
});
