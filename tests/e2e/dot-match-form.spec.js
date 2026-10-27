const { test, expect } = require('playwright/test');
const fs = require('node:fs');
const path = require('node:path');

async function openMatchEditor(page, matchId) {
  await page.addInitScript(() => window.localStorage.setItem('siteLang', 'zh'));
  await page.request.get('/__e2e__/admin-session');
  await page.goto(`/admin/matches/edit/${matchId}`);
  await expect(page.locator('#matchForm')).toBeVisible();
}

async function saveAndReopen(page, matchId) {
  const saveResponse = page.waitForResponse(response =>
    response.url().endsWith(`/admin/matches/edit/${matchId}`) &&
    response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: '保存修改' }).click();
  await saveResponse;
  await expect(page).toHaveURL(/\/admin\/matches$/);
  await page.goto(`/admin/matches/edit/${matchId}`);
  await expect(page.locator('#matchForm')).toBeVisible();
}

async function saveScreenshot(page, testInfo, name) {
  const outputDirectory = path.resolve('output/ui-audit/codex-dot-match-form');
  fs.mkdirSync(outputDirectory, { recursive: true });
  await page.screenshot({
    path: path.join(outputDirectory, `${name}-${testInfo.project.name}.png`),
    fullPage: true,
  });
}

async function showRosterTab(page) {
  await page.getByRole('button', { name: '出场名单与替补' }).click();
  await expect(page.locator('#pane-roster')).toBeVisible();
}

test('互换两支队伍后，五人出场名单跟随队伍保存并重开', async ({ page }, testInfo) => {
  await page.setViewportSize({
    width: testInfo.project.name === 'mobile' ? 390 : 1280,
    height: testInfo.project.name === 'mobile' ? 844 : 900,
  });
  const fixture = await (await page.request.get('/__e2e__/dot-match-form-fixture')).json();
  const [teamA, teamB] = fixture.teams;
  await openMatchEditor(page, fixture.match_id);

  await page.getByRole('button', { name: '互换参赛双方' }).click();
  await expect(page.locator('#side1_select')).toHaveValue(String(teamB.id));
  await expect(page.locator('#side2_select')).toHaveValue(String(teamA.id));
  await showRosterTab(page);
  for (let slot = 0; slot < 5; slot += 1) {
    await expect(page.locator(`[name="match_team1_p${slot}"]`)).toHaveValue(String(teamB.player_ids[slot]));
    await expect(page.locator(`[name="match_team2_p${slot}"]`)).toHaveValue(String(teamA.player_ids[slot]));
  }
  await saveScreenshot(page, testInfo, 'team-swap-before-save');

  await saveAndReopen(page, fixture.match_id);
  await expect(page.locator('#side1_select')).toHaveValue(String(teamB.id));
  await expect(page.locator('#side2_select')).toHaveValue(String(teamA.id));
  await showRosterTab(page);
  for (let slot = 0; slot < 5; slot += 1) {
    await expect(page.locator(`[name="match_team1_p${slot}"]`)).toHaveValue(String(teamB.player_ids[slot]));
    await expect(page.locator(`[name="match_team2_p${slot}"]`)).toHaveValue(String(teamA.player_ids[slot]));
  }
  await saveScreenshot(page, testInfo, 'team-swap-after-reopen');
});

test('互换普通队伍与自选选手时，模式和五名临时选手一起保存并重开', async ({ page }, testInfo) => {
  await page.setViewportSize({
    width: testInfo.project.name === 'mobile' ? 390 : 1280,
    height: testInfo.project.name === 'mobile' ? 844 : 900,
  });
  const fixture = await (await page.request.get('/__e2e__/dot-match-form-fixture')).json();
  const [teamA, teamB] = fixture.teams;
  await openMatchEditor(page, fixture.match_id);

  await page.locator('input[name="side2_type"][value="players"]').check();
  for (let slot = 0; slot < 5; slot += 1) {
    await page.locator(`[name="side2_p${slot}"]`).selectOption(String(teamB.player_ids[slot]));
  }
  await page.getByRole('button', { name: '互换参赛双方' }).click();
  await expect(page.locator('input[name="side1_type"][value="players"]')).toBeChecked();
  await expect(page.locator('input[name="side2_type"][value="team"]')).toBeChecked();
  await expect(page.locator('#side2_select')).toHaveValue(String(teamA.id));
  await showRosterTab(page);
  for (let slot = 0; slot < 5; slot += 1) {
    await expect(page.locator(`[name="side1_p${slot}"]`)).toHaveValue(String(teamB.player_ids[slot]));
    await expect(page.locator(`[name="match_team1_p${slot}"]`)).toHaveValue(String(teamB.player_ids[slot]));
    await expect(page.locator(`[name="match_team2_p${slot}"]`)).toHaveValue(String(teamA.player_ids[slot]));
  }
  await saveScreenshot(page, testInfo, 'mixed-swap-before-save');

  await saveAndReopen(page, fixture.match_id);
  await expect(page.locator('input[name="side1_type"][value="players"]')).toBeChecked();
  await expect(page.locator('input[name="side2_type"][value="team"]')).toBeChecked();
  await expect(page.locator('#side2_select')).toHaveValue(String(teamA.id));
  await showRosterTab(page);
  for (let slot = 0; slot < 5; slot += 1) {
    await expect(page.locator(`[name="side1_p${slot}"]`)).toHaveValue(String(teamB.player_ids[slot]));
    await expect(page.locator(`[name="match_team1_p${slot}"]`)).toHaveValue(String(teamB.player_ids[slot]));
    await expect(page.locator(`[name="match_team2_p${slot}"]`)).toHaveValue(String(teamA.player_ids[slot]));
  }
  await saveScreenshot(page, testInfo, 'mixed-swap-after-reopen');
});
