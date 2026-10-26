const { test, expect } = require('playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('siteLang', 'en'));
  await page.request.get('/__e2e__/admin-session');
});

test('赛程日期和选手对比空结果显示英文', async ({ page }) => {
  await page.goto('/matches?date=2026-10-01');
  await expect(page.locator('h2.panel-title').filter({ hasText: 'Matches on' })).toHaveText('Matches on 2026-10-01');
  const fixture = await (await page.request.get('/__e2e__/public-backend-fixture')).json();
  await page.goto(`/stats?tab=compare&id1=${fixture.player_id}&id2=${fixture.other_player_id}&event=999999`);
  await expect(page.getByText('No comparable data for the current filters', { exact: true })).toBeVisible();
});

test('后台保存结果和带原因的错误提示显示英文', async ({ page }) => {
  await page.goto('/admin/matches/add');
  const cases = [
    ['比赛添加成功', 'Match added'],
    ['比赛更新成功', 'Match updated'],
    ['选手更新成功', 'Player updated'],
    ['队伍添加成功', 'Team added'],
    ['赛事更新成功', 'Event updated'],
    ['新闻添加成功', 'News added'],
    ['数据保存失败：该地图比分尚未确认，不能按旧的 30 回合默认值保存', 'Stats save failed: The map score has not been confirmed; the old default of 30 rounds cannot be used'],
    ['比赛保存失败：比分尚未达到该赛制的获胜条件', 'Match save failed: The score has not reached the winning condition for this format'],
    ['de_nuke 数据已保存', 'de_nuke stats saved'],
    ['比赛已结束，新增保存 3 条 Game Log', 'Match completed; 3 new Game Log entries saved'],
  ];
  for (const [source, translated] of cases) {
    await page.evaluate(value => window.showToast(value, 'error', { key: 'translation-regression', duration: 0 }), source);
    await expect(page.locator('.site-toast-msg').last()).toHaveText(translated);
  }
});

for (const mode of ['team', 'players', 'mixed']) {
  test(`新建测试比赛保留先选中的参赛方：${mode}`, async ({ page }) => {
    const fixture = await (await page.request.get('/__e2e__/dot-match-form-fixture')).json();
    await page.goto('/admin/matches/add');
    await page.locator('[name="event_id"]').selectOption(String(fixture.event_id));
    await page.locator('#matchDate').fill('2027-12-01');
    await page.locator('[name="stage"]').fill('E2E selected test ' + mode);
    for (const side of [1, 2]) {
      const isTeam = mode === 'team' || (mode === 'mixed' && side === 1);
      await page.locator(`[name="side${side}_type"][value="${isTeam ? 'team' : 'players'}"]`).check();
      const field = isTeam ? `side${side}_id` : `side${side}_p0`;
      const value = isTeam ? fixture.teams[side - 1].id : fixture.teams[side - 1].player_ids[0];
      await page.locator(`[name="${field}"]`).selectOption(String(value));
    }
    for (const checked of [true, false, true]) {
      await page.locator('#testMode').setChecked(checked);
      await expect(page.locator('#matchParticipants')).toBeVisible();
      for (const side of [1, 2]) {
        const isTeam = mode === 'team' || (mode === 'mixed' && side === 1);
        const field = isTeam ? `side${side}_id` : `side${side}_p0`;
        const value = isTeam ? fixture.teams[side - 1].id : fixture.teams[side - 1].player_ids[0];
        await expect(page.locator(`[name="${field}"]`)).toBeEnabled();
        expect(await page.locator('#matchForm').evaluate((form, name) => new FormData(form).get(name), field)).toBe(String(value));
      }
    }
    await page.locator('#submitBtn').click();
    await expect(page).toHaveURL(/\/admin\/matches$/);
    await expect(page.locator('.site-toast-msg').last()).toHaveText('Match added');
    const state = await (await page.request.get('/__e2e__/review-state/' + fixture.event_id)).json();
    const saved = state.matches.find(match => match.stage === 'E2E selected test ' + mode);
    expect(saved).toBeTruthy();
    expect(saved.is_test_mode).toBe(1);
    await page.goto('/admin/matches/edit/' + saved.id);
    for (const side of [1, 2]) {
      const isTeam = mode === 'team' || (mode === 'mixed' && side === 1);
      const field = isTeam ? `side${side}_id` : `side${side}_p0`;
      const value = isTeam ? fixture.teams[side - 1].id : fixture.teams[side - 1].player_ids[0];
      await expect(page.locator(`[name="${field}"]`)).toHaveValue(String(value));
    }
  });
}
