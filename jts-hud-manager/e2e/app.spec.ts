import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

let app: ElectronApplication
let page: Page

test.beforeAll(async () => {
  const userDataDir = join(tmpdir(), `80gotv-director-smoke-${process.pid}`)
  app = await electron.launch({
    args: ['.', `--user-data-dir=${userDataDir}`],
    env: { ...process.env, HUD_PORT: '15491' }
  })
  page = await app.firstWindow()
})

test.afterAll(async () => {
  await app?.close()
})

test('opens the director app and renders navigation', async () => {
  await expect(page).toHaveTitle('JTs Hud Manager 中文版')
  await expect(page.getByText('导播台', { exact: true }).first()).toBeVisible()
})
