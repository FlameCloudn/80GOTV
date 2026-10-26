const { test, expect } = require('playwright/test');
const fs = require('node:fs');
const path = require('node:path');

test('multiple long errors remain readable and closable within the viewport', async ({ page }, testInfo) => {
  const mobile = testInfo.project.name === 'mobile';
  await page.setViewportSize({ width: mobile ? 390 : 1280, height: 800 });
  await page.addInitScript(({ mobile }) => {
    localStorage.setItem('siteLang', mobile ? 'zh' : 'en');
    localStorage.setItem('theme', mobile ? 'light' : 'dark');
  }, { mobile });
  await page.goto('/login');
  await page.evaluate(() => {
    for (let index = 1; index <= 5; index += 1) {
      window.showToast(`Error ${index}: ` + 'The request failed. Please check your input and try again. '.repeat(25), 'error');
    }
  });
  const toasts = page.locator('.site-toast');
  await expect(toasts).toHaveCount(5);
  await expect(toasts.last()).toHaveCSS('opacity', '1');
  const folder = path.resolve('output/ui-audit/toast-overflow-20261026');
  fs.mkdirSync(folder, { recursive: true });
  await page.screenshot({ path: path.join(folder, `${testInfo.project.name}-long-errors.png`) });
  const container = page.locator('.site-toast-container');
  const bounds = await container.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(page.viewportSize().width);
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(page.viewportSize().height - 4);
  for (let remaining = 5; remaining > 0; remaining -= 1) {
    await toasts.last().locator('.site-toast-close').click();
    await expect(toasts).toHaveCount(remaining - 1);
  }
});
