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
    victim: Player
  ) {
    const now = Date.now()
    if (!events.kills.some((entry) => entry.killerSide !== entry.victimSide)) {
      this.counter(events, killer.steamid).firstKills += 1
      this.counter(events, victim.steamid).firstDeaths += 1
    }

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
      at: now
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
      this.recordHostileKill(events, killer, victim)
      if (event.flashed && event.assister?.steamid) {
        this.counter(events, event.assister.steamid).flashAssists += 1
      }
    } else {
      events.kills.push({
        killerSteamid: killer?.steamid || '',
        victimSteamid: victim.steamid,
        killerSide: killer?.team.side || null,
        victimSide: victim.team.side,
        at: Date.now()
      })
    }
  }

  recordSnapshot(previous: CSGO | null | undefined, current: CSGO) {
    const events = this.round(current)
    const previousPlayers = new Map(
      (previous && cleanMap(previous.map.name) === cleanMap(current.map.name)
        ? previous.players
        : []
      ).map((player) => [player.steamid, player])
    )
    const newlyDead = current.players.filter((player) => {
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

    current.players.forEach((killer) => {
      if (!killer.steamid) return
      const recordedKills = events.kills.filter(
        (entry) =>
          entry.killerSteamid === killer.steamid && entry.killerSide !== entry.victimSide
      ).length
      let missingKills = Math.max(0, Number(killer.state.round_kills) - recordedKills)
      while (missingKills > 0) {
        let victimIndex = availableVictims.findIndex(
          (victim) => victim.team.side !== killer.team.side
        )
        if (victimIndex < 0) {
          victimIndex = current.players.findIndex(
            (victim) =>
              victim.steamid &&
              victim.team.side !== killer.team.side &&
              Number(victim.state.health) <= 0 &&
              !events.kills.some((entry) => entry.victimSteamid === victim.steamid)
          )
          if (victimIndex < 0) break
          const victim = current.players[victimIndex]
          this.recordHostileKill(events, killer, victim)
        } else {
          const [victim] = availableVictims.splice(victimIndex, 1)
          this.recordHostileKill(events, killer, victim)
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
  const impact = roundsPlayed
    ? (sum(rows, 'firstKills') * 1.5 -
        sum(rows, 'firstDeaths') * 0.7 +
        rows.filter((row) => Number(row.kills) >= 2).length * 0.5 +
        rows.filter((row) => Number(row.clutchSize) > 0).length * 2) /
      roundsPlayed
    : 0
  // A calculated Impact of zero is valid; do not silently replace it with a
  // second formula just because it is falsy.
  const effectiveImpact = impact
  const rating = roundsPlayed
    ? 0.0073 * kast +
      0.3591 * kpr -
      0.5329 * dpr +
      0.2372 * effectiveImpact +
      0.0032 * adr +
      0.2698
    : 0
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
    rating: Number(Math.max(0, Math.min(3, rating)).toFixed(2))
  }
}

const mappedTeamId = (teamId: string | null, isReversed: boolean, ctId: string, tId: string) => {
  const value = teamId || ''
  if (!isReversed) return value
  if (value === ctId) return tId
  if (value === tId) return ctId
  return value
}

export const buildMapPlayerStats = ({
  players,
  rounds,
  isReversed,
  ctId,
  tId,
  fallbackRounds
}: {
  players: Player[]
  rounds: (RoundData | null)[]
  isReversed: boolean
  ctId: string
  tId: string
  fallbackRounds: number
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
      const fallbackRoundCount = Math.max(1, Number(fallbackRounds) || 1)
      const roundsPlayed = playerRounds.length || fallbackRoundCount
      const roundTotals = roundMetrics(playerRounds)
      const hasOfficialRounds = playerRounds.length > 0
      const kills = hasOfficialRounds ? roundTotals.kills : Number(player?.stats.kills) || 0
      const deaths = hasOfficialRounds ? roundTotals.deaths : Number(player?.stats.deaths) || 0
      const assists = hasOfficialRounds ? roundTotals.assists : Number(player?.stats.assists) || 0
      const damage = hasOfficialRounds
        ? roundTotals.damage
        : Math.round((Number(player?.state.adr) || 0) * roundsPlayed)
      const adr = roundsPlayed ? damage / roundsPlayed : 0
      const kpr = roundsPlayed ? kills / roundsPlayed : 0
      const dpr = roundsPlayed ? deaths / roundsPlayed : 0
      const officialKastRounds = playerRounds.filter(
        (row) =>
          Number(row.kills) > 0 ||
          Number(row.assists) > 0 ||
          Boolean(row.survived) ||
          Number(row.tradeDeaths) > 0
      ).length
      // If a disconnect skipped the round buffer, do not treat every round as
      // a KAST miss. The official K/D line still tells us the minimum likely
      // KAST: kills/assists or rounds survived (rounds minus deaths).
      const fallbackKastRounds = Math.min(
        roundsPlayed,
        Math.max(kills, assists, roundsPlayed - deaths)
      )
      const kastRounds = hasOfficialRounds ? officialKastRounds : fallbackKastRounds
      const kast = roundsPlayed ? (kastRounds * 100) / roundsPlayed : 0
      const firstKills = sum(playerRounds, 'firstKills')
      const firstDeaths = sum(playerRounds, 'firstDeaths')
      const multi = [1, 2, 3, 4, 5].map(
        (amount) => playerRounds.filter((row) => Math.min(5, Number(row.kills) || 0) === amount).length
      )
      const clutches = [1, 2, 3, 4, 5].map(
        (size) => playerRounds.filter((row) => Number(row.clutchSize) === size).length
      )
      const clutchesWon = clutches.reduce((total, value) => total + value, 0)
      const impact = roundsPlayed
        ? (firstKills * 1.5 -
            firstDeaths * 0.7 +
            multi.slice(1).reduce((total, value) => total + value, 0) * 0.5 +
            clutchesWon * 2) /
          roundsPlayed
        : 0
      const effectiveImpact = impact
      const rating =
        0.0073 * kast +
        0.3591 * kpr -
        0.5329 * dpr +
        0.2372 * effectiveImpact +
        0.0032 * adr +
        0.2698
      const damageTaken = sum(playerRounds, 'damageTaken')
      const tStats = roundMetrics(playerRounds.filter((row) => row.side === 'T'))
      const ctStats = roundMetrics(playerRounds.filter((row) => row.side === 'CT'))
      const rwsPoints = rounds.reduce((total, round) => {
        const row = round?.players?.[steamid]
        if (!round || !row?.side || round.winner !== row.side) return total
        const teamDamage = Object.values(round.players)
          .filter((candidate) => candidate.side === row.side)
          .reduce((amount, candidate) => amount + (Number(candidate.damage) || 0), 0)
        return teamDamage > 0 ? total + ((Number(row.damage) || 0) * 100) / teamDamage : total
      }, 0)
      const latestRound = [...playerRounds].reverse()[0]
      const currentTeamId = player
        ? mappedTeamId(player.team.id, isReversed, ctId, tId)
        : latestRound?.teamId || ''

      return [
        steamid,
        {
          name: player?.name || latestRound?.name || 'PLAYER',
          avatar: player?.avatar || latestRound?.avatar || undefined,
          teamId: latestRound?.teamId || currentTeamId,
          kills,
          deaths,
          assists,
          damage,
          damageTaken,
          roundsPlayed,
          headshots: sum(playerRounds, 'killshs'),
          adr: Number(adr.toFixed(1)),
          kpr: Number(kpr.toFixed(2)),
          dpr: Number(dpr.toFixed(2)),
          kast: Number(kast.toFixed(1)),
          kastRounds,
          impact: Number(Math.max(0, impact).toFixed(2)),
          rating: Number(Math.max(0, Math.min(3, rating)).toFixed(2)),
          firstKills,
          firstDeaths,
          multi1k: multi[0],
          multi2k: multi[1],
          multi3k: multi[2],
          multi4k: multi[3],
          multi5k: multi[4],
          tradeKills: sum(playerRounds, 'tradeKills'),
          tradeDeaths: sum(playerRounds, 'tradeDeaths'),
          clutchesWon,
          clutch1v1: clutches[0],
          clutch1v2: clutches[1],
          clutch1v3: clutches[2],
          clutch1v4: clutches[3],
          clutch1v5: clutches[4],
          mvpCount: sum(playerRounds, 'mvpCount'),
          utilityDamage: sum(playerRounds, 'utilityDamage'),
          utilityDamagePerRound: Number((sum(playerRounds, 'utilityDamage') / roundsPlayed).toFixed(1)),
          damageDeltaPerRound: Number(((damage - damageTaken) / roundsPlayed).toFixed(1)),
          bombPlants: sum(playerRounds, 'bombPlants'),
          bombDefuses: sum(playerRounds, 'bombDefuses'),
          flashAssists: sum(playerRounds, 'flashAssists'),
          rwsBasic: Number((rwsPoints / roundsPlayed).toFixed(2)),
          tStats,
          ctStats
        } satisfies MapPlayerData
      ]
    })
  )
}
