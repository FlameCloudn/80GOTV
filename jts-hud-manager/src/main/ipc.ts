import { shell, BrowserWindow, ipcMain, dialog, clipboard } from 'electron'
import path from 'path'
import fs from 'fs'
import net from 'net'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { enforceOverlayOnTop } from './overlayUtils'
import { configureDirectorShortcuts, registerHudKeybinds, unregisterHudKeybinds } from './shortcuts'
import { getHudsDir, getBuiltinHudDir } from './paths'
import { setActiveHudId } from './server/server'
import { getLogDirectory } from './logging'

const GSI_CFG_CONTENT = `"JTS_HUD_MANAGER"
{
	"uri"		"http://localhost:23415/cs2/input"
	"timeout"		"0.1"
	"buffer"		"0"
	"throttle"		"0.05"
	"output"
	{
	}
	"heartbeat"		"1.0"
	"data"
	{
		"provider"		"1"
		"map"		"1"
		"round"		"1"
		"player_id"		"1"
		"allplayers_id"		"1"
		"player_state"		"1"
		"allplayers_state"		"1"
		"allplayers_match_stats"		"1"
		"allplayers_weapons"		"1"
		"allplayers_position"		"1"
		"phase_countdowns"		"1"
		"allgrenades"		"1"
		"map_round_wins"		"1"
		"player_position"		"1"
		"bomb"		"1"
	}
}
`

const getCfgPath = (steamPath: string) =>
  path.join(
    steamPath,
    'steamapps',
    'common',
    'Counter-Strike Global Offensive',
    'game',
    'csgo',
    'cfg',
    'gamestate_integration_jts_hud_manager.cfg'
  )

const execFileAsync = promisify(execFile)

const findSteamLibraries = async (): Promise<string[]> => {
  const roots = new Set<string>()
  const addRoot = (value?: string | null) => {
    const cleaned = String(value || '').trim().replace(/^"|"$/g, '')
    if (cleaned && fs.existsSync(cleaned)) roots.add(path.normalize(cleaned))
  }

  addRoot(path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'Steam'))
  addRoot(path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Steam'))

  if (process.platform === 'win32') {
    const registryQueries = [
      ['HKCU\\Software\\Valve\\Steam', 'SteamPath'],
      ['HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam', 'InstallPath']
    ]
    for (const [key, valueName] of registryQueries) {
      try {
        const { stdout } = await execFileAsync(
          'reg.exe',
          ['query', key, '/v', valueName],
          { windowsHide: true, timeout: 3000 }
        )
        const line = stdout.split(/\r?\n/).find((item) => item.includes(valueName))
        if (line) addRoot(line.replace(/^.*REG_\w+\s+/, ''))
      } catch {
        // A missing registry key is normal on portable Steam installs.
      }
    }
  }

  for (const steamRoot of [...roots]) {
    const libraryFile = path.join(steamRoot, 'steamapps', 'libraryfolders.vdf')
    if (!fs.existsSync(libraryFile)) continue
    try {
      const content = fs.readFileSync(libraryFile, 'utf-8')
      for (const match of content.matchAll(/"path"\s+"([^"]+)"/g)) {
        addRoot(match[1].replace(/\\\\/g, '\\'))
      }
    } catch {
      // Keep the main Steam folder as a fallback when the library file cannot be read.
    }
  }

  return [...roots]
}

const detectCs2Libraries = async () => {
  const libraries = await findSteamLibraries()
  const withCs2 = libraries.filter((library) => fs.existsSync(path.dirname(getCfgPath(library))))
  return {
    ok: withCs2.length > 0,
    paths: withCs2.length ? withCs2 : libraries,
    selected: withCs2[0] || libraries[0] || '',
    message: withCs2.length
      ? `已找到 ${withCs2.length} 个可用的 CS2 安装位置。`
      : libraries.length
        ? '找到了 Steam，但没有找到 CS2。可以手动选择游戏所在的 Steam 库。'
        : '没有自动找到 Steam，请手动选择 Steam 或 SteamLibrary 文件夹。'
  }
}

let activeOverlay: BrowserWindow | null = null

export function registerIpcHandlers(): void {
  ipcMain.on('open-hud', (_, hudUrl) => {
    // Ensure only one overlay window at a time
    if (activeOverlay && !activeOverlay.isDestroyed()) {
      activeOverlay.close()
      activeOverlay = null
    }

    // Extract HUD id from URL: http://localhost:PORT/huds/{id}/index.html
    const hudIdMatch = (hudUrl as string).match(/\/huds\/([^/]+)\//)
    const hudId = hudIdMatch ? hudIdMatch[1] : null

    // Tell the server which HUD is active so hud_config lookups use the correct id
    // regardless of what name the HUD client sends in its register event.
    setActiveHudId(hudId)

    // Load hud keybinds
    if (hudId) {
      const hudDir = hudId === 'default' ? getBuiltinHudDir() : path.join(getHudsDir(), hudId)
      const keybindsPath = path.join(hudDir, 'keybinds.json')
      if (fs.existsSync(keybindsPath)) {
        try {
          const keybinds: { bind: string; action: string }[] = JSON.parse(
            fs.readFileSync(keybindsPath, 'utf-8')
          )
          registerHudKeybinds(keybinds)
          console.log(`Loaded ${keybinds.length} keybind(s) for HUD "${hudId}"`)
        } catch (e) {
          console.error(`Failed to parse keybinds.json for HUD "${hudId}":`, e)
        }
      }
    }

    // TODO: May want to use hud name instead for the title
    const overlayWindow = new BrowserWindow({
      title: 'JTs Hud Manager Overlay',
      width: 1920,
      height: 1080,
      transparent: true,
      frame: false,
      alwaysOnTop: true,
      fullscreen: true,
      skipTaskbar: false,
      focusable: true,
      webPreferences: {
        sandbox: false,
        contextIsolation: true
      }
    })

    activeOverlay = overlayWindow
    overlayWindow.setIgnoreMouseEvents(true, { forward: true })
    overlayWindow.loadURL(hudUrl)
    enforceOverlayOnTop(overlayWindow)

    overlayWindow.on('closed', () => {
      activeOverlay = null
      setActiveHudId(null)
      unregisterHudKeybinds()
    })
  })

  ipcMain.on('open-huds-folder', () => {
    shell.openPath(getHudsDir())
  })

  ipcMain.handle('open-log-folder', async () => {
    const directory = getLogDirectory()
    fs.mkdirSync(directory, { recursive: true })
    return shell.openPath(directory)
  })

  // Open folder picker and return the selected path
  ipcMain.handle('select-folder', async (_, defaultPath?: string) => {
    const result = await dialog.showOpenDialog({
      title: 'Select Steam Folder',
      defaultPath: defaultPath || 'C:\\Program Files (x86)\\Steam',
      properties: ['openDirectory']
    })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('detect-cs2-paths', async () => detectCs2Libraries())

  // Validate the steam path, then install/update the GSI cfg file
  ipcMain.handle(
    'install-gsi-cfg',
    async (_, steamPath: string): Promise<{ ok: boolean; message: string }> => {
      try {
        const cfgPath = getCfgPath(steamPath)
        const cfgDir = path.dirname(cfgPath)

        if (!fs.existsSync(cfgDir)) {
          return {
            ok: false,
            message: `没有找到 CS2 配置文件夹：\n${cfgDir}\n\n请确认选择的是 Steam 安装文件夹，并且已经安装 CS2。`
          }
        }

        // Check if already up-to-date
        if (fs.existsSync(cfgPath)) {
          const existing = fs.readFileSync(cfgPath, 'utf-8')
          if (existing === GSI_CFG_CONTENT) {
            return { ok: true, message: 'GSI 配置已经安装，并且是最新版本。' }
          }
        }

        fs.writeFileSync(cfgPath, GSI_CFG_CONTENT, 'utf-8')
        return { ok: true, message: 'GSI 配置安装成功！' }
      } catch (err: any) {
        return { ok: false, message: `GSI 配置安装失败：${err.message}` }
      }
    }
  )

  // Open a URL in the user's default browser
  ipcMain.handle('open-external', async (_, url: string) => {
    await shell.openExternal(url)
  })

  ipcMain.handle('copy-text', (_, value: string) => {
    clipboard.writeText(String(value || ''))
  })

  ipcMain.handle('configure-director-shortcuts', (_, bindings: Record<string, string>) =>
    configureDirectorShortcuts(bindings && typeof bindings === 'object' ? bindings : {})
  )

  // Send one or more console commands to CS2 via telnet.
  // Commands separated by ; are sent sequentially with a small delay between each.
  ipcMain.handle(
    'send-telnet',
    (
      _,
      {
        command,
        host = '127.0.0.1',
        port = 2020
      }: { command: string; host?: string; port?: number }
    ): Promise<void> => {
      return new Promise((resolve, reject) => {
        const socket = net.createConnection({ host, port: Number(port) })
        const timeoutId = setTimeout(() => socket.destroy(new Error('Telnet timeout')), 4000)
        socket.setTimeout(4000)

        socket.on('connect', () => {
          const lines = String(command)
            .split('\n')
            .map((l) => l.trim())
            .filter(Boolean)
          let i = 0
          const writeNext = () => {
            if (i >= lines.length) {
              clearTimeout(timeoutId)
              socket.end()
              resolve()
              return
            }
            socket.write(`${lines[i++]}\r\n`, () => setTimeout(writeNext, 10))
          }
          writeNext()
        })

        socket.on('timeout', () => socket.destroy(new Error('Telnet timeout')))
        socket.on('error', (err) => {
          clearTimeout(timeoutId)
          reject(err)
        })
      })
    }
  )
}
