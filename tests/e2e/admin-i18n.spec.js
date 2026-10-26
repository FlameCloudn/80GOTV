const { test, expect } = require('playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('siteLang', 'en'));
  await page.request.get('/__e2e__/admin-session');
});

test('新版后台分组、筛选和动态提示完整显示英文', async ({ page }) => {
  const cases = [
    ['/admin/', '赛事运营', 'Tournament operations'],
    ['/admin/', '进行中与即将开始', 'Live and upcoming'],
    ['/admin/', '没有进行中或即将开始的比赛', 'No live or upcoming matches'],
    ['/admin/', '没有待处理的反馈', 'No feedback awaiting review'],
    ['/admin/', '还没有队伍', 'No teams yet'],
    ['/admin/', '还没有选手', 'No players yet'],
    ['/admin/', '还没有赛事', 'No events yet'],
    ['/admin/', '还没有新闻', 'No news yet'],
    ['/admin/events', '状态：全部', 'Status: All'],
    ['/admin/events/add', '基本信息', 'Basic information'],
    ['/admin/events/add', '开始时间', 'Start date and time'],
    ['/admin/matches/add', '搜索队伍名 / 赛事 / ID', 'Search teams, events or ID'],
    ['/admin/matches/add', '未指定 (位置 3)', 'Unassigned (Slot 3)'],
    ['/admin/matches/add', '确定结束这场比赛吗？', 'Mark this match as complete?'],
    ['/admin/teams/add', '队伍资料', 'Team details'],
    ['/admin/players/add', '网站登录账号', 'Website account'],
    ['/admin/news/add', '留空打开新闻正文；只能填本站地址。', 'Leave blank to open the article. Only URLs on this site are allowed.'],
    ['/admin/news/add', '3 个待审核', '3 pending reviews'],
    ['/admin/news/add', '4 条待处理', '4 pending items'],
    ['/admin/news/add', '待处理反馈 (4)', 'Feedback to review (4)'],
  ];
  let previousPath;
  for (const [url, source, translated] of cases) {
    if (previousPath !== url) {
      const response = await page.goto(url);
      expect(response.ok()).toBeTruthy();
      await expect(page.locator('html')).toHaveAttribute('lang', 'en');
      previousPath = url;
    }
    expect(await page.evaluate(value => window.siteTranslate(value), source)).toBe(translated);
  }
  await expect(page.locator('summary').filter({ hasText: 'Related pages and redirect' })).toBeVisible();
  await expect(page.locator('.form-group-title').filter({ hasText: 'Title and body' })).toBeVisible();
});

test('英文删除确认保留原始名称，取消后不会提交', async ({ page }) => {
  const posts = [];
  page.on('request', request => {
    if (request.method() === 'POST') posts.push(request.url());
  });
  await page.goto('/admin/events');
  const form = page.locator('form[data-confirm]').first();
  const source = await form.getAttribute('data-confirm');
  const eventName = source.match(/^确定删除赛事【([\s\S]*)】吗？$/)[1];
  await form.getByRole('button').click();
  await expect(page.locator('.site-modal-body')).toHaveText(`Delete event "${eventName}"?`);
  await page.locator('.site-modal-cancel').click();
  await expect(page.locator('.site-modal-body')).toBeHidden();
  expect(posts).toEqual([]);

  const name = '新闻杯 · 比赛队 / Players';
  const translations = await page.evaluate(value => ({
    prompt: window.siteTranslate(`确定删除队伍【${value}】吗？`),
    label: window.siteTranslate(`删除新闻 ${value}`),
  }), name);
  expect(translations).toEqual({
    prompt: `Delete team "${name}"?`,
    label: `Delete news ${name}`,
  });
});
