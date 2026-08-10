import { ref, onMounted } from 'vue'
import { API_URL } from '../../../index'
import { useHuds } from './useHuds'

export function useHudsView() {
  const { huds, isLoading, fetchHuds, deleteHud } = useHuds()

  const importing = ref(false)
  const importError = ref<string | null>(null)

  const handleZipImport = async (file: File) => {
    importing.value = true
    importError.value = null
    try {
      const formData = new FormData()
      formData.append('hud', file)
      const res = await fetch(`${API_URL}/huds/upload-zip`, { method: 'POST', body: formData })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? '上传失败')
      await fetchHuds()
    } catch (err: any) {
      importError.value = err.message
    } finally {
      importing.value = false
    }
  }

  onMounted(() => fetchHuds())

  return {
    huds,
    isLoading,
    fetchHuds,
    deleteHud,
    importing,
    importError,
    handleZipImport
  }
}
