import { ref } from 'vue'
import { errorText, showToast } from '../../../composables/useToasts'
import { API_URL } from '../../../index'

export interface HudData {
  id: string
  url: string
  thumb?: string
  hasPanel?: boolean
  canDelete?: boolean
  isSigned?: boolean
  signatureVerified?: boolean
  config: {
    name: string
    version: string
    author: string
    legacy: boolean
    radar: boolean
    killfeed: boolean
    game: string
    variants?: string[]
  }
}

export function useHuds() {
  const huds = ref<HudData[]>([])
  const isLoading = ref(false)

  const fetchHuds = async () => {
    isLoading.value = true
    try {
      const res = await fetch(`${API_URL}/huds`)
      if (res.ok) {
        huds.value = await res.json()
      }
    } catch (error) {
      console.error('Failed to fetch huds:', error)
    } finally {
      isLoading.value = false
    }
  }

  const buildUrl = (url: string, variant?: string) => {
    if (!variant) return url
    const separator = url.includes('?') ? '&' : '?'
    return `${url}${separator}variant=${encodeURIComponent(variant)}`
  }

  const launchHud = (url: string, variant?: string) => {
    const finalUrl = buildUrl(url, variant)
    // Uses standard electron-vite preload APIs to send IPC message
    if (window.electron && window.electron.ipcRenderer) {
      window.electron.ipcRenderer.send('open-hud', finalUrl)
    } else {
      alert('只有在桌面版程序中才能启动导播画面。')
      // Fallback for browser dev mode
      window.open(finalUrl, '_blank')
    }
  }

  const openFolder = () => {
    window.electron.ipcRenderer.send('open-huds-folder')
  }

  // 删除失败（比如内置 HUD 不能删）：右上角提示，列表里保留
  const deleteHud = async (id: string) => {
    try {
      const res = await fetch(`${API_URL}/huds/${encodeURIComponent(id)}`, { method: 'DELETE' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || '删除 HUD 失败')
      huds.value = huds.value.filter((h) => h.id !== id)
    } catch (error) {
      showToast(errorText(error), 'error', { key: 'hud-delete' })
    }
  }

  return {
    huds,
    isLoading,
    fetchHuds,
    buildUrl,
    launchHud,
    openFolder,
    deleteHud
  }
}
