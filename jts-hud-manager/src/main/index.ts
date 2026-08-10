import { app, BrowserWindow, net } from 'electron'
import { electronApp, optimizer } from '@electron-toolkit/utils'
import { createWindow } from './window'
import { registerIpcHandlers } from './ipc'
import { registerShortcuts, unregisterShortcuts } from './shortcuts'
import { startServers, shutdown } from './server/server'
import { db } from './server/database/sqlite'
import { installFileLogging } from './logging'

installFileLogging()

// Broadcast overlays must be able to start their scene music from socket/game events.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')

// Single-instance lock
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
}

// Focus existing window on second-instance launch
app.on('second-instance', () => {
  const win = BrowserWindow.getAllWindows()[0]
  if (win) {
    if (win.isMinimized()) win.restore()
    win.focus()
  }
})

app.whenReady().then(() => {
  console.log('[App] Electron ready')
  electronApp.setAppUserModelId('com.electron')

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  registerIpcHandlers()
  registerShortcuts()
  createWindow()

  // Start local servers
  startServers()

  // Update check
  if (app.isPackaged) {
    checkForUpdate()
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('render-process-gone', (_, webContents, details) => {
  console.error(`[Renderer] Process gone; url=${webContents.getURL()} reason=${details.reason} exitCode=${details.exitCode}`)
})

app.on('child-process-gone', (_, details) => {
  console.error(`[ChildProcess] Gone; type=${details.type} reason=${details.reason} exitCode=${details.exitCode}`)
})

async function checkForUpdate(): Promise<void> {
  try {
    const response = await net.fetch(
      'https://api.github.com/repos/JohnTimmermann/JTs-Hud-Manager/releases/latest',
      { headers: { 'User-Agent': 'jts-hud-manager-electron' } }
    )
    if (!response.ok) return
    const data = (await response.json()) as { tag_name: string }
    const latestVersion = data.tag_name.replace(/^v/, '')
    const currentVersion = app.getVersion()
    if (latestVersion !== currentVersion) {
      const win = BrowserWindow.getAllWindows()[0]
      if (win && !win.isDestroyed()) {
        win.webContents.send('update-available', latestVersion)
      }
    }
  } catch {
    // Silently ignore update check failures
  }
}

app.on('window-all-closed', () => {
  unregisterShortcuts()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', async (event) => {
  event.preventDefault()
  // If cleanup hangs, force-exit after 5 seconds to prevent zombie
  const forceExit = setTimeout(() => {
    console.warn('[Shutdown] Cleanup timed out — forcing exit.')
    app.exit(0)
  }, 5000)
  try {
    await shutdown()
    db.close((err) => {
      clearTimeout(forceExit)
      if (err) console.error('[DB] Error closing SQLite:', err.message)
      else console.log('[DB] SQLite connection closed.')
      app.exit(0)
    })
  } catch (err) {
    clearTimeout(forceExit)
    console.error('[Shutdown] Error during cleanup:', err)
    app.exit(1)
  }
})
