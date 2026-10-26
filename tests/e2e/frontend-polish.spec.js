// 2026-10-26 前端打磨：标题行不挤压、可滑动标签条提示、新闻详情英文、日期标题、表单状态与“返回”后的未保存提醒。
const { test, expect } = require('playwright/test');

// 只在还没选过语言时写入；测试中途改语言（localStorage）后，后面打开的页面保持新语言
async function useLanguage(page, language) {
  await page.addInitScript(value => {
    if (!localStorage.getItem('siteLang')) localStorage.setItem('siteLang', value);
  }, language);
}

test('手机上面板标题不会被右边内容挤成一字一行', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile');
  await useLanguage(page, 'zh');
  const fixture = await (await page.request.get('/__e2e__/live-fixture')).json();
  await page.goto(`/matches/${fixture.match_id}`);
  const titles = await page.locator('.panel-head > .panel-title').evaluateAll(nodes => nodes
    .filter(node => node.getClientRects().length)
    .map(node => {
      const style = getComputedStyle(node);
      const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.3;
      return { text: node.textContent.trim(), lines: Math.round(node.getBoundingClientRect().height / lineHeight) };
    }));
  expect(titles.length).toBeGreaterThan(0);
  for (const title of titles) expect(title.lines, title.text).toBeLessThanOrEqual(1);
});

test('手机上可左右滑的标签条有提示，选中的那一项会露出来', async ({ page }, testInfo) => {
  await useLanguage(page, 'zh');
  await page.goto('/forum');
  const strip = page.locator('.forum-tabs');
  if (testInfo.project.name !== 'mobile') {
    await expect(strip).not.toHaveClass(/has-more-(start|end)/);
    return;
  }
  await expect(strip).toHaveClass(/has-more-end/);
  const lastHref = await strip.locator('a').last().getAttribute('href');
  await page.goto(lastHref);
  await expect(strip).toHaveClass(/has-more-start/);
  const visible = await strip.evaluate(node => {
    const active = node.querySelector('.active, [aria-current="page"]');
    const box = node.getBoundingClientRect();
    const item = active.getBoundingClientRect();
    return item.left >= box.left - 1 && item.right <= box.right + 1;
  });
  expect(visible).toBeTruthy();
});

test('新闻详情英文：界面文字和日期翻译，标题、作者、正文保持原文', async ({ page }) => {
  await useLanguage(page, 'zh');
  await page.request.get('/__e2e__/admin-session');
  const title = `前端打磨英文检查 ${Date.now().toString(36)}`;
  await page.goto('/admin/news/add');
  await expect.poll(() => page.locator('#newsForm').evaluate(form => !!form._adminState)).toBe(true);
  await page.locator('input[name="title"]').fill(title);
  await page.locator('.ql-editor').click();
  await page.keyboard.type('正文保持中文原文。');
  await page.locator('#referenceToggle').click();
  await page.locator('#referenceUrl').fill('/stats');
  await page.locator('#referenceResolve').click();
  await expect(page.locator('#referenceInsert')).toBeEnabled();
  await page.locator('#referenceInsert').click();
  await page.locator('input[name="author"]').evaluate(input => { input.closest('details').open = true; });
  await page.locator('input[name="author"]').fill('赛事组小编');
  await page.locator('#newsForm button[type="submit"]').click();
  await expect(page).toHaveURL(/\/admin\/news$/);
  const href = await page.getByRole('link', { name: title, exact: true }).evaluate(link =>
    link.closest('tr').querySelector('a[target="_blank"]').getAttribute('href'));

  await page.evaluate(() => localStorage.setItem('siteLang', 'en'));
  await page.goto(href);
  await expect(page.locator('.news-detail-title')).toHaveText(title);
  await expect(page.locator('.news-detail-meta')).toContainText('赛事组小编');
  await expect(page.locator('.news-detail-meta')).toContainText('Comments');
  await expect(page.locator('.news-detail-meta')).not.toContainText('评论');
  await expect(page.locator('.news-detail-meta')).not.toContainText('年');
  await expect(page.locator('.news-content')).toContainText('正文保持中文原文。');
  await expect(page.locator('.news-content .news-reference-type')).toHaveText('Stats');
  await expect(page.locator('.back-link')).toHaveText('Back to news');

  await page.evaluate(() => localStorage.setItem('siteLang', 'zh'));
  await page.goto(href);
  await expect(page.locator('.news-detail-meta')).toContainText('评论');
  await expect(page.locator('.news-content .news-reference-type')).toHaveText('数据');
});

test('赛事日历月份和比赛筛选里的日期随语言显示', async ({ page }) => {
  await useLanguage(page, 'en');
  await page.goto('/events');
  const months = await page.locator('.events-month-title').allTextContents();
  expect(months.length).toBeGreaterThan(0);
  for (const month of months) expect(month.trim()).toMatch(/^([A-Z][a-z]+ \d{4}|Unknown)$/);
  await page.goto('/matches');
  for (const date of await page.locator('.match-side-filter .match-filter-date').allTextContents()) {
    expect(date).not.toMatch(/[年月日]/);
  }

  await page.evaluate(() => localStorage.setItem('siteLang', 'zh'));
  await page.goto('/events');
  for (const month of await page.locator('.events-month-title').allTextContents()) {
    expect(month.trim()).toMatch(/^(\d{4}年\d{1,2}月|未知)$/);
  }
});

test('后台表单分组状态在选择后立即刷新', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await useLanguage(page, 'zh');
  await page.request.get('/__e2e__/admin-session');
  await page.goto('/admin/players/add');
  await expect.poll(() => page.locator('#playerForm').evaluate(form => !!form._adminState)).toBe(true);
  const status = page.locator('.form-group:has(input[name="nickname"]) [data-group-status]');
  await page.locator('input[name="is_bashizhong_student"][value="1"]').check();
  expect(await status.textContent()).toContain('还差');
  await page.locator('input[name="is_bashizhong_student"][value="0"]').check();
  await page.locator('input[name="nickname"]').fill('Polish Status Player');
  // 不等待，立即读取：状态要跟着输入马上变
  expect(await status.evaluate(node => node.textContent)).toBe('必填已完成');
});

test('浏览器返回时填回的未保存内容仍会提醒和清理', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await useLanguage(page, 'zh');
  await page.request.get('/__e2e__/admin-session');
  page.on('dialog', dialog => dialog.accept());
  await page.goto('/admin/teams/add');
  await expect.poll(() => page.locator('#teamForm').evaluate(form => !!form._adminState)).toBe(true);
  const name = `Polish Back ${Date.now().toString(36)}`;
  await page.locator('#teamForm input[name="name"]').fill(name);
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage)
    .some(key => key.startsWith('80gotv:admin-draft:v1|') && key.includes('/admin/teams/add|teamForm')))).toBe(true);
  await page.locator('.admin-sidenav a[href="/admin/players"]').click();
  await expect(page).toHaveURL(/\/admin\/players$/);
  await page.goBack();
  await expect.poll(() => page.locator('#teamForm').evaluate(form => !!form._adminState)).toBe(true);
  const restoredValue = await page.locator('#teamForm input[name="name"]').inputValue();
  if (restoredValue !== name) {
    // 浏览器没有替用户填回：这时必须提供“恢复草稿”
    await expect(page.locator('#teamForm .form-notice-draft')).toHaveCount(1);
    await page.locator('#teamForm .form-notice-draft button', { hasText: '恢复草稿' }).click();
    await expect(page.locator('#teamForm input[name="name"]')).toHaveValue(name);
  }
  expect(await page.locator('#teamForm').evaluate(form => form._adminState.check())).toBe(true);
  await page.locator('#teamForm a[data-discard]').click();
  await expect(page.locator('.site-modal-overlay')).toHaveCount(1);
  await page.locator('.site-modal-overlay .site-modal-ok').click();
  await expect(page).toHaveURL(/\/admin\/teams$/);
  const left = await page.evaluate(() => Object.keys(localStorage)
    .filter(key => key.startsWith('80gotv:admin-draft:v1|') && key.includes('/admin/teams/add|teamForm')));
  expect(left).toEqual([]);
});

test('浏览器自带的填写气泡换成右上角同一套提示：标红、定位、改好自动收起', async ({ page }, testInfo) => {
  await useLanguage(page, 'zh');
  await page.goto('/login');
  await page.locator('form[action="/login"] button[type="submit"]').click();
  const toast = page.locator('.site-toast.toast-error');
  await expect(toast.locator('[role="alert"]')).toContainText('2 处需要填写或修改');
  await expect(toast.locator('.site-toast-action')).toHaveText(['请填写用户名', '请填写密码']);
  await expect(page.locator('#loginUsername')).toBeFocused();
  await expect(page.locator('#loginUsername')).toHaveAttribute('aria-invalid', 'true');
  const box = await toast.boundingBox();
  const width = page.viewportSize().width;
  expect(box.x + box.width).toBeLessThanOrEqual(width);
  expect(box.x).toBeGreaterThanOrEqual(testInfo.project.name === 'mobile' ? 0 : width / 2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  await page.locator('#loginUsername').fill('polish-toast-user');
  await page.locator('#loginPassword').fill('fixture-only-password');
  await expect(toast).toHaveCount(0);
  await expect(page.locator('[aria-invalid="true"]')).toHaveCount(0);
});

test('错误提示不会自己消失，成功提示过几秒收起，都能手动关', async ({ page }) => {
  await useLanguage(page, 'zh');
  await page.clock.install();
  await page.goto('/matches');
  await page.evaluate(() => { window.showToast('保存失败，请重试', 'error'); window.showToast('已保存', 'success'); });
  await expect(page.locator('.site-toast')).toHaveCount(2);
  await page.clock.runFor(10000);
  await expect(page.locator('.site-toast.toast-success')).toHaveCount(0);
  await expect(page.locator('.site-toast.toast-error')).toBeVisible();
  await page.locator('.site-toast.toast-error .site-toast-close').click();
  await page.clock.runFor(1000);
  await expect(page.locator('.site-toast')).toHaveCount(0);
});

test('后台右上角提示避开标题行右边的按钮，标题行没有按钮时贴着顶栏', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await useLanguage(page, 'zh');
  await page.request.get('/__e2e__/admin-session');
  await page.goto('/admin/teams');
  await page.evaluate(() => window.showToast('检查提示位置', 'success'));
  const toast = await page.locator('.site-toast').first().boundingBox();
  for (const action of await page.locator('.page-head a, .page-head button').all()) {
    const box = await action.boundingBox();
    if (!box) continue;
    const overlap = toast.x < box.x + box.width && box.x < toast.x + toast.width
      && toast.y < box.y + box.height && box.y < toast.y + toast.height;
    expect(overlap).toBeFalsy();
  }
  await page.goto('/admin/teams/add');
  await page.evaluate(() => window.showToast('检查提示位置', 'success'));
  const header = await page.locator('.admin-topbar').boundingBox();
  expect((await page.locator('.site-toast').first().boundingBox()).y).toBeLessThan(header.y + header.height + 24);
});
