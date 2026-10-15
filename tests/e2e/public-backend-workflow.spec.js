const { test, expect } = require('playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem('siteLang')) localStorage.setItem('siteLang', 'zh');
  });
});

test('administrator signs in from the real form with the captcha empty', async ({ page }) => {
  const fixture = await (await page.request.get('/__e2e__/public-backend-fixture')).json();
  await page.goto('/login?next=/admin/');
  await expect(page.getByText('后台账号可不填验证码', { exact: true })).toBeVisible();
  await page.getByLabel('用户名', { exact: true }).fill('e2e-dot-admin');
  await page.getByLabel('密码', { exact: true }).fill('e2e-only-admin-password');
  await expect(page.locator('#loginCaptcha')).toHaveValue('');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/$/);
  await page.goto('/admin/teams');
  await expect(page.locator(`a[href="/admin/teams/edit/${fixture.team_id}"]`)).toBeVisible();
});

test('an admin username with the wrong password does not receive access', async ({ page }) => {
  await page.goto('/login?next=/admin/');
  await page.getByLabel('用户名', { exact: true }).fill('e2e-dot-admin');
  await page.getByLabel('密码', { exact: true }).fill('not-the-admin-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto('/admin/teams');
  await expect(page).toHaveURL(/\/admin\/login$/);
});

test('real search, team, player and match links preserve their identity and counts', async ({ page }, testInfo) => {
  const fixture = await (await page.request.get('/__e2e__/public-backend-fixture')).json();
  await page.goto('/');
  if (testInfo.project.name === 'desktop') {
    await page.locator(`.h-rank-row[href="/teams/${fixture.team_id}"]`).click();
    await expect(page.getByRole('heading', { name: 'E2E Dot Alpha', exact: true })).toBeVisible();
    await page.goto('/');
  }
  if (!await page.locator('#searchInput').isVisible()) {
    if (!await page.locator('#searchToggle').isVisible()) {
      await page.locator('#hamburger').click();
    }
    await page.locator('#searchToggle').click();
  }
  await page.locator('#searchInput').fill('E2E Dot Alpha');
  await page.locator(`#searchDropdown a[href="/teams/${fixture.team_id}"]`).click();
  await expect(page).toHaveURL(new RegExp(`/teams/${fixture.team_id}$`));
  await expect(page.getByRole('heading', { name: 'E2E Dot Alpha', exact: true })).toBeVisible();
  await expect(page.locator('.team-list-row').filter({ hasText: 'E2E Dot Player' })).toBeVisible();
  await expect(page.locator('a.match-card')).toHaveCount(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath('team-detail.png'), fullPage: true });

  await page.locator(`a[href="/players/${fixture.player_id}"]`).click();
  const facts = page.locator('.pp-facts');
  await expect(facts.locator('div').filter({ has: page.locator('dt', { hasText: /^比赛数$/ }) }).locator('dd')).toHaveText('3');
  await expect(facts.locator('div').filter({ has: page.locator('dt', { hasText: /^地图数$/ }) }).locator('dd')).toHaveText('4');
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath('player-counts.png'), fullPage: true });
  await page.locator('[data-tab-target="matches"]').click();
  await expect(page.locator('#matches tbody tr')).toHaveCount(3);
  await page.locator('#matches tbody tr a').first().click();
  await expect(page).toHaveURL(/\/matches\/e2e-dot-\d+$/);

  await page.goto('/teams');
  await page.locator(`a.team-list-row[href="/teams/${fixture.team_id}"]`).click();
  if (!await page.locator('#languageSelect').isVisible()) {
    await page.locator('#hamburger').click();
  }
  await page.locator('#languageSelect').selectOption('en');
  await expect(page.getByText('Current roster', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'E2E Dot Alpha', exact: true })).toBeVisible();
});
