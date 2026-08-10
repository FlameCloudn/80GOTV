import { Router, Request, Response } from 'express'
import fs from 'fs/promises'
import path from 'path'
import { Server } from 'socket.io'
import { dbAll, dbGet, dbRun } from '../database/sqlite'
import { getSettings } from '../domains/settings/settings.routes'
import { Veto } from '../domains/matches/match.types'
import { downloadSteamAvatar, fetchSteamPublicProfile } from '../domains/players/steam-profile.service'
import { uploadsPath } from '../utils/multer'

type WebsitePlayer = {
  id: number
  slot?: number
  nickname: string
  group_username: string
  steam_id: string
  avatar: string
  is_bashizhong_student: number | null
  role?: 'substitute'
}

type WebsiteTeam = {
  id: number | null
  source_id?: string
  name: string
  short_name: string
  logo: string
  series_score: number
  players: WebsitePlayer[]
}

type WebsiteMap = {
  slot: number
  name: string
  team1_score: number
  team2_score: number
  picked_by: string
  opening_ct_team?: 't1' | 't2' | ''
  opening_side_source?: string
}

type WebsiteMatch = {
  id: number
  status: string
  event: { id: number | null; name: string; short_name: string }
  stage: string
  bo: string
  match_time: string
  team1: WebsiteTeam
  team2: WebsiteTeam
  substitutes?: WebsitePlayer[]
  substitute_count?: number
  maps: WebsiteMap[]
  bp?: Record<string, any> | null
  bp_revision?: number
  roster_revision?: string
  roster_locked?: boolean
  roster_issues?: string[]
  ready_for_start?: boolean
}

type WebsiteEvent = {
  source_type: 'event'
  id: number
  name: string
  short_name: string
  status: string
  start_date: string
  end_date: string
  teams: WebsiteTeam[]
  team_count: number
  substitutes: WebsitePlayer[]
  substitute_count: number
}

type WebsitePlayerPresentation = {
  name: string
  avatar: string
}

// The website nickname is the broadcast name. Keep group usernames out of HUD payloads.
const websitePlayerPresentation = new Map<string, WebsitePlayerPresentation>()

const broadcastPlayerName = (value: string): string => {
  const name = String(value || '').trim()
  const duplicate = name.match(/^(.+?)@(.+)$/)
  if (duplicate && duplicate[1].trim().toLocaleLowerCase() === duplicate[2].trim().toLocaleLowerCase()) {
    return duplicate[1].trim()
  }
  return name
}

export const getWebsitePlayerPresentation = (steamid: string) =>
  websitePlayerPresentation.get(String(steamid || '').trim())

export const applyWebsitePlayerPresentation = (payload: Record<string, any>): Record<string, any> => {
  const allplayers = payload?.allplayers
  if (!allplayers || typeof allplayers !== 'object' || websitePlayerPresentation.size === 0) return payload
  let changed = false
  const presentedPlayers = Object.fromEntries(
    Object.entries(allplayers).map(([steamid, player]) => {
      const presentation = websitePlayerPresentation.get(steamid)
      if (!presentation || !player || typeof player !== 'object') return [steamid, player]
      changed = true
      const currentPlayer = player as Record<string, any>
      return [
        steamid,
        {
          ...currentPlayer,
          name: presentation.name || currentPlayer.name,
          ...(presentation.avatar ? { avatar: presentation.avatar } : {})
        }
      ]
    })
  )
  return changed ? { ...payload, allplayers: presentedPlayers } : payload
}

type WebsiteSource = {
  key: string
  source_type: 'match' | 'event'
  label: string
  id: number
}

type SyncStatus = {
  lastSyncAt: string | null
  lastBpSyncAt: string | null
  lastBpSyncError: string | null
  lastForwardAt: string | null
  lastLocalDataAt: string | null
  lastConfirmedAt: string | null
  lastConnectionTestAt: string | null
  lastResultAt: string | null
  lastError: string | null
  importedMatchId: number | null
  confirmedMatchId: number | null
  forwardTargetMatchId: number | null
  forwardGeneration: number
  forwarding: boolean
  forwardAttempts: number
  pendingResults: number
  sessionId: string | null
  frameSeq: number
}

const status: SyncStatus = {
  lastSyncAt: null,
  lastBpSyncAt: null,
  lastBpSyncError: null,
  lastForwardAt: null,
  lastLocalDataAt: null,
  lastConfirmedAt: null,
  lastConnectionTestAt: null,
  lastResultAt: null,
  lastError: null,
  importedMatchId: null,
  confirmedMatchId: null,
  forwardTargetMatchId: null,
  forwardGeneration: 0,
  forwarding: false,
  forwardAttempts: 0,
  pendingResults: 0,
  sessionId: null,
  frameSeq: 0
}

const normalizeWebsiteUrl = (value: string): string => {
  const trimmed = String(value || '').trim().replace(/\/+$/, '')
  const parsed = new URL(trimmed)
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('网站地址必须以 http:// 或 https:// 开头')
  }
  if (parsed.username || parsed.password) throw new Error('网站地址不能包含账号或密码')
  return parsed.origin
}

const websiteAssetUrl = (baseUrl: string, value: string): string => {
  if (!value) return ''
  return new URL(value, `${baseUrl}/`).toString()
}

const fetchJson = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(10000),
    headers: { Accept: 'application/json', ...(options.headers || {}) }
  })
  const payload = (await response.json().catch(() => null)) as T | null
  if (!response.ok || !payload) {
    const endpoint = new URL(url).pathname
    if (response.status === 404) {
      throw new Error(`网站接口尚未部署或地址错误（HTTP 404）：${endpoint}`)
    }
    const message = (payload as any)?.error || (payload as any)?.msg || `HTTP ${response.status}`
    throw new Error(`${message}（${endpoint}）`)
  }
  return payload
}

type WebsiteConnectionCheck = {
  ok: boolean
  match_id: number
  team1_name: string
  team2_name: string
  server_time: string
  roster_locked?: boolean
  roster_issues?: string[]
  ready_for_start?: boolean
}

type WebsiteLiveReceipt = {
  ok: boolean
  match_id: number
}

const readSelectedMatchId = (value: unknown): number | null => {
  const selected = String(value || '').trim()
  if (!/^\d+$/.test(selected)) return null
  const id = Number(selected)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

const requireMatchingReceipt = (payload: WebsiteLiveReceipt, expectedMatchId: number) => {
  if (!payload?.ok || Number(payload.match_id) !== expectedMatchId) {
    throw new Error('网站确认的比赛不一致，已停止本次实时数据上传')
  }
}

const checkWebsiteConnection = async (
  baseUrl: string,
  token: string,
  expectedMatchId: number
): Promise<WebsiteConnectionCheck> => {
  if (!token) throw new Error('请填写网站 GSI 密钥')
  const payload = await fetchJson<WebsiteConnectionCheck>(
    `${baseUrl}/api/broadcast/matches/${expectedMatchId}/connection-test`,
    { headers: { 'X-80GOTV-Token': token } }
  )
  if (!payload.ok || Number(payload.match_id) !== expectedMatchId) {
    throw new Error('网站连接检查返回了错误的比赛')
  }
  if (payload.roster_locked === false) {
    const issues =
      Array.isArray(payload.roster_issues) && payload.roster_issues.length
        ? `（${payload.roster_issues.join('、')}）`
        : ''
    throw new Error(`网站本场十人名单尚未锁定${issues}`)
  }
  if (payload.ready_for_start === false) throw new Error('网站 BP 尚未完成，暂不能开赛')
  return payload
}

const downloadAsset = async (
  baseUrl: string,
  remotePath: string,
  prefix: string
): Promise<string> => {
  if (!remotePath) return ''
  const url = websiteAssetUrl(baseUrl, remotePath)
  const response = await fetch(url, { signal: AbortSignal.timeout(10000) })
  if (!response.ok) throw new Error(`图片下载失败：HTTP ${response.status}`)
  const data = Buffer.from(await response.arrayBuffer())
  if (data.length > 5 * 1024 * 1024) throw new Error('图片超过 5 MB，已跳过')

  const remoteExt = path.extname(new URL(url).pathname).toLowerCase()
  const allowed = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'])
  const extension = allowed.has(remoteExt) ? remoteExt : '.png'
  const filename = `${prefix}${extension}`
  await fs.writeFile(path.join(uploadsPath, filename), data)
  return `/api/uploads/${filename}`
}

const teamId = (team: WebsiteTeam, side: number): string =>
  team.source_id
    ? `80gotv-team-${team.source_id}`
    : team.id
      ? `80gotv-team-${team.id}`
      : `80gotv-temp-team-${side}`

const playerId = (id: number): string => `80gotv-player-${id}`
const matchId = (id: number): string => `80gotv-match-${id}`

const normalizedTeamName = (value: string): string =>
  String(value || '')
    .normalize('NFKC')
    .trim()
    .toLowerCase()
    .replace(/^team\s+/, '')
    .replace(/[^\p{L}\p{N}]+/gu, '')

const fillMissingTeamLogo = (team: WebsiteTeam, eventTeams: WebsiteTeam[]): WebsiteTeam => {
  if (team.logo) return team
  const key = normalizedTeamName(team.name)
  if (!key) return team
  const registrationTeam = eventTeams.find(
    (candidate) => normalizedTeamName(candidate.name) === key && candidate.logo
  )
  return registrationTeam ? { ...team, logo: registrationTeam.logo } : team
}

const fillMatchLogosFromEvent = async (
  baseUrl: string,
  match: WebsiteMatch
): Promise<WebsiteMatch> => {
  if ((match.team1.logo && match.team2.logo) || !match.event?.id) return match
  try {
    const payload = await fetchJson<{ ok: boolean; event: WebsiteEvent }>(
      `${baseUrl}/api/broadcast/events/${encodeURIComponent(match.event.id)}`
    )
    if (!payload.ok || !payload.event?.teams?.length) return match
    return {
      ...match,
      team1: fillMissingTeamLogo(match.team1, payload.event.teams),
      team2: fillMissingTeamLogo(match.team2, payload.event.teams)
    }
  } catch (error) {
    console.warn('[80GOTV] event team logos unavailable:', error)
    return match
  }
}

const mapName = (value: string): string => {
  const clean = String(value || '').trim().toLowerCase()
  return clean ? (clean.startsWith('de_') ? clean : `de_${clean}`) : ''
}

const buildVetos = (match: WebsiteMatch): Veto[] => {
  const leftId = teamId(match.team1, 1)
  const rightId = teamId(match.team2, 2)
  const picks = Array.isArray(match.bp?.picks) ? match.bp?.picks : []
  const bans = Array.isArray(match.bp?.action_log)
    ? match.bp.action_log.filter((entry: any) => entry?.action === 'ban')
    : []

  const vetoes: Veto[] = bans
    .filter((entry: any) => entry?.map)
    .map((entry: any): Veto => ({
      teamId: entry.team === 't2' ? rightId : leftId,
      mapName: mapName(entry.map),
      side: 'NO',
      type: 'ban',
      mapEnd: false
    }))

  for (const map of match.maps || []) {
    if (!map.name) continue
    const pick = picks.find((entry: any) => mapName(entry?.map) === mapName(map.name))
    const pickedBy = map.picked_by || pick?.picked_by || ''
    const picker = pickedBy === 't2' ? rightId : pickedBy === 't1' ? leftId : ''
    const isDecider = !picker
    const mapFinished = Number(map.team1_score) > 0 || Number(map.team2_score) > 0
    // The website's side field is only a cross-check for a decider. TGPro's
    // stable post-knife 5v5 frame is the authority for its opening side.
    const openingCtTeam = isDecider ? '' : map.opening_ct_team || ''
    const winner = mapFinished
      ? Number(map.team1_score) > Number(map.team2_score)
        ? leftId
        : rightId
      : ''
    vetoes.push({
      teamId: picker,
      mapName: mapName(map.name),
      side: pick?.side === 'CT' || pick?.side === 'T' ? pick.side : 'NO',
      type: picker ? 'pick' : 'decider',
      reverseSide: false,
      openingCtTeamId: openingCtTeam === 't1' ? leftId : openingCtTeam === 't2' ? rightId : undefined,
      sideSource: !isDecider && map.opening_side_source === 'website_bp' ? 'website_bp' : 'unknown',
      rounds: [],
      score: { [leftId]: Number(map.team1_score) || 0, [rightId]: Number(map.team2_score) || 0 },
      winner,
      mapEnd: mapFinished
    })
  }

  // During an active BP the website state may contain a pick before the
  // completed BP has been written into map1..map5. Include those picks now so
  // the local HUD does not lag behind the website until the final step.
  const knownMaps = new Set(vetoes.map((veto) => veto.mapName))
  for (const pick of picks) {
    const normalizedMap = mapName(pick?.map)
    if (!normalizedMap || knownMaps.has(normalizedMap)) continue
    const pickedBy = pick?.picked_by || ''
    const picker = pickedBy === 't2' ? rightId : pickedBy === 't1' ? leftId : ''
    const isDecider = !picker
    const sideTeam = pick?.side_team === 't2' ? rightId : pick?.side_team === 't1' ? leftId : ''
    vetoes.push({
      teamId: picker || sideTeam,
      mapName: normalizedMap,
      side: pick?.side === 'CT' || pick?.side === 'T' ? pick.side : 'NO',
      type: picker ? 'pick' : 'decider',
      reverseSide: false,
      openingCtTeamId: !isDecider && pick?.opening_ct_team === 't1' ? leftId : !isDecider && pick?.opening_ct_team === 't2' ? rightId : undefined,
      sideSource: !isDecider && pick?.opening_ct_team ? 'website_bp' : 'unknown',
      rounds: [],
      score: { [leftId]: 0, [rightId]: 0 },
      winner: '',
      mapEnd: false
    })
    knownMaps.add(normalizedMap)
  }
  return vetoes
}

const mergeWebsiteVetos = (existing: Veto[], incoming: Veto[]): Veto[] => {
  const previous = new Map(existing.map((veto) => [veto.mapName, veto]))
  const merged = incoming.map((next) => {
    const old = previous.get(next.mapName)
    if (!old) return next
    return {
      ...old,
      ...next,
      // The website is authoritative for BP decisions, while local GSI is
      // authoritative for live rounds and player stats.
      teamId: next.teamId || old.teamId,
      side: next.side !== 'NO' ? next.side : old.side,
      type: next.type || old.type,
      // Once a match is synced from the website, an old manual toggle is not
      // allowed to override the BP opening side.
      reverseSide: next.sideSource === 'website_bp' ? false : old.reverseSide ?? next.reverseSide,
      openingCtTeamId: next.openingCtTeamId || old.openingCtTeamId,
      sideSource:
        next.sideSource === 'unknown' && old.sideSource === 'tgpro_stable_gsi'
          ? old.sideSource
          : next.sideSource || old.sideSource,
      rounds: old.rounds?.length ? old.rounds : next.rounds,
      playerStats: old.playerStats,
      score: next.mapEnd ? { ...(old.score || {}), ...(next.score || {}) } : old.score || next.score,
      winner: next.winner || old.winner,
      mapEnd: Boolean(next.mapEnd || old.mapEnd)
    }
  })
  const incomingMaps = new Set(incoming.map((veto) => veto.mapName))
  // Do not discard a map result that GSI has already collected while the
  // website is still catching up with the latest BP snapshot.
  return merged.concat(existing.filter((veto) => !incomingMaps.has(veto.mapName)))
}

let websiteBpPollTimer: NodeJS.Timeout | null = null
let websiteBpPollInFlight = false

export const syncWebsiteBp = async (): Promise<boolean> => {
  const settings = await getSettings()
  const selected = readSelectedMatchId(settings.websiteMatchId)
  if (!selected) return false

  const baseUrl = normalizeWebsiteUrl(settings.websiteUrl)
  const payload = await fetchJson<{ ok: boolean; match: WebsiteMatch }>(
    `${baseUrl}/api/broadcast/matches/${encodeURIComponent(selected)}`
  )
  if (!payload.ok || !payload.match?.bp) return false
  if (payload.match.roster_locked === false) {
    status.lastBpSyncError = `网站名单未锁定：${(payload.match.roster_issues || []).join(', ') || '需要两队各五人'}`
    return false
  }
  if (payload.match.ready_for_start === false) {
    status.lastBpSyncError = '网站 BP 尚未完成，导播暂不进入正式状态'
    return false
  }

  const local = await dbGet('SELECT id, current, vetos FROM matches WHERE id=?', [matchId(selected)])
  if (!local || Number(local.current) !== 1) return false

  let existing: Veto[] = []
  try {
    existing = local.vetos ? JSON.parse(local.vetos) : []
  } catch {
    existing = []
  }
  const merged = mergeWebsiteVetos(Array.isArray(existing) ? existing : [], buildVetos(payload.match))
  const changed = JSON.stringify(existing) !== JSON.stringify(merged)
  if (changed) {
    await dbRun('UPDATE matches SET vetos=? WHERE id=?', [JSON.stringify(merged), matchId(selected)])
    console.log(`[80GOTV] BP synchronized for match ${selected}`)
  }
  status.lastBpSyncAt = new Date().toISOString()
  status.lastBpSyncError = null
  return changed
}

const startWebsiteBpPolling = (io: Server) => {
  if (websiteBpPollTimer) return
  const run = async () => {
    if (websiteBpPollInFlight) return
    websiteBpPollInFlight = true
    try {
      if (await syncWebsiteBp()) io.emit('match')
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (status.lastBpSyncError !== message) console.warn(`[80GOTV] BP sync paused: ${message}`)
      status.lastBpSyncError = message
    } finally {
      websiteBpPollInFlight = false
    }
  }
  void run()
  websiteBpPollTimer = setInterval(run, 3000)
  websiteBpPollTimer.unref?.()
}

const upsertTeam = async (baseUrl: string, team: WebsiteTeam, side: number): Promise<string> => {
  const id = teamId(team, side)
  let logo = ''
  if (team.logo) {
    try {
      logo = await downloadAsset(baseUrl, team.logo, id)
      console.log(`[80GOTV] Team logo synced: ${team.name} -> ${path.basename(logo)}`)
    } catch (error) {
      console.warn(`[80GOTV] ${team.name} logo skipped:`, error)
    }
  }
  await dbRun(
    `INSERT INTO teams (_id, name, country, shortName, logo, extra)
     VALUES (?, ?, '', ?, ?, ?)
     ON CONFLICT(_id) DO UPDATE SET
       name=excluded.name, shortName=excluded.shortName, logo=excluded.logo, extra=excluded.extra`,
    [
      id,
      team.name || 'TBD',
      team.short_name || 'TBD',
      logo,
      JSON.stringify({
        source: '80gotv',
        websiteTeamId: team.id,
        websiteSourceId: team.source_id || null
      })
    ]
  )
  return id
}

const upsertPlayer = async (
  baseUrl: string,
  player: WebsitePlayer,
  localTeamId: string | null,
  isSubstitute = false
): Promise<string> => {
  const stableId = playerId(player.id)
  const existing = player.steam_id
    ? await dbGet('SELECT _id, avatar FROM players WHERE steamid=? LIMIT 1', [player.steam_id])
    : null
  const id = existing?._id || stableId
  let avatar = ''
  if (player.avatar) {
    try {
      avatar = await downloadAsset(baseUrl, player.avatar, stableId)
      console.log(`[80GOTV] Player avatar synced: ${player.nickname} -> ${path.basename(avatar)}`)
    } catch (error) {
      console.warn(`[80GOTV] ${player.nickname} avatar skipped:`, error)
    }
  }
  if (!avatar && player.steam_id) {
    try {
      const profile = await fetchSteamPublicProfile(player.steam_id)
      if (profile.avatarUrl) avatar = await downloadSteamAvatar(player.steam_id, profile.avatarUrl)
    } catch (error) {
      console.warn(`[80GOTV] ${player.nickname} Steam avatar skipped:`, error)
    }
  }
  if (!avatar) avatar = existing?.avatar || ''
  await dbRun(
    `INSERT INTO players
       (_id, firstName, lastName, username, avatar, country, steamid, team, isCoach, extra)
     VALUES (?, '', ?, ?, ?, '', ?, ?, 0, ?)
     ON CONFLICT(_id) DO UPDATE SET
       lastName=excluded.lastName, username=excluded.username, avatar=excluded.avatar,
       steamid=excluded.steamid, team=excluded.team, isCoach=0, extra=excluded.extra`,
    [
      id,
      '',
      player.nickname || `Player ${player.id}`,
      avatar,
      player.steam_id || null,
      localTeamId,
      JSON.stringify({
        source: '80gotv',
        websitePlayerId: player.id,
        groupUsername: player.group_username || '',
        isBashizhongStudent: player.is_bashizhong_student,
        isSubstitute,
        matchSlot: player.slot || null
      })
    ]
  )
  if (player.steam_id && player.nickname) {
    websitePlayerPresentation.set(player.steam_id, { name: broadcastPlayerName(player.nickname), avatar })
  }
  return id
}

const syncHudWebsiteConfig = async (baseUrl: string, selectedMatchId: number) => {
  const rows = await dbAll('SELECT hud_id, config_data FROM hud_configs')
  for (const row of rows) {
    let config: Record<string, any>
    try {
      config = JSON.parse(row.config_data || '{}')
    } catch {
      config = {}
    }
    if (!config.broadcast_settings) continue
    config.broadcast_settings = {
      ...config.broadcast_settings,
      api_base: baseUrl,
      match_id: String(selectedMatchId)
    }
    await dbRun('UPDATE hud_configs SET config_data=? WHERE hud_id=?', [
      JSON.stringify(config),
      row.hud_id
    ])
  }
}

export const listWebsiteSources = async (): Promise<WebsiteSource[]> => {
  const settings = await getSettings()
  const baseUrl = normalizeWebsiteUrl(settings.websiteUrl)
  const matchPayload = await fetchJson<{ ok: boolean; matches: WebsiteMatch[] }>(
    `${baseUrl}/api/broadcast/matches`
  )
  let events: WebsiteEvent[] = []
  try {
    const eventPayload = await fetchJson<{ ok: boolean; events: WebsiteEvent[] }>(
      `${baseUrl}/api/broadcast/events`
    )
    events = eventPayload.events || []
  } catch (error) {
    console.warn('[80GOTV] event roster list unavailable:', error)
  }
  const matches = (matchPayload.matches || []).sort((a, b) => {
    const aLive = a.status === 'live' ? 0 : 1
    const bLive = b.status === 'live' ? 0 : 1
    if (aLive !== bLive) return aLive - bLive
    return String(a.match_time || '').localeCompare(String(b.match_time || ''))
  })
  return [
    ...matches.map((match) => ({
      key: String(match.id),
      source_type: 'match' as const,
      id: match.id,
      label: `#${match.id} ${match.team1.name} vs ${match.team2.name} · ${match.event.name}`
    })),
    ...events.map((event) => ({
      key: `event:${event.id}`,
      source_type: 'event' as const,
      id: event.id,
      label: `${event.name} · ${event.team_count} 支队伍 · ${event.substitute_count} 名替补`
    }))
  ]
}

const syncWebsiteEvent = async (baseUrl: string, eventId: string): Promise<WebsiteEvent> => {
  const payload = await fetchJson<{ ok: boolean; event: WebsiteEvent }>(
    `${baseUrl}/api/broadcast/events/${encodeURIComponent(eventId)}`
  )
  if (!payload.ok || !payload.event) throw new Error('网站没有可同步的赛事名单')
  const event = payload.event
  websitePlayerPresentation.clear()
  for (let index = 0; index < event.teams.length; index += 1) {
    const team = event.teams[index]
    const localTeamId = await upsertTeam(baseUrl, team, index + 1)
    for (const player of team.players || []) await upsertPlayer(baseUrl, player, localTeamId)
  }
  for (const player of event.substitutes || []) await upsertPlayer(baseUrl, player, null, true)
  await dbRun(
    `INSERT INTO settings(key, value) VALUES('websiteMatchId', ?)
     ON CONFLICT(key) DO UPDATE SET value=excluded.value`,
    [`event:${event.id}`]
  )
  status.lastSyncAt = new Date().toISOString()
  status.lastError = null
  status.importedMatchId = null
  resetForwardTarget(null)
  return event
}

export const syncWebsiteMatch = async (requestedMatchId?: string): Promise<WebsiteMatch> => {
  const settings = await getSettings()
  const baseUrl = normalizeWebsiteUrl(settings.websiteUrl)
  const selected = String(requestedMatchId || settings.websiteMatchId || '').trim()
  if (selected.startsWith('event:')) {
    throw new Error('请选择具体比赛，或使用赛事名单同步')
  }
  if (selected && !/^\d+$/.test(selected)) {
    throw new Error('网站比赛编号无效，请重新选择后再同步')
  }
  const endpoint = selected
    ? `${baseUrl}/api/broadcast/matches/${encodeURIComponent(selected)}`
    : `${baseUrl}/api/broadcast/current`
  const payload = await fetchJson<{ ok: boolean; match: WebsiteMatch }>(endpoint)
  if (!payload.ok || !payload.match) throw new Error('网站没有可同步的比赛')
  const match = await fillMatchLogosFromEvent(baseUrl, payload.match)
  websitePlayerPresentation.clear()
  console.log(
    `[80GOTV] Syncing match ${match.id}: ${match.team1.name} (${match.team1.players?.length || 0}) vs ${match.team2.name} (${match.team2.players?.length || 0})`
  )

  const leftId = await upsertTeam(baseUrl, match.team1, 1)
  const rightId = await upsertTeam(baseUrl, match.team2, 2)
  // Import the event substitute pool first. A substitute selected for this
  // match is written again below with its real team, so it cannot be cleared
  // back to a free substitute by the later pool sync.
  for (const player of match.substitutes || []) await upsertPlayer(baseUrl, player, null, true)
  for (const player of match.team1.players || []) {
    await upsertPlayer(baseUrl, player, leftId, player.role === 'substitute')
  }
  for (const player of match.team2.players || []) {
    await upsertPlayer(baseUrl, player, rightId, player.role === 'substitute')
  }

  const localMatchId = matchId(match.id)
  const bo = String(match.bo || 'BO3').toLowerCase()
  const matchType = ['bo1', 'bo2', 'bo3', 'bo5'].includes(bo) ? bo : 'bo3'
  await dbRun('UPDATE matches SET current=0')
  await dbRun(
    `INSERT INTO matches
       (id, current, left_id, left_wins, right_id, right_wins, matchType, vetos)
     VALUES (?, 1, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       current=1, left_id=excluded.left_id, left_wins=excluded.left_wins,
       right_id=excluded.right_id, right_wins=excluded.right_wins,
       matchType=excluded.matchType, vetos=excluded.vetos`,
    [
      localMatchId,
      leftId,
      Number(match.team1.series_score) || 0,
      rightId,
      Number(match.team2.series_score) || 0,
      matchType,
      JSON.stringify(buildVetos(match))
    ]
  )
  await dbRun(
    `INSERT INTO settings(key, value) VALUES('websiteMatchId', ?)
     ON CONFLICT(key) DO UPDATE SET value=excluded.value`,
    [String(match.id)]
  )
  await syncHudWebsiteConfig(baseUrl, match.id)
  console.log(`[80GOTV] Match ${match.id} sync completed`)
  resetForwardTarget(match.id)
  status.lastSyncAt = new Date().toISOString()
  status.lastError = null
  status.importedMatchId = match.id
  return match
}

export const syncWebsiteSource = async (
  requestedSource?: string
): Promise<{ source_type: 'match' | 'event'; match?: WebsiteMatch; event?: WebsiteEvent; summary: string }> => {
  const settings = await getSettings()
  const selected = String(requestedSource || settings.websiteMatchId || '').trim()
  const baseUrl = normalizeWebsiteUrl(settings.websiteUrl)
  if (selected.startsWith('event:')) {
    const event = await syncWebsiteEvent(baseUrl, selected.slice('event:'.length))
    return {
      source_type: 'event',
      event,
      summary: `${event.name}：${event.team_count} 支队伍，${event.substitute_count} 名替补`
    }
  }
  const match = await syncWebsiteMatch(selected)
  return {
    source_type: 'match',
    match,
    summary: `${match.team1.name} vs ${match.team2.name}`
  }
}

type PendingLivePayload = {
  payload: Record<string, any>
  matchId: number
  generation: number
}

let pendingPayload: PendingLivePayload | null = null
let forwardTimer: NodeJS.Timeout | null = null
let forwardInFlight = false
let forwardAttempts = 0

const resetForwardTarget = (matchId: number | null) => {
  status.forwardGeneration += 1
  status.forwardTargetMatchId = matchId
  status.sessionId = matchId ? `80gotv:${matchId}:${Date.now()}` : null
  status.frameSeq = 0
  status.confirmedMatchId = null
  status.lastConfirmedAt = null
  pendingPayload = null
  // Keep unacknowledged map results across re-sync/restart. Results for the
  // same match can continue with the new generation; other matches remain in
  // the durable outbox until their original match is selected again.
  for (const entry of resultQueue) {
    if (entry.matchId === matchId) entry.generation = status.forwardGeneration
  }
  status.pendingResults = resultQueue.length
  forwardAttempts = 0
  status.forwardAttempts = 0
  if (forwardTimer) {
    clearTimeout(forwardTimer)
    forwardTimer = null
  }
}

const flushForward = async () => {
  forwardTimer = null
  if (forwardInFlight || !pendingPayload) return
  const queued = pendingPayload
  pendingPayload = null
  forwardInFlight = true
  status.forwarding = true
  let shouldRetry = true
  try {
    const settings = await getSettings()
    if (!settings.forwardLiveData) {
      shouldRetry = false
      return
    }
    const selected = readSelectedMatchId(settings.websiteMatchId)
    if (!selected) throw new Error('请先选择并同步一场网站比赛')
    if (selected !== queued.matchId || selected !== status.importedMatchId || selected !== status.forwardTargetMatchId) {
      shouldRetry = false
      throw new Error('比赛已切换，请先同步新比赛后再上传实时数据')
    }
    if (queued.generation !== status.forwardGeneration) {
      shouldRetry = false
      return
    }
    if (!settings.websiteGsiToken) throw new Error('请填写网站 GSI 密钥')
    const baseUrl = normalizeWebsiteUrl(settings.websiteUrl)
    const cleanPayload = { ...queued.payload }
    delete cleanPayload.auth
    const receipt = await fetchJson<WebsiteLiveReceipt>(`${baseUrl}/api/broadcast/matches/${selected}/live`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-80GOTV-Token': settings.websiteGsiToken
      },
      body: JSON.stringify(cleanPayload)
    })
    requireMatchingReceipt(receipt, selected)
    if (queued.generation !== status.forwardGeneration) return
    status.lastForwardAt = new Date().toISOString()
    status.lastConfirmedAt = status.lastForwardAt
    status.confirmedMatchId = selected
    status.lastError = null
    forwardAttempts = 0
    status.forwardAttempts = 0
  } catch (error) {
    // A sync may have selected a new match while the old request was in flight.
    // Do not let that old failure turn the new target red or restart its retry counter.
    if (queued.generation !== status.forwardGeneration) return
    forwardAttempts += 1
    status.forwardAttempts = forwardAttempts
    status.lastError = error instanceof Error ? error.message : String(error)
    // Keep only one current snapshot. A newer local frame wins over a failed old request.
    if (shouldRetry && !pendingPayload && queued.generation === status.forwardGeneration) pendingPayload = queued
  } finally {
    forwardInFlight = false
    status.forwarding = false
    if (pendingPayload && !forwardTimer) {
      const delay = forwardAttempts
        ? Math.min(10000, 500 * 2 ** Math.min(5, forwardAttempts - 1))
        : 300
      forwardTimer = setTimeout(flushForward, delay)
    }
  }
}

export const queueWebsiteLiveData = (payload: Record<string, any>) => {
  status.lastLocalDataAt = new Date().toISOString()
  const matchId = status.forwardTargetMatchId
  if (!matchId || status.importedMatchId !== matchId) return
  status.frameSeq += 1
  const stampedPayload = {
    ...payload,
    _80gotv: {
      ...(payload._80gotv || {}),
      session_id: status.sessionId,
      frame_seq: status.frameSeq,
      sent_at: new Date().toISOString()
    }
  }
  pendingPayload = { payload: stampedPayload, matchId, generation: status.forwardGeneration }
  if (!forwardTimer) forwardTimer = setTimeout(flushForward, 300)
}

type QueuedMapResult = {
  resultId: string
  payload: Record<string, any>
  attempts: number
  matchId: number
  generation: number
}

const resultQueue: QueuedMapResult[] = []
let resultForwarding = false
let resultTimer: NodeJS.Timeout | null = null
let resultQueueLoaded = false

const loadResultOutbox = async () => {
  if (resultQueueLoaded) return
  resultQueueLoaded = true
  try {
    const rows = await dbAll('SELECT result_id, match_id, payload, attempts FROM broadcast_outbox ORDER BY created_at, result_id')
    for (const row of rows) {
      try {
        const payload = JSON.parse(row.payload || '{}')
        resultQueue.push({
          resultId: String(row.result_id),
          payload,
          attempts: Number(row.attempts) || 0,
          matchId: Number(row.match_id),
          generation: status.forwardGeneration
        })
      } catch {
        // Keep malformed rows out of the active queue; the database row is
        // retained for manual inspection rather than silently deleted.
      }
    }
    status.pendingResults = resultQueue.length
  } catch (error) {
    resultQueueLoaded = false
    status.lastError = error instanceof Error ? error.message : String(error)
  }
}

const flushMapResults = async () => {
  resultTimer = null
  await loadResultOutbox()
  if (resultForwarding || !resultQueue.length) return
  let settings: Awaited<ReturnType<typeof getSettings>>
  try {
    settings = await getSettings()
  } catch (error) {
    status.lastError = error instanceof Error ? error.message : String(error)
    return
  }
  const selectedMatchId = readSelectedMatchId(String(settings.websiteMatchId || ''))
  const queued = resultQueue.find(
    (entry) => entry.matchId === selectedMatchId && entry.generation === status.forwardGeneration
  )
  if (!queued) return
  resultForwarding = true
  status.forwarding = true
  try {
    const selected = String(settings.websiteMatchId || '').trim()
    if (!selected || selected.startsWith('event:')) throw new Error('请先选择并同步一场网站比赛')
    if (
      !selectedMatchId ||
      selectedMatchId !== queued.matchId ||
      selectedMatchId !== status.importedMatchId ||
      queued.generation !== status.forwardGeneration
    ) {
      throw new Error('比赛已切换，旧地图结算暂不上传，等待重新同步原比赛')
    }
    if (!settings.websiteGsiToken) throw new Error('请填写网站 GSI 密钥')
    const baseUrl = normalizeWebsiteUrl(settings.websiteUrl)
    await fetchJson<{ ok: boolean }>(
      `${baseUrl}/api/broadcast/matches/${selected}/map-result`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-80GOTV-Token': settings.websiteGsiToken
        },
        body: JSON.stringify(queued.payload)
      }
    )
    const queueIndex = resultQueue.indexOf(queued)
    if (queueIndex >= 0) resultQueue.splice(queueIndex, 1)
    await dbRun('DELETE FROM broadcast_outbox WHERE result_id=?', [queued.resultId])
    status.lastResultAt = new Date().toISOString()
    status.lastError = null
  } catch (error) {
    queued.attempts += 1
    await dbRun('UPDATE broadcast_outbox SET attempts=? WHERE result_id=?', [queued.attempts, queued.resultId]).catch(() => undefined)
    status.lastError = error instanceof Error ? error.message : String(error)
  } finally {
    resultForwarding = false
    status.forwarding = false
    status.pendingResults = resultQueue.length
    if (resultQueue.length && !resultTimer) {
      const delay = resultQueue[0].attempts
        ? Math.min(60000, 1000 * 2 ** Math.min(6, resultQueue[0].attempts - 1))
        : 50
      resultTimer = setTimeout(flushMapResults, delay)
    }
  }
}

export const queueWebsiteMapResult = (payload: Record<string, any>) => {
  const selectedMatchId = status.forwardTargetMatchId
  if (!selectedMatchId || status.importedMatchId !== selectedMatchId) {
    return
  }
  const mapName = String(payload.map_name || '')
  const existing = resultQueue.find(
    (entry) => entry.matchId === selectedMatchId && String(entry.payload.map_name || '') === mapName
  )
  // Replacing a still-pending result keeps its durable ID. Otherwise the old
  // SQLite row would remain orphaned and be uploaded again after a restart.
  const resultId = String(existing?.resultId || payload.result_id || `${selectedMatchId}:${mapName}:${Date.now()}`)
  const durablePayload = {
    ...payload,
    result_id: resultId,
    session_id: payload.session_id || status.sessionId,
    frame_seq: payload.frame_seq ?? status.frameSeq,
    sent_at: payload.sent_at || new Date().toISOString()
  }
  if (existing) {
    existing.payload = durablePayload
    existing.attempts = 0
    void dbRun(
      'INSERT OR REPLACE INTO broadcast_outbox(result_id, match_id, payload, attempts) VALUES(?,?,?,0)',
      [resultId, selectedMatchId, JSON.stringify(durablePayload)]
    )
  } else {
    resultQueue.push({
      resultId,
      payload: durablePayload,
      attempts: 0,
      matchId: selectedMatchId,
      generation: status.forwardGeneration
    })
    void dbRun(
      'INSERT OR REPLACE INTO broadcast_outbox(result_id, match_id, payload, attempts) VALUES(?,?,?,0)',
      [resultId, selectedMatchId, JSON.stringify(durablePayload)]
    )
  }
  status.pendingResults = resultQueue.length
  if (!resultTimer) resultTimer = setTimeout(flushMapResults, 50)
}

export const setup80Gotv = (io: Server) => {
  const router = Router()
  void loadResultOutbox()
  startWebsiteBpPolling(io)

  router.get('/status', async (_req: Request, res: Response) => {
    const settings = await getSettings()
    if (settings.forwardLiveData && resultQueue.length && !resultTimer) {
      resultTimer = setTimeout(flushMapResults, 50)
    }
    res.json({
      ok: true,
      websiteUrl: settings.websiteUrl,
      selectedMatchId: settings.websiteMatchId,
      forwardLiveData: settings.forwardLiveData,
      ...status
    })
  })

  router.get('/matches', async (_req: Request, res: Response) => {
    try {
      const sources = await listWebsiteSources()
      res.json({ ok: true, sources, matches: sources })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      status.lastError = message
      res.status(502).json({ ok: false, error: message })
    }
  })

  router.post('/connection-test', async (req: Request, res: Response) => {
    try {
      const settings = await getSettings()
      const matchId = readSelectedMatchId(req.body?.matchId ?? settings.websiteMatchId)
      if (!matchId) throw new Error('请选择一场具体比赛后再测试连接')
      const baseUrl = normalizeWebsiteUrl(settings.websiteUrl)
      const result = await checkWebsiteConnection(baseUrl, settings.websiteGsiToken, matchId)
      status.lastConnectionTestAt = new Date().toISOString()
      status.lastError = null
      res.json({ ok: true, connection: result, status })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      status.lastError = message
      res.status(502).json({ ok: false, error: message, status })
    }
  })

  router.post('/sync', async (req: Request, res: Response) => {
    try {
      const result = await syncWebsiteSource(req.body?.matchId)
      io.emit('teams')
      io.emit('players')
      io.emit('match')
      res.json({ ok: true, ...result, status })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      status.lastError = message
      res.status(502).json({ ok: false, error: message })
    }
  })

  return router
}
