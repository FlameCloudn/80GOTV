import type { CSGO, HurtEvent, KillEvent, Player, Side } from 'csgogsi'
import type {
  MapPlayerData,
  MapSidePlayerData,
  PlayerRoundData,
  RoundData
} from '../domains/matches/match.types'

type EventCounter = {
  firstKills: number
  firstDeaths: number
  tradeKills: number
  tradeDeaths: number
  utilityDamage: number
  damageTaken: number
  mvpCount: number
  bombPlants: number
  bombDefuses: number
  flashAssists: number
}

type KillRecord = {
  killerSteamid: string
  victimSteamid: string
  killerSide: Side | null
  victimSide: Side
  at: number
  source: 'event' | 'snapshot'
}

type RoundEvents = {
  players: Record<string, EventCounter>
  kills: KillRecord[]
}

const emptyCounter = (): EventCounter => ({
  firstKills: 0,
  firstDeaths: 0,
  tradeKills: 0,
  tradeDeaths: 0,
  utilityDamage: 0,
  damageTaken: 0,
  mvpCount: 0,
  bombPlants: 0,
  bombDefuses: 0,
  flashAssists: 0
})

const cleanMap = (value: string) => value.substring(value.lastIndexOf('/') + 1)
const roundKey = (mapName: string, round: number) => `${cleanMap(mapName)}:${round}`
const opposingSide = (side: Side): Side => (side === 'CT' ? 'T' : 'CT')
const roundNumberForEvents = (game: CSGO) => Number(game.map.round || 0) + 1
const isHostileKill = (entry: KillRecord) =>
  Boolean(entry.killerSteamid && entry.killerSide && entry.killerSide !== entry.victimSide)

export class LiveStatsTracker {
  private rounds = new Map<string, RoundEvents>()

  resetMap(mapName: string) {
    const prefix = `${cleanMap(mapName)}:`
    for (const key of this.rounds.keys()) {
      if (key.startsWith(prefix)) this.rounds.delete(key)
    }
  }

  private round(game: CSGO): RoundEvents {
    const key = roundKey(game.map.name, roundNumberForEvents(game))
    const existing = this.rounds.get(key)
    if (existing) return existing
    const created = { players: {}, kills: [] }
    this.rounds.set(key, created)
    return created
  }

  private counter(events: RoundEvents, steamid: string): EventCounter {
    if (!events.players[steamid]) events.players[steamid] = emptyCounter()
    return events.players[steamid]
  }

  private recordHostileKill(
    events: RoundEvents,
    killer: Player,
    victim: Player,
    source: KillRecord['source']
  ) {
    const now = Date.now()
    this.counter(events, killer.steamid)
    this.counter(events, victim.steamid)

    const traded = [...events.kills]
      .reverse()
      .find(
        (entry) =>
          now - entry.at <= 5000 &&
          entry.killerSteamid === victim.steamid &&
          entry.victimSide === killer.team.side
      )
    if (traded) {
      this.counter(events, killer.steamid).tradeKills += 1
      this.counter(events, traded.victimSteamid).tradeDeaths += 1
    }
    events.kills.push({
      killerSteamid: killer.steamid,
      victimSteamid: victim.steamid,
      killerSide: killer.team.side,
      victimSide: victim.team.side,
      at: now,
      source
    })
  }

  recordKill(game: CSGO, event: KillEvent) {
    const events = this.round(game)
    const victim = event.victim
    const killer = event.killer
    if (!victim?.steamid) return

    const hostileKill = Boolean(
      killer?.steamid &&
        killer.steamid !== victim.steamid &&
        killer.team.side !== victim.team.side
    )
    if (hostileKill && killer) {
      this.recordHostileKill(events, killer, victim, 'event')
      if (event.flashed && event.assister?.steamid) {
        this.counter(events, event.assister.steamid).flashAssists += 1
      }
    } else {
      events.kills.push({
        killerSteamid: killer?.steamid || '',
        victimSteamid: victim.steamid,
        killerSide: killer?.team.side || null,
        victimSide: victim.team.side,
        at: Date.now(),
        source: 'event'
      })
    }
  }

  recordSnapshot(previous: CSGO | null | undefined, current: CSGO) {
    const events = this.round(current)
    const orderedPlayers = [...current.players]
      .filter((player) => player.steamid)
      .sort((left, right) => left.steamid.localeCompare(right.steamid))
    const previousPlayers = new Map(
      (previous && cleanMap(previous.map.name) === cleanMap(current.map.name)
        ? previous.players
        : []
      ).map((player) => [player.steamid, player])
    )
    const newlyDead = orderedPlayers.filter((player) => {
      if (!player.steamid) return false
      const old = previousPlayers.get(player.steamid)
      if (!old) return Number(player.state.health) <= 0
      return (
        Number(player.stats.deaths) > Number(old.stats.deaths) ||
        (Number(old.state.health) > 0 && Number(player.state.health) <= 0)
      )
    })
    const alreadyRecordedVictims = new Set(events.kills.map((entry) => entry.victimSteamid))
    const availableVictims = newlyDead.filter(
      (player) => !alreadyRecordedVictims.has(player.steamid)
    )

    orderedPlayers.forEach((killer) => {
      if (!killer.steamid) return
      const recordedKills = events.kills.filter(
        (entry) => entry.killerSteamid === killer.steamid && isHostileKill(entry)
      ).length
      let missingKills = Math.max(0, Number(killer.state.round_kills) - recordedKills)
      while (missingKills > 0) {
        let victimIndex = availableVictims.findIndex(
          (victim) => victim.team.side !== killer.team.side
        )
        if (victimIndex < 0) {
          victimIndex = orderedPlayers.findIndex(
            (victim) =>
              victim.steamid &&
              victim.team.side !== killer.team.side &&
              Number(victim.state.health) <= 0 &&
              !events.kills.some((entry) => entry.victimSteamid === victim.steamid)
          )
          if (victimIndex < 0) break
          const victim = orderedPlayers[victimIndex]
          this.recordHostileKill(events, killer, victim, 'snapshot')
        } else {
          const [victim] = availableVictims.splice(victimIndex, 1)
          this.recordHostileKill(events, killer, victim, 'snapshot')
        }
        missingKills -= 1
      }
    })
  }

  recordHurt(game: CSGO, event: HurtEvent) {
    if (!event.attacker?.steamid || !event.victim?.steamid) return
    if (event.attacker.team.side === event.victim.team.side) return
    const events = this.round(game)
    const damage = Math.max(0, Number(event.dmg_health) || 0)
    this.counter(events, event.victim.steamid).damageTaken += damage
    const weapon = String(event.weapon || '').toLowerCase()
    if (/grenade|molotov|incendiary|inferno|fire/.test(weapon)) {
      this.counter(events, event.attacker.steamid).utilityDamage += damage
    }
  }

  recordMvp(game: CSGO, player: Player) {
    if (player.steamid) this.counter(this.round(game), player.steamid).mvpCount += 1
  }

  recordBombPlant(game: CSGO, player: Player) {
    if (player.steamid) this.counter(this.round(game), player.steamid).bombPlants += 1
  }

  recordBombDefuse(game: CSGO, player: Player) {
    if (player.steamid) this.counter(this.round(game), player.steamid).bombDefuses += 1
  }

  consume(mapName: string, round: number, players: Player[], winner: Side) {
    const key = roundKey(mapName, round)
    const events = this.rounds.get(key) || { players: {}, kills: [] }
    Object.values(events.players).forEach((counter) => {
      counter.firstKills = 0
      counter.firstDeaths = 0
    })
    const firstKill = events.kills
      .filter(isHostileKill)
      .sort((left, right) => {
        if (left.source !== right.source) return left.source === 'event' ? -1 : 1
        if (left.at !== right.at) return left.at - right.at
        if (left.source === 'event') return 0
        return left.killerSteamid.localeCompare(right.killerSteamid) ||
          left.victimSteamid.localeCompare(right.victimSteamid)
      })[0]
    if (firstKill) {
      this.counter(events, firstKill.killerSteamid).firstKills = 1
      this.counter(events, firstKill.victimSteamid).firstDeaths = 1
    }
    const alive: Record<Side, Set<string>> = { CT: new Set(), T: new Set() }
    players.forEach((player) => {
      if (player.steamid) alive[player.team.side].add(player.steamid)
    })
    const clutchCandidates = new Map<string, number>()

    events.kills.forEach((kill) => {
      alive[kill.victimSide].delete(kill.victimSteamid)
      const survivors = alive[kill.victimSide]
      const enemies = alive[opposingSide(kill.victimSide)]
      if (survivors.size === 1 && enemies.size > 0) {
        const survivor = [...survivors][0]
        if (!clutchCandidates.has(survivor)) clutchCandidates.set(survivor, enemies.size)
      }
    })

    const clutchWinner = alive[winner].size === 1 ? [...alive[winner]][0] : ''
    const clutchSize = clutchWinner ? clutchCandidates.get(clutchWinner) || 0 : 0
    this.rounds.delete(key)
    return {
      counters: events.players,
      clutchWinner,
      clutchSize: Math.max(0, Math.min(5, clutchSize)),
      survivors: new Set([...alive.CT, ...alive.T]),
      hadKillEvents: events.kills.length > 0
    }
  }
}

export const liveStatsTracker = new LiveStatsTracker()

const sum = (rows: PlayerRoundData[], key: keyof PlayerRoundData) =>
  rows.reduce((total, row) => total + (Number(row[key]) || 0), 0)

// 和网站同一套 Rating 2.0 近似（CSDA 用的公开回归，网站见 utils/stats_calc.py）：
// Impact = 2.13×场均击杀 + 0.42×场均助攻 − 0.41。显示、上传的 Impact 最低记 0；Rating 用原值算，最低 0。
// 这样直播画面上的 Rating 和网站上同一张图的 Rating 一致。
const impactEstimate = (kpr: number, apr: number) => 2.13 * kpr + 0.42 * apr - 0.41

type RatingInputs = { kast: number; kpr: number; dpr: number; apr: number; adr: number }
const ratingEstimate = ({ kast, kpr, dpr, apr, adr }: RatingInputs) =>
  Math.max(
    0,
    0.0073 * kast +
      0.3591 * kpr -
      0.5329 * dpr +
      0.2372 * impactEstimate(kpr, apr) +
      0.0032 * adr +
      0.1587
  )

const roundMetrics = (rows: PlayerRoundData[]): MapSidePlayerData => {
  const roundsPlayed = rows.length
  const kills = sum(rows, 'kills')
  const deaths = sum(rows, 'deaths')
  const assists = sum(rows, 'assists')
  const damage = sum(rows, 'damage')
  const kastRounds = rows.filter(
    (row) =>
      Number(row.kills) > 0 ||
      Number(row.assists) > 0 ||
      Boolean(row.survived) ||
      Number(row.tradeDeaths) > 0
  ).length
  const adr = roundsPlayed ? damage / roundsPlayed : 0
  const kpr = roundsPlayed ? kills / roundsPlayed : 0
  const dpr = roundsPlayed ? deaths / roundsPlayed : 0
  const kast = roundsPlayed ? (kastRounds * 100) / roundsPlayed : 0
  const apr = roundsPlayed ? assists / roundsPlayed : 0
  const rating = roundsPlayed ? ratingEstimate({ kast, kpr, dpr, apr, adr }) : 0
  return {
    kills,
    deaths,
    assists,
    damage,
    roundsPlayed,
    kastRounds,
    adr: Number(adr.toFixed(1)),
    kpr: Number(kpr.toFixed(2)),
    dpr: Number(dpr.toFixed(2)),
    kast: Number(kast.toFixed(1)),
    rating: Number(rating.toFixed(2))
  }
}

const mappedTeamId = (teamId: string | null, isReversed: boolean, ctId: string, tId: string) => {
  const value = teamId || ''
  if (value && (value === ctId || value === tId)) return value
  if (!isReversed) return value
  if (value === ctId) return tId
  if (value === tId) return ctId
  return value
}

export type ScoreboardTotals = { kills: number; deaths: number; assists: number }
export type DamageObservation = { damage: number; rounds: number }

type MapTotals = ScoreboardTotals & {
  roundsPlayed: number
  roundsRecorded: number
  scale: number
  damage: number
  kastRounds: number
}

// 导播全程记录到每一回合时，直接按回合相加。漏回合时，KDA 使用终场计分板，KAST 用 K/A/D 能确认的最低回合数；
// 伤害优先使用完整回合 round_totaldmg 观测值的均值估算整图，没有观测样本才使用 GSI 的 ADR。
const mapTotals = (
  playerRounds: PlayerRoundData[],
  player: Player | undefined,
  scoreboard: ScoreboardTotals | undefined,
  damageObservation: DamageObservation | undefined,
  fallbackRounds: number
): MapTotals => {
  const recorded = playerRounds.length
  const mapRounds = Math.max(1, Number(fallbackRounds) || 1)
  const totals = roundMetrics(playerRounds)
  if (recorded && recorded >= mapRounds) {
    const { kills, deaths, assists, damage, kastRounds } = totals
    return { roundsPlayed: recorded, roundsRecorded: recorded, scale: 1, kills, deaths, assists, damage, kastRounds }
  }
  const finalStat = (key: keyof ScoreboardTotals) => {
    const boardValue = scoreboard?.[key]
    if (boardValue !== undefined && boardValue !== null && Number.isFinite(Number(boardValue))) {
      return Math.max(0, Number(boardValue))
    }
    return Math.max(0, Number(player?.stats[key]) || 0)
  }
  const board = {
    kills: finalStat('kills'),
    deaths: finalStat('deaths'),
    assists: finalStat('assists')
  }
  const observationDamage = Number(damageObservation?.damage)
  const observationRounds = Number(damageObservation?.rounds)
  const hasDamageObservation =
    damageObservation?.damage !== undefined &&
    damageObservation.damage !== null &&
    Number.isFinite(observationDamage) &&
    observationDamage >= 0 &&
    damageObservation.rounds !== undefined &&
    damageObservation.rounds !== null &&
    Number.isFinite(observationRounds) &&
    observationRounds > 0
  const estimatedDamage = hasDamageObservation
    ? Math.round((observationDamage / observationRounds) * mapRounds)
    : Math.round((Math.max(0, Number(player?.state.adr) || 0)) * mapRounds)
  const kastRounds = Math.min(mapRounds, Math.max(board.kills, board.assists, mapRounds - board.deaths))
  if (!recorded) {
    // 一回合都没记到：使用终场计分板；KAST 取 K/A/D 能确认的最低回合数。
    return {
      roundsPlayed: mapRounds,
      roundsRecorded: 0,
      scale: 1,
      ...board,
      damage: estimatedDamage,
      kastRounds
    }
  }
  const scale = mapRounds / recorded
  return {
    roundsPlayed: mapRounds,
    roundsRecorded: recorded,
    scale,
    ...board,
    damage: estimatedDamage,
    kastRounds
  }
}

// 多杀、残局只能按记录到的回合数（漏掉的回合补不回来）
const eventCounts = (playerRounds: PlayerRoundData[]) => {
  const multi = [1, 2, 3, 4, 5].map(
    (amount) => playerRounds.filter((row) => Math.min(5, Number(row.kills) || 0) === amount).length
  )
  const clutches = [1, 2, 3, 4, 5].map(
    (size) => playerRounds.filter((row) => Number(row.clutchSize) === size).length
  )
  return { multi, clutches, clutchesWon: clutches.reduce((total, value) => total + value, 0) }
}

// 每个赢下的回合里，这名选手的伤害占本方伤害的百分比之和
const rwsPointsFor = (rounds: (RoundData | null)[], steamid: string) =>
  rounds.reduce((total, round) => {
    const row = round?.players?.[steamid]
    if (!round || !row?.side || round.winner !== row.side) return total
    const teamDamage = Object.values(round.players)
      .filter((candidate) => candidate.side === row.side)
      .reduce((amount, candidate) => amount + (Number(candidate.damage) || 0), 0)
    return teamDamage > 0 ? total + ((Number(row.damage) || 0) * 100) / teamDamage : total
  }, 0)

type PlayerMapInput = {
  steamid: string
  player: Player | undefined
  playerRounds: PlayerRoundData[]
  rounds: (RoundData | null)[]
  scoreboard: ScoreboardTotals | undefined
  damageObservation: DamageObservation | undefined
  fallbackRounds: number
  teamId: string
}

const buildPlayerMapData = (input: PlayerMapInput): MapPlayerData => {
  const { steamid, player, playerRounds } = input
  const totals = mapTotals(
    playerRounds,
    player,
    input.scoreboard,
    input.damageObservation,
    input.fallbackRounds
  )
  const { roundsPlayed, kills, deaths, assists, damage, kastRounds } = totals
  const [adr, kpr, dpr, apr] = [damage, kills, deaths, assists].map((value) => value / roundsPlayed)
  const kast = (kastRounds * 100) / roundsPlayed
  const damageTaken = Math.round(sum(playerRounds, 'damageTaken') * totals.scale)
  const utilityDamage = Math.round(sum(playerRounds, 'utilityDamage') * totals.scale)
  const { multi, clutches, clutchesWon } = eventCounts(playerRounds)
  const latestRound = [...playerRounds].reverse()[0]
  return {
    name: player?.name || latestRound?.name || 'PLAYER',
    avatar: player?.avatar || latestRound?.avatar || undefined,
    teamId: latestRound?.teamId || input.teamId,
    kills, deaths, assists, damage, damageTaken, roundsPlayed, kastRounds,
    roundsRecorded: totals.roundsRecorded,
    headshots: sum(playerRounds, 'killshs'),
    adr: Number(adr.toFixed(1)),
    kpr: Number(kpr.toFixed(2)),
    dpr: Number(dpr.toFixed(2)),
    kast: Number(kast.toFixed(1)),
    impact: Number(Math.max(0, impactEstimate(kpr, apr)).toFixed(2)),
    rating: Number(ratingEstimate({ kast, kpr, dpr, apr, adr }).toFixed(2)),
    firstKills: sum(playerRounds, 'firstKills'),
    firstDeaths: sum(playerRounds, 'firstDeaths'),
    multi1k: multi[0], multi2k: multi[1], multi3k: multi[2], multi4k: multi[3], multi5k: multi[4],
    tradeKills: sum(playerRounds, 'tradeKills'),
    tradeDeaths: sum(playerRounds, 'tradeDeaths'),
    clutchesWon,
    clutch1v1: clutches[0], clutch1v2: clutches[1], clutch1v3: clutches[2], clutch1v4: clutches[3], clutch1v5: clutches[4],
    mvpCount: sum(playerRounds, 'mvpCount'),
    utilityDamage,
    utilityDamagePerRound: Number((utilityDamage / roundsPlayed).toFixed(1)),
    damageDeltaPerRound: Number(((damage - damageTaken) / roundsPlayed).toFixed(1)),
    bombPlants: sum(playerRounds, 'bombPlants'),
    bombDefuses: sum(playerRounds, 'bombDefuses'),
    flashAssists: sum(playerRounds, 'flashAssists'),
    rwsBasic: Number((rwsPointsFor(input.rounds, steamid) / Math.max(1, totals.roundsRecorded || roundsPlayed)).toFixed(2)),
    tStats: roundMetrics(playerRounds.filter((row) => row.side === 'T')),
    ctStats: roundMetrics(playerRounds.filter((row) => row.side === 'CT'))
  }
}

export const buildMapPlayerStats = ({
  players,
  rounds,
  isReversed,
  ctId,
  tId,
  fallbackRounds,
  scoreboard = {},
  damageObservations = {}
}: {
  players: Player[]
  rounds: (RoundData | null)[]
  isReversed: boolean
  ctId: string
  tId: string
  fallbackRounds: number
  // CS2 计分板的整图累计（已扣热身），按 steamid；漏回合时用它补正击杀、死亡、助攻
  scoreboard?: Record<string, ScoreboardTotals>
  // 完整回合的 round_totaldmg 观测值合计；只用于补估漏回合的整图伤害
  damageObservations?: Record<string, DamageObservation>
}): Record<string, MapPlayerData> => {
  const current = new Map(players.filter((player) => player.steamid).map((player) => [player.steamid, player]))
  const steamids = new Set(current.keys())
  rounds.forEach((round) => Object.keys(round?.players || {}).forEach((steamid) => steamids.add(steamid)))

  return Object.fromEntries(
    [...steamids].map((steamid) => {
      const player = current.get(steamid)
      const playerRounds = rounds
        .map((round) => round?.players?.[steamid])
        .filter((row): row is PlayerRoundData => Boolean(row))
      const latestRound = [...playerRounds].reverse()[0]
      const teamId = player ? mappedTeamId(player.team.id, isReversed, ctId, tId) : latestRound?.teamId || ''
      const data = buildPlayerMapData({
        steamid,
        player,
        playerRounds,
        rounds,
        scoreboard: scoreboard[steamid],
        damageObservation: damageObservations[steamid],
        fallbackRounds,
        teamId
      })
      return [steamid, data]
    })
  )
}
