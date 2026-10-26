const { test, expect } = require('playwright/test');
const path = require('node:path');
const fs = require('node:fs');

for (const blockDraftStorage of [false, true]) {
  test(`统计保存失败保留数字和当前地图，修正后可以继续保存（${blockDraftStorage ? '禁用草稿存储' : '正常草稿'}）`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: testInfo.project.name === 'mobile' ? 390 : 1280, height: 900 });
    await page.addInitScript(block => {
      localStorage.setItem('siteLang', 'zh');
      if (!block) return;
      const setItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (key === '__t' || key.startsWith('80gotv:admin-')) {
          throw new DOMException('Draft storage disabled for this test', 'SecurityError');
        }
        return setItem.call(this, key, value);
      };
    }, blockDraftStorage);
    await page.request.get('/__e2e__/admin-session');
    const fixture = await (await page.request.get('/__e2e__/dot-stats-fixture')).json();
    const statsUrl = `/admin/matches/${fixture.match_id}/stats`;
    await page.goto(statsUrl);
    const form = page.locator('#tab-1 form.match-stats-form');
    await expect.poll(() => form.evaluate(element => Boolean(element._adminState))).toBe(true);
    await page.locator('.stats-map-tabs .tab-btn').nth(1).click();
    await expect(form).toBeVisible();

    if (blockDraftStorage) {
      expect(await form.evaluate(element => {
        window.adminForms.writeDraft(element._adminState.key, element);
        return { draft: window.adminForms.readDraft(element._adminState.key), session: window.adminForms.session };
      })).toEqual({ draft: null, session: null });
    }
    const values = { kills: '21', deaths: '17', assists: '6', adr: '92.4', impact: '1.37', kast: '83.3', hs: '61.5' };
    for (const team of fixture.teams) {
      for (const [field, value] of Object.entries(values)) {
        await form.locator(`[name="${field}_${team.player_ids[0]}"]`).fill(value);
      }
    }
    const rejection = page.waitForResponse(response =>
      response.url().endsWith(statsUrl) && response.request().method() === 'POST' && response.status() === 400
    );
    await form.getByRole('button', { name: '保存此图数据' }).click();
    await rejection;
    await expect(page.locator('.admin-flashes .alert-error')).toContainText('该地图比分尚未确认');
    await expect(form).toBeVisible();
    await expect(form).toHaveAttribute('data-server-rejected', '');
    await expect(form).toHaveClass(/is-dirty/);
    await expect.poll(() => form.evaluate(element => element._adminState.dirty)).toBe(true);
    for (const team of fixture.teams) {
      for (const [field, value] of Object.entries(values)) {
        await expect(form.locator(`[name="${field}_${team.player_ids[0]}"]`)).toHaveValue(value);
      }
      await expect(form.locator(`[name="rating_${team.player_ids[0]}"]`)).toHaveValue('1.2');
      await expect(page.locator(`#tab-0 [name="kills_${team.player_ids[0]}"]`)).toHaveValue('10');
    }
    const draftKey = await form.evaluate(element => element._adminState.key);
    const folder = path.resolve('output/ui-audit/dot-stats-20261026');
    fs.mkdirSync(folder, { recursive: true });
    const variant = `${blockDraftStorage ? 'blocked' : 'normal'}-${testInfo.project.name}`;
    await page.screenshot({ path: path.join(folder, `stats-rejected-${variant}.png`), fullPage: true });

    let leavePrompt = false;
    page.once('dialog', async dialog => {
      leavePrompt = dialog.type() === 'beforeunload';
      await dialog.dismiss();
    });
    await form.getByRole('link', { name: '返回', exact: true }).click();
    await expect.poll(() => leavePrompt).toBe(true);
    await expect(page).toHaveURL(new RegExp(`${statsUrl}$`));
    await expect(form.locator(`[name="kills_${fixture.teams[0].player_ids[0]}"]`)).toHaveValue('21');

    await page.request.get(`/__e2e__/dot-stats-fixture/${fixture.match_id}/confirm-score`);
    const saved = page.waitForResponse(response =>
      response.url().endsWith(statsUrl) && response.request().method() === 'POST' && response.status() === 302
    );
    await form.getByRole('button', { name: '保存此图数据' }).click();
    await saved;
    await expect(page.locator('.admin-flashes .alert-success')).toContainText('de_nuke 数据已保存');
    await page.locator('.stats-map-tabs .tab-btn').nth(1).click();
    await expect(form).toBeVisible();
    await expect(form).not.toHaveAttribute('data-server-rejected', '');
    for (const team of fixture.teams) {
      await expect(form.locator(`[name="kills_${team.player_ids[0]}"]`)).toHaveValue('21');
      await expect(form.locator(`[name="adr_${team.player_ids[0]}"]`)).toHaveValue('92.4');
    }
    await expect.poll(() => form.evaluate(element => element._adminState.check())).toBe(false);
    if (!blockDraftStorage) expect(await page.evaluate(key => localStorage.getItem(key), draftKey)).toBeNull();
    await page.screenshot({ path: path.join(folder, `stats-saved-${variant}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  });
}
