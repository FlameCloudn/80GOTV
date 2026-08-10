import { BrowserWindow } from 'electron'

/**
 * Enforces that a transparent overlay window stays above all other windows,
 * working around Electron's known bug where alwaysOnTop can silently drop.
 *
 *  Use the highest alwaysOnTop level ('screen-saver') supported on Windows.
 *  Re-assert on every 'blur' event (e.g. alt+tab away and back).
 *  Re-assert on a periodic interval as a final fallback (every 2s).
 *  Clean up the interval when the window is closed.
 */
export function enforceOverlayOnTop(win: BrowserWindow): void {
  const assertOnTop = () => {
    if (win.isDestroyed()) return
    // 'screen-saver' is the highest level on Windows/macOS, keeps it above taskbar and fullscreen apps
    win.setAlwaysOnTop(true, 'screen-saver')
    // macOS: ensure it's visible on all spaces
    if (process.platform === 'darwin') {
      win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    }
  }

  // Initial assertion
  assertOnTop()

  // Re-assert whenever the OS moves it behind another window
  win.on('blur', assertOnTop)
  win.on('show', assertOnTop)

  // Periodic fallback: some Windows compositor states ignore event-based fixes
  const interval = setInterval(() => {
    if (win.isDestroyed()) {
      clearInterval(interval)
      return
    }
    assertOnTop()
  }, 2000)

  // Cleanup on close
  win.on('closed', () => {
    clearInterval(interval)
  })
}
