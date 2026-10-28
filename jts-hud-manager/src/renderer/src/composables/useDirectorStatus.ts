import { computed, ref } from 'vue'
import { API_URL } from '../index'
import { socket } from '../socket'
import { assetUrl, boLabel, teamAbbr } from '../utils/display'
import { logActivity } from './useActivityLog'
import { showToast, useToasts } from './useToasts'

// 导播状态（全软件共用一份）：顶部节目条、导播台、底部状态栏都从这里读，只轮询一次。
export type IntegrationStatus = {
  websiteUrl?: string
  selectedMatchId?: string | null
  importedMatchId?: number | null
  confirmedMatchId?: number | null
  forwardTargetMatchId?: number | null
  forwardClosedMatchId?: number | null
  forwardLiveData?: boolean
  forwarding?: boolean
  forwardAttempts?: number
  pendingResults?: number
  lastLocalDataAt?: string | null
  lastForwardAt?: string | null
  lastConfirmedAt?: string | null
  lastConnectionTestAt?: string | null
  lastSyncAt?: string | null
  lastError?: string | null
  restoredAt?: string | null
}
export type DirectorState = { scene: string; visible: boolean; hudClients: number }
export type MatchVeto = {
  teamId?: string
  mapName?: string
  type?: string
  score?: Record<string, number>
  winner?: string
  mapEnd?: boolean
}
export type CurrentMatch = {
  id?: string
  matchType?: string
  left?: { id?: string | null; wins?: number }
  right?: { id?: string | null; wins?: number }
  vetos?: MatchVeto[]
}
export type TeamInfo = { _id: string; name?: string; shortName?: string; logo?: string }
export type LiveGame = { mapName: string; round: number; mapPhase: string; ctScore: number; tScore: number }
export type SeriesTeam = { id: string; name: string; abbr: string; logo: string; wins: number }

export const SCENE_LABELS: Record<string, string> = {
  auto: '自动跟随',
  game: '比赛画面',
  pause_current: '战术暂停',
  pause_technical: '技术暂停',
  halftime: '中场',
  map_end: '单图结束',
  series_end: '整场结束'
}

const CS2_FRESH_MS = 5000
const WEBSITE_CHECK_FRESH_MS = 10 * 60 * 1000
const UPLOAD_CONFIRM_FRESH_MS = 10000

const integration = ref<IntegrationStatus | null>(null)
const director = ref<DirectorState>({ scene: 'auto', visible: true, hudClients: 0 })
const currentMatch = ref<CurrentMatch | null>(null)
const teams = ref<Record<string, TeamInfo>>({})
const apiOnline = ref(false)
const liveGame = ref<LiveGame | null>(null)
const lastSocketUpdate = ref(0)
const sceneSince = ref(Date.now())
const now = ref(Date.now())

let consumers = 0
let pollTimer: ReturnType<typeof setInterval> | null = null
let clockTimer: ReturnType<typeof setInterval> | null = null
let lastSeenError = ''
let lastSeenRestore = ''

const ageOf = (value?: string | null): number => {
  if (!value) return Number.POSITIVE_INFINITY
  const time = new Date(value).getTime()
  return Number.isFinite(time) ? now.value - time : Number.POSITIVE_INFINITY
}

const loadTeams = async (): Promise<void> => {
  try {
    const response = await fetch(`${API_URL}/teams`)
    if (!response.ok) return
    const list: TeamInfo[] = await response.json()
    teams.value = Object.fromEntries(list.map((team) => [team._id, team]))
  } catch {
    // 读不到战队时顶部比分条只显示“未知战队”，不打扰导播
  }
}

const applyDirectorState = (next: DirectorState): void => {
  const changed = next.scene !== director.value.scene || next.visible !== director.value.visible
  if (changed) sceneSince.value = Date.now()
  director.value = { scene: next.scene, visible: next.visible !== false, hudClients: Number(next.hudClients) || 0 }
}

const applyCurrentMatch = (match: CurrentMatch | null): void => {
  const valid = match && match.id ? match : null
  currentMatch.value = valid
  const ids = [valid?.left?.id, valid?.right?.id].filter((id): id is string => Boolean(id))
  if (ids.some((id) => !teams.value[id])) void loadTeams()
}

// 网站连接的后台报错、重启自动接上：有新情况才提示一次
const noticeIntegrationChanges = (value: IntegrationStatus): void => {
  const error = String(value.lastError || '')
  // 按钮刚报过同一个错（红色）就不再叠一条黄色的
  const alreadyShown = useToasts().toasts.value.some((toast) => toast.text === error)
  if (error && error !== lastSeenError && !alreadyShown) {
    showToast(error, 'warn', { key: 'website-link', title: '网站连接' })
    logActivity(error, 'warn')
  }
  lastSeenError = error
  const restored = String(value.restoredAt || '')
  if (restored && restored !== lastSeenRestore) {
    logActivity(`软件重启后已自动接上网站比赛 #${value.importedMatchId ?? ''}`)
  }
  lastSeenRestore = restored
}

export const refreshStatus = async (): Promise<void> => {
  try {
    const [integrationResponse, directorResponse, matchResponse] = await Promise.all([
      fetch(`${API_URL}/80gotv/status`),
      fetch(`${API_URL}/huds/default/director-status`),
      fetch(`${API_URL}/match/current`)
    ])
    apiOnline.value = integrationResponse.ok && directorResponse.ok
    if (integrationResponse.ok) {
      integration.value = await integrationResponse.json()
      noticeIntegrationChanges(integration.value || {})
    }
    if (directorResponse.ok) applyDirectorState(await directorResponse.json())
    applyCurrentMatch(matchResponse.ok ? await matchResponse.json().catch(() => null) : null)
  } catch {
    apiOnline.value = false
  }
}

const parseLiveGame = (raw: any): LiveGame | null => {
  const map = raw?.map
  if (!map?.name) return null
  return {
    mapName: String(map.name),
    round: Number(map.round) || 0,
    mapPhase: String(map.phase || ''),
    ctScore: Number(map.team_ct?.score) || 0,
    tScore: Number(map.team_t?.score) || 0
  }
}

const onGameUpdate = (raw: unknown): void => {
  lastSocketUpdate.value = Date.now()
  liveGame.value = parseLiveGame(raw)
}
const onMatchEvent = (): void => void refreshStatus()

// 发一个场景指令（按钮和快捷键共用同一个接口）
export type DirectorCommandDelivery = {
  scene: string
  delivery?: 'sent' | 'pending'
  hudClients?: number
}

export const sendDirectorCommand = async (command: string): Promise<DirectorCommandDelivery> => {
  const response = await fetch(`${API_URL}/huds/default/director-command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command })
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || !payload.ok) throw new Error(payload.error || '场景指令发送失败')
  return {
    scene: String(payload.scene || command),
    delivery: payload.delivery,
    hudClients: Number.isFinite(Number(payload.hudClients)) ? Number(payload.hudClients) : undefined
  }
}

// 软件外壳挂上时开始轮询；全部用到它的地方都关掉后才停
export const startDirectorStatus = (): void => {
  consumers += 1
  if (consumers > 1) return
  void refreshStatus()
  void loadTeams()
  pollTimer = setInterval(refreshStatus, 2000)
  clockTimer = setInterval(() => (now.value = Date.now()), 1000)
  socket.on('update', onGameUpdate)
  socket.on('match', onMatchEvent)
}

export const stopDirectorStatus = (): void => {
  consumers = Math.max(0, consumers - 1)
  if (consumers) return
  if (pollTimer) clearInterval(pollTimer)
  if (clockTimer) clearInterval(clockTimer)
  pollTimer = null
  clockTimer = null
  socket.off('update', onGameUpdate)
  socket.off('match', onMatchEvent)
}

const toSeriesTeam = (side?: { id?: string | null; wins?: number }): SeriesTeam => {
  const id = String(side?.id || '')
  const team = id ? teams.value[id] : undefined
  const name = team?.name || (id ? '未知战队' : '待定')
  return { id, name, abbr: teamAbbr(team?.name, team?.shortName), logo: assetUrl(team?.logo), wins: Number(side?.wins) || 0 }
}

const cs2Fresh = computed(() => {
  const socketAge = lastSocketUpdate.value ? now.value - lastSocketUpdate.value : Number.POSITIVE_INFINITY
  return Math.min(ageOf(integration.value?.lastLocalDataAt), socketAge) <= CS2_FRESH_MS
})
const selectedMatch = computed(() => integration.value?.selectedMatchId || null)
const websiteConfirmed = computed(() =>
  Boolean(selectedMatch.value && ageOf(integration.value?.lastConnectionTestAt) <= WEBSITE_CHECK_FRESH_MS)
)
const uploadConfirmed = computed(() => {
  const value = integration.value
  return Boolean(
    value?.lastConfirmedAt &&
      value.confirmedMatchId != null &&
      String(value.confirmedMatchId) === String(selectedMatch.value) &&
      ageOf(value.lastConfirmedAt) <= UPLOAD_CONFIRM_FRESH_MS
  )
})
const activeSceneLabel = computed(() =>
  director.value.visible ? SCENE_LABELS[director.value.scene] || director.value.scene : '全部隐藏'
)
const seriesTeams = computed(() => ({
  left: toSeriesTeam(currentMatch.value?.left),
  right: toSeriesTeam(currentMatch.value?.right)
}))
const currentBo = computed(() => boLabel(currentMatch.value?.matchType) || 'BO')

export const useDirectorStatus = () => ({
  integration,
  director,
  currentMatch,
  teams,
  apiOnline,
  liveGame,
  lastSocketUpdate,
  sceneSince,
  now,
  cs2Fresh,
  selectedMatch,
  websiteConfirmed,
  uploadConfirmed,
  activeSceneLabel,
  seriesTeams,
  currentBo,
  refreshStatus,
  sendDirectorCommand,
  ageOf
})
