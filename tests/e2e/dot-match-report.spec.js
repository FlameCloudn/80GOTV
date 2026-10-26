const fs = require('fs');
const path = require('path');
const { test, expect } = require('playwright/test');

test('比赛战报按对阵侧汇总错配和临时统计', async ({ page }, testInfo) => {
  const fixtureResponse = await page.request.get('/__e2e__/dot-match-report-fixture');
  expect(fixtureResponse.ok()).toBeTruthy();
  const fixture = await fixtureResponse.json();

  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));
  if (testInfo.project.name === 'desktop') {
    await page.setViewportSize({ width: 1280, height: 900 });
  }
  const response = await page.goto(`/matches/${fixture.match_id}/report`);
  expect(response.ok()).toBeTruthy();
  await expect(page.locator('h1')).toHaveText('比赛战报');

  const compare = label => page.locator('.match-detailed-compare-row').filter({
    has: page.getByText(label, { exact: true }),
  });
  for (const [label, left, right] of [
    ['总击杀', '10', '20'],
    ['总死亡', '5', '10'],
    ['场均 ADR', '0.0', '-'],
    ['场均 RATING', '1.5', '1.2'],
  ]) {
    const row = compare(label);
    await expect(row).toHaveCount(1);
    await expect(row.locator('.match-detailed-compare-left')).toHaveText(left);
    await expect(row.locator('.match-detailed-compare-right')).toHaveText(right);
  }
  await expect(page.locator('.map-report-score').first()).toHaveText(/13\s*:\s*8/);
  const bestPlayers = page.locator('.map-report-best .best-player-card');
  await expect(bestPlayers).toHaveCount(2);
  const bestNames = await bestPlayers.locator('.best-player-name').allTextContents();
  expect(bestNames).toContain(`Dot ${fixture.suffix} side 1 player 1`);
  expect(bestNames).toContain(`Dot ${fixture.suffix} side 2 player 1`);
  await expect(page.locator('.map-report-best')).not.toContainText('999');
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
  ).toBeLessThanOrEqual(1);

  const screenshot = path.resolve(
    `output/ui-audit/codex-dot-match-report/match-report-${testInfo.project.name}.png`,
  );
  fs.mkdirSync(path.dirname(screenshot), { recursive: true });
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach('比赛战报截图', { path: screenshot, contentType: 'image/png' });
});
