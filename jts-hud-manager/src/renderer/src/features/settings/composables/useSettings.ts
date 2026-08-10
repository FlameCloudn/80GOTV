import { ref } from 'vue'
import { API_URL } from '../../../index'

export interface AppSettings {
  autoSwitchSides: boolean
  websiteUrl: string
  websiteGsiToken: string
  websiteMatchId: string
  forwardLiveData: boolean
  directorShortcuts: string
}

export function useSettings() {
  const settings = ref<AppSettings>({
    autoSwitchSides: true,
    websiteUrl: 'https://80gotv.cn',
    websiteGsiToken: '',
    websiteMatchId: '',
    forwardLiveData: false,
    directorShortcuts: '{}'
  })
  const isLoading = ref(false)
  const isSaving = ref(false)

  const fetchSettings = async () => {
    isLoading.value = true
    try {
      const res = await fetch(`${API_URL}/settings`)
      if (res.ok) settings.value = await res.json()
    } catch (err) {
      console.error('Failed to fetch settings:', err)
    } finally {
      isLoading.value = false
    }
  }

  const saveSettings = async (updates: Partial<AppSettings>): Promise<boolean> => {
    isSaving.value = true
    try {
      const res = await fetch(`${API_URL}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      })
      if (res.ok) {
        settings.value = await res.json()
        return true
      }
    } catch (err) {
      console.error('Failed to save settings:', err)
    } finally {
      isSaving.value = false
    }
    return false
  }

  return { settings, isLoading, isSaving, fetchSettings, saveSettings }
}
