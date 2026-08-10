import { app } from 'electron'
import path from 'path'
import fs from 'fs'

/**
 * Returns the path to the user-facing HUDs directory.
 * Stored in ~/jthm-huds so users can easily find and manage their HUDs.
 */
export const getHudsDir = (): string => {
  const dir = path.join(app.getPath('home'), 'jthm-huds')
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
  return dir
}

/**
 * Returns the path to the bundled default HUD inside the app package.
 * Tries multiple locations to support dev, packed, and unpacked scenarios.
 */
export const getBuiltinHudDir = (): string => {
  const candidates = [
    // Production packed build
    path.join(app.getAppPath(), 'resources/default-hud'),
    // Unpacked build
    path.join(process.execPath, '../resources/default-hud'),
    // Development
    path.join(__dirname, '../../resources/default-hud')
  ]

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate
    }
  }

  // Fallback to development path if none exist (will error at runtime if actually needed)
  return path.join(__dirname, '../../resources/default-hud')
}
