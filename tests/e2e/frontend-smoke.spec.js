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

test('public home loads the v3 stylesheet and quick navigation', async ({ page }, testInfo) => {
  const response = await page.goto('/');
  expect(response.ok()).toBeTruthy();

  const appStylesheet = page.locator('head link[rel="stylesheet"][href*="app.css"]');
  await expect(appStylesheet).toHaveCount(1);
  await expect(appStylesheet).toHaveAttribute('href', /app\.css\?v=\d+$/);
  await expect(page.locator('head link[rel="stylesheet"][href*="style_v2.css"]')).toHaveCount(0);

  const quickNav = page.locator('header.navbar nav.nav-quick');
  await expect(quickNav).toHaveCount(1);
  await expect(quickNav).toHaveAttribute('aria-label', /快捷导航|Quick navigation/);
  await expect(quickNav.locator('a')).toHaveCount(4);
  for (const href of ['/news', '/matches', '/results', '/events']) {
    await expect(quickNav.locator(`a[href="${href}"]`)).toHaveCount(1);
  }
  if (testInfo.project.name === 'mobile') {
    await expect(quickNav).toBeVisible();
  } else {
    await expect(quickNav).toBeHidden();
  }
  await page.screenshot({ path: testInfo.outputPath('home-v3-navigation.png'), fullPage: true });
});

test('desktop dropdown supports ArrowDown and Escape', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.goto('/');
  await page.evaluate(() => {
    window.__dropdownKeyboardResult = null;
    window.addEventListener('keydown', event => {
      if (event.key !== 'ArrowDown') return;
      const menu = document.querySelector('.nav-events > .nav-dropdown-menu');
      const firstLink = menu.querySelector('a');
      window.__dropdownKeyboardResult = {
        menuVisibility: getComputedStyle(menu).visibility,
        firstLinkFocused: document.activeElement === firstLink,
      };
    }, { once: true });
  });
  const toggle = page.locator('.nav-events > .nav-dropdown-toggle');
  await toggle.focus();
  await page.keyboard.press('ArrowDown');
  const firstMenuLink = page.locator('.nav-events > .nav-dropdown-menu a').first();
  const keyboardResult = await page.evaluate(() => window.__dropdownKeyboardResult);
  expect(keyboardResult).toEqual({ menuVisibility: 'visible', firstLinkFocused: true });
  await expect(firstMenuLink).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath('dropdown-keyboard-open.png') });
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
  const stylesheetHref = await page.locator('link[href*="app.css"]').getAttribute('href');
  expect(stylesheetHref).toMatch(/app\.css\?v=\d+$/);
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
  // 成功：弹窗关上，右上角绿色提示
  await expect(page.locator('.site-toast.toast-success .site-toast-msg')).toHaveText('感谢反馈！');
  await expect(page.locator('#fbOverlay')).not.toHaveAttribute('open', '');
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
  // 失败：右上角红色提示（在弹窗里、读屏 role=alert），弹窗不关、内容不丢
  const failure = page.locator('#fbOverlay .site-toast.toast-error');
  await expect(failure).toContainText('暂时无法确认账号权限，请稍后重试');
  await expect(failure.locator('[role="alert"]')).toHaveCount(1);
  await expect(page.locator('#fbOverlay')).toHaveAttribute('open', '');
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

test('mobile event filters keep labels on one line in Chinese and English', async ({ page }, testInfo) => {
  for (const width of [360, 390]) {
    await page.setViewportSize({ width, height: 780 });
    for (const language of ['zh', 'en']) {
      await page.goto('/');
      await page.evaluate(value => localStorage.setItem('siteLang', value), language);
      await page.reload();
      await expect(page.locator('html')).toHaveAttribute('lang', language === 'zh' ? 'zh-CN' : 'en');

      for (const filter of [
        { path: '/matches?month=2026-10', selector: '.mobile-match-event-filter', label: '赛事' },
        { path: '/results', selector: '.mobile-result-event-filter', label: '赛事' },
      ]) {
        await page.goto(filter.path);
        const form = page.locator(filter.selector);
        const label = form.locator('label');
        const select = form.locator('select');
        await expect(form).toBeVisible();
        await expect(label).toHaveText(language === 'zh' ? filter.label : 'Events');

        const geometry = await form.evaluate(element => {
          const labelElement = element.querySelector('label');
          const selectElement = element.querySelector('select');
          const range = document.createRange();
          range.selectNodeContents(labelElement);
          const formRect = element.getBoundingClientRect();
          const labelRect = labelElement.getBoundingClientRect();
          const selectRect = selectElement.getBoundingClientRect();
          return {
            labelLines: range.getClientRects().length,
            labelRight: labelRect.right,
            selectLeft: selectRect.left,
            selectRight: selectRect.right,
            selectWidth: selectRect.width,
            formRight: formRect.right,
          };
        });
        expect(geometry.labelLines, `${width}px ${language} ${filter.path} label lines`).toBe(1);
        expect(geometry.labelRight).toBeLessThanOrEqual(geometry.selectLeft);
        expect(geometry.selectWidth).toBeGreaterThan(0);
        expect(geometry.selectRight).toBeLessThanOrEqual(geometry.formRight + 1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);

        if (filter.path.startsWith('/matches')) {
          await page.screenshot({ path: testInfo.outputPath(`matches-filter-${width}-${language}.png`), fullPage: true });
        }
      }
    }
  }
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
  await expect(page.locator('.page-head h1')).toHaveText('Statistics');
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

test('English mode translates static UI without hiding user content', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('siteLang', 'en'));
  const publicPaths = [
    '/', '/matches', '/results', '/events', '/players', '/stats', '/predictions',
    '/dashboard', '/forum', '/games', '/guess-player', '/map-quiz', '/player-bingo',
    '/login', '/register', '/change-password', '/search?q=test',
    '/teams', '/awards', '/players/compare', '/stats?tab=players',
  ];

  async function untranslatedText(path, expectFeedback = false) {
    const response = await page.goto(path);
    expect(response.ok(), path).toBeTruthy();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('html')).not.toHaveClass(/i18n-pending/);
    if (expectFeedback) {
      await expect(page.locator('#fbOverlay')).toHaveCount(1);
      const options = page.locator('#fbType option');
      await expect(options).toHaveText(['Suggestion', 'Bug report', 'Question', 'Other']);
    }
    if (path === '/notifications') {
      await page.evaluate(() => {
        window.__feedbackOpenState = null;
        const captureOpen = event => {
          if (!event.target.closest('#fbBtn')) return;
          window.removeEventListener('click', captureOpen);
          const dialog = document.querySelector('#fbOverlay');
          window.__feedbackOpenState = {
            isOpen: dialog.open,
            title: document.querySelector('#fbTitle').textContent.trim(),
            options: [...document.querySelectorAll('#fbType option')].map(option => option.textContent.trim()),
          };
        };
        window.addEventListener('click', captureOpen);
      });
      await page.locator('#fbBtn').click();
      const openState = await page.evaluate(() => window.__feedbackOpenState);
      expect(openState).toEqual({
        isOpen: true,
        title: 'Feedback',
        options: ['Suggestion', 'Bug report', 'Question', 'Other'],
      });
      await expect(page.locator('#fbOverlay')).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath('feedback-open-en.png') });
    }
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
    const values = await untranslatedText(path, true);
    if (values.length) untranslated[path] = values;
  }

  await page.goto('/__e2e__/admin-session');
  for (const path of ['/admin', '/admin/registrations', '/admin/players', '/admin/events/add', '/admin/matches/add', '/admin/news/add']) {
    const values = await untranslatedText(path);
    if (values.length) untranslated[path] = values;
  }
  expect(untranslated).toEqual({});
});

test('tablet widths keep all home columns aligned and result rows on one line', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  for (const width of [1024, 820]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    const main = await page.locator('.home-main-col').boundingBox();
    const sides = [await page.locator('.home-left-col').boundingBox(), await page.locator('.home-right-col').boundingBox()];
    // 761px 以上的平板和桌面都保留三栏，并确保左右侧栏与新闻主栏顶边对齐。
    expect(sides[0].x + sides[0].width, `${width}px 左栏在新闻左侧`).toBeLessThanOrEqual(main.x + 1);
    expect(main.x + main.width, `${width}px 新闻在左右栏中间`).toBeLessThanOrEqual(sides[1].x + 1);
    expect(Math.abs(sides[0].y - main.y), `${width}px 左栏顶部对齐`).toBeLessThanOrEqual(1);
    expect(Math.abs(sides[1].y - main.y), `${width}px 右栏顶部对齐`).toBeLessThanOrEqual(1);

    await page.goto('/results');
    const rows = page.locator('.result-row');
    expect(await rows.count()).toBeGreaterThan(0);
    const geometry = await rows.evaluateAll(list => list.map(row => {
      const group = row.querySelector('.result-score-group').getBoundingClientRect();
      const event = row.querySelector('.result-event').getBoundingClientRect();
      return { groupTop: group.top, groupBottom: group.bottom, eventTop: event.top, eventBottom: event.bottom };
    }));
    for (const row of geometry) {
      // 赛事名和对阵、比分在同一行（以前会掉到下一行并居中）
      expect(row.eventTop, `${width}px`).toBeLessThan(row.groupBottom);
      expect(row.eventBottom, `${width}px`).toBeGreaterThan(row.groupTop);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  }
});

test('desktop home side columns use the same compact width', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.goto('/');
  const left = await page.locator('.home-left-col').boundingBox();
  const right = await page.locator('.home-right-col').boundingBox();
  expect(left).not.toBeNull();
  expect(right).not.toBeNull();
  expect(Math.abs(left.width - right.width)).toBeLessThanOrEqual(1);
  // 第三版首页两侧栏固定 240px（左右等宽）
  expect(left.width).toBeLessThanOrEqual(240);
});
