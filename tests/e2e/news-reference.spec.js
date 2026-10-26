const { test, expect } = require('playwright/test');
const path = require('node:path');
const fs = require('node:fs');

test.beforeEach(async ({ page }, testInfo) => {
  await page.setViewportSize({ width: testInfo.project.name === 'mobile' ? 390 : 1280, height: 900 });
  await page.addInitScript(() => localStorage.setItem('siteLang', 'zh'));
  await page.request.get('/__e2e__/admin-session');
});

async function openEditor(page) {
  await page.goto('/admin/news/add');
  await expect(page.locator('#referenceToggle')).toBeVisible();
  await expect.poll(() => page.locator('#newsForm').evaluate(form => !!form._adminState)).toBe(true);
}

async function insertReference(page, url) {
  await page.locator('#referenceToggle').click();
  await page.locator('#referenceUrl').fill(url);
  await page.locator('#referenceResolve').click();
  await expect(page.locator('#referenceInsert')).toBeEnabled();
  await page.locator('#referenceInsert').click();
  await expect(page.locator('#referenceControls')).toBeHidden();
}

async function saveAndReopen(page, title) {
  await page.locator('#newsForm button[type="submit"]').click();
  await expect(page).toHaveURL(/\/admin\/news$/);
  await page.getByRole('link', { name: title, exact: true }).click();
  await expect(page.locator('input[name="title"]')).toHaveValue(title);
}

async function screenshot(page, testInfo, name) {
  const folder = path.resolve('output/playwright/news-reference-codex');
  fs.mkdirSync(folder, { recursive: true });
  await page.screenshot({ path: path.join(folder, `${name}-${testInfo.project.name}.png`), fullPage: true });
}

async function expectFits(page) {
  const widths = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(widths.page).toBeLessThanOrEqual(widths.viewport);
}

test('news reference inserts without erasing text, survives undo and repeated editing', async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const fixture = await (await page.request.get('/__e2e__/public-backend-fixture')).json();
  const title = `Reference roundtrip ${testInfo.project.name} ${Date.now()}`;
  await openEditor(page);
  await page.locator('input[name="title"]').fill(title);
  const editor = page.locator('#editor .ql-editor');
  await editor.fill('Before the reference.\nAfter the reference.');
  await editor.press('Control+Home');
  await editor.press('End');
  await insertReference(page, `https://80gotv.cn/events/${fixture.event_id}`);
  await expect(editor.locator('.news-reference')).toHaveCount(1);
  await expect(editor.locator('.news-reference a')).toHaveAttribute('href', `/events/${fixture.event_id}`);
  await expect(editor).toContainText('Before the reference.');
  await expect(editor).toContainText('After the reference.');
  await editor.press('Control+z');
  await expect(editor.locator('.news-reference')).toHaveCount(0);
  await expect(editor).toContainText('Before the reference.');
  await editor.press('Control+Shift+z');
  await expect(editor.locator('.news-reference')).toHaveCount(1);
  await saveAndReopen(page, title);
  const firstParagraphs = await editor.locator('p').allTextContents();
  await expect(editor.locator('.news-reference-title')).toHaveText('E2E Dot Cup');
  await saveAndReopen(page, title);
  expect(await editor.locator('p').allTextContents()).toEqual(firstParagraphs);
  await expect(editor.locator('.news-reference')).toHaveCount(1);
  await expectFits(page);
  await screenshot(page, testInfo, 'reference-reopened');
  const href = await page.getByRole('link', { name: '前台查看', exact: true }).getAttribute('href');
  await page.goto(href);
  await expect(page.locator('.news-content .news-reference-title')).toHaveText('E2E Dot Cup');
  await expect(page.locator('.news-content')).toContainText('Before the reference.');
  await expect(page.locator('.news-content')).toContainText('After the reference.');
  await expectFits(page);
  await screenshot(page, testInfo, 'reference-public');
  expect(errors).toEqual([]);
});

test('reference lookup errors cannot insert stale or external links or erase the article', async ({ page }) => {
  const fixture = await (await page.request.get('/__e2e__/public-backend-fixture')).json();
  await openEditor(page);
  await page.locator('#editor .ql-editor').fill('Keep this article.');
  await page.locator('#referenceToggle').click();
  await page.locator('#referenceUrl').fill(`/events/${fixture.event_id}`);
  await page.locator('#referenceResolve').click();
  await expect(page.locator('#referenceInsert')).toBeEnabled();
  await page.locator('#referenceUrl').fill('https://example.com/private');
  await expect(page.locator('#referenceInsert')).toBeDisabled();
  await page.locator('#referenceResolve').click();
  // 读取失败的原因在右上角红色提示里；链接本身不对时链接框标红
  const referenceError = page.locator('.site-toast[data-toast-key="news-reference"] .site-toast-msg');
  await expect(referenceError).toContainText('不能引用外部网站');
  await expect(page.locator('#referenceUrl')).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#referencePreview')).toBeHidden();
  await page.locator('#referenceUrl').fill('/admin/news');
  await page.locator('#referenceUrl').press('Enter');
  await expect(referenceError).toContainText('不是可引用');
  await page.route('**/admin/news/reference', route => route.fulfill({ status: 502, contentType: 'text/html', body: '<p>unavailable</p>' }));
  await page.locator('#referenceUrl').fill('/news');
  await page.locator('#referenceResolve').click();
  await expect(referenceError).toHaveText('页面读取失败，请稍后重试');
  await expect(page.locator('#referenceResolve')).toBeEnabled();
  await expect(page.locator('#editor .ql-editor')).toHaveText('Keep this article.');
  await expect(page.locator('#editor .news-reference')).toHaveCount(0);
  await expect(page).toHaveURL(/\/admin\/news\/add$/);
});

test('reference-only article restores from a draft and saves without losing the block', async ({ page }, testInfo) => {
  const title = `Reference draft ${testInfo.project.name} ${Date.now()}`;
  await openEditor(page);
  await page.locator('input[name="title"]').fill(title);
  await insertReference(page, '/news');
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).some(key => key.startsWith('80gotv:admin-draft:')))).toBe(true);
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(page.locator('input[name="title"]')).toHaveValue('');
  await page.getByRole('button', { name: '恢复草稿', exact: true }).click();
  await expect(page.locator('input[name="title"]')).toHaveValue(title);
  await expect(page.locator('#editor .news-reference')).toHaveCount(1);
  await expect(page.locator('#contentTextarea')).not.toHaveValue('');
  await saveAndReopen(page, title);
  await expect(page.locator('#editor .news-reference')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '恢复草稿', exact: true })).toHaveCount(0);
});

test('reference and ordinary rich text remain intact in English and dark mode', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('siteLang', 'en');
    localStorage.setItem('theme', 'dark');
  });
  const title = `Rich reference ${testInfo.project.name} ${Date.now()}`;
  await openEditor(page);
  const csrf = await page.locator('input[name="csrf_token"]').inputValue();
  const content = '<p><strong>保留作者原文</strong> <a href="/teams">Ordinary link</a></p>'
    + '<img src="/static/favicon.ico" alt="Fixture image">'
    + '<div class="news-reference"><a href="/news"><span class="news-reference-type">页面</span>'
    + '<strong class="news-reference-title">新闻</strong></a></div>';
  const saved = await page.request.post('/admin/news/add', { form: { csrf_token: csrf, title, content }, maxRedirects: 0 });
  expect(saved.status()).toBe(302);
  await page.goto('/admin/news');
  await page.getByRole('link', { name: title, exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('#newsForm')).not.toHaveClass(/is-dirty/);
  await expect(page.locator('#referenceToggle')).toHaveText('Reference a site page');
  await expect(page.locator('#editor .news-reference-type')).toHaveText('Page');
  await expect(page.locator('#editor .ql-editor strong').first()).toHaveText('保留作者原文');
  await expect(page.locator('#editor .ql-editor a[href="/teams"]')).toHaveText('Ordinary link');
  await expect(page.locator('#editor .ql-editor img')).toHaveAttribute('src', '/static/favicon.ico');
  await saveAndReopen(page, title);
  await expect(page.locator('#editor .news-reference')).toHaveCount(1);
  await expectFits(page);
  await screenshot(page, testInfo, 'reference-english-dark');
  const href = await page.locator('.page-actions a').getAttribute('href');
  await page.goto(href);
  await expect(page.locator('.news-content .news-reference-type')).toHaveText('Page');
  await expect(page.locator('.news-content')).toContainText('保留作者原文');
  await expect(page.locator('.news-content a[href="/teams"]')).toHaveText('Ordinary link');
  await expect(page.locator('.news-content img')).toHaveAttribute('src', '/static/favicon.ico');
  await expectFits(page);
  await screenshot(page, testInfo, 'reference-public-english-dark');
});
