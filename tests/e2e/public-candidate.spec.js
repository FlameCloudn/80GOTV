const { test, expect } = require('playwright/test');

test('首页在桌面、平板和手机宽度保留正确的信息顺序', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  const widths = [360, 390, 760, 761, 768, 820, 960, 1024, 1100, 1180, 1280, 1440];
  const fixtureResponse = await page.request.get('/__e2e__/home-fixture');
  expect(fixtureResponse.ok()).toBeTruthy();
  const fixture = await fixtureResponse.json();

  for (const width of widths) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/');
    await expect(page.locator('.home-feature h1')).toHaveText(fixture.featured_news_title);
    expect(await page.locator('.h-news-row').count()).toBeGreaterThan(0);
    expect(await page.locator('.h-match-mini').count()).toBeGreaterThan(0);
    await page.evaluate(() => {
      document.querySelectorAll('.h-mini-teams b').forEach((element, index) => {
        element.textContent = index % 2 ? 'The Extremely Long International Invitational Team' : '超级长队伍名称用于检查会不会挤出比分行';
      });
      document.querySelectorAll('.h-result-team .truncate').forEach((element, index) => {
        element.textContent = index % 2 ? 'The Extremely Long International Invitational Team' : '超级长队伍名称用于检查会不会挤出比分行';
      });
    });
    const layout = await page.evaluate(() => {
      const box = selector => {
        const element = document.querySelector(selector);
        const rect = element.getBoundingClientRect();
        return {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          visible: getComputedStyle(element).display !== 'none',
        };
      };
      const rows = [...document.querySelectorAll('.h-match-mini, .h-result-mini, .h-news-row')].map(element => {
        const rect = element.getBoundingClientRect();
        return {
          kind: element.classList.contains('h-match-mini') ? 'match' : element.classList.contains('h-result-mini') ? 'score' : 'news',
          overflow: element.scrollWidth - element.clientWidth,
          childrenFit: [...element.children].every(child => {
            const childRect = child.getBoundingClientRect();
            return childRect.left >= rect.left - 1 && childRect.right <= rect.right + 1;
          }),
        };
      });
      return {
        viewport: innerWidth,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        main: box('.home-main-col'),
        left: box('.home-left-col'),
        right: box('.home-right-col'),
        rows,
      };
    });

    expect(layout.viewport, `${width}px viewport`).toBe(width);
    expect(layout.overflow, `${width}px horizontal overflow`).toBeLessThanOrEqual(1);
    expect.soft(layout.rows.filter(row => row.overflow > 1 || !row.childrenFit), `${width}px headline, score, date and team labels fit their rows`).toEqual([]);

    if (width <= 760) {
      expect.soft(layout.left.visible, `${width}px left sidebar is hidden on mobile`).toBeFalsy();
      expect.soft(layout.right.visible, `${width}px right sidebar is hidden on mobile`).toBeFalsy();
      expect.soft(layout.left.height, `${width}px left sidebar has no stacked card height`).toBe(0);
      expect.soft(layout.right.height, `${width}px right sidebar has no stacked card height`).toBe(0);
    } else if (width <= 1023) {
      expect.soft(layout.left.visible, `${width}px left sidebar remains visible`).toBeTruthy();
      expect.soft(layout.right.visible, `${width}px right sidebar remains visible`).toBeTruthy();
      expect.soft(layout.left.y, `${width}px left sidebar aligns with main`).toBe(layout.main.y);
      expect.soft(layout.right.y, `${width}px right sidebar aligns with main`).toBe(layout.main.y);
      expect.soft(layout.left.width, `${width}px left sidebar remains readable`).toBe(160);
      expect.soft(layout.main.width, `${width}px main retains room for its content`).toBeGreaterThanOrEqual(350);
      expect.soft(layout.right.width, `${width}px right sidebar remains readable`).toBe(180);
      expect.soft(layout.left.x + layout.left.width, `${width}px left sidebar stays left of main`).toBeLessThanOrEqual(layout.main.x);
      expect.soft(layout.main.x + layout.main.width, `${width}px main stays left of right sidebar`).toBeLessThanOrEqual(layout.right.x);
    } else {
      expect(layout.left.x, `${width}px left sidebar is first`).toBeLessThan(layout.main.x);
      expect(layout.main.x, `${width}px main is between both sidebars`).toBeLessThan(layout.right.x);
      expect(layout.left.y, `${width}px all desktop columns align`).toBe(layout.main.y);
      expect(layout.right.y, `${width}px all desktop columns align`).toBe(layout.main.y);
    }
  }
});

test('首页焦点标题不会把一个汉字单独挤到末行', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));
  const fixtureResponse = await page.request.get('/__e2e__/home-fixture');
  expect(fixtureResponse.ok()).toBeTruthy();
  const fixture = await fixtureResponse.json();
  const widths = [768, 820, 960, 1024, 390];
  const titles = [
    'Preview Autumn Cup 2026 今晚开打',
    '2026 秋季冠军邀请赛今晚正式开打，欢迎关注最新比赛直播与战报',
    'Preview Autumn Championship Invitational 2026 begins tonight with the grand final live',
  ];

  for (const width of widths) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/');
    const heading = page.locator('.home-feature h1');
    await expect(heading).toHaveText(fixture.featured_news_title);

    for (const [index, title] of titles.entries()) {
      await heading.evaluate((element, value) => { element.textContent = value; }, title);
      const layout = await heading.evaluate(element => {
        const style = getComputedStyle(element);
        const text = element.firstChild;
        const ranges = document.createRange();
        const lines = new Map();
        let offset = 0;
        for (const character of Array.from(element.textContent)) {
          ranges.setStart(text, offset);
          ranges.setEnd(text, offset + character.length);
          const rect = ranges.getBoundingClientRect();
          const top = Math.round(rect.top);
          if (!lines.has(top)) lines.set(top, []);
          if (!/\s/.test(character)) lines.get(top).push(character);
          offset += character.length;
        }
        return {
          textWrap: style.textWrap || style.getPropertyValue('text-wrap'),
          lines: [...lines.entries()].filter(([, characters]) => characters.length),
        };
      });

      expect(layout.textWrap, `${width}px title uses balanced wrapping`).toBe('balance');
      if (index > 0) expect(layout.lines.length, `${width}px long title wraps into multiple lines`).toBeGreaterThan(1);
      if (layout.lines.length > 1) {
        expect(layout.lines.at(-1)[1].length, `${width}px title has no single-character last line`).toBeGreaterThan(1);
      }
    }
  }
});

test('BP、比赛战报和旧直播链接都进入对应新页面', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));

  const reportFixtureResponse = await page.request.get('/__e2e__/refactor-fixture');
  expect(reportFixtureResponse.ok()).toBeTruthy();
  const reportFixture = await reportFixtureResponse.json();
  const reportResponse = await page.goto(`/matches/${reportFixture.match_id}/report`);
  expect(reportResponse.ok()).toBeTruthy();
  await expect(page.locator('h1')).toContainText('比赛战报');
  const matchCss = page.locator('link[rel="stylesheet"][href*="/css/pages/match.css"]');
  await expect(matchCss).toHaveCount(1);
  expect(await matchCss.evaluate(link => fetch(link.href).then(response => response.status))).toBe(200);

  const liveFixtureResponse = await page.request.get('/__e2e__/live-fixture');
  expect(liveFixtureResponse.ok()).toBeTruthy();
  const liveFixture = await liveFixtureResponse.json();
  const liveResponse = await page.goto(`/matches/${liveFixture.match_id}/live`);
  expect(liveResponse.ok()).toBeTruthy();
  await expect(page).toHaveURL(new RegExp(`/matches/${liveFixture.match_id}#data-live$`));
  await expect(page.locator('#data-live')).toBeVisible();

  const adminSessionResponse = await page.request.get('/__e2e__/admin-session');
  expect(adminSessionResponse.ok()).toBeTruthy();
  const bpResponse = await page.goto(`/bp/${liveFixture.match_id}`);
  expect(bpResponse.ok()).toBeTruthy();
  await expect(page.locator('.bp-team-name')).toHaveCount(2);
  await expect(page.locator('.bp-board')).toBeVisible();
  const bpCss = page.locator('link[rel="stylesheet"][href*="/css/pages/bp.css"]');
  await expect(bpCss).toHaveCount(1);
  expect(await bpCss.evaluate(link => fetch(link.href).then(response => response.status))).toBe(200);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
});
