const { test, expect } = require('playwright/test');

for (const path of ['/', '/matches', '/players', '/login']) {
  test(`${path} renders without page errors or horizontal overflow`, async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const response = await page.goto(path);
    expect(response.ok()).toBeTruthy();
    await expect(page.locator('body')).toBeVisible();
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  });
}

test('desktop dropdown supports ArrowDown and Escape', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.goto('/');
  const toggle = page.locator('.nav-events > .nav-dropdown-toggle');
  await toggle.focus();
  await page.keyboard.press('ArrowDown');
  await expect(page.locator('.nav-events > .nav-dropdown-menu a').first()).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(toggle).toBeFocused();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
});

test('desktop admin player list shows CS2 playtime controls', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.goto('/__e2e__/admin-session');
  const response = await page.goto('/admin/players');
  expect(response.ok()).toBeTruthy();
  await expect(page.getByRole('columnheader', { name: /CS2 时长|CS2 playtime/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /更新选手时长|Refresh player playtime/ })).toBeVisible();
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);
});

test('desktop admin can enable test match mode without participants', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.goto('/__e2e__/admin-session');
  await page.goto('/admin/matches/add');

  const testMode = page.locator('#testMode');
  const participants = page.locator('#matchParticipants');
  await expect(testMode).toBeVisible();
  await expect(participants).toBeVisible();
  await testMode.check();
  await expect(participants).toBeHidden();
  await expect(page.locator('select[name="side1_id"]')).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath('test-match-mode.png'), fullPage: true });
});

test('feedback dialog opens, closes, and restores focus', async ({ page }, testInfo) => {
  await page.goto('/__e2e__/admin-session');
  await page.goto('/');
  const stylesheetHref = await page.locator('link[href*="hltv_refresh.css"]').getAttribute('href');
  expect(stylesheetHref).toMatch(/hltv_refresh\.css\?v=\d+$/);
  const opener = page.locator('#fbBtn');
  const dialog = page.locator('#fbOverlay');
  await expect(opener).toBeVisible();
  await opener.click();
  await expect(dialog).toHaveAttribute('open', '');
  await expect(dialog).toHaveCSS('display', 'grid');
  await expect(dialog).toHaveCSS('position', 'fixed');
  const panelBox = await page.locator('.feedback-dialog').boundingBox();
  expect(panelBox).not.toBeNull();
  expect(panelBox.width).toBeLessThanOrEqual(testInfo.project.name === 'mobile' ? 340 : 440);
  expect(panelBox.width).toBeGreaterThanOrEqual(testInfo.project.name === 'mobile' ? 300 : 400);
  expect(panelBox.x).toBeGreaterThanOrEqual(0);
  expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(page.viewportSize().width);
  await expect(page.locator('#fbType')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toHaveAttribute('open', '');
  await expect(opener).toBeFocused();
});

test('feedback submits through the visible entry and is saved for admin review', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));
  const login = await page.request.get('/__e2e__/user-session');
  const { user_id: userId } = await login.json();
  await page.goto('/');
  const opener = page.getByRole('button', { name: '意见反馈', exact: true });
  await expect(opener).toBeVisible();
  const box = await opener.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize().width);
  expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize().height);
  await opener.click();
  await expect(page.getByRole('dialog', { name: '意见反馈' })).toBeVisible();
  const content = `浏览器反馈审查 ${testInfo.project.name} ${Date.now()}`;
  await page.locator('#fbType').selectOption('bug');
  await page.locator('#fbContent').fill(content);
  await page.locator('#fbContact').fill('audit@example.invalid');
  await page.screenshot({ path: testInfo.outputPath('feedback-filled.png'), fullPage: true });
  const submitted = page.waitForResponse(response =>
    response.url().endsWith('/api/feedback/submit') && response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: '提交', exact: true }).click();
  const response = await submitted;
  expect(response.status()).toBe(200);
  expect((await response.json()).ok).toBe(true);
  await expect(page.locator('#fbMsg')).toHaveText('成功 感谢反馈！');
  await expect(page.locator('#fbMsg')).toHaveAttribute('data-type', 'success');
  await expect(page.locator('#fbContent')).toHaveValue('');
  const stored = await page.request.get(`/__e2e__/feedback-records?content=${encodeURIComponent(content)}`);
  expect(await stored.json()).toEqual([expect.objectContaining({
    content, type: 'bug', contact: 'audit@example.invalid', user_id: userId, status: 'open',
  })]);
  await page.request.get('/__e2e__/admin-session');
  await page.goto('/admin/feedback');
  await expect(page.getByText(content, { exact: true })).toBeVisible();
});

test('feedback failure preserves the draft and a real retry stores it once', async ({ page }, testInfo) => {
  if (testInfo.project.name === 'mobile') await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));
  await page.request.get('/__e2e__/user-session');
  await page.goto('/');
  await page.getByRole('button', { name: '意见反馈', exact: true }).click();
  const content = `失败重试审查 ${testInfo.project.name} ${Date.now()}`;
  await page.locator('#fbContent').fill(content);
  // Simulate only the unavailable-service response; the retry uses the real backend.
  await page.route('**/api/feedback/submit', route => route.fulfill({
    status: 503, contentType: 'application/json',
    body: JSON.stringify({ ok: false, success: false, error: '暂时无法确认账号权限，请稍后重试' }),
  }));
  await page.locator('#fbSubmit').click();
  await expect(page.locator('#fbMsg')).toContainText('暂时无法确认账号权限，请稍后重试');
  await expect(page.locator('#fbMsg')).toHaveAttribute('data-type', 'error');
  await expect(page.locator('#fbContent')).toHaveValue(content);
  await expect(page.locator('#fbSubmit')).toBeEnabled();
  const before = await page.request.get(`/__e2e__/feedback-records?content=${encodeURIComponent(content)}`);
  expect(await before.json()).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  await page.screenshot({ path: testInfo.outputPath('feedback-retry.png'), fullPage: true });
  await page.unroute('**/api/feedback/submit');
  const submitted = page.waitForResponse(response => response.url().endsWith('/api/feedback/submit'));
  await page.locator('#fbSubmit').click();
  expect((await (await submitted).json()).ok).toBe(true);
  const stored = await page.request.get(`/__e2e__/feedback-records?content=${encodeURIComponent(content)}`);
  expect(await stored.json()).toEqual([expect.objectContaining({ content, status: 'open' })]);
});

test('mobile menu closes with Escape and touch targets are large enough', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile');
  await page.goto('/matches');
  const hamburger = page.locator('#hamburger');
  await hamburger.click();
  await expect(hamburger).toHaveAttribute('aria-label', /关闭菜单|Close menu/);
  await page.keyboard.press('Escape');
  await expect(page.locator('#navLinks')).not.toHaveClass(/open/);
  await expect(hamburger).toHaveAttribute('aria-expanded', 'false');
  await expect(hamburger).toHaveAttribute('aria-label', /打开菜单|Open menu/);

  const calendarHeight = await page.locator('.match-calendar-head a').first().evaluate(el => el.getBoundingClientRect().height);
  const selectHeight = await page.locator('#mobileMatchEvent').evaluate(el => el.getBoundingClientRect().height);
  expect(calendarHeight).toBeGreaterThanOrEqual(40);
  expect(selectHeight).toBeGreaterThanOrEqual(40);

  await page.goto('/players');
  const letterHeight = await page.locator('.player-initial-filter a').first().evaluate(el => el.getBoundingClientRect().height);
  expect(letterHeight).toBeGreaterThanOrEqual(40);
});

test('live player rows and weapon images stay stable between polls', async ({ page }, testInfo) => {
  const errors = [];
  let matchImageRequests = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.resourceType() === 'image' && request.url().includes('/resources/icons/match/')) {
      matchImageRequests += 1;
    }
  });

  const fixtureResponse = await page.request.get('/__e2e__/live-fixture');
  expect(fixtureResponse.ok()).toBeTruthy();
  const fixture = await fixtureResponse.json();
  await page.goto(`/matches/${fixture.match_id}`);

  const firstRow = page.locator('#team1Players .player-row').first();
  await expect(firstRow).toContainText('Player One');
  await expect(firstRow.locator('.p-weapon img')).toHaveAttribute(
    'src',
    '/resources/icons/match/ak47.webp',
  );
  await expect(page.locator('#team2Players .p-weapon img').first()).toHaveAttribute(
    'src',
    '/resources/icons/match/ump45.svg',
  );

  await firstRow.evaluate(row => { window.__firstLiveRow = row; });
  await page.waitForTimeout(1300);
  const requestsAfterInitialPolls = matchImageRequests;
  await page.waitForTimeout(2200);

  expect(await firstRow.evaluate(row => window.__firstLiveRow === row)).toBeTruthy();
  expect(matchImageRequests).toBe(requestsAfterInitialPolls);
  expect(errors).toEqual([]);

  await page.goto(`/matches/${fixture.match_id}`);
  await expect(page.locator('#data-live')).toBeVisible();
  await expect(page.locator('#roundTeam1 .round-cell')).toHaveCount(24);
  await expect(page.locator('#roundTeam2 .round-cell')).toHaveCount(24);
  await expect(
    page.locator('#roundTeam1 .round-cell:nth-child(n+25), #roundTeam2 .round-cell:nth-child(n+25)'),
  ).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('live-stable.png'), fullPage: true });
});

test('English mode keeps the first visible games page free of Chinese source text', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('siteLang', 'en'));

  let releaseI18n;
  let markI18nRequested;
  const i18nRequested = new Promise(resolve => { markI18nRequested = resolve; });
  const i18nGate = new Promise(resolve => { releaseI18n = resolve; });

  await page.route(/\/static\/js\/i18n\.js(?:\?.*)?$/, async route => {
    markI18nRequested();
    await i18nGate;
    await route.continue();
  });

  const navigation = page.goto('/games', { waitUntil: 'domcontentloaded' });
  await i18nRequested;

  const html = page.locator('html');
  const body = page.locator('body');
  await expect(html).toHaveClass(/i18n-pending/);
  await expect(body).toHaveCSS('visibility', 'hidden');
  await page.waitForTimeout(150);
  await expect(body).toHaveCSS('visibility', 'hidden');

  releaseI18n();
  const response = await navigation;
  expect(response.ok()).toBeTruthy();
  await expect(html).toHaveAttribute('lang', 'en');
  await expect(body).toHaveCSS('visibility', 'visible');
  await expect(page.getByRole('heading', { name: 'Games' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Guess the player' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('i18n-games-first-visible.png'), fullPage: true });
});

test('English games and stats use translated common and dynamic labels', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('siteLang', 'en'));

  await page.goto('/games');
  await expect(page.getByRole('heading', { name: 'Games' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Guess the player' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Map locations' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Player Bingo' })).toBeVisible();

  await page.evaluate(() => {
    const label = document.createElement('p');
    label.id = 'e2eDynamicI18nLabel';
    label.textContent = '开始挑战 →';
    document.body.appendChild(label);
  });
  await expect(page.locator('#e2eDynamicI18nLabel')).toHaveText('Start challenge →');

  await page.goto('/stats');
  await expect(page.locator('.stats-page-heading h1')).toHaveText('Statistics');
  await expect(page.locator('.overview-quick-title')).toHaveText('Quick navigation');
  await expect(page.locator('.overview-summary-grid')).toContainText('Map stats');
  await page.screenshot({ path: testInfo.outputPath('i18n-stats.png'), fullPage: true });
});

test('Chinese content remains available when JavaScript is disabled', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const noJavaScriptPage = await context.newPage();
  try {
    const response = await noJavaScriptPage.goto(`${baseURL}/games`);
    expect(response.ok()).toBeTruthy();
    await expect(noJavaScriptPage.locator('html')).not.toHaveClass(/i18n-pending/);
    await expect(noJavaScriptPage.getByRole('heading', { name: '游戏' })).toBeVisible();
  } finally {
    await context.close();
  }
});

test('English mode translates static UI without hiding user content', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('siteLang', 'en'));
  const publicPaths = [
    '/', '/matches', '/results', '/events', '/players', '/stats', '/predictions',
    '/dashboard', '/forum', '/games', '/guess-player', '/map-quiz', '/player-bingo',
    '/login', '/register', '/change-password', '/search?q=test',
    '/teams', '/awards', '/players/compare', '/stats?tab=players',
  ];

  async function untranslatedText(path) {
    const response = await page.goto(path);
    expect(response.ok(), path).toBeTruthy();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await page.waitForTimeout(120);
    return page.evaluate(() => {
      const ignored = [
        '[data-i18n-ignore]', '.news-title', '.news-summary', '.news-detail',
        '.comment-content', '.comment-body', '.comment-author', '.username',
        '.team', '.team-name', '.player-name', '.player-link', '.sidebar-event-name',
      ].join(',');
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const found = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const parent = node.parentElement;
        if (!parent || /^(SCRIPT|STYLE|TEXTAREA)$/.test(parent.tagName) || parent.closest(ignored)) continue;
        const value = node.nodeValue.replace(/\s+/g, ' ').trim();
        if (/[\u3400-\u9fff]/.test(value)) found.push(value);
      }
      return [...new Set(found)];
    });
  }

  const untranslated = {};
  for (const path of publicPaths) {
    const values = await untranslatedText(path);
    if (values.length) untranslated[path] = values;
  }

  await page.goto('/__e2e__/user-session');
  for (const path of [
    '/profile', '/notifications', '/guess-player', '/guess-player/practice',
    '/guess-player/multiplayer', '/map-quiz', '/map-quiz/practice',
    '/player-bingo', '/player-bingo/practice',
  ]) {
    const values = await untranslatedText(path);
    if (values.length) untranslated[path] = values;
  }

  await page.goto('/__e2e__/admin-session');
  for (const path of ['/admin', '/admin/registrations', '/admin/players', '/admin/events/add', '/admin/matches/add', '/admin/news/add']) {
    const values = await untranslatedText(path);
    if (values.length) untranslated[path] = values;
  }
  expect(untranslated).toEqual({});
});

test('desktop home side columns use the same compact width', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.goto('/');
  const left = await page.locator('.home-left-col').boundingBox();
  const right = await page.locator('.home-right-col').boundingBox();
  expect(left).not.toBeNull();
  expect(right).not.toBeNull();
  expect(Math.abs(left.width - right.width)).toBeLessThanOrEqual(1);
  expect(left.width).toBeLessThanOrEqual(220);
});
