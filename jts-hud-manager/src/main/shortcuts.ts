import { globalShortcut } from 'electron'
import { io } from './server/server'
import { getLastGSIState } from './server/integrations/gsi'
import { MatchService } from './server/domains/matches/match.service'

const matchService = new MatchService()

// HUD specific keybinds that will be unregistered when HUD is closed
const activeHudBinds: string[] = []
const activeDirectorBinds = new Map<string, string>()

export const DIRECTOR_COMMANDS = new Set([
  'bp', 'auto', 'game', 'pause_tactical', 'pause_technical',
  'halftime', 'map_end', 'series_end', 'hide_all'
])

const triggerDirectorCommand = async (command: string): Promise<void> => {
  try {
    await fetch(`http://127.0.0.1:${process.env.HUD_PORT ?? 1349}/api/huds/default/director-command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command })
    })
  } catch (error) {
    console.warn(`[Director] shortcut command failed: ${command}`, error)
  }
}

export type DirectorShortcutResult = { ok: boolean; errors: Record<string, string> }

export const configureDirectorShortcuts = (
  bindings: Record<string, string> = {}
): DirectorShortcutResult => {
  const errors: Record<string, string> = {}
  const requested = new Map<string, string>()
  for (const [command, accelerator] of Object.entries(bindings)) {
    const value = String(accelerator || '').trim()
    if (!value) continue
    if (!DIRECTOR_COMMANDS.has(command)) {
      errors[command] = '未知场景'
      continue
    }
    const duplicate = [...requested.entries()].find(([, other]) => other.toLowerCase() === value.toLowerCase())
    if (duplicate) {
      errors[command] = `与 ${duplicate[0]} 重复`
      continue
    }
    requested.set(command, value)
  }

  const previous = new Map(activeDirectorBinds)
  for (const bind of previous.values()) globalShortcut.unregister(bind)
  const registered: string[] = []
  if (!Object.keys(errors).length) {
    for (const [command, bind] of requested) {
      if (globalShortcut.isRegistered(bind) || !globalShortcut.register(bind, () => void triggerDirectorCommand(command))) {
        errors[command] = '快捷键被系统或其他程序占用'
        break
      }
      registered.push(bind)
    }
  }
  if (Object.keys(errors).length) {
    for (const bind of registered) globalShortcut.unregister(bind)
    activeDirectorBinds.clear()
    for (const [command, bind] of previous) {
      if (globalShortcut.register(bind, () => void triggerDirectorCommand(command))) activeDirectorBinds.set(command, bind)
    }
    return { ok: false, errors }
  }

  activeDirectorBinds.clear()
  for (const [command, bind] of requested) activeDirectorBinds.set(command, bind)
  return { ok: true, errors: {} }
}

const restoreDirectorShortcuts = async (attempt = 0): Promise<void> => {
  try {
    const { getSettings } = await import('./server/domains/settings/settings.routes')
    const settings = await getSettings()
    const bindings = JSON.parse(settings.directorShortcuts || '{}')
    configureDirectorShortcuts(bindings && typeof bindings === 'object' ? bindings : {})
  } catch (error) {
    if (attempt < 8) setTimeout(() => void restoreDirectorShortcuts(attempt + 1), 500)
    else console.warn('[Director] failed to restore saved shortcuts', error)
  }
}

export function registerHudKeybinds(keybinds: { bind: string; action: string }[]): void {
  unregisterHudKeybinds()

  for (const { bind, action } of keybinds) {
    const ok = globalShortcut.register(bind, () => {
      io.emit('keybindAction', action)
      // console.log(`HUD keybind [${bind}] → action "${action}"`);
    })
    if (ok) {
      activeHudBinds.push(bind)
    } else {
      console.warn(`HUD keybind [${bind}] could not be registered (already in use?)`)
    }
  }
}

export function unregisterHudKeybinds(): void {
  for (const bind of activeHudBinds) {
    globalShortcut.unregister(bind)
  }
  activeHudBinds.length = 0
}

export function registerShortcuts(): void {
  // Global Alt+F: Refresh HUDs
  globalShortcut.register('Alt+F', () => {
    io.emit('refreshHUD')
    // console.log('Emitted refresh to all HUD clients')
  })

  // Global Alt+R: Toggle reverseSide on the current map veto of the active match
  globalShortcut.register('Alt+R', async () => {
    const gsi = getLastGSIState()
    if (!gsi?.map?.name) {
      console.warn('Alt+R: No GSI map data available yet')
      return
    }

    const mapName = gsi.map.name.substring(gsi.map.name.lastIndexOf('/') + 1)

    try {
      await matchService.toggleVetoReverseSide(mapName)
      io.emit('match')
      console.log(`Alt+R: Toggled reverseSide for map "${mapName}" and notified HUDs`)
    } catch (err: any) {
      console.error('Alt+R: Failed to toggle reverseSide —', err.message)
    }
  })
  void restoreDirectorShortcuts()
}

export function unregisterShortcuts(): void {
  globalShortcut.unregisterAll()
  activeDirectorBinds.clear()
}
