import { ref, computed, onMounted } from 'vue'
import { usePlayers } from './usePlayers'
import { useTeams } from '../../teams/composables/useTeams'
import { usePlayerExcel } from '../../../composables/useExcel'

const TABLE_HEADERS = [
  { key: 'avatar', label: '头像' },
  { key: 'username', label: '游戏昵称', sortable: true },
  { key: 'firstName', label: '名字', sortable: true },
  { key: 'lastName', label: '姓氏', sortable: true },
  { key: 'team', label: '战队', sortable: true }
]

const getEmptyForm = () => ({
  firstName: '',
  lastName: '',
  username: '',
  avatar: '',
  country: '',
  steamid: '',
  team: '',
  isCoach: false,
  extra: {}
})

export function usePlayersView() {
  const {
    players,
    isLoading: isPlayersLoading,
    fetchPlayers,
    savePlayer,
    deletePlayer,
    deleteManyPlayers
  } = usePlayers()
  const { teams: availableTeams, fetchTeams } = useTeams()
  const { exportPlayers, importPlayers } = usePlayerExcel(fetchPlayers)

  // --- Sort ---
  const sortKey = ref('username')
  const sortDir = ref<'asc' | 'desc'>('asc')

  const handleSort = ({ key, dir }: { key: string; dir: 'asc' | 'desc' }) => {
    sortKey.value = key
    sortDir.value = dir
  }

  // --- Team Resolution ---
  const teamMap = computed(() => {
    const map: Record<string, { name: string; logo: string; shortName: string }> = {}
    for (const t of availableTeams.value)
      map[t._id] = { name: t.name, logo: t.logo, shortName: t.shortName }
    return map
  })

  const getTeamName = (teamId: string) => teamMap.value[teamId]?.name ?? ''

  // --- Sorted Players ---
  const sortedPlayers = computed(() => {
    const list = [...players.value]
    const dir = sortDir.value === 'asc' ? 1 : -1
    return list.sort((a, b) => {
      let aVal = ''
      let bVal = ''
      if (sortKey.value === 'team') {
        aVal = getTeamName(a.team)
        bVal = getTeamName(b.team)
      } else {
        aVal = (a[sortKey.value] ?? '').toLowerCase()
        bVal = (b[sortKey.value] ?? '').toLowerCase()
      }
      return aVal < bVal ? -dir : aVal > bVal ? dir : 0
    })
  })

  // --- Selection ---
  const selectedPlayerIds = ref<string[]>([])

  const handleSelectionChange = (ids: string[]) => {
    selectedPlayerIds.value = ids
  }

  const handleDeleteSelected = async () => {
    await deleteManyPlayers(selectedPlayerIds.value)
    selectedPlayerIds.value = []
  }

  const handleDeleteAll = async () => {
    await deleteManyPlayers(players.value.map((p) => p._id))
    selectedPlayerIds.value = []
  }

  // --- Modal ---
  const isModalOpen = ref(false)
  const isEditing = ref(false)
  const editingId = ref<string | null>(null)
  const formData = ref(getEmptyForm())

  const handleSave = async (payload: any, file: File | null) => {
    await savePlayer(payload, isEditing.value ? editingId.value : null, file)
    isModalOpen.value = false
  }

  const openCreateModal = () => {
    isEditing.value = false
    editingId.value = null
    formData.value = getEmptyForm()
    isModalOpen.value = true
  }

  const openEditModal = (player: any) => {
    isEditing.value = true
    editingId.value = player._id
    formData.value = { ...player, team: player.team ?? '' }
    isModalOpen.value = true
  }

  onMounted(() => {
    fetchPlayers()
    fetchTeams()
  })

  return {
    // Data
    players,
    availableTeams,
    isPlayersLoading,
    sortedPlayers,
    teamMap,
    tableHeaders: TABLE_HEADERS,
    // Sort
    sortKey,
    sortDir,
    handleSort,
    // Selection
    selectedPlayerIds,
    handleSelectionChange,
    handleDeleteSelected,
    handleDeleteAll,
    // Modal
    isModalOpen,
    isEditing,
    formData,
    handleSave,
    openCreateModal,
    openEditModal,
    // Excel
    exportPlayers,
    importPlayers,
    // CRUD
    deletePlayer
  }
}
