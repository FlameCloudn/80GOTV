const { test, expect } = require('playwright/test');
const path = require('node:path');

test.beforeEach(async ({ page }, testInfo) => {
  await page.setViewportSize({
    width: testInfo.project.name === 'mobile' ? 390 : 1280,
    height: 900,
  });
  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));
});

async function screenshot(page, testInfo, name) {
  await page.screenshot({
    path: path.resolve('output/ui-audit', `${name}-${testInfo.project.name}.png`),
    fullPage: true,
  });
}

async function expectAdminFormFits(page) {
  const dimensions = await page.evaluate(() => {
    const form = document.querySelector('#matchForm');
    const bounds = form.getBoundingClientRect();
    const controls = form.querySelectorAll(
      'input:not([type="hidden"]), select, textarea, .tab-pane.active .btn, .status-pills, .sticky-form-actions, .field-section'
    );
    const outside = Array.from(controls).filter(control => {
      if (!control.getClientRects().length) return false;
      const rect = control.getBoundingClientRect();
      return rect.left < bounds.left - 1 || rect.right > bounds.right + 1;
    }).map(control => control.id || control.name || control.className);
    return {
      pageWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      formLeft: bounds.left,
      formRight: bounds.right,
      outside,
    };
  });
  expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  expect(dimensions.bodyWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  expect(dimensions.formLeft).toBeGreaterThanOrEqual(0);
  expect(dimensions.formRight).toBeLessThanOrEqual(dimensions.viewportWidth);
  expect(dimensions.outside).toEqual([]);
  if (dimensions.viewportWidth <= 768) {
    const pane = await page.locator('#matchForm .tab-pane.active').boundingBox();
    const actions = await page.locator('#matchForm .sticky-form-actions').boundingBox();
    expect(actions.y).toBeGreaterThanOrEqual(pane.y + pane.height);
  }
}

async function expectDarkMatchFormContrast(page) {
  const styles = await page.evaluate(() => {
    const probe = document.createElement('span');
    probe.style.backgroundColor = 'var(--surface-soft)';
    document.body.appendChild(probe);
    const themeSurface = getComputedStyle(probe).backgroundColor;
    probe.remove();
    const targets = [
      ['.match-status-bar h2', '.match-status-bar'],
      ['.vs-matchup-heading strong', '.vs-matchup-card'],
      ['.time-chip:not(.active)', null],
    ];
    const pairs = targets.flatMap(([selector, surface]) =>
      Array.from(document.querySelectorAll(selector), element => ({
        selector,
        color: getComputedStyle(element).color,
        background: getComputedStyle(surface ? element.closest(surface) : element).backgroundColor,
      }))
    );
    return { themeSurface, pairs };
  });
  const luminance = color => {
    const channels = color.match(/[\d.]+/g).slice(0, 3).map(Number).map(value => {
      const channel = value / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  expect(styles.pairs.length).toBeGreaterThanOrEqual(3);
  for (const pair of styles.pairs) {
    const text = luminance(pair.color);
    const background = luminance(pair.background);
    const contrast = (Math.max(text, background) + 0.05) / (Math.min(text, background) + 0.05);
    expect(contrast, pair.selector).toBeGreaterThanOrEqual(4.5);
    expect(pair.background, pair.selector).toBe(styles.themeSurface);
  }
}

for (const size of ['wide', 'narrow']) {
  for (const theme of ['light', 'dark']) {
    test(`admin navigation and every match form tab fit ${size} ${theme}`, async ({ page }, testInfo) => {
      const widths = testInfo.project.name === 'mobile' ? [390, 360] : [1280, 768];
      const width = widths[size === 'wide' ? 0 : 1];
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      await page.request.get('/__e2e__/admin-session');
      const fixture = await (await page.request.get('/__e2e__/review-fixture?test_match=1')).json();
      await page.goto(`/admin/matches/edit/${fixture.test_match_id}`);
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await screenshot(page, testInfo, `admin-matchup-${width}-${theme}`);
      await expectAdminFormFits(page);
      if (theme === 'dark') await expectDarkMatchFormContrast(page);
      await expect(page.locator('.top-nav .nav-links')).toHaveCSS('position', 'static');
      await expect(page.locator('.top-nav .nav-links')).toHaveCSS('flex-direction', 'row');
      const nav = await page.locator('.top-nav').boundingBox();
      const form = await page.locator('#matchForm').boundingBox();
      expect(form.y).toBeGreaterThanOrEqual(nav.y + nav.height);

      await page.locator('input[name="side1_type"][value="players"]').check();
      await expect(page.locator('#side1_players')).toBeVisible();
      await expectAdminFormFits(page);
      await page.locator('input[name="side1_type"][value="team"]').check();
      for (const tab of ['maps', 'roster', 'broadcast']) {
        await page.locator(`.match-tab[data-tab="${tab}"]`).click();
        await expect(page.locator(`#pane-${tab}`)).toBeVisible();
        if (tab === 'broadcast') {
          await page.getByRole('button', { name: '+ 添加平台', exact: true }).click();
          await expect(page.locator('input[name="watch_name_0"]')).toBeVisible();
        }
        await expectAdminFormFits(page);
        await screenshot(page, testInfo, `admin-${tab}-${width}-${theme}`);
      }

      await page.locator('.top-nav a[href="/admin/nicknames"]').click();
      await expect(page).toHaveURL(/\/admin\/nicknames$/);
      await page.locator('.top-nav a[href="/admin"]').click();
      await expect(page).toHaveURL(/\/admin$/);
      await page.locator('.top-nav a[href="/admin/matches"]').click();
      await expect(page).toHaveURL(/\/admin\/matches$/);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy();
      await screenshot(page, testInfo, `admin-navigation-${width}-${theme}`);
      await page.locator('a[href="/admin/matches/add"]').click();
      await expect(page).toHaveURL(/\/admin\/matches\/add$/);
      await expectAdminFormFits(page);
      if (theme === 'dark') await expectDarkMatchFormContrast(page);
      for (const tab of ['maps', 'roster', 'broadcast']) {
        await page.locator(`.match-tab[data-tab="${tab}"]`).click();
        await expect(page.locator(`#pane-${tab}`)).toBeVisible();
        await expectAdminFormFits(page);
      }
      await screenshot(page, testInfo, `admin-add-${width}-${theme}`);
    });
  }
}

test('unknown metrics survive JSON, HTML, browser refresh and mobile layout', async ({ page }, testInfo) => {
  const fixture = await (await page.request.get('/__e2e__/refactor-fixture')).json();
  const detail = await (await page.request.get(`/api/front/players/${fixture.player_id}`)).json();
  expect(detail.summary.rating).toBeNull();
  expect(detail.summary.adr).toBeNull();
  expect(detail.summary.kast).toBeNull();
  expect(detail.summary.impact).toBeNull();
  expect(detail.summary.kpr).toBe(0);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/players/${fixture.player_id}`);
  await expect(page.locator('.pp-stat-lead > b')).toHaveText('-');
  await expect(page.locator('.pp-stat-lead > b')).not.toHaveText('0.00');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await screenshot(page, testInfo, 'missing-player-metrics');
  await page.goto('/');
  const refresh = await page.request.get('/api/front/home');
  expect(refresh.ok()).toBeTruthy();
  const result = (await refresh.json()).recent_results.find(row => row.id === fixture.match_id);
  expect(result.team1).toBe('ALP');
  expect(result.team2).toBe('BRV');
  await expect(page.locator('[data-front-home]')).toHaveAttribute('data-api-ready', '1');
  const refreshedResult = page.locator(`.h-result-mini[href="/matches/${fixture.match_id}"]`);
  await expect(refreshedResult).toContainText('ALP');
  await expect(refreshedResult).toContainText('BRV');
  expect(errors).toEqual([]);
  await screenshot(page, testInfo, 'home-refactor');
});

test('ending an undecided series shows a failure and leaves its database row unchanged', async ({ page }, testInfo) => {
  await page.request.get('/__e2e__/admin-session');
  const fixture = await (await page.request.get('/__e2e__/review-fixture?test_match=1')).json();
  await page.goto(`/admin/matches/edit/${fixture.test_match_id}`);
  if (testInfo.project.name === 'mobile') {
    await screenshot(page, testInfo, 'existing-mobile-admin-obstruction');
  }
  await page.locator('button[data-status="live"]').click();
  await page.locator('button[type="submit"]').first().click();
  await expect(page).toHaveURL(/\/admin\/matches(?:\?.*)?$/);
  const readState = async () => (await (await page.request.get(`/__e2e__/review-state/${fixture.event_id}`)).json()).matches;
  const before = await readState();
  expect(before).toHaveLength(1);
  expect(before[0].status).toBe('live');
  await page.goto(`/admin/matches?event=${fixture.event_id}`);
  const form = page.locator(`form[action="/admin/matches/${fixture.test_match_id}/complete"]`);
  await expect(form).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await form.getByRole('button', { name: '结束比赛', exact: true }).click();
  await expect(page.getByText('比分尚未达到该赛制的获胜条件，或比分无效，不能结束比赛', { exact: true })).toBeVisible();
  expect(await readState()).toEqual(before);
  await screenshot(page, testInfo, 'undecided-series-rejected');
});

test('API failures remain JSON and prediction reads do not break guest pages', async ({ page }) => {
  const missing = await page.request.get('/api/front/does-not-exist');
  expect(missing.status()).toBe(404);
  expect(missing.headers()['content-type']).toContain('application/json');
  const body = await missing.json();
  expect(body.ok).toBe(false);
  expect(body.request_id).toBeTruthy();
  const predictions = await (await page.request.get('/api/front/predictions')).json();
  expect(predictions.ok).toBe(true);
  expect(predictions.upcoming_matches.length).toBeLessThanOrEqual(10);
  await page.goto('/predictions');
  await expect(page.locator('body')).not.toContainText('Internal Server Error');
});
