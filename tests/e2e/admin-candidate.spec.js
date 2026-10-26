const { test, expect } = require('playwright/test');
const path = require('node:path');

test('列表提交后返回，忙碌按钮恢复图标和再次提交能力', async ({ page }, testInfo) => {
  await page.setViewportSize({
    width: testInfo.project.name === 'mobile' ? 360 : 1280,
    height: testInfo.project.name === 'mobile' ? 780 : 900,
  });
  await page.addInitScript(() => {
    window.localStorage.setItem('siteLang', 'zh');
    window.__busyPageShows = [];
    window.addEventListener('pageshow', event => {
      window.__busyPageShows.push({ persisted: event.persisted });
    });
  });

  await page.request.get('/__e2e__/admin-session');
  await page.goto('/admin/players');
  await expect(page.getByRole('heading', { name: '选手管理' })).toBeVisible();

  const form = page.locator('form[action="/admin/players/refresh-playtime"]');
  const button = form.getByRole('button', { name: '更新选手时长' });
  await button.click();
  await expect(page.locator('.site-modal-ok')).toBeVisible();

  const firstPost = page.waitForResponse(response =>
    response.url().endsWith('/admin/players/refresh-playtime') && response.request().method() === 'POST'
  );
  await page.locator('.site-modal-ok').click();
  await firstPost;
  await expect(page).toHaveURL(/\/admin\/players$/);

  await page.goBack();
  await expect(page.locator('form[action="/admin/players/refresh-playtime"]')).toBeVisible();
  const returnedButton = page.locator('form[action="/admin/players/refresh-playtime"] button[type="submit"]');
  await expect(returnedButton).toBeEnabled();
  await expect(returnedButton).toContainText('更新选手时长');
  await expect(returnedButton.locator('svg')).toHaveCount(1);

  const returnPageShow = await page.evaluate(() => window.__busyPageShows.at(-1));
  expect(returnPageShow).not.toBeNull();

  await page.evaluate(() => {
    const form = document.querySelector('form[action="/admin/players/refresh-playtime"]');
    const intercept = event => {
      if (event.target !== form) return;
      event.preventDefault();
      document.removeEventListener('submit', intercept);
    };
    document.addEventListener('submit', intercept);
  });
  await returnedButton.click();
  await page.locator('.site-modal-ok').click();
  await expect(returnedButton).toBeDisabled();
  await expect(returnedButton).toHaveText('更新中……');

  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
  const simulatedBfcachePageShow = await page.evaluate(() => window.__busyPageShows.at(-1));
  expect(simulatedBfcachePageShow).toEqual({ persisted: true });
  await expect(returnedButton).toBeEnabled();
  await expect(returnedButton).toContainText('更新选手时长');
  await expect(returnedButton.locator('svg')).toHaveCount(1);

  await page.screenshot({
    path: path.resolve('output/ui-audit/codex-admin-pages', `busy-return-${testInfo.project.name}.png`),
  });

  await returnedButton.click();
  await expect(page.locator('.site-modal-ok')).toBeVisible();
  const secondPost = page.waitForResponse(response =>
    response.url().endsWith('/admin/players/refresh-playtime') && response.request().method() === 'POST'
  );
  await page.locator('.site-modal-ok').click();
  await secondPost;
  await expect(page).toHaveURL(/\/admin\/players$/);
});
