import { ref, computed, onMounted, onUnmounted } from 'vue'
import { io, Socket } from 'socket.io-client'
import { API_URL } from '../../../index'
import type { CSGORaw } from 'csgogsi'
import { usePlayers } from '../../players/composables/usePlayers'
import { useTeams } from '../../teams/composables/useTeams'

export interface GsiPlayer {
  steamid: string
  name: string
  side: string
  stats: any
  inDB: boolean
  isCoach: boolean
}

const getEmptyForm = () => ({
  firstName: '',
  lastName: '',
  username: '',
  avatar: '',
  country: '',
  steamid: '',
  team: '',
  extra: {}
})

export function useLiveView() {
  const { players: dbPlayers, fetchPlayers, savePlayer } = usePlayers()
  const { teams: availableTeams, fetchTeams } = useTeams()

  const socket = ref<Socket | null>(null)
  const isConnected = ref(false)
  const gameState = ref<CSGORaw | null>(null)

  // --- GSI Parsing ---
  const allPlayersList = computed((): GsiPlayer[] => {
    if (!gameState.value?.allplayers) return []
    return Object.entries(gameState.value.allplayers).map(([steamid, p]: [string, any]) => ({
      steamid,
      name: p.name,
      side: p.team,
      stats: p.match_stats,
      inDB: dbPlayers.value.some((db) => db.steamid === steamid),
      isCoach: dbPlayers.value.some((db) => db.steamid === steamid && db.isCoach)
    }))
  })

  const ctPlayers = computed(() => allPlayersList.value.filter((p) => p.side === 'CT'))
  const tPlayers = computed(() => allPlayersList.value.filter((p) => p.side === 'T'))

  // --- Player Modal ---
  const isModalOpen = ref(false)
  const isEditing = ref(false)
  const editingId = ref<string | null>(null)
  const formData = ref(getEmptyForm())

  const handleSave = async (payload: any, file: File | null) => {
    try {
      await savePlayer(payload, isEditing.value ? editingId.value : null, file)
      isModalOpen.value = false
    } catch (error) {
      console.error('Failed to save player from LiveView:', error)
    }
  }

  const openEditModal = (gsiPlayer: GsiPlayer) => {
    const existingPlayer = dbPlayers.value.find((p) => p.steamid === gsiPlayer.steamid)
    if (existingPlayer) {
      isEditing.value = true
      editingId.value = existingPlayer._id
      formData.value = {
        ...existingPlayer,
        username: gsiPlayer.name,
        team: existingPlayer.team ?? ''
      }
    } else {
      isEditing.value = false
      editingId.value = null
      formData.value = { ...getEmptyForm(), steamid: gsiPlayer.steamid, username: gsiPlayer.name }
    }
    isModalOpen.value = true
  }

  // --- Add All to Team Modal ---
  const isAddAllModalOpen = ref(false)
  const addAllSide = ref<'CT' | 'T' | null>(null)
  const selectedTeamForAddAll = ref('')
  const isAddingAll = ref(false)

  const openAddAllModal = (side: 'CT' | 'T') => {
    addAllSide.value = side
    selectedTeamForAddAll.value = ''
    isAddAllModalOpen.value = true
  }

  const handleAddAll = async () => {
    if (!selectedTeamForAddAll.value || !addAllSide.value) return
    const playersToAdd = addAllSide.value === 'CT' ? ctPlayers.value : tPlayers.value
    isAddingAll.value = true
    try {
      for (const gsiPlayer of playersToAdd) {
        const existingPlayer = dbPlayers.value.find((p) => p.steamid === gsiPlayer.steamid)
        const payload = existingPlayer
          ? { ...existingPlayer, username: gsiPlayer.name, team: selectedTeamForAddAll.value }
          : {
              firstName: '',
              lastName: '',
              username: gsiPlayer.name,
              avatar: '',
              country: '',
              steamid: gsiPlayer.steamid,
              team: selectedTeamForAddAll.value,
              extra: {}
            }
        await savePlayer(payload, existingPlayer ? existingPlayer._id : null, null)
      }
      isAddAllModalOpen.value = false
    } catch (error) {
      console.error('Failed to add all players:', error)
    } finally {
      isAddingAll.value = false
    }
  }

  onMounted(async () => {
    await Promise.all([fetchPlayers(), fetchTeams()])
    const socketUrl = API_URL.replace('/api', '')
    socket.value = io(socketUrl)
    socket.value.on('connect', () => {
      isConnected.value = true
    })
    socket.value.on('disconnect', () => {
      isConnected.value = false
    })
    socket.value.on('update', (data: CSGORaw) => {
      gameState.value = data
    })
  })

  onUnmounted(() => {
    if (socket.value) socket.value.disconnect()
  })

  return {
    // Connection
    isConnected,
    gameState,
    // Players
    ctPlayers,
    tPlayers,
    availableTeams,
    // Player modal
    isModalOpen,
    isEditing,
    formData,
    handleSave,
    openEditModal,
    // Add all modal
    isAddAllModalOpen,
    addAllSide,
    selectedTeamForAddAll,
    isAddingAll,
    openAddAllModal,
    handleAddAll
  }
}
