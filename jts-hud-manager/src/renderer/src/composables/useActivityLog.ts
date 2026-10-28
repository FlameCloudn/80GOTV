import { computed, ref } from 'vue'

// “最近操作”记录（全软件共用一份）：导播台列表和底部状态栏都从这里读
export type ActivityLevel = 'ok' | 'warn' | 'bad'
export type Activity = { id: number; at: number; text: string; level: ActivityLevel }

const MAX_ENTRIES = 50
const entries = ref<Activity[]>([])
let nextId = 1

const DUPLICATE_WINDOW_MS = 5000

export const logActivity = (text: string, level: ActivityLevel = 'ok'): void => {
  // 5 秒内同一句话只记一次（按钮报错和后台状态常常是同一件事）
  const last = entries.value[0]
  if (last && last.text === text && Date.now() - last.at < DUPLICATE_WINDOW_MS) return
  entries.value = [{ id: nextId++, at: Date.now(), text, level }, ...entries.value].slice(0, MAX_ENTRIES)
}

const latest = computed(() => entries.value[0] || null)

export const formatClock = (time: number | string | null | undefined): string => {
  if (!time) return '—'
  const date = new Date(time)
  return Number.isFinite(date.getTime()) ? date.toLocaleTimeString('zh-CN', { hour12: false }) : '—'
}

export const useActivityLog = () => ({ entries, latest, logActivity })
