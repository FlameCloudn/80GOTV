const { test, expect } = require('playwright/test');
const fs = require('node:fs');
const path = require('node:path');

test('a player with no Steam ID can be renamed and saved', async ({ page }, testInfo) => {
  await page.setViewportSize({
    width: testInfo.project.name === 'mobile' ? 390 : 1280,
    height: 900,
  });
  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));
  await page.request.get('/__e2e__/admin-session');
  const fixture = await (await page.request.get('/__e2e__/refactor-fixture')).json();
  const editUrl = `/admin/players/edit/${fixture.player_id}`;
  const screenshots = path.resolve(
    'output/ui-audit/dot-player-null-steam-20261026',
  );
  fs.mkdirSync(screenshots, { recursive: true });

  await page.goto(editUrl);
  const steamInput = page.locator('input[name="steam_id"]');
  await expect(steamInput).toHaveValue('');
  await page.locator('input[name="is_bashizhong_student"][value="0"]').check();
  const nickname = page.locator('input[name="nickname"]');
  const renamed = `E2E Rename ${Date.now()}`;
  await nickname.fill(renamed);
  await page.screenshot({
    path: path.join(screenshots, `${testInfo.project.name}-null-steam-before-save.png`),
    fullPage: true,
  });

  await page.locator('#playerForm button[type="submit"]').click();
  await expect(page).toHaveURL(/\/admin\/players(?:\?.*)?$/);
  await expect(page.getByText('选手更新成功', { exact: true })).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, `${testInfo.project.name}-save-success.png`),
    fullPage: true,
  });

  await page.goto(editUrl);
  await expect(page.locator('input[name="nickname"]')).toHaveValue(renamed);
  await expect(page.locator('input[name="steam_id"]')).toHaveValue('');
  await page.screenshot({
    path: path.join(screenshots, `${testInfo.project.name}-saved-null-steam-readback.png`),
    fullPage: true,
  });
});
