const { test, expect } = require('playwright/test');
const path = require('node:path');

test.beforeEach(async ({ page }, testInfo) => {
  await page.setViewportSize({
    width: testInfo.project.name === 'mobile' ? 390 : 1280,
    height: 900,
  });
  const language = testInfo.title.includes('英文初始化') ? 'en' : 'zh';
  await page.addInitScript(value => localStorage.setItem('siteLang', value), language);
  await page.request.get('/__e2e__/admin-session');
});

async function screenshot(page, testInfo, name) {
  await page.screenshot({
    path: path.resolve('output/ui-audit/codex-form-guard', `${name}-${testInfo.project.name}-viewport.png`),
    fullPage: false,
  });
}

async function openForm(page, url, selector) {
  await page.goto(url);
  await expect.poll(() => page.locator(selector).evaluate(form => Boolean(form._adminState))).toBe(true);
}

test('服务器拒绝后保留输入并继续提醒未保存', async ({ page }, testInfo) => {
  await openForm(page, '/admin/teams/add', '#teamForm');
  await page.locator('#teamForm input[name="name"]').fill('E2E Dot Alpha');
  await page.locator('#teamForm input[name="short_name"]').fill('E2E_GUARD_REJECT');

  const rejected = page.waitForResponse(response =>
    response.url().endsWith('/admin/teams/add') && response.request().method() === 'POST' && response.status() === 400
  );
  await page.getByRole('button', { name: '添加队伍' }).click();
  await rejected;

  await expect(page.locator('#teamForm input[name="name"]')).toHaveValue('E2E Dot Alpha');
  await expect(page.locator('#teamForm input[name="short_name"]')).toHaveValue('E2E_GUARD_REJECT');
  // 服务器的原因是右上角红色提示（读屏 role=alert）；“已放回表单、尚未提交”是紧跟着的黄色提示
  await expect(page.locator('.admin-flashes .alert-error [role="alert"]')).toBeVisible();
  await expect(page.locator('.site-toast.toast-warning')).toContainText('服务器没有保存');
  await expect(page.locator('#teamForm')).toHaveClass(/is-dirty/);
  expect(await page.locator('#teamForm').evaluate(form => form._adminState.dirty)).toBe(true);
  await screenshot(page, testInfo, 'rejected-form-kept');
});

test('折叠组里的格式错误会展开并定位到字段', async ({ page }, testInfo) => {
  await openForm(page, '/admin/events/add', '#eventForm');
  await page.locator('#eventForm input[name="name"]').fill('E2E Form Guard Event');
  await page.locator('#eventForm input[name="short_name"]').fill('E2E_GUARD');
  await page.locator('#eventForm input[name="start_date"]').fill('2027-11-17T10:00');
  await page.locator('#eventForm input[name="end_date"]').fill('2027-11-18T20:00');
  const details = page.locator('#eventForm details.form-group.optional');
  await details.locator('summary').click();
  await page.locator('#eventForm input[name="slug"]').fill('invalid slug');
  await details.locator('summary').click();

  let posted = false;
  page.on('request', request => {
    if (request.url().endsWith('/admin/events/add') && request.method() === 'POST') posted = true;
  });
  await page.getByRole('button', { name: '添加赛事' }).click();

  await expect(page.locator('#eventForm details.form-group.optional')).toHaveAttribute('open', '');
  await expect(page.locator('#eventForm input[name="slug"]')).toBeFocused();
  await expect(page.locator('#eventForm input[name="slug"]')).toHaveAttribute('aria-invalid', 'true');
  // 右上角红色提示写明这一处的问题（和字段下方的说明一致）
  const summary = page.locator('.site-toast.toast-error [role="alert"]');
  await expect(summary).toBeVisible();
  await expect(summary).toContainText(await page.locator('#eventForm .field-error').first().innerText());
  expect(posted).toBe(false);
  await screenshot(page, testInfo, 'collapsed-field-error');
});

test('网站账号密码不会进入自动草稿', async ({ page }) => {
  await openForm(page, '/admin/players/add', '#playerForm');
  await page.locator('#playerForm input[name="nickname"]').fill('E2E Draft Password Check');
  await page.locator('#playerForm input[name="password"]').fill('fixture-only-password-123');
  await page.locator('#playerForm input[name="password2"]').fill('fixture-only-password-123');

  await expect.poll(() => page.evaluate(() => {
    const key = Object.keys(localStorage).find(name => name.startsWith('80gotv:admin-draft:v1|') && name.includes('/admin/players/add|'));
    return key ? localStorage.getItem(key) : null;
  })).not.toBeNull();
  const draft = await page.evaluate(() => {
    const key = Object.keys(localStorage).find(name => name.startsWith('80gotv:admin-draft:v1|') && name.includes('/admin/players/add|'));
    return key ? localStorage.getItem(key) : '';
  });
  expect(draft).toContain('E2E Draft Password Check');
  expect(draft).not.toContain('fixture-only-password-123');
  expect(draft).not.toContain('password2');
  const fields = JSON.parse(draft).fields;
  expect(fields.password).toBeUndefined();
  expect(fields.csrf_token).toBeUndefined();
});

test('手动恢复草稿只回填字段，不会代为提交', async ({ page }) => {
  await openForm(page, '/admin/players/add', '#playerForm');
  await page.locator('#playerForm input[name="nickname"]').fill('E2E Restore Without Submit');
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).some(key =>
    key.startsWith('80gotv:admin-draft:v1|') && key.includes('/admin/players/add|playerForm')
  ))).toBe(true);

  let posted = false;
  page.on('request', request => {
    if (request.url().endsWith('/admin/players/add') && request.method() === 'POST') posted = true;
  });
  await page.reload();
  await expect(page.locator('#playerForm .form-notice-draft')).toBeVisible();
  await page.getByRole('button', { name: '恢复草稿' }).click();
  await expect(page.locator('#playerForm input[name="nickname"]')).toHaveValue('E2E Restore Without Submit');
  expect(await page.locator('#playerForm').evaluate(form => form._adminState.submitting)).toBe(false);
  expect(posted).toBe(false);
});

test('英文初始化后编辑器文字已翻译且草稿保持干净', async ({ page }) => {
  await openForm(page, '/admin/news/add', '#newsForm');
  const editor = page.locator('#editor .ql-editor');
  await expect(editor).toBeVisible();
  await expect(editor).toHaveAttribute('data-placeholder', 'News body...');
  await expect.poll(() => page.locator('#newsForm').evaluate(form => form._adminState.check())).toBe(false);
  await expect(page.locator('#newsForm')).not.toHaveClass(/is-dirty/);
});

test('浏览器返回后表单恢复可操作状态', async ({ page }) => {
  await openForm(page, '/admin/teams/add', '#teamForm');
  await page.locator('#teamForm input[name="name"]').fill('E2E Back Navigation Draft');
  await page.locator('#teamForm input[name="short_name"]').fill('E2E_BACK');
  await page.evaluate(() => { window.adminConfirm = undefined; });
  const dialogs = [];
  page.on('dialog', async dialog => {
    dialogs.push(dialog.message());
    if (dialogs.length === 1) await dialog.dismiss();
    else await dialog.accept();
  });

  await page.getByRole('link', { name: '取消' }).click();
  await expect(page).toHaveURL(/\/admin\/teams\/add$/);
  await expect(page.locator('#teamForm input[name="name"]')).toHaveValue('E2E Back Navigation Draft');
  await page.getByRole('link', { name: '取消' }).click();
  await expect(page).toHaveURL(/\/admin\/teams$/);
  expect(dialogs).toEqual(['放弃未保存的修改吗？', '放弃未保存的修改吗？']);
  await page.goBack();
  await expect(page.locator('#teamForm')).toBeVisible();
  await expect.poll(() => page.locator('#teamForm').evaluate(form => Boolean(form._adminState))).toBe(true);
  await expect(page.locator('#teamForm button[type="submit"]')).toBeEnabled();
  await page.evaluate(() => {
    const form = document.querySelector('#teamForm');
    form._adminState.submitting = true;
    window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
  });

  await expect.poll(() => page.locator('#teamForm').evaluate(form => form._adminState.submitting)).toBe(false);
});

test('保存成功后清除这张表单的草稿', async ({ page }) => {
  await openForm(page, '/admin/teams/add', '#teamForm');
  const suffix = Date.now().toString(36).toUpperCase();
  await page.locator('#teamForm input[name="name"]').fill('E2E Guard Success ' + suffix);
  await page.locator('#teamForm input[name="short_name"]').fill('OK_' + suffix);
  await page.getByRole('button', { name: '添加队伍' }).click();
  await expect(page).toHaveURL(/\/admin\/teams$/);
  await expect(page.locator('.admin-flashes .alert-success')).toContainText('队伍添加成功');
  const draftKeys = await page.evaluate(() => Object.keys(localStorage).filter(key =>
    key.startsWith('80gotv:admin-draft:v1|') && key.includes('/admin/teams/add|teamForm')
  ));
  expect(draftKeys).toEqual([]);
});

test('比赛连接字符串与 BP 口令不会进入自动草稿', async ({ page }) => {
  const fixture = await (await page.request.get('/__e2e__/review-fixture?test_match=1')).json();
  await openForm(page, `/admin/matches/edit/${fixture.test_match_id}`, '#matchForm');
  await page.locator('.match-tab[data-tab="broadcast"]').click();

  const fakeServerAddress = 'password demo-only;connect 127.0.0.1:27015';
  const fakeBpPassword = 'demo-only-bp-secret';
  await page.locator('#matchForm input[name="server_address"]').fill(fakeServerAddress);
  await page.locator('#matchForm input[name="bp_password"]').fill(fakeBpPassword);

  await expect.poll(() => page.locator('#matchForm').evaluate(form =>
    Boolean(localStorage.getItem(form._adminState.key))
  )).toBe(true);
  const leakFlags = await page.locator('#matchForm').evaluate((form, probes) => {
    const serialized = localStorage.getItem(form._adminState.key) || '';
    const fields = (JSON.parse(serialized || '{}').fields || {});
    return {
      serverAddressLeaked: Object.prototype.hasOwnProperty.call(fields, 'server_address') || serialized.includes(probes.serverAddress),
      bpPasswordLeaked: Object.prototype.hasOwnProperty.call(fields, 'bp_password') || serialized.includes(probes.bpPassword),
    };
  }, { serverAddress: fakeServerAddress, bpPassword: fakeBpPassword });
  expect(leakFlags).toEqual({ serverAddressLeaked: false, bpPasswordLeaked: false });
});

test('比赛统计草稿身份随地图名稳定，不随表单序号串图', async ({ page }) => {
  const fixture = await (await page.request.get('/__e2e__/review-fixture?test_match=1')).json();
  const editUrl = `/admin/matches/edit/${fixture.test_match_id}`;
  const statsUrl = `/admin/matches/${fixture.test_match_id}/stats`;

  async function setMaps(first, second) {
    await openForm(page, editUrl, '#matchForm');
    await page.locator('.match-tab[data-tab="maps"]').click();
    await page.locator('#matchForm select[name="bo_format"]').selectOption('BO3');
    await page.locator('#matchForm select[name="map1"]').selectOption(first);
    await page.locator('#matchForm select[name="map2"]').selectOption(second);
    await page.locator('#submitBtn').click();
    await expect(page).toHaveURL(/\/admin\/matches(?:\?.*)?$/);
    await page.goto(statsUrl);
    await expect(page.locator('.match-stats-form[data-draft]')).toHaveCount(2);
  }

  const keysByMap = async () => page.locator('.match-stats-form[data-draft]').evaluateAll(forms =>
    forms.map(form => ({
      id: form.id,
      map: form.elements.namedItem('map_name').value,
      context: form.getAttribute('data-draft-context'),
      key: window.adminForms.draftKey(form),
    }))
  );

  await setMaps('de_mirage', 'de_nuke');
  const firstOrder = await keysByMap();
  const mirageKey = firstOrder.find(item => item.map === 'de_mirage').key;
  const nukeKey = firstOrder.find(item => item.map === 'de_nuke').key;
  expect(mirageKey).not.toBe(nukeKey);

  await setMaps('de_nuke', 'de_mirage');
  const reversedOrder = await keysByMap();
  expect(reversedOrder.find(item => item.map === 'de_mirage').key).toBe(mirageKey);
  expect(reversedOrder.find(item => item.map === 'de_nuke').key).toBe(nukeKey);
  expect(reversedOrder.find(item => item.id === 'statsForm-0').map).toBe('de_nuke');
  expect(firstOrder.find(item => item.id === 'statsForm-0').map).toBe('de_mirage');
});

test('TOP10 年份已经包含在表单身份里', async ({ page }) => {
  await openForm(page, '/admin/top10?year=2026', '#top10Form-2026');
  const identity = await page.locator('#top10Form-2026').evaluate(form => ({
    id: form.id,
    key: window.adminForms.draftKey(form),
  }));
  expect(identity.id).toBe('top10Form-2026');
  expect(identity.key).toContain('|top10Form-2026');
  expect(identity.key).not.toContain('?year=');
});
