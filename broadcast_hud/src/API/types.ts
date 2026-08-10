export interface Player {
  _id: string;
  firstName: string;
  lastName: string;
  username: string;
  avatar: string;
  country: string;
  steamid: string;
  team: string;
  extra: Record<string, string>;
}

export interface Team {
  _id: string;
  name: string;
  country: string;
  shortName: string;
  logo: string;
  extra: Record<string, string>;
}
/*
export interface HUD {
    name: string,
    version: string,
    author: string,
    legacy: boolean,
    dir: string
}
 
export interface Config {
    port: number,
    steamApiKey: string,
    token: string,
}*/
export interface TournamentMatchup {
  _id: string;
  loser_to: string | null; // IDs of Matchups, not Matches
  winner_to: string | null;
  label: string;
  matchId: string | null;
  parents: TournamentMatchup[];
}

export interface DepthTournamentMatchup extends TournamentMatchup {
  depth: number;
  parents: DepthTournamentMatchup[];
}

export type TournamentTypes = 'swiss' | 'single' | 'double';

export type TournamentStage = {
  type: TournamentTypes;
  matchups: TournamentMatchup[];
  teams: number;
  phases: number;
  participants: string[];
};
export interface Tournament {
  _id: string;
  name: string;
  logo: string;
  groups: TournamentStage[];
  playoffs: TournamentStage;
  autoCreate: boolean;
}
export interface RoundData {
  round: number,
  players: {
    [steamid: string]: PlayerRoundData
  },
  winner: 'CT' | 'T' | null,
  win_type: 'bomb' | 'elimination' | 'defuse' | 'time',
}

export interface PlayerRoundData {
  kills: number,
  killshs: number,
  damage: number,
  name?: string;
  avatar?: string;
  teamId?: string;
  side?: "CT" | "T";
  assists?: number;
  deaths?: number;
  survived?: boolean;
  firstKills?: number;
  firstDeaths?: number;
  tradeKills?: number;
  tradeDeaths?: number;
  clutchSize?: number;
  utilityDamage?: number;
  damageTaken?: number;
  mvpCount?: number;
  bombPlants?: number;
  bombDefuses?: number;
  flashAssists?: number;
}

export interface MapPlayerData {
  name: string;
  avatar?: string;
  teamId: string;
  kills: number;
  deaths: number;
  assists?: number;
  damage?: number;
  damageTaken?: number;
  roundsPlayed?: number;
  headshots?: number;
  adr?: number;
  kpr?: number;
  dpr?: number;
  kast?: number;
  kastRounds?: number;
  impact?: number;
  rating?: number;
  firstKills?: number;
  firstDeaths?: number;
  multi1k?: number;
  multi2k?: number;
  multi3k?: number;
  multi4k?: number;
  multi5k?: number;
  tradeKills?: number;
  tradeDeaths?: number;
  clutchesWon?: number;
  clutch1v1?: number;
  clutch1v2?: number;
  clutch1v3?: number;
  clutch1v4?: number;
  clutch1v5?: number;
  mvpCount?: number;
  utilityDamage?: number;
  utilityDamagePerRound?: number;
  damageDeltaPerRound?: number;
  bombPlants?: number;
  bombDefuses?: number;
  flashAssists?: number;
  rwsBasic?: number;
  tStats?: MapSidePlayerData;
  ctStats?: MapSidePlayerData;
}

export interface MapSidePlayerData {
  kills: number;
  deaths: number;
  assists: number;
  damage: number;
  roundsPlayed: number;
  kastRounds: number;
  adr: number;
  kpr: number;
  dpr: number;
  kast: number;
  rating: number;
}

export interface Veto {
  teamId: string;
  mapName: string;
  side: "CT" | "T" | "NO";
  type: "ban" | "pick" | "decider";
  reverseSide?: boolean;
  openingCtTeamId?: string;
  sideSource?: "website_bp" | "tgpro_stable_gsi" | "legacy_manual" | "unknown";
  rounds?: (RoundData | null)[],
  score?: {
    [key: string]: number;
  };
  playerStats?: {
    [steamid: string]: MapPlayerData;
  };
  winner?: string;
  mapEnd: boolean;
}

export interface Match {
  id: string;
  current: boolean;
  left: {
    id: string | null;
    wins: number;
  };
  right: {
    id: string | null;
    wins: number;
  };
  matchType: "bo1" | "bo2" | "bo3" | "bo5";
  vetos: Veto[];
}

export type Weapon =
  | "ak47"
  | "aug"
  | "awp"
  | "bizon"
  | "famas"
  | "g3sg1"
  | "galilar"
  | "m4a1"
  | "m4a1_silencer"
  | "m249"
  | "mac10"
  | "mag7"
  | "mp5sd"
  | "mp7"
  | "mp9"
  | "negev"
  | "nova"
  | "p90"
  | "sawedoff"
  | "scar20"
  | "sg556"
  | "ssg08"
  | "ump45"
  | "xm1014"
  | Pistol
  | Knife;

export type Pistol = "c75a" | "deagle" | "elite" | "fiveseven" | "glock" | "hkp2000" | "p250" | "revolver" | "taser" | "tec9" | "usp_silencer";

export type Knife =
  | "knife"//
  | "knife_css"//--
  | "knife_butterfly"//
  | "knife_falchion"//
  | "knife_flip"//
  | "knife_outdoor" // Nomad Knife
  | "knife_gut"//
  | "knife_gypsy_jackknife"//
  | "knife_karambit"// 
  | "knife_bayonet" //
  | "knife_cord" //
  | "knife_m9_bayonet"//
  | "knife_push" // Shadow daggers
  | "knife_stiletto"//
  | "knife_survival_bowie"//
  | "knife_t"//
  | "knife_skeleton" //
  | "knife_tactical"//
  | "knife_ursus"//
  | "knife_widowmaker"//
  | "knife_canis";//

export interface GameMapRadar {
  id: number;
  lhmId: string;
  originHeight?: number;
  originX?: number;
  originY?: number;
  pxPerUX?: number;
  pxPerUY?: number;
  radar: string;
  visibleOverHeight: number | null;
  visibleUnderHeight: number | null;
}

export interface GameMap {
  _id: string;
  name: string;
  lhmId: string;
  game: string;
  image?: string;
  radars: GameMapRadar[];
  verticalImage?: string;
  inVetoPool: boolean;
  isActive: boolean;
}
