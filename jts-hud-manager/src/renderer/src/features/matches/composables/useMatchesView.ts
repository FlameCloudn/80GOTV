import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMatches } from './useMatches'
import { useTeams } from '../../teams/composables/useTeams'
import { useDirectorStatus } from '../../../composables/useDirectorStatus'
import { assetUrl, boLabel, mapLabel, teamAbbr } from '../../../utils/display'

export type MatchFilter = 'all' | 'website' | 'manual'
export type MatchSideCard = { name: string; abbr: string; logo: string; wins: number; tbd: boolean }
export type MapChip = { key: string; name: string; score: string; state: '' | 'live' | 'todo' }
export type MatchCard = {
  id: string
  raw: any
  current: boolean
  bo: string
  websiteId: string
  left: MatchSideCard
  right: MatchSideCard
  maps: MapChip[]
}

const websiteIdOf = (id: string): string => /^80gotv-match-(\d+)$/.exec(id)?.[1] || ''

export function useMatchesView() {
  const router = useRouter()
  const { matches, isLoading, fetchMatches, deleteMatch, toggleCurrent } = useMatches()
  const { teams, fetchTeams } = useTeams()
  const { liveGame } = useDirectorStatus()
  const filter = ref<MatchFilter>('all')
  const search = ref('')

  const teamById = computed(() => Object.fromEntries(teams.value.map((team: any) => [team._id, team])))

  const sideCard = (side: any): MatchSideCard => {
    const team = side?.id ? teamById.value[side.id] : null
    return {
      name: team?.name || (side?.id ? '未知战队' : '待定'),
      abbr: team ? teamAbbr(team.name, team.shortName) : '?',
      logo: assetUrl(team?.logo),
      wins: Number(side?.wins) || 0,
      tbd: !team
    }
  }

  // 地图小标签：打完的写比分，正在打的标红，没打的变灰（ban 掉的图不显示）
  const mapChips = (match: any): MapChip[] => {
    const leftId = match.left?.id
    const rightId = match.right?.id
    const liveMap = match.current ? String(liveGame.value?.mapName || '') : ''
    return (match.vetos || [])
      .filter((veto: any) => veto?.mapName && veto.type !== 'ban')
      .map((veto: any, index: number) => {
        const left = leftId ? veto.score?.[leftId] : undefined
        const right = rightId ? veto.score?.[rightId] : undefined
        const hasScore = left != null && right != null && (Number(left) > 0 || Number(right) > 0)
        const live = Boolean(liveMap && !veto.mapEnd && liveMap.includes(veto.mapName))
        const state: MapChip['state'] = live ? 'live' : veto.mapEnd || hasScore ? '' : 'todo'
        return { key: `${veto.mapName}-${index}`, name: mapLabel(veto.mapName), score: hasScore ? `${left}:${right}` : '', state }
      })
  }

  const cards = computed<MatchCard[]>(() =>
    matches.value.map((match: any) => {
      const id = String(match._id || match.id || '')
      return {
        id, raw: match, current: Boolean(match.current), bo: boLabel(match.matchType) || 'BO1',
        websiteId: websiteIdOf(id), left: sideCard(match.left), right: sideCard(match.right), maps: mapChips(match)
      }
    })
  )

  const counts = computed<Record<MatchFilter, number>>(() => ({
    all: cards.value.length,
    website: cards.value.filter((card) => card.websiteId).length,
    manual: cards.value.filter((card) => !card.websiteId).length
  }))

  const visibleCards = computed(() => {
    const query = search.value.trim().toLowerCase()
    return cards.value
      .filter((card) => filter.value === 'all' || (filter.value === 'website') === Boolean(card.websiteId))
      .filter((card) => !query || `${card.left.name} ${card.right.name}`.toLowerCase().includes(query))
      .sort((a, b) => Number(b.current) - Number(a.current))
  })

  const openEdit = (card: MatchCard) => router.push(`/matches/${card.id}/edit`)
  const openCreate = () => router.push('/matches/new')

  onMounted(() => {
    void fetchMatches()
    void fetchTeams()
  })

  return { isLoading, filter, search, counts, visibleCards, deleteMatch, toggleCurrent, openEdit, openCreate }
}
