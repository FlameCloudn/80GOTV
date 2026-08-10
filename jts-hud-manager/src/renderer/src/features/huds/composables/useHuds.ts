import { ref } from 'vue'
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

  const deleteHud = async (id: string) => {
    await fetch(`${API_URL}/huds/${encodeURIComponent(id)}`, { method: 'DELETE' })
    huds.value = huds.value.filter((h) => h.id !== id)
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
