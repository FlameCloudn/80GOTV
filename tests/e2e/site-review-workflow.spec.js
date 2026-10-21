const { test, expect } = require('playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem('siteLang')) localStorage.setItem('siteLang', 'zh');
  });
});

let adminCookies;
async function loginAdmin(page) {
  if (adminCookies) {
    await page.context().addCookies(adminCookies);
    return;
  }
  await page.goto('/login?next=/admin/');
  await page.getByLabel('用户名', { exact: true }).fill('e2e-review-admin');
  await page.getByLabel('密码', { exact: true }).fill('e2e-only-review-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/$/);
  adminCookies = await page.context().cookies();
}

async function state(page, id) {
  const response = await page.request.get(`/__e2e__/review-state/${id}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

for (const [size, matchCount] of [[4, 6], [8, 14]]) {
  test(`${size}-team bracket rejects incomplete input, saves real matches and survives reload`, async ({ page }, testInfo) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width: 1280, height: 2200 });
    await loginAdmin(page);
    const fixture = await (await page.request.get(`/__e2e__/review-fixture?size=${size}`)).json();
    const id = fixture.event_id;
    const before = await state(page, id);
    await page.goto(`/admin/events/${id}/bracket`);
    await expect(page.locator('#bracketEditor .bracket-slot')).toHaveCount(6);
    await page.locator('#formatSelect').selectOption(`${size}de`);
    const rejected = page.waitForResponse(r => r.url().endsWith('/bracket/api/save'));
    await page.locator('#saveBracketBtn').click();
    expect((await rejected).status()).toBe(400);
    await expect(page.locator('.site-toast-msg').last()).toContainText(`请先把 ${size} 支队伍全部放入首轮`);
    expect(await state(page, id)).toEqual(before);

    for (let index = 0; index < size; index += 1) {
      await page.locator('#teamSearch').fill(fixture.teams[index].name);
      const chip = page.locator(`.team-chip[data-team-id="${fixture.teams[index].db_id}"]`);
      const slot = page.locator(`.slot-team[data-match-id="UB_R1_M${Math.floor(index / 2) + 1}"][data-slot-index="${index % 2}"]`);
      await chip.dragTo(slot);
      await expect(slot.locator(':scope > .team-name-text')).toHaveText(`R${index + 1}`);
    }
    const first = page.locator('.bracket-slot[data-match-id="UB_R1_M1"]');
    await first.locator('input[type="datetime-local"]').fill('2027-11-17T14:30');
    await first.locator('.slot-bo-row select').selectOption('BO5');
    const saved = page.waitForResponse(r => r.url().endsWith('/bracket/api/save'));
    await page.locator('#saveBracketBtn').click();
    expect((await saved).status()).toBe(200);
    await expect(page.locator('#saveBracketBtn')).toBeEnabled();
    const persisted = await state(page, id);
    expect(persisted.matches).toHaveLength(matchCount);
    const match = persisted.matches.find(m => m.team1_id === fixture.teams[0].db_id);
    expect(match.team2_id).toBe(fixture.teams[1].db_id);
    expect(match.match_time).toBe('2027-11-17T14:30');
    expect(match.bo_format).toBe('BO5');
    await page.reload();
    await expect(page.locator('#formatSelect')).toHaveValue(`${size}de`);
    await expect(first.locator('.slot-binding-row select')).toHaveValue(String(match.id));
    await expect(first.locator('input[type="datetime-local"]')).toHaveValue('2027-11-17T14:30');
    await expect(first.locator('.slot-bo-row select')).toHaveValue('BO5');
    const repeated = page.waitForResponse(r => r.url().endsWith('/bracket/api/save'));
    await page.locator('#saveBracketBtn').click();
    expect((await repeated).status()).toBe(200);
    const again = await state(page, id);
    expect(again.matches.map(m => m.id)).toEqual(persisted.matches.map(m => m.id));
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({ path: testInfo.outputPath(`bracket-${size}.png`), fullPage: true });
  });
}

test('opening a legacy bracket reads its format and all bindings without a database write', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await loginAdmin(page);
  const fixture = await (await page.request.get('/__e2e__/review-fixture?legacy=1')).json();
  const before = await state(page, fixture.event_id);
  await page.goto(`/admin/events/${fixture.event_id}/bracket`);
  await expect(page.locator('#formatSelect')).toHaveValue('4de');
  await expect(page.locator('.slot-actions a')).toHaveCount(6);
  for (const match of before.matches) {
    await expect(page.locator(`.slot-actions a[href="/admin/matches/edit/${match.id}"]`)).toBeVisible();
  }
  expect(await state(page, fixture.event_id)).toEqual(before);
  await page.screenshot({ path: testInfo.outputPath('legacy-bracket.png'), fullPage: true });
});

test('one-day and two-day shortcuts persist the same calendar days shown in the form', async ({ page }) => {
  await loginAdmin(page);
  const fixture = await (await page.request.get('/__e2e__/review-fixture')).json();
  for (const [label, expected] of [['1天 (单日赛)', '2027-11-17T20:00'], ['2天 (周末杯)', '2027-11-18T20:00']]) {
    await page.goto(`/admin/events/edit/${fixture.event_id}`);
    await page.locator('#startDateInput').fill('2027-11-17T10:00');
    await page.getByRole('button', { name: label, exact: true }).click();
    await expect(page.locator('#endDateInput')).toHaveValue(expected);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/admin\/events$/);
    expect((await state(page, fixture.event_id)).event.end_date).toBe(expected);
  }
});

test('an existing test match can be edited and saved without inventing team assignments', async ({ page }) => {
  await loginAdmin(page);
  const fixture = await (await page.request.get('/__e2e__/review-fixture?test_match=1')).json();
  await page.goto(`/admin/matches/edit/${fixture.test_match_id}`);
  await expect(page.getByText('这是一场测试比赛，不要求填写参赛队伍或选手。')).toBeVisible();
  await page.locator('input[name="stage"]').fill('E2E Review Edited');
  await page.locator('button[type="submit"]').first().click();
  await expect(page).toHaveURL(/\/admin\/matches(?:\?.*)?$/);
  const saved = (await state(page, fixture.event_id)).matches;
  expect(saved).toHaveLength(1);
  expect(saved[0].stage).toBe('E2E Review Edited');
  expect(saved[0].is_test_mode).toBe(1);
  expect(saved[0].team1_id).toBeNull();
  expect(saved[0].team2_id).toBeNull();
});

test('comparison side clicks preserve two distinct players and change their real recorded values', async ({ page }) => {
  const fixture = await (await page.request.get('/__e2e__/public-backend-fixture')).json();
  await page.goto('/stats?tab=compare');
  await page.locator('.stats-compare-picker select[name="id1"]').selectOption(String(fixture.player_id));
  await page.locator('.stats-compare-picker select[name="id2"]').selectOption(String(fixture.other_player_id));
  await page.locator('.stats-compare-submit').click();
  for (const [side, left, right] of [['ct', '0.80', '1.40'], ['t', '1.60', '0.80']]) {
    await page.locator(`.stats-side-tabs a[href*="side=${side}"]`).click();
    await expect(page).toHaveURL(new RegExp(`side=${side}.*id1=${fixture.player_id}.*id2=${fixture.other_player_id}`));
    await expect(page.locator('.stats-compare-picker select[name="id1"]')).toHaveValue(String(fixture.player_id));
    await expect(page.locator('.stats-compare-picker select[name="id2"]')).toHaveValue(String(fixture.other_player_id));
    const rating = page.locator('.stats-comparison-row').filter({ has: page.locator('span', { hasText: /^RATING/ }) });
    await expect(rating.locator('b').first()).toHaveText(left);
    await expect(rating.locator('b').last()).toHaveText(right);
  }
  await page.reload();
  await expect(page.locator('.stats-compare-picker select[name="id2"]')).toHaveValue(String(fixture.other_player_id));
});

test('match date and event controls preserve each other and link to the filtered results', async ({ page }) => {
  const fixture = await (await page.request.get('/__e2e__/public-backend-fixture')).json();
  await page.goto(`/matches?event=${fixture.event_id}&date=2026-10-01&month=2026-10`);
  await expect(page.locator('.empty-state')).toContainText('这天的比赛已结束');
  await page.locator('.match-calendar-head a[aria-label="下一月"]').click();
  expect(new URL(page.url()).searchParams.get('event')).toBe(String(fixture.event_id));
  expect(new URL(page.url()).searchParams.get('date')).toBe('2026-10-01');
  expect(new URL(page.url()).searchParams.get('month')).toBe('2026-11');
  await page.locator('.empty-state a').click();
  await expect(page).toHaveURL(new RegExp(`/results\\?event=${fixture.event_id}$`));
  await expect(page.locator('a.result-row')).toHaveCount(3);
});

test('navigation remains clickable in both languages at narrow and wide widths', async ({ page }, testInfo) => {
  test.setTimeout(120000);
  const fixture = await page.request.get('/__e2e__/review-fixture');
  expect(fixture.ok()).toBeTruthy();
  const widths = testInfo.project.name === 'mobile' ? [375, 390] : [761, 768, 820, 1180, 1440];
  for (const identity of ['guest', 'user', 'admin']) {
    await page.context().clearCookies();
    if (identity !== 'guest') await page.request.get(`/__e2e__/${identity}-session`);
    for (const lang of ['zh', 'en']) {
      await page.goto('/');
      await page.evaluate(value => { localStorage.setItem('siteLang', value); }, lang);
      await page.reload();
      await expect(page.locator('html')).toHaveAttribute('lang', lang === 'zh' ? 'zh-CN' : 'en');
      for (const width of widths) {
        await page.setViewportSize({ width, height: 900 });
        await expect.poll(() => page.evaluate(() => {
          const nav = document.querySelector('.navbar');
          const bottom = nav.getBoundingClientRect().bottom;
          const blocked = [];
          for (const item of nav.querySelectorAll('a,button,select,input')) {
            const r = item.getBoundingClientRect();
            if (!r.width || !r.height || r.top < 0 || r.bottom > bottom + 1) continue;
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            if (!hit || !(hit === item || item.contains(hit))) blocked.push(item.id || item.className || item.textContent);
          }
          return { overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth, blocked };
        }), { message: `${identity}/${lang}/${width}` }).toEqual({ overflow: false, blocked: [] });
        if ((width === 390 || width === 820) && lang === 'en' && identity === 'admin') {
          await page.screenshot({ path: testInfo.outputPath(`navigation-${width}.png`), fullPage: true });
        }
        const eventLink = page.getByRole('navigation', { name: lang === 'zh' ? '主导航' : 'Main navigation' }).locator('.nav-events > a');
        if (await page.locator('#hamburger').isVisible()) {
          await page.locator('#hamburger').click();
          await eventLink.click();
        } else if (await eventLink.isVisible()) {
          await eventLink.click();
        } else {
          await page.locator('.nav-more-compact').hover();
          await page.locator('.nav-more-compact a[href="/events"]').click();
        }
        await expect(page).toHaveURL(/\/events$/);
        expect(await page.locator('.event-list-row').evaluateAll(rows => rows.flatMap(row => {
          const date = row.querySelector('.event-list-date').getBoundingClientRect();
          const status = row.querySelector('.event-list-status').getBoundingClientRect();
          const bounds = row.getBoundingClientRect();
          return date.right > bounds.right + 1 || date.left < status.right - 1 ? [row.textContent] : [];
        })), `${identity}/${lang}/${width}: event dates must remain readable`).toEqual([]);
      }
    }
  }
});
