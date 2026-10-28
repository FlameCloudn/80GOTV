import { onBeforeUnmount, onMounted, ref } from 'vue'
import { API_URL } from '../../../index'
import { logActivity } from '../../../composables/useActivityLog'
import { errorText, showToast } from '../../../composables/useToasts'

// 全局场景快捷键（切到别的程序也能用）。新安装默认不绑定。
export const SHORTCUT_COMMANDS = [
  { key: 'bp', label: '赛前 BP' },
  { key: 'auto', label: '自动跟随' },
  { key: 'game', label: '切出覆盖层' },
  { key: 'pause_tactical', label: '战术暂停' },
  { key: 'pause_technical', label: '技术暂停' },
  { key: 'halftime', label: '中场' },
  { key: 'map_end', label: '单图结束' },
  { key: 'series_end', label: '系列赛结束' },
  { key: 'hide_all', label: '全部隐藏' }
] as const

const MODIFIER_KEYS = ['Control', 'Alt', 'Shift', 'Meta']

const labelOf = (command: string): string =>
  SHORTCUT_COMMANDS.find((item) => item.key === command)?.label || command

// 键盘事件 → Electron 认识的组合键写法（Ctrl+Shift+F1）；只按了修饰键返回空
const acceleratorOf = (event: KeyboardEvent): string => {
  const key = event.key.length === 1 ? event.key.toUpperCase() : event.key
  if (MODIFIER_KEYS.includes(key)) return ''
  const modifiers: string[] = []
  if (event.ctrlKey) modifiers.push('Ctrl')
  if (event.altKey) modifiers.push('Alt')
  if (event.shiftKey) modifiers.push('Shift')
  if (event.metaKey) modifiers.push('Super')
  return [...modifiers, key === ' ' ? 'Space' : key].join('+')
}

export function useDirectorShortcuts() {
  const bindings = ref<Record<string, string>>({})
  const recording = ref<string | null>(null)

  const restoreBindings = () => void window.api?.configureDirectorShortcuts?.(bindings.value)

  const saveBindings = async (next: Record<string, string>) => {
    const result = window.api?.configureDirectorShortcuts
      ? await window.api.configureDirectorShortcuts(next)
      : { ok: true, errors: {} }
    if (!result.ok) throw new Error(Object.values(result.errors || {}).join('；') || '快捷键注册失败')
    const response = await fetch(`${API_URL}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directorShortcuts: next })
    })
    if (!response.ok) throw new Error('快捷键保存失败')
    bindings.value = { ...next }
  }

  // 录入时先临时取消全局快捷键，按下的组合键才能被这个窗口收到
  const startRecording = async (command: string) => {
    recording.value = command
    await window.api?.configureDirectorShortcuts?.({})
  }
  const cancelRecording = () => {
    recording.value = null
    restoreBindings()
  }

  const finishRecording = (command: string, accelerator: string) => {
    const next = { ...bindings.value, [command]: accelerator }
    const duplicate = Object.entries(next).find(
      ([other, value]) => other !== command && value.toLowerCase() === accelerator.toLowerCase()
    )
    recording.value = null
    if (duplicate) {
      restoreBindings()
      showToast(`${accelerator} 已被“${labelOf(duplicate[0])}”使用，换一个组合键`, 'warn', { key: 'shortcut' })
      return
    }
    saveBindings(next)
      .then(() => logActivity(`快捷键：${labelOf(command)} = ${accelerator}`))
      .catch((error) => {
        restoreBindings()
        showToast(errorText(error), 'error', { key: 'shortcut' })
      })
  }

  const onKeydown = (event: KeyboardEvent) => {
    const command = recording.value
    if (!command) return
    event.preventDefault()
    event.stopPropagation()
    if (event.key === 'Escape') return cancelRecording()
    const accelerator = acceleratorOf(event)
    if (accelerator) finishRecording(command, accelerator)
  }

  const clearShortcut = (command: string) => {
    const next = { ...bindings.value }
    delete next[command]
    saveBindings(next)
      .then(() => logActivity(`快捷键：已清除“${labelOf(command)}”`))
      .catch((error) => showToast(errorText(error), 'error', { key: 'shortcut' }))
  }

  const loadBindings = async () => {
    try {
      const response = await fetch(`${API_URL}/settings`)
      if (!response.ok) return
      const settings = await response.json()
      const parsed = JSON.parse(settings.directorShortcuts || '{}')
      bindings.value = parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
      bindings.value = {}
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', onKeydown, true)
    void loadBindings()
  })
  onBeforeUnmount(() => {
    if (recording.value) restoreBindings()
    window.removeEventListener('keydown', onKeydown, true)
  })

  return { bindings, recording, startRecording, cancelRecording, clearShortcut }
}
