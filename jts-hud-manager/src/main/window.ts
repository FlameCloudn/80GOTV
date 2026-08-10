import { BrowserWindow, shell } from 'electron'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'

export function createWindow(): void {
  const hudPort = String(process.env.HUD_PORT ?? 1349)
  const mainWindow = new BrowserWindow({
    minWidth: 1280,
    minHeight: 720,
    width: 1280,
    height: 720,
    show: false,
    autoHideMenuBar: true,
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  // When the main window closes, close all other windows
  mainWindow.on('close', () => {
    BrowserWindow.getAllWindows().forEach((win) => {
      if (win.id !== mainWindow.id) win.destroy()
    })
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  mainWindow.webContents.on('console-message', (event) => {
    const level = String(event.level).toLowerCase()
    if (is.dev || ['warning', 'warn', 'error'].includes(level)) {
      const message = `[Renderer:${event.level}] ${event.message}`
      if (level === 'error') console.error(message)
      else if (level === 'warning' || level === 'warn') console.warn(message)
      else console.log(message)
    }
  })

  mainWindow.webContents.on('did-fail-load', (_, errorCode, errorDescription, validatedURL) => {
    console.error(`[Renderer] Failed to load; code=${errorCode} description=${errorDescription} url=${validatedURL}`)
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    const rendererUrl = new URL(process.env['ELECTRON_RENDERER_URL'])
    rendererUrl.searchParams.set('port', hudPort)
    mainWindow.loadURL(rendererUrl.toString())
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'), { query: { port: hudPort } })
  }
}
