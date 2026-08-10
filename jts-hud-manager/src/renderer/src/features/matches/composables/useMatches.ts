import { ref, onMounted, onUnmounted } from 'vue'
import { API_URL } from '../../../index'
import { useConfirmation } from '../../../composables/useConfirmation'
import { socket } from '../../../socket'

export function useMatches() {
  const matches = ref<any[]>([])
  const isLoading = ref(false)

  const fetchMatches = async () => {
    isLoading.value = true
    try {
      const res = await fetch(`${API_URL}/match`)
      if (res.ok) matches.value = await res.json()
    } catch (error) {
      console.error('Failed to fetch matches:', error)
    } finally {
      isLoading.value = false
    }
  }

  const saveMatch = async (payload: any, id: string | null = null) => {
    try {
      const method = id ? 'PUT' : 'POST'
      const url = id ? `${API_URL}/match/${id}` : `${API_URL}/match`

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })

      if (!res.ok) throw new Error('保存比赛失败')

      await fetchMatches() // Auto-refresh the list
      return await res.json()
    } catch (error) {
      console.error(error)
      throw error
    }
  }

  const { confirm } = useConfirmation()

  // Re-fetch whenever the backend emits 'match' (halftime, map end, manual update, etc.)
  const onMatchEvent = () => fetchMatches()
  onMounted(() => socket.on('match', onMatchEvent))
  onUnmounted(() => socket.off('match', onMatchEvent))

  const deleteMatch = async (id: string) => {
    if (!(await confirm('这场比赛将被永久删除。'))) return false
    try {
      const res = await fetch(`${API_URL}/match/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('删除比赛失败')

      await fetchMatches() // Auto-refresh the list
      return true
    } catch (error) {
      console.error(error)
      return false
    }
  }

  const toggleCurrent = async (match: any) => {
    try {
      const id = match._id || match.id
      const res = await fetch(`${API_URL}/match/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...match, current: !match.current })
      })
      if (!res.ok) throw new Error('更新比赛失败')
      await fetchMatches()
    } catch (error) {
      console.error(error)
    }
  }

  return {
    matches,
    isLoading,
    fetchMatches,
    saveMatch,
    deleteMatch,
    toggleCurrent
  }
}
