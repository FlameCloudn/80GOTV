import { CSGO, CSGOGSI, CSGORaw, Player, Score } from 'csgogsi'
import { Router, Request, Response } from 'express'
import { Server } from 'socket.io'
import { MatchService } from '../domains/matches/match.service'
import { TeamService } from '../domains/teams/team.service'
import { PlayerRepository } from '../domains/players/player.repository'
import { getSettings } from '../domains/settings/settings.routes'
import { RoundData } from '../domains/matches/match.types'
import {
  applyWebsitePlayerPresentation,
  getWebsitePlayerPresentation,
  queueWebsiteLiveData,
  queueWebsiteMapResult
} from './80gotv'
import { buildMapPlayerStats, liveStatsTracker } from './live-stats'

const matchService = new MatchService()
const teamService = new TeamService()
const playerRepo = new PlayerRepository()

// --- COACH FILTER CACHE ---
// Stores steamids of players marked as coaches so they can be stripped
// from GSI payloads before broadcasting. Refreshed on startup and after
// any player create/update via syncCoaches().
let coachSteamIds = new Set<string>()

export const syncCoaches = async () => {
  try {
    const all = await playerRepo.getPlayers()
    coachSteamIds = new Set(all.filter((p) => p.isCoach && p.steamid).map((p) => p.steamid))
  } catch (err) {
    console.error('[GSI] Failed to sync coach list:', err)
  }
}

export const GSI = new CSGOGSI()
GSI.regulationMR = 12
GSI.overtimeMR = 3

const GSI_GAP_WARNING_MS = 5000
let lastGsiInputAt = 0
let gsiGapTimer: NodeJS.Timeout | null = null
let gsiGapLogged = false

const recordGsiInput = () => {
  const now = Date.now()
  if (gsiGapLogged && lastGsiInputAt) {
    console.log(`[GSI] Data stream restored after ${((now - lastGsiInputAt) / 1000).toFixed(1)}s`)
  }
  gsiGapLogged = false
  lastGsiInputAt = now
  if (gsiGapTimer) clearTimeout(gsiGapTimer)
  gsiGapTimer = setTimeout(() => {
    gsiGapLogged = true
    console.warn('[GSI] No data received for 5s; keeping the last valid match state')
  }, GSI_GAP_WARNING_MS)
}

// Sync GSI.teams from the current match
// Call this whenever the match changes or on startup
// This may actually not be needed as huds create their own GSI instance, need to verify this
export const syncGSITeams = async () => {
  try {
    const match = await matchService.getCurrentMatch()

    if (match.left.id) {
      const left = await teamService.getTeamById(match.left.id)
      if (left) {
        const data = {
          id: left._id,
          name: left.name,
          country: left.country,
          logo: left.logo,
          map_score: match.left.wins,
          extra: left.extra
        }
        GSI.teams.left = data
      }
    } else {
      GSI.teams.left = null
    }

    if (match.right.id) {
      const right = await teamService.getTeamById(match.right.id)
      if (right) {
        const data = {
          id: right._id,
          name: right.name,
          country: right.country,
          logo: right.logo,
          map_score: match.right.wins,
          extra: right.extra
        }
        GSI.teams.right = data
      }
    } else {
      GSI.teams.right = null
    }
  } catch {
    // No current match — clear team data
    GSI.teams.left = null
    GSI.teams.right = null
  }
}

let lastGSIState: CSGORaw | null = null
let lastPhaseSignature = ''

type MatchStatKey = 'assists' | 'deaths' | 'mvps' | 'kills' | 'damage'
type MatchStatBaseline = Record<MatchStatKey, number>
type PhaseState = {
  map?: { name?: string; phase?: string }
  phase_countdowns?: { phase?: string }
}

const warmupTotals = new Map<string, Map<string, MatchStatBaseline>>()
const officialBaselines = new Map<string, Map<string, MatchStatBaseline>>()
const deciderStability = new Map<string, { signature: string; count: number }>()
const cleanMapName = (value = '') => value.substring(value.lastIndexOf('/') + 1)
const isWarmupState = (game: PhaseState | null | undefined) => {
  const phases = [game?.map?.phase, game?.phase_countdowns?.phase]
  return phases.some((phase) => String(phase || '').trim().toLowerCase() === 'warmup')
}
const playerMatchStats = (player: Player): MatchStatBaseline => ({
  assists: Number(player.stats.assists) || 0,
  deaths: Number(player.stats.deaths) || 0,
  mvps: Number(player.stats.mvps) || 0,
  kills: Number((player.stats as any).kills) || 0,
  damage: Number((player.stats as any).damage) || 0
})
const captureWarmupTotals = (game: CSGO) => {
  const mapName = cleanMapName(game.map.name)
  warmupTotals.set(
    mapName,
    new Map(
      game.players
        .filter((player) => player.steamid)
        .map((player) => [player.steamid, playerMatchStats(player)])
    )
  )
}
const beginOfficialStats = (game: CSGO) => {
  const mapName = cleanMapName(game.map.name)
  const warmup = warmupTotals.get(mapName) || new Map<string, MatchStatBaseline>()
  officialBaselines.set(
    mapName,
    new Map(
      game.players
        .filter((player) => player.steamid)
        .map((player) => {
          const current = playerMatchStats(player)
          const previous = warmup.get(player.steamid)
          const baseline: MatchStatBaseline = { assists: 0, deaths: 0, mvps: 0, kills: 0, damage: 0 }
          if (previous) {
            for (const key of ['assists', 'deaths', 'mvps', 'kills', 'damage'] as MatchStatKey[]) {
              baseline[key] = current[key] >= previous[key] ? previous[key] : 0
            }
          }
          return [player.steamid, baseline]
        })
    )
  )
}

const lockStableDeciderSide = async (game: CSGO | null | undefined) => {
  if (!game || isWarmupState(game)) return
  const mapName = cleanMapName(game.map?.name || '')
  const ctId = String(game.map?.team_ct?.id || '')
  const tId = String(game.map?.team_t?.id || '')
  const ctScore = Number(game.map?.team_ct?.score || 0)
  const tScore = Number(game.map?.team_t?.score || 0)
  if (!mapName || !ctId || !tId || ctScore !== 0 || tScore !== 0) return
  const players = (game.players || []).filter((player) => player.steamid)
  const ctPlayers = new Set(players.filter((player) => String(player.team?.id || '') === ctId).map((player) => player.steamid))
  const tPlayers = new Set(players.filter((player) => String(player.team?.id || '') === tId).map((player) => player.steamid))
  if (ctPlayers.size !== 5 || tPlayers.size !== 5) return

  const match = await matchService.getCurrentMatch()
  if (!match) return
  const veto = match.vetos.find((entry) => entry.mapName === mapName && entry.type === 'decider')
  if (!veto || veto.openingCtTeamId) return
  const key = `${match.id}:${mapName}`
  const signature = `${ctId}|${tId}|${[...ctPlayers].sort().join(',')}|${[...tPlayers].sort().join(',')}`
  const previous = deciderStability.get(key)
  const next = previous && previous.signature === signature
    ? { signature, count: previous.count + 1 }
    : { signature, count: 1 }
  deciderStability.set(key, next)
  if (next.count < 2) return

  const updatedVetos = match.vetos.map((entry) =>
    entry.mapName === mapName && entry.type === 'decider'
      ? { ...entry, openingCtTeamId: ctId, sideSource: 'tgpro_stable_gsi' as const }
      : entry
  )
  await matchService.updateMatch(match.id, { vetos: updatedVetos })
  console.log(`[GSI] Decider side locked from stable 5v5: ${mapName} CT=${ctId}`)
}
const officialMatchStat = (mapName: string, player: Player, key: MatchStatKey) => {
  const value = Number(player.stats[key]) || 0
  const baseline = officialBaselines.get(cleanMapName(mapName))?.get(player.steamid)?.[key] || 0
  return Math.max(0, value - baseline)
}

type WebsiteRoundEvent = {
  id: string
  round: number
  round_number: number
  winner_side: string
  side: string
  score_ct: number
  score_t: number
  reason_code: string
  captured_at: string
  captured_at_epoch: number
}

type WebsiteDeathMarker = {
  id: string
  steamid: string
  name: string
  side: string
  round: number
  round_number: number
  x: number
  y: number
  z: number | null
  observer_slot?: number
  captured_at: string
  captured_at_epoch: number
}

const websiteRoundEvents = new Map<string, WebsiteRoundEvent[]>()
const websiteDeathMarkers = new Map<string, WebsiteDeathMarker[]>()
const websiteDamageTotals = new Map<string, Map<string, { round: number; last: number; total: number }>>()
let websitePreviousRaw: any = null

const websiteFormalRoundNumber = (rawRound: unknown): number =>
  Math.max(1, Number(rawRound || 0) + 1)

const websiteMapName = (value: unknown): string => cleanMapName(String(value || ''))

const websiteReasonCode = (outcome: unknown): string => {
  switch (String(outcome || '').toLowerCase()) {
    case 't_win_bomb':
      return 'bomb_exploded'
    case 'ct_win_defuse':
      return 'bomb_defused'
    case 'ct_win_time':
      return 'time_expired'
    case 'ct_win_elimination':
    case 't_win_elimination':
      return 'elimination'
    default:
      return 'elimination'
  }
}

const recordWebsiteRoundEvent = (score: Score): void => {
  const mapName = websiteMapName(score.map?.name)
  if (!mapName || isWarmupState(score)) return
  const round = websiteFormalRoundNumber(score.map?.round)
  if (round > 24) return
  const roundWins = score.map?.round_wins || {}
  const rawRound = Number(score.map?.round || 0)
  const outcome = roundWins[String(rawRound)] || roundWins[String(rawRound + 1)]
  const now = Date.now()
  const event: WebsiteRoundEvent = {
    id: `round-${mapName}-${round}`,
    round,
    round_number: round,
    winner_side: String(score.winner?.side || '').toUpperCase(),
    side: String(score.winner?.side || '').toLowerCase(),
    score_ct: Number(score.map?.team_ct?.score || 0),
    score_t: Number(score.map?.team_t?.score || 0),
    reason_code: websiteReasonCode(outcome),
    captured_at: new Date(now).toISOString(),
    captured_at_epoch: now / 1000
  }
  const events = websiteRoundEvents.get(mapName) || []
  if (!events.some((item) => item.id === event.id)) {
    websiteRoundEvents.set(mapName, [...events, event].sort((a, b) => a.round - b.round).slice(-24))
  }
}

const captureWebsiteDeathMarkers = (raw: any): void => {
  const mapName = websiteMapName(raw?.map?.name)
  if (!mapName || isWarmupState(raw)) {
    websitePreviousRaw = raw
    return
  }
  const previousMap = websiteMapName(websitePreviousRaw?.map?.name)
  if (previousMap !== mapName) websiteDeathMarkers.delete(mapName)
  const rawRound = Number(raw?.map?.round || 0)
  const round = websiteFormalRoundNumber(rawRound)
  const previousPlayers = websitePreviousRaw?.allplayers || {}
  const currentPlayers = raw?.allplayers || {}
  const markers = websiteDeathMarkers.get(mapName) || []
  for (const [steamid, player] of Object.entries(currentPlayers) as [string, any][]) {
    const oldPlayer = previousPlayers[steamid] || {}
    const oldHealth = Number(oldPlayer?.state?.health ?? 0)
    const newHealth = Number(player?.state?.health ?? 0)
    if (oldHealth <= 0 || newHealth > 0) continue
    const position = oldPlayer?.position || player?.position
    if (!position || typeof position !== 'string') continue
    const values = position.split(',').map((value: string) => Number(value.trim()))
    if (values.length < 2 || values.some((value: number) => !Number.isFinite(value))) continue
    const now = Date.now()
    const marker: WebsiteDeathMarker = {
      id: `death-${mapName}-${round}-${steamid}-${now}`,
      steamid,
      name: String(player?.name || ''),
      side: String(player?.team || '').toUpperCase(),
      round,
      round_number: round,
      x: values[0],
      y: values[1],
      z: values.length > 2 ? values[2] : null,
      observer_slot: Number(player?.observer_slot ?? 99),
      captured_at: new Date(now).toISOString(),
      captured_at_epoch: now / 1000
    }
    markers.push(marker)
  }
  websiteDeathMarkers.set(mapName, markers.slice(-24))
  websitePreviousRaw = JSON.parse(JSON.stringify(raw))
}

const recordWebsiteDamage = (raw: any): void => {
  const mapName = websiteMapName(raw?.map?.name)
  if (!mapName || isWarmupState(raw)) return
  const round = websiteFormalRoundNumber(raw?.map?.round)
  const totals = websiteDamageTotals.get(mapName) || new Map<string, { round: number; last: number; total: number }>()
  for (const [steamid, player] of Object.entries(raw?.allplayers || {}) as [string, any][]) {
    const current = Math.max(0, Number(player?.state?.round_totaldmg || 0))
    const previous = totals.get(steamid)
    if (!previous) {
      totals.set(steamid, { round, last: current, total: 0 })
    } else if (previous.round !== round) {
      previous.total += previous.last
      previous.round = round
      previous.last = current
    } else {
      previous.last = Math.max(previous.last, current)
    }
  }
  websiteDamageTotals.set(mapName, totals)
}

const withOfficialWebsiteStats = (raw: any): any => {
  const payload = JSON.parse(JSON.stringify(raw || {}))
  const mapName = websiteMapName(payload?.map?.name)
  for (const [steamid, player] of Object.entries(payload?.allplayers || {}) as [string, any][]) {
    const rawStats = player?.match_stats || {}
    const baseline = officialBaselines.get(mapName)?.get(steamid)
    if (!baseline) continue
    player.match_stats = {
      ...rawStats,
      kills: Math.max(0, Number(rawStats.kills || 0) - baseline.kills),
      deaths: Math.max(0, Number(rawStats.deaths || 0) - baseline.deaths),
      assists: Math.max(0, Number(rawStats.assists || 0) - baseline.assists),
      damage: Math.max(
        0,
        Number(websiteDamageTotals.get(mapName)?.get(steamid)?.total || rawStats.damage || 0) - baseline.damage
      )
    }
  }
  return payload
}

export const getLastGSIState = (): CSGORaw | null => lastGSIState

// csgogsi applies the locally configured team extension after parsing the raw
// frame. When a match id is reused, that extension may contain an old series
// score. Restore the scores from this CS2 frame so backend listeners and logs
// see the same live value as the HUD.
const patchLiveSeriesScores = (raw: any, parsed: CSGO | null | undefined): void => {
  if (!parsed?.map) return
  const left = GSI.teams.left
  const right = GSI.teams.right
  const leftScore = Number(left?.map_score)
  const rightScore = Number(right?.map_score)
  if (!left || !right || !Number.isFinite(leftScore) || !Number.isFinite(rightScore)) return

  // csgogsi chooses CT/T orientation from observer slots. Keep only the
  // live side labels from the raw CS2 frame, while fixing each team to the
  // scheduled match position used by the website and HUD.
  const rawCtId = String(raw?.map?.team_ct?.id || '')
  const rawTId = String(raw?.map?.team_t?.id || '')
  const knownIds = new Set([left.id, right.id])
  const ctId = knownIds.has(rawCtId) ? rawCtId : parsed.map.team_ct.id
  const tId = knownIds.has(rawTId) ? rawTId : parsed.map.team_t.id
  parsed.map.team_ct.id = ctId
  parsed.map.team_t.id = tId
  parsed.map.team_ct.matches_won_this_series = ctId === left.id ? leftScore : rightScore
  parsed.map.team_t.matches_won_this_series = tId === left.id ? leftScore : rightScore
  parsed.map.team_ct.orientation = ctId === left.id ? 'left' : 'right'
  parsed.map.team_t.orientation = tId === left.id ? 'left' : 'right'
}

// Spectator slot map
// Populated via PUT /api/spectator/slots from the Spectator Binds page
let nameToSlot: Map<string, number> = new Map()

export const setSpectatorSlots = (slots: Record<number, string>): void => {
  nameToSlot = new Map()
  for (const [slot, name] of Object.entries(slots)) {
    if (name) nameToSlot.set(name, Number(slot) === 10 ? 0 : Number(slot))
  }
}

export const setupGSI = (io: Server) => {
  const router = Router()

  // Sync teams whenever the map changes (reverseSide may differ per map)
  GSI.on('data', (data) => {
    const prevMap = GSI.last?.map?.name
    const nextMap = data.map?.name
    const phaseSignature = [
      cleanMapName(nextMap || ''),
      data.map?.phase || '',
      data.round?.phase || '',
      data.phase_countdowns?.phase || '',
      data.map?.team_t?.timeouts_remaining ?? '',
      data.map?.team_ct?.timeouts_remaining ?? ''
    ].join('|')
    if (phaseSignature !== lastPhaseSignature) {
      lastPhaseSignature = phaseSignature
      console.log(`[GSI] Phase state: ${phaseSignature}`)
    }
    if (nextMap && nextMap !== prevMap) {
      const mapName = cleanMapName(nextMap)
      warmupTotals.delete(mapName)
      officialBaselines.delete(mapName)
      websiteRoundEvents.delete(mapName)
      websiteDeathMarkers.delete(mapName)
      websiteDamageTotals.delete(mapName)
      websitePreviousRaw = null
      liveStatsTracker.resetMap(nextMap)
      syncGSITeams()
    }
    const warmup = isWarmupState(data)
    const wasWarmup = isWarmupState(GSI.last)
    if (warmup) {
      captureWarmupTotals(data)
      liveStatsTracker.resetMap(nextMap || '')
      return
    }
    if (wasWarmup) {
      beginOfficialStats(data)
      liveStatsTracker.resetMap(nextMap || '')
    }
    liveStatsTracker.recordSnapshot(wasWarmup ? null : GSI.last, data)
  })

  // Halftime Logic: flip reverseSide on the current map veto so team sides stay correct.
  // Overtime intermissions should not always flip sides
  GSI.on('intermissionEnd', async () => {
    try {
      const settings = await getSettings()
      if (!settings.autoSwitchSides) {
        console.log('[GSI] autoSwitchSides disabled — skipping halftime flip')
        return
      }

      const match = await matchService.getCurrentMatch()
      if (!match || !GSI.last) return

      const totalScore = GSI.last.map.team_ct.score + GSI.last.map.team_t.score
      const regulationTotal = GSI.regulationMR * 2 // 24
      const otPeriod = GSI.overtimeMR * 2 // 6

      // Skip reversing sides when going into a new OT period
      // e.g. 24, 30, 36: Sides are the same going into each new OT
      const isOvertimeEntry =
        totalScore >= regulationTotal && (totalScore - regulationTotal) % otPeriod === 0

      if (isOvertimeEntry) {
        console.log(`[GSI] Overtime entry (score ${totalScore}) — skipping reverseSide flip`)
        return
      }

      const mapName = GSI.last.map.name.substring(GSI.last.map.name.lastIndexOf('/') + 1)
      const currentVeto = match.vetos.find((veto) => veto.mapName === mapName)
      if (currentVeto?.sideSource === 'website_bp' || currentVeto?.openingCtTeamId) {
        await syncGSITeams()
        return
      }
      const updatedVetos = match.vetos.map((veto) =>
        veto.mapName === mapName ? { ...veto, reverseSide: !veto.reverseSide } : veto
      )

      await matchService.updateMatch(match.id, { vetos: updatedVetos })
      await syncGSITeams()
      io.emit('match')
      console.log(`[GSI] Halftime — flipped reverseSide for map: ${mapName}`)
    } catch (err) {
      console.error('[GSI] intermissionEnd error:', err)
    }
  })

  GSI.on('kill', (event) => {
    if (GSI.current && !isWarmupState(GSI.current)) {
      liveStatsTracker.recordKill(GSI.current, event)
    }
  })
  GSI.on('hurt', (event) => {
    if (GSI.current && !isWarmupState(GSI.current)) {
      liveStatsTracker.recordHurt(GSI.current, event)
    }
  })
  GSI.on('bombPlant', (player) => {
    if (GSI.current && !isWarmupState(GSI.current)) {
      liveStatsTracker.recordBombPlant(GSI.current, player)
    }
  })
  GSI.on('bombDefuse', (player) => {
    if (GSI.current && !isWarmupState(GSI.current)) {
      liveStatsTracker.recordBombDefuse(GSI.current, player)
    }
  })

  const getWinType = (outcome: string): RoundData['win_type'] => {
    switch (outcome) {
      case 'ct_win_defuse':
        return 'defuse'
      case 'ct_win_time':
        return 'time'
      case 't_win_bomb':
        return 'bomb'
      case 'ct_win_elimination':
      case 't_win_elimination':
        return 'elimination'
      default:
        return 'time'
    }
  }

  const persistRoundEnd = async (score: Score) => {
    if (!GSI.current) return
    if (isWarmupState(GSI.current) || isWarmupState(score)) return
    const players = GSI.current.players
    const match = await matchService.getCurrentMatch()
    if (!match) return

    const mapName = score.map.name.substring(score.map.name.lastIndexOf('/') + 1)
    const veto = match.vetos.find((entry) => entry.mapName === mapName && !entry.mapEnd)
    if (!veto) return
    const roundNumber = websiteFormalRoundNumber(score.map.round)
    if (veto.rounds?.[roundNumber - 1]) return

    const eventStats = liveStatsTracker.consume(mapName, roundNumber, players, score.winner.side)
    const previousRounds = (veto.rounds || []).slice(0, roundNumber - 1)
    const previousTotal = (steamid: string, key: 'assists' | 'deaths' | 'mvpCount') =>
      previousRounds.reduce(
        (total, round) => total + (Number(round?.players?.[steamid]?.[key]) || 0),
        0
      )
    const ctId = score.map.team_ct.id || ''
    const tId = score.map.team_t.id || ''
    const isReversed = veto.openingCtTeamId
      ? Boolean(ctId && tId && ctId !== veto.openingCtTeamId && tId === veto.openingCtTeamId)
      : Boolean(veto.reverseSide)
    const mapTeamId = (teamId: string | null) => {
      const value = teamId || ''
      if (!isReversed) return value
      if (value === ctId) return tId
      if (value === tId) return ctId
      return value
    }
    const rawRound = Number(score.map.round || 0)
    const roundOutcome = score.map.round_wins?.[rawRound] || score.map.round_wins?.[rawRound + 1]
    const roundData: RoundData = {
      round: roundNumber,
      winner: score.winner.side,
      win_type: roundOutcome ? getWinType(roundOutcome) : 'elimination',
      players: Object.fromEntries(
        players
          .filter((player) => player.steamid)
          .map((player) => {
            const counters = eventStats.counters[player.steamid] || {}
            return [
              player.steamid,
              {
                name: player.name || player.defaultName || 'PLAYER',
                avatar: player.avatar || undefined,
                teamId: mapTeamId(player.team.id),
                side: player.team.side,
                kills: Number(player.state.round_kills) || 0,
                killshs: Number(player.state.round_killhs) || 0,
                damage: Number(player.state.round_totaldmg) || 0,
                assists: Math.max(
                  0,
                  officialMatchStat(mapName, player, 'assists') -
                    previousTotal(player.steamid, 'assists')
                ),
                deaths: Math.max(
                  0,
                  officialMatchStat(mapName, player, 'deaths') -
                    previousTotal(player.steamid, 'deaths')
                ),
                survived: eventStats.hadKillEvents
                  ? eventStats.survivors.has(player.steamid)
                  : Number(player.state.health) > 0,
                firstKills: Number(counters.firstKills) || 0,
                firstDeaths: Number(counters.firstDeaths) || 0,
                tradeKills: Number(counters.tradeKills) || 0,
                tradeDeaths: Number(counters.tradeDeaths) || 0,
                clutchSize:
                  eventStats.clutchWinner === player.steamid ? eventStats.clutchSize : 0,
                utilityDamage: Number(counters.utilityDamage) || 0,
                damageTaken: Number(counters.damageTaken) || 0,
                mvpCount: Math.max(
                  0,
                  officialMatchStat(mapName, player, 'mvps') -
                    previousTotal(player.steamid, 'mvpCount')
                ),
                bombPlants: Number(counters.bombPlants) || 0,
                bombDefuses: Number(counters.bombDefuses) || 0,
                flashAssists: Number(counters.flashAssists) || 0
              }
            ]
          })
      )
    }

    const updatedVetos = match.vetos.map((entry) => {
      if (entry.mapName !== mapName) return entry
      const rounds = [...(entry.rounds ?? [])]
      rounds[roundNumber - 1] = roundData
      return { ...entry, rounds: rounds.slice(0, roundNumber) }
    })
    await matchService.updateMatch(match.id, { vetos: updatedVetos })
    io.emit('match')
  }

  let roundWriteQueue: Promise<void> = Promise.resolve()
  GSI.on('roundEnd', (score: Score) => {
    recordWebsiteRoundEvent(score)
    roundWriteQueue = roundWriteQueue
      .then(() => persistRoundEnd(score))
      .catch((error) => console.error('[GSI] roundEnd error:', error))
  })

  // Map end logic: record final score, winner, mapEnd flag, and increment series wins
  GSI.on('matchEnd', async (score: Score) => {
    try {
      await roundWriteQueue
      const match = await matchService.getCurrentMatch()
      if (!match) return

      const mapName = score.map.name.substring(score.map.name.lastIndexOf('/') + 1)
      const ctId = score.map.team_ct.id || ''
      const tId = score.map.team_t.id || ''
      const ctScore = score.map.team_ct.score
      const tScore = score.map.team_t.score

      const activeVeto = match.vetos.find((veto) => veto.mapName === mapName)
      if (!activeVeto || activeVeto.mapEnd) return
      const isReversed = activeVeto.openingCtTeamId
        ? Boolean(
            ctId &&
              tId &&
              ctId !== activeVeto.openingCtTeamId &&
              tId === activeVeto.openingCtTeamId
          )
        : Boolean(activeVeto.reverseSide)
      const playerStats = buildMapPlayerStats({
        players: GSI.current?.players || [],
        rounds: activeVeto?.rounds || [],
        isReversed,
        ctId,
        tId,
        fallbackRounds: ctScore + tScore
      })
      const presentedPlayerStats = Object.fromEntries(
        Object.entries(playerStats).map(([steamid, stats]) => {
          const presentation = getWebsitePlayerPresentation(steamid)
          return [
            steamid,
            presentation
              ? {
                  ...stats,
                  name: presentation.name || stats.name,
                  avatar: presentation.avatar || stats.avatar
                }
              : stats
          ]
        })
      )

      const updatedVetos = match.vetos.map((veto) => {
        if (veto.mapName !== mapName || !ctId || !tId) return veto

        // Determine winner based on score and reverseSide
        const ctWon = ctScore > tScore
        const winnerSideId = ctWon ? ctId : tId
        const winnerTeamId = isReversed
          ? ctWon
            ? tId
            : ctId // reversed: CT in-game = T in database
          : winnerSideId

        return {
          ...veto,
          winner: winnerTeamId,
          mapEnd: true,
          score: isReversed
            ? { [ctId]: tScore, [tId]: ctScore } // swap scores back to match DB orientation
            : { [ctId]: ctScore, [tId]: tScore },
          playerStats: Object.keys(presentedPlayerStats).length ? presentedPlayerStats : veto.playerStats
        }
      })

      // Do not trust TGPro's raw series wins. Recompute from the confirmed
      // map winners so a repeated matchEnd cannot add a second series point.
      const confirmedWins = updatedVetos.reduce(
        (totals, veto) => {
          if (veto.mapEnd && veto.winner === match.left.id) totals.left += 1
          if (veto.mapEnd && veto.winner === match.right.id) totals.right += 1
          return totals
        },
        { left: 0, right: 0 }
      )
      const left = { ...match.left, wins: confirmedWins.left }
      const right = { ...match.right, wins: confirmedWins.right }

      await matchService.updateMatch(match.id, { vetos: updatedVetos, left, right })
      const completedVeto = updatedVetos.find((veto) => veto.mapName === mapName)
      const leftId = match.left.id
      const rightId = match.right.id
      const resultPlayers = Object.entries(presentedPlayerStats)
        .filter(([, stats]) => stats.teamId === leftId || stats.teamId === rightId)
        .map(([steamid, stats]) => ({
          steam_id: steamid,
          ...stats,
          team_side: stats.teamId === leftId ? 'team1' : 'team2'
        }))
      const bestOf = Math.max(1, Number(match.matchType.replace(/^bo/i, '')) || 1)
      const winsRequired = Math.floor(bestOf / 2) + 1
      queueWebsiteMapResult({
        map_name: mapName,
        map_slot: Math.max(1, match.vetos.filter((veto) => veto.type !== 'ban').findIndex((veto) => veto.mapName === mapName) + 1),
        team1_score: leftId ? Number(completedVeto?.score?.[leftId]) || 0 : 0,
        team2_score: rightId ? Number(completedVeto?.score?.[rightId]) || 0 : 0,
        series_complete: Math.max(left.wins, right.wins) >= winsRequired,
        players: resultPlayers
      })
      await syncGSITeams()
      io.emit('match')
      console.log(`[GSI] Map ended: ${mapName} — winner: ${score.winner.name}`)
    } catch (err) {
      console.error('[GSI] matchEnd error:', err)
    }
  })

  // --- GSI HTTP endpoint ---
  router.post('/input', (req: Request, res: Response) => {
    try {
      recordGsiInput()
      // --- Dead player position preservation ---
      // Cache: steamid -> last death position
      if (!global.deadPlayerPositions) global.deadPlayerPositions = {}
      const deadPlayerPositions = global.deadPlayerPositions

      if (req.body?.allplayers) {
        for (const steamid of Object.keys(req.body.allplayers)) {
          const player = req.body.allplayers[steamid]

          // Player is dead
          if (player.state && player.state.health === 0) {
            // If not already cached, cache their current position
            if (!deadPlayerPositions[steamid]) {
              deadPlayerPositions[steamid] = player.position
            }

            // Overwrite position with cached death position
            player.position = deadPlayerPositions[steamid]
          } else {
            // Player is alive, clear cache
            if (deadPlayerPositions[steamid]) {
              delete deadPlayerPositions[steamid]
            }
          }
        }
      }
      // Fix player observer_slot: CS2 raw data sends 0–10 but HUDs expect 1–10 with 10 wrapping to 0
      if (req.body?.allplayers) {
        for (const key of Object.keys(req.body.allplayers)) {
          const player = req.body.allplayers[key]
          if (typeof player?.observer_slot === 'number') {
            player.observer_slot = player.observer_slot + 1 === 10 ? 0 : player.observer_slot + 1
          }
        }
      }

      // Keep a local formal-match event buffer before parsing the frame. The
      // website receives these canonical events together with the snapshot,
      // so a skipped 300 ms upload can be recovered by the next one.
      captureWebsiteDeathMarkers(req.body)
      lastGSIState = req.body

      // Build payload for for HUDs
      let hudPayload = req.body
      const needsCoachFilter = req.body?.allplayers && coachSteamIds.size > 0
      const needsSlotRemap = req.body?.allplayers && nameToSlot.size > 0

      if (needsCoachFilter || needsSlotRemap) {
        let remapped = { ...req.body.allplayers }

        // Remove coaches
        if (needsCoachFilter) {
          for (const steamid of Object.keys(remapped)) {
            if (coachSteamIds.has(steamid)) delete remapped[steamid]
          }
        }

        // Remap observer_slot values to match custom slot assignments
        if (needsSlotRemap) {
          for (const steamid of Object.keys(remapped)) {
            const player = remapped[steamid]
            if (player?.name && nameToSlot.has(player.name)) {
              remapped[steamid] = { ...player, observer_slot: nameToSlot.get(player.name) }
            }
          }

          // Rebuild allplayers sorted by the new observer_slot
          const slotOrder = (s: number) => (s === 0 ? 10 : s)
          remapped = Object.fromEntries(
            Object.entries(remapped).sort(([, a], [, b]) => {
              const aSlot = (a as any)?.observer_slot ?? 99
              const bSlot = (b as any)?.observer_slot ?? 99
              return slotOrder(aSlot) - slotOrder(bSlot)
            })
          )
        }

        hudPayload = { ...req.body, allplayers: remapped }
      }

      // Feed raw payload into CSGOGSI so backend listeners fire
      const parsed = GSI.digest(req.body)
      patchLiveSeriesScores(req.body, parsed)
      void lockStableDeciderSide(parsed)
      const leftId = GSI.teams.left?.id || ''
      const rightId = GSI.teams.right?.id || ''
      const matchSide = (teamId: string | null) => {
        if (teamId && teamId === leftId) return 'team1'
        if (teamId && teamId === rightId) return 'team2'
        return ''
      }
      // Use the team IDs from the raw CS2 frame for the website mapping.
      // csgogsi may reorder team objects from observer slots before parsing;
      // using that reordered value caused CT/T labels and round colors to
      // drift away from the actual live side.
      const rawTeamCTId = String(req.body?.map?.team_ct?.id || parsed?.map.team_ct.id || '')
      const rawTeamTId = String(req.body?.map?.team_t?.id || parsed?.map.team_t.id || '')
      const teamCT = matchSide(rawTeamCTId)
      const teamT = matchSide(rawTeamTId)
      recordWebsiteDamage(req.body)
      const officialPayload = withOfficialWebsiteStats(req.body)
      const presentedPayload = applyWebsitePlayerPresentation(officialPayload)
      const mapName = websiteMapName(req.body?.map?.name)
      const roundEvents = (websiteRoundEvents.get(mapName) || []).map((event) => ({
        ...event,
        winner:
          event.winner_side === 'CT'
            ? teamCT
            : event.winner_side === 'T'
              ? teamT
              : '',
        side: event.winner_side.toLowerCase()
      }))
      const deathMarkers = (websiteDeathMarkers.get(mapName) || []).map((marker) => {
        const presentation = getWebsitePlayerPresentation(marker.steamid)
        return presentation ? { ...marker, name: presentation.name || marker.name } : marker
      })
      const websitePayload =
        teamCT && teamT && teamCT !== teamT
          ? {
              ...presentedPayload,
              _80gotv: {
                ...(presentedPayload as any)._80gotv,
                schema_version: 2,
                team_ct: teamCT,
                team_t: teamT,
                round_events: roundEvents,
                death_markers: deathMarkers
              }
            }
          : {
              ...presentedPayload,
              _80gotv: {
                ...((presentedPayload as any)._80gotv || {}),
                schema_version: 2,
                round_events: roundEvents,
                death_markers: deathMarkers
              }
            }
      queueWebsiteLiveData(websitePayload)

      // Vue UI gets the full payload (coaches visible in LiveView)
      io.except('huds').emit('update', presentedPayload)
      // HUDs get filtered payload
      const hudPayloadWithMapping =
        teamCT && teamT && teamCT !== teamT
          ? {
              ...hudPayload,
              _80gotv: {
                ...((hudPayload as any)._80gotv || {}),
                schema_version: 2,
                team_ct: teamCT,
                team_t: teamT
              }
            }
          : hudPayload
      io.to('huds').emit('update', applyWebsitePlayerPresentation(hudPayloadWithMapping))

      // CS2 expects a 200 OK so it doesn't throttle the GSI engine
      res.status(200).send('OK')
    } catch (error) {
      console.error('Error broadcasting GSI data:', error)
      res.status(500).send('Error')
    }
  })

  // Populate coach filter and Sync team data on startup
  syncGSITeams()
  syncCoaches()

  return router
}
