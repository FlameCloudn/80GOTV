import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMatches } from './useMatches'
import { useTeams } from '../../teams/composables/useTeams'

const TABLE_HEADERS = [
  { key: 'matchup', label: '对阵' },
  { key: 'matchType', label: '赛制' },
  { key: 'score', label: '大比分' }
]

export function useMatchesView() {
  const router = useRouter()
  const { matches, isLoading, fetchMatches, deleteMatch, toggleCurrent } = useMatches()
  const { teams: availableTeams, fetchTeams } = useTeams()

  const teamMap = computed(() => {
    const map: Record<string, { logo: string; name: string }> = {}
    for (const t of availableTeams.value) map[t._id] = { logo: t.logo, name: t.name }
    return map
  })

  const getTeamLogo = (teamId: string | null): string | null => {
    if (!teamId) return null
    const team = teamMap.value[teamId]
    return team?.logo ? team.logo : null
  }

  const openEdit = (match: any) => {
    router.push(`/matches/${match._id || match.id}/edit`)
  }

  const openCreate = () => {
    router.push('/matches/new')
  }

  onMounted(() => {
    fetchMatches()
    fetchTeams()
  })

  return {
    matches,
    isLoading,
    tableHeaders: TABLE_HEADERS,
    getTeamLogo,
    deleteMatch,
    toggleCurrent,
    openEdit,
    openCreate
  }
}
