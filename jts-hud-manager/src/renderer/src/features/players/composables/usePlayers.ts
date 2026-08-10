import { ref } from 'vue'
import { API_URL } from '../../../index'
import { useConfirmation } from '../../../composables/useConfirmation'

export function usePlayers() {
  const players = ref<any[]>([])
  const isLoading = ref(false)

  const fetchPlayers = async () => {
    isLoading.value = true
    try {
      const res = await fetch(`${API_URL}/players`)
      if (res.ok) players.value = await res.json()
    } catch (error) {
      console.error('Failed to fetch players:', error)
    } finally {
      isLoading.value = false
    }
  }

  const savePlayer = async (payload: any, id: string | null = null, file: File | null = null) => {
    try {
      const method = id ? 'PUT' : 'POST'
      const url = id ? `${API_URL}/players/${id}` : `${API_URL}/players`

      // Switch from JSON to FormData
      const formData = new FormData()
      Object.keys(payload).forEach((key) => {
        const value = typeof payload[key] === 'object' ? JSON.stringify(payload[key]) : payload[key]
        formData.append(key, value)
      })

      if (file) formData.append('avatar', file)

      const res = await fetch(url, {
        method,
        body: formData
      })

      if (!res.ok) throw new Error('保存选手失败')
      await fetchPlayers()
      return await res.json()
    } catch (error) {
      console.error(error)
      throw error
    }
  }

  const { confirm } = useConfirmation()

  const deletePlayer = async (id: string) => {
    if (!(await confirm('这名选手将被永久删除。'))) return false
    try {
      const res = await fetch(`${API_URL}/players/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('删除选手失败')

      await fetchPlayers()
      return true
    } catch (error) {
      console.error(error)
      return false
    }
  }

  const deleteManyPlayers = async (ids: string[]) => {
    if (!ids.length) return false
    if (!(await confirm(`${ids.length} 名选手将被永久删除。`))) return false
    try {
      for (const id of ids) {
        await fetch(`${API_URL}/players/${id}`, { method: 'DELETE' })
      }
      await fetchPlayers()
      return true
    } catch (error) {
      console.error(error)
      return false
    }
  }

  return {
    players,
    isLoading,
    fetchPlayers,
    savePlayer,
    deletePlayer,
    deleteManyPlayers
  }
}
