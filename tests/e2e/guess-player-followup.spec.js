const { test, expect } = require('playwright/test');

test.beforeEach(async ({ page }) => {
  await page.request.get('/__e2e__/user-session');
  await page.goto('/guess-player/practice');
  const reset = page.locator('.guess-new-round-form button');
  if (await reset.count()) await reset.click();
});

test('昵称匹配排在真实姓名前，支持键盘和鼠标选中', async ({ page }) => {
  const input = page.locator('#guessPlayerQuery');
  await input.fill('Nik');
  const candidates = page.locator('#guessPlayerSuggestions [role="option"]');
  await expect(candidates.first().locator('strong')).toHaveText('NiKo');
  const names = await candidates.locator('strong').allTextContents();
  const firstRealNameOnly = names.findIndex(name => !name.toLowerCase().includes('nik'));
  if (firstRealNameOnly >= 0) expect(names.slice(firstRealNameOnly).every(name => !name.toLowerCase().includes('nik'))).toBeTruthy();
  await input.press('ArrowDown');
  await input.press('Enter');
  await expect(input).toHaveValue('NiKo');
  await expect(page.locator('#guessPlayerSuggestions')).toBeHidden();
  expect(await page.locator('#guessPlayerId').inputValue()).not.toBe('');
  await input.fill('Mathieu');
  await expect(candidates.first().locator('strong')).toHaveText('ZywOo');
  await candidates.first().click();
  await expect(input).toHaveValue('ZywOo');
  await input.fill('no-player-matches-this-query');
  await expect(page.locator('#guessPlayerId')).toHaveValue('');
  await expect(page.locator('#guessPlayerSuggestions')).toBeHidden();
});

test('国籍输出真正的国旗 emoji 并加载本地彩色字体', async ({ page }) => {
  await page.locator('#guessPlayerQuery').fill('NiKo');
  await page.locator('#guessPlayerSuggestions [role="option"]').first().click();
  await page.locator('#guessPlayerForm [type="submit"]').click();
  const flag = page.locator('.guess-country-flag').first();
  await expect(flag).toHaveText('\u{1F1E7}\u{1F1E6}');
  await expect(flag).toHaveAttribute('aria-label', 'Bosnia and Herzegovina');
  const font = await flag.evaluate(async element => {
    await document.fonts.load('22px "Twemoji Country Flags"', element.textContent);
    return {
      loaded: document.fonts.check('22px "Twemoji Country Flags"', element.textContent),
      family: getComputedStyle(element).fontFamily,
      width: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    };
  });
  expect(font.loaded).toBeTruthy();
  expect(font.family).toContain('Twemoji Country Flags');
  expect(font.width).toBeLessThanOrEqual(font.viewport);
});
