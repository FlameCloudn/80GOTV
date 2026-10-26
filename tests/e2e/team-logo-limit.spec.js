const { test, expect } = require('playwright/test');
const fs = require('node:fs');
const path = require('node:path');

test('team logos accept 10MB and rejected replacements preserve saved data', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile', '后台只检查电脑端');
  test.setTimeout(60000);
  const limit = 10 * 1024 * 1024;
  const source = fs.readFileSync(path.resolve('static/logos/80gotv-mark.png'));
  expect(source.length).toBeLessThan(limit);
  const image = Buffer.alloc(limit);
  source.copy(image);
  const screenshots = path.resolve('output/ui-audit/team-logo-10mb-20261026');
  fs.mkdirSync(screenshots, { recursive: true });
  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));
  await page.request.get('/__e2e__/admin-session');
  await page.goto('/admin/teams/add');
  await expect(page.locator('input[name="logo"]')).not.toHaveAttribute('accept', /webp/);
  await expect(page.locator('.field-hint').filter({ hasText: '10MB' })).toBeVisible();
  const name = `E2E Logo Limit ${Date.now()}`;
  await page.locator('input[name="name"]').fill(name);
  await page.locator('input[name="short_name"]').fill('TENMB');
  await page.locator('details summary').click();
  await page.locator('textarea[name="description"]').fill('Ten MB browser upload');

  let submitted = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/admin/teams/add') submitted += 1;
  });
  await page.locator('input[name="logo"]').setInputFiles({
    name: 'too-large.png', mimeType: 'image/png', buffer: Buffer.concat([image, Buffer.from([0])]),
  });
  if (await page.locator('input[name="logo"]').evaluate(input => input.files.length > 0)) {
    await page.locator('#teamForm button[type="submit"]').click();
  }
  const sizeToast = page.locator('.site-toast').filter({ hasText: '10MB' }).first();
  await expect(sizeToast).toBeVisible();
  await expect(sizeToast).toHaveCSS('opacity', '1');
  expect(submitted).toBe(0);
  await expect(page.locator('input[name="name"]')).toHaveValue(name);
  await page.screenshot({ path: path.join(screenshots, 'client-rejected-desktop.png'), fullPage: true });

  await page.locator('input[name="logo"]').setInputFiles({
    name: 'at-limit.png', mimeType: 'image/png', buffer: image,
  });
  const created = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/admin/teams/add');
  await page.locator('#teamForm button[type="submit"]').click();
  expect((await created).status()).toBe(302);
  await expect(page).toHaveURL(/\/admin\/teams$/);
  const editUrl = await page.locator('a.cell-title').filter({ hasText: name }).getAttribute('href');
  await page.goto(editUrl);
  const oldLogo = await page.locator('.file-preview img').getAttribute('src');
  await expect(page.locator('.file-preview img')).toBeVisible();
  await expect.poll(() => page.locator('.file-preview img').evaluate(img => img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('textarea[name="description"]')).toHaveValue('Ten MB browser upload');

  await page.locator('textarea[name="description"]').fill('Keep this after a rejected replacement');
  await page.locator('input[name="logo"]').setInputFiles({
    name: 'broken.png', mimeType: 'image/png', buffer: Buffer.from('not an image'),
  });
  const rejected = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname === editUrl);
  await page.locator('#teamForm button[type="submit"]').click();
  expect((await rejected).status()).toBe(400);
  const errorToast = page.locator('.site-toast').filter({ hasText: '队标无效' }).first();
  await expect(errorToast).toBeVisible();
  await expect(errorToast).toHaveCSS('opacity', '1');
  const errorBox = await errorToast.boundingBox();
  expect(errorBox.x).toBeGreaterThanOrEqual(page.viewportSize().width - 480);
  expect(errorBox.y).toBeLessThan(200);
  await expect(page.locator('textarea[name="description"]')).toHaveValue('Keep this after a rejected replacement');
  await expect(page.locator('.file-preview img')).toHaveAttribute('src', oldLogo);
  await page.screenshot({ path: path.join(screenshots, 'server-rejected-desktop.png'), fullPage: true });

  const saved = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname === editUrl);
  await page.locator('#teamForm button[type="submit"]').click();
  expect((await saved).status()).toBe(302);
  await expect(page).toHaveURL(/\/admin\/teams$/);
  await page.goto(editUrl);
  await expect(page.locator('textarea[name="description"]')).toHaveValue('Keep this after a rejected replacement');
  await expect(page.locator('.file-preview img')).toHaveAttribute('src', oldLogo);
  await page.screenshot({ path: path.join(screenshots, 'saved-reopened-desktop.png'), fullPage: true });
});
