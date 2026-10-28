// 用独立数据目录启动刚编译的导播软件（out/），逐页截图。不碰真实导播数据。
// 用法：先 npx electron-vite build，再 node scripts/ui-screenshots.cjs <软件目录> <独立数据目录> <截图目录> 页面1 页面2 ...
// 页面写法：director、matches、director!快捷键（进页面后点一下“快捷键”再截图）、teams@edit（点表格第一行的编辑）
// 环境变量：FEED=1 喂假的 CS2 数据；WIDTH/HEIGHT 改窗口大小；START_WAIT 启动后等多久
const { _electron: electron } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')
const { startFeed } = require('./fake-gsi-feed.cjs')

const [appDir, userDataDir, outDir, ...routes] = process.argv.slice(2)

const shoot = async (page, route) => {
  const [target, clickText] = route.split('!')
  const [hash, special] = target.split('@')
  await page.evaluate((value) => { window.location.hash = `#/${value}` }, hash)
  await page.waitForTimeout(1500)
  if (special === 'edit') await page.locator('button[title="编辑"]').first().click()
  if (clickText) await page.getByText(clickText, { exact: true }).first().click()
  if (special || clickText) await page.waitForTimeout(700)
  const file = path.join(outDir, `${route.replace(/[/!@]/g, '-')}.png`)
  await page.screenshot({ path: file })
  console.log('已截图', file)
  await page.keyboard.press('Escape').catch(() => undefined)
}

const run = async () => {
  fs.mkdirSync(userDataDir, { recursive: true })
  fs.mkdirSync(outDir, { recursive: true })
  const app = await electron.launch({
    args: [appDir, `--user-data-dir=${userDataDir}`],
    cwd: appDir,
    env: { ...process.env, HUD_PORT: '15491', GSI_PORT: '15492' },
    timeout: 60000
  })
  let stopFeed = () => undefined
  try {
    const page = await app.firstWindow()
    page.on('console', (message) => message.type() === 'error' && console.log('[界面报错]', message.text()))
    page.on('response', (response) => response.status() >= 400 && console.log('[请求失败]', response.status(), response.url()))
    if (process.env.WIDTH) {
      await app.evaluate(({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0].setSize(size.w, size.h), { w: Number(process.env.WIDTH), h: Number(process.env.HEIGHT) })
    }
    await page.waitForLoadState('domcontentloaded')
    await page.waitForTimeout(Number(process.env.START_WAIT || 2500))
    if (process.env.FEED) stopFeed = await startFeed('http://127.0.0.1:15491/api', 'http://127.0.0.1:15492')
    await page.waitForTimeout(1500)
    for (const route of routes) await shoot(page, route)
  } finally {
    stopFeed()
    await app.close()
  }
}

run().catch((error) => {
  console.error('截图失败：', error)
  process.exit(1)
})
