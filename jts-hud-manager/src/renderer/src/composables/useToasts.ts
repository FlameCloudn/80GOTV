import { ref } from 'vue'

// 右上角浮动提示（全软件共用一份）。规则照网站后台：
// 错误和警告不自动消失、能手动关；同一个 key 的提示只保留一条（新内容替换旧的）。
export type ToastLevel = 'error' | 'warn' | 'info' | 'success'
export type Toast = { id: number; key?: string; level: ToastLevel; title: string; text: string }

const DEFAULT_TITLES: Record<ToastLevel, string> = {
  error: '出错了',
  warn: '请注意',
  info: '提示',
  success: '完成'
}
// 只有“提示”和“完成”会自己消失
const AUTO_HIDE_MS: Partial<Record<ToastLevel, number>> = { info: 3000, success: 2500 }

const toasts = ref<Toast[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let nextId = 1

export const dismissToast = (id: number): void => {
  const timer = timers.get(id)
  if (timer) clearTimeout(timer)
  timers.delete(id)
  toasts.value = toasts.value.filter((toast) => toast.id !== id)
}

export const showToast = (
  text: string,
  level: ToastLevel = 'error',
  options: { key?: string; title?: string } = {}
): number => {
  // 同一个 key、或者一模一样的内容（比如按钮报错和后台状态报的是同一件事）只留一条
  const existing = toasts.value.filter((toast) => (options.key && toast.key === options.key) || toast.text === text)
  existing.forEach((toast) => dismissToast(toast.id))
  const toast: Toast = {
    id: nextId++,
    key: options.key,
    level,
    title: options.title || DEFAULT_TITLES[level],
    text
  }
  toasts.value = [toast, ...toasts.value]
  const hideAfter = AUTO_HIDE_MS[level]
  if (hideAfter) timers.set(toast.id, setTimeout(() => dismissToast(toast.id), hideAfter))
  return toast.id
}

// 把各种报错变成一句能看懂的话
export const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : String(error || '未知错误')

export const useToasts = () => ({ toasts, showToast, dismissToast })
