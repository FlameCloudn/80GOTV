import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { socket } from '../../../socket'
import { API_URL } from '../../../index'
import type { CSGORaw } from 'csgogsi'

export interface LivePlayer {
  steamid: string
  name: string
  side: 'CT' | 'T'
  observerSlot: number
}

const SLOT_KEYS: Record<number, string> = {
  1: '1',
  2: '2',
  3: '3',
  4: '4',
  5: '5',
  6: '6',
  7: '7',
  8: '8',
  9: '9',
  10: '0'
}

const STORAGE_KEY = 'spectator-slots'
const PRE_COMMAND_KEY = 'spectator-precommand'

export function useSpectator() {
  const gameState = ref<CSGORaw | null>(null)
  const slots = ref<Record<number, string>>(
    Object.fromEntries(Array.from({ length: 10 }, (_, i) => [i + 1, ''])) as Record<number, string>
  )

  const preCommand = ref(localStorage.getItem(PRE_COMMAND_KEY) ?? '')

  const telnetHost = ref('127.0.0.1')
  const telnetPort = ref(2020)
  const settingsOpen = ref(false)
  const showInfo = ref(false)
  const settingsSaving = ref(false)

  const applying = ref(false)
  const applyResult = ref<{ ok: boolean; message: string } | null>(null)
  const clearing = ref(false)
  const testing = ref(false)
  const testResult = ref<{ ok: boolean; message: string } | null>(null)

  const pushSlots = async () => {
    try {
      await fetch(`${API_URL}/spectator/slots`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slots: slots.value })
      })
    } catch {
      /* server may not be up yet */
    }
  }

  const loadSlots = () => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved)
        for (let i = 1; i <= 10; i++) {
          slots.value[i] = parsed[i] ?? ''
        }
      }
    } catch {
      /* ignore */
    }
  }

  watch(
    slots,
    (v) => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(v))
      pushSlots()
    },
    { deep: true }
  )

  watch(preCommand, (v) => {
    localStorage.setItem(PRE_COMMAND_KEY, v)
  })

  const livePlayers = computed((): LivePlayer[] => {
    if (!gameState.value?.allplayers) return []
    return Object.entries(gameState.value.allplayers).map(([steamid, p]: [string, any]) => ({
      steamid,
      name: p.name,
      side: p.team as 'CT' | 'T',
      observerSlot: p.observer_slot ?? 0
    }))
  })

  const ctPlayers = computed(() => livePlayers.value.filter((p) => p.side === 'CT'))
  const tPlayers = computed(() => livePlayers.value.filter((p) => p.side === 'T'))
  const allPlayerNames = computed(() => livePlayers.value.map((p) => p.name))

  const sideForName = (name: string): 'CT' | 'T' | null => {
    const p = livePlayers.value.find((p) => p.name === name)
    return p?.side ?? null
  }

  const loadSettings = async () => {
    try {
      const res = await fetch(`${API_URL}/settings`)
      if (res.ok) {
        const s = await res.json()
        if (s.telnetHost) telnetHost.value = s.telnetHost
        if (s.telnetPort) telnetPort.value = Number(s.telnetPort)
      }
    } catch {
      /* ignore */
    }
  }

  const saveSettings = async () => {
    settingsSaving.value = true
    try {
      await fetch(`${API_URL}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ telnetHost: telnetHost.value, telnetPort: telnetPort.value })
      })
    } finally {
      settingsSaving.value = false
      settingsOpen.value = false
    }
  }

  const testConnection = async () => {
    testing.value = true
    testResult.value = null
    try {
      await (window as any).electron.ipcRenderer.invoke('send-telnet', {
        command: 'echo JtsHudManager_ping',
        host: telnetHost.value,
        port: telnetPort.value
      })
      testResult.value = { ok: true, message: '已连接到 CS2！' }
    } catch (err: any) {
      testResult.value = { ok: false, message: err.message ?? '连接失败' }
    } finally {
      testing.value = false
      setTimeout(() => {
        testResult.value = null
      }, 3000)
    }
  }

  const buildCommand = (): string => {
    const lines: string[] = ['spec_usenumberkeys_nobinds false']
    const pre = preCommand.value.trim()
    for (let slot = 1; slot <= 10; slot++) {
      const name = slots.value[slot]
      if (!name) continue
      const key = SLOT_KEYS[slot]
      const aliasName = `player${key}`
      const body = pre
        ? `${pre}; spec_player ${name}; spec_mode 1`
        : `spec_player ${name}; spec_mode 1`
      lines.push(`alias ${aliasName} "${body}"`)
      lines.push(`bind ${key} ${aliasName}`)
    }
    return lines.join('\n')
  }

  const previewCommand = computed(() => buildCommand().split('\n').join('; '))

  const applyBinds = async () => {
    const command = buildCommand()
    if (!command) {
      applyResult.value = { ok: false, message: '还没有分配选手，请先设置数字键。' }
      setTimeout(() => {
        applyResult.value = null
      }, 3000)
      return
    }

    applying.value = true
    applyResult.value = null
    try {
      await (window as any).electron.ipcRenderer.invoke('send-telnet', {
        command,
        host: telnetHost.value,
        port: telnetPort.value
      })
      applyResult.value = { ok: true, message: '按键绑定已应用到 CS2！' }
    } catch (err: any) {
      applyResult.value = {
        ok: false,
        message: (err.message ?? '连接失败') + '。请确认 CS2 已使用 -netconport 2020 启动。'
      }
    } finally {
      applying.value = false
      setTimeout(() => {
        applyResult.value = null
      }, 4000)
    }
  }

  const clearAll = () => {
    for (let i = 1; i <= 10; i++) slots.value[i] = ''
  }

  const clearBinds = async () => {
    clearAll()
    const restoreBinds = [
      'bind "1" "slot1"',
      'bind "2" "slot2"',
      'bind "3" "slot3"',
      'bind "4" "slot4"',
      'bind "5" "slot5"',
      'bind "6" "slot6"',
      'bind "7" "slot7"',
      'bind "8" "slot8"',
      'bind "9" "slot9"',
      'bind "0" "slot10"'
    ]
    const lines = [
      'spec_usenumberkeys_nobinds true',
      ...Object.values(SLOT_KEYS).map((key) => `unbind ${key}`),
      ...restoreBinds
    ]
    clearing.value = true
    applyResult.value = null
    try {
      await (window as any).electron.ipcRenderer.invoke('send-telnet', {
        command: lines.join('\n'),
        host: telnetHost.value,
        port: telnetPort.value
      })
      applyResult.value = { ok: true, message: '全部选手位置已清空，CS2 数字键已恢复。' }
    } catch (err: any) {
      applyResult.value = {
        ok: false,
        message: (err.message ?? '连接失败') + '。请确认 CS2 已使用 -netconport 2020 启动。'
      }
    } finally {
      clearing.value = false
      setTimeout(() => {
        applyResult.value = null
      }, 4000)
    }
  }

  const quickAssign = (name: string) => {
    for (let i = 1; i <= 10; i++) {
      if (!slots.value[i]) {
        slots.value[i] = name
        return
      }
    }
  }

  const clearSlot = async (slot: number) => {
    slots.value[slot] = ''
    const key = SLOT_KEYS[slot]
    try {
      await (window as any).electron.ipcRenderer.invoke('send-telnet', {
        command: [`unbind ${key}`, `bind "${key}" "slot${slot}"`].join('\n'),
        host: telnetHost.value,
        port: telnetPort.value
      })
    } catch {
      /* ignore */
    }
  }

  const numericNameWarnings = computed(() =>
    Object.values(slots.value).filter((name): name is string => !!name && /^\d/.test(name))
  )

  const fillFromCS2 = () => {
    clearAll()
    for (const p of livePlayers.value) {
      const slot = p.observerSlot === 0 ? 10 : p.observerSlot
      if (slot >= 1 && slot <= 10) {
        slots.value[slot] = p.name
      }
    }
  }

  const onUpdate = (data: CSGORaw) => {
    gameState.value = data
  }

  onMounted(async () => {
    loadSlots()
    await loadSettings()
    await pushSlots()
    socket.on('update', onUpdate)
  })

  onUnmounted(() => {
    socket.off('update', onUpdate)
  })

  return {
    gameState,
    slots,
    telnetHost,
    telnetPort,
    settingsOpen,
    showInfo,
    settingsSaving,
    applying,
    applyResult,
    clearing,
    testing,
    testResult,
    livePlayers,
    ctPlayers,
    tPlayers,
    allPlayerNames,
    sideForName,
    preCommand,
    previewCommand,
    numericNameWarnings,
    saveSettings,
    testConnection,
    applyBinds,
    clearBinds,
    quickAssign,
    clearSlot,
    clearAll,
    fillFromCS2,
    SLOT_KEYS,
    buildCommand
  }
}
