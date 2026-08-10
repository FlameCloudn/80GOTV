export interface PlayerRoundData {
  kills: number
  killshs: number
  damage: number
  name?: string
  avatar?: string
  teamId?: string
  side?: 'CT' | 'T'
  assists?: number
  deaths?: number
  survived?: boolean
  firstKills?: number
  firstDeaths?: number
  tradeKills?: number
  tradeDeaths?: number
  clutchSize?: number
  utilityDamage?: number
  damageTaken?: number
  mvpCount?: number
  bombPlants?: number
  bombDefuses?: number
  flashAssists?: number
}

export interface RoundData {
  round: number
  players: {
    [steamid: string]: PlayerRoundData
  }
  winner: 'CT' | 'T' | null
  win_type: 'bomb' | 'elimination' | 'defuse' | 'time'
}

export interface MapPlayerData {
  name: string
  avatar?: string
  teamId: string
  kills: number
  deaths: number
  assists?: number
  damage?: number
  damageTaken?: number
  roundsPlayed?: number
  headshots?: number
  adr?: number
  kpr?: number
  dpr?: number
  kast?: number
  kastRounds?: number
  impact?: number
  rating?: number
  firstKills?: number
  firstDeaths?: number
  multi1k?: number
  multi2k?: number
  multi3k?: number
  multi4k?: number
  multi5k?: number
  tradeKills?: number
  tradeDeaths?: number
  clutchesWon?: number
  clutch1v1?: number
  clutch1v2?: number
  clutch1v3?: number
  clutch1v4?: number
  clutch1v5?: number
  mvpCount?: number
  utilityDamage?: number
  utilityDamagePerRound?: number
  damageDeltaPerRound?: number
  bombPlants?: number
  bombDefuses?: number
  flashAssists?: number
  rwsBasic?: number
  tStats?: MapSidePlayerData
  ctStats?: MapSidePlayerData
}

export interface MapSidePlayerData {
  kills: number
  deaths: number
  assists: number
  damage: number
  roundsPlayed: number
  kastRounds: number
  adr: number
  kpr: number
  dpr: number
  kast: number
  rating: number
}

export interface Veto {
  teamId: string
  mapName: string
  side: 'CT' | 'T' | 'NO'
  type: 'ban' | 'pick' | 'decider'
  reverseSide?: boolean
  openingCtTeamId?: string
  sideSource?: 'website_bp' | 'tgpro_stable_gsi' | 'legacy_manual' | 'unknown'
  rounds?: (RoundData | null)[]
  score?: {
    [key: string]: number
  }
  playerStats?: {
    [steamid: string]: MapPlayerData
  }
  winner?: string
  mapEnd: boolean
}

export interface Match {
  id: string
  current: boolean
  left: {
    id: string | null
    wins: number
  }
  right: {
    id: string | null
    wins: number
  }
  matchType: 'bo1' | 'bo2' | 'bo3' | 'bo5'
  vetos: Veto[]
}

// Utility types for CRUD
export type CreateMatchDTO = Omit<Match, 'id'>
export type UpdateMatchDTO = Partial<CreateMatchDTO>
