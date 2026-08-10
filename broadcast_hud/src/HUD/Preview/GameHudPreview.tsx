import { Map, Player, Team } from "csgogsi";
import MatchBar from "../MatchBar/MatchBar";
import Observed from "../Players/Observed";
import TeamBox from "../Players/TeamBox";
import nukeRadar from "../../assets/images/de_nuke_radar.png";

const leftTeam: Team = {
  id: "g8",
  name: "G8 Esports",
  logo: "/api/uploads/80gotv-team-registration-5.png",
  score: 7,
  consecutive_round_losses: 0,
  timeouts_remaining: 2,
  matches_won_this_series: 0,
  side: "CT",
  country: null,
  orientation: "left",
  extra: {},
};

const rightTeam: Team = {
  id: "u8",
  name: "U8",
  logo: "/api/uploads/80gotv-team-12.png",
  score: 5,
  consecutive_round_losses: 1,
  timeouts_remaining: 2,
  matches_won_this_series: 0,
  side: "T",
  country: null,
  orientation: "right",
  extra: {},
};

const makePlayer = (
  steamid: string,
  name: string,
  slot: number,
  team: Team,
  health: number,
  money: number,
  kills: number,
  assists: number,
  deaths: number,
  weapon: string,
  avatar: string | null,
): Player => ({
  steamid,
  name,
  defaultName: name,
  observer_slot: slot,
  team,
  stats: { kills, assists, deaths, mvps: 0, score: kills * 2 },
  weapons: [
    {
      id: `${steamid}-${weapon}`,
      name: `weapon_${weapon}`,
      paintkit: "default",
      type: weapon === "deagle" ? "Pistol" : "Rifle",
      ammo_clip: weapon === "awp" ? 7 : 24,
      ammo_clip_max: weapon === "awp" ? 10 : 30,
      ammo_reserve: 90,
      state: "active",
    },
    ...(weapon === "deagle" ? [] : [{
      id: `${steamid}-pistol`,
      name: "weapon_usp_silencer",
      paintkit: "default",
      type: "Pistol" as const,
      ammo_clip: 12,
      ammo_clip_max: 12,
      ammo_reserve: 24,
      state: "holstered" as const,
    }]),
    {
      id: `${steamid}-flashbang`,
      name: "weapon_flashbang",
      paintkit: "default",
      type: "Grenade",
      ammo_reserve: 1,
      state: "holstered",
    },
    {
      id: `${steamid}-smokegrenade`,
      name: "weapon_smokegrenade",
      paintkit: "default",
      type: "Grenade",
      ammo_reserve: 1,
      state: "holstered",
    },
    ...(team.side === "T" && slot === 6 ? [{
      id: `${steamid}-c4`,
      name: "weapon_c4",
      paintkit: "default",
      type: "C4" as const,
      state: "holstered" as const,
    }] : []),
  ],
  state: {
    health,
    armor: 90,
    helmet: true,
    defusekit: team.side === "CT" && slot === 2,
    flashed: 0,
    smoked: 0,
    burning: 0,
    money,
    round_kills: 0,
    round_killhs: 0,
    round_totaldmg: 0,
    equip_value: 4500,
    adr: 80,
  },
  position: [0, 0, 0],
  forward: [0, 0, 0],
  avatar,
  country: null,
  realName: null,
  extra: { recentDamage: "7" },
});

const leftPlayers = [
  makePlayer("76561198846740714", "cmdrJacob", 1, leftTeam, 100, 1200, 18, 8, 8, "m4a1_silencer", "/api/uploads/80gotv-player-20.jpg"),
  makePlayer("76561199505982342", "Ning", 2, leftTeam, 95, 1600, 17, 9, 9, "awp", "/api/uploads/80gotv-player-21.jpg"),
  makePlayer("76561199571335197", "ZZJ", 3, leftTeam, 90, 2000, 16, 10, 8, "m4a1", "/api/uploads/80gotv-player-22.jpg"),
  makePlayer("76561199019316014", "franklinwqf", 4, leftTeam, 85, 2400, 15, 11, 10, "famas", "/api/uploads/80gotv-player-23.jpg"),
  makePlayer("76561199174430317", "yonix", 5, leftTeam, 80, 2800, 14, 12, 9, "deagle", "/api/uploads/80gotv-player-31.jpg"),
];

const rightPlayers = [
  makePlayer("76561199437997294", "AAA'钢板批发可师傅", 6, rightTeam, 28, 4300, 16, 8, 12, "ak47", "/api/uploads/80gotv-player-9.jpg"),
  makePlayer("76561199494464507", "dongsi666", 7, rightTeam, 70, 3600, 12, 9, 9, "awp", "/api/uploads/80gotv-player-24.jpg"),
  makePlayer("76561199026205129", "Nightmire", 8, rightTeam, 65, 4000, 11, 10, 10, "ak47", "/api/uploads/80gotv-player-35.jpg"),
  makePlayer("76561199158454974", "上杉绘梨衣", 9, rightTeam, 0, 1950, 13, 11, 11, "galilar", "/api/uploads/80gotv-player-29.jpg"),
  makePlayer("76561199640169490", "小米果", 0, rightTeam, 55, 4800, 9, 12, 11, "deagle", "/api/uploads/80gotv-player-30.jpg"),
];

const map: Map = {
  mode: "competitive",
  name: "de_nuke",
  phase: "live",
  round: 12,
  team_ct: leftTeam,
  team_t: rightTeam,
  num_matches_to_win_series: 2,
  current_spectators: 0,
  souvenirs_total: 0,
  round_wins: {},
  rounds: [],
};

const GameHudPreview = () => {
  const observed = rightPlayers[0];
  return (
    <div className="layout live-hud director-game-preview">
      <div id="radar_maps_container" className="director-preview-radar-shell">
        <div id="maps_container">
          <div className="bestof">BEST OF 3</div>
          <div className="veto_entry"><div className="map_name active">NUKE</div></div>
          <div className="veto_entry"><div className="map_name">MIRAGE</div></div>
          <div className="veto_entry"><div className="map_name">DUST2</div></div>
        </div>
        <div className="director-preview-radar">
          <img src={nukeRadar} alt="" />
          <span className="radar-site site-a">A</span><span className="radar-site site-b">B</span>
          <span className="radar-chip ct c1">1</span><span className="radar-chip ct c2">2</span><span className="radar-chip ct c3">3</span><span className="radar-chip ct c4">4</span><span className="radar-chip ct c5">5</span>
          <span className="radar-chip t t1">6</span><span className="radar-chip t t2">7</span><span className="radar-chip t t3">8</span><span className="radar-chip t t4">9</span><span className="radar-chip t t5">0</span>
        </div>
      </div>

      <MatchBar
        map={map}
        phase={{ phase: "live", phase_ends_in: 27 }}
        bomb={null}
        match={null}
      />

      <div className="players_alive">
        <div className="title_container">Players alive</div>
        <div className="counter_container">
          <div className="team_counter CT">5</div><div className="vs_counter">VS</div><div className="team_counter T">4</div>
        </div>
      </div>

      <TeamBox team={leftTeam} players={leftPlayers} side="left" current={observed} />
      <TeamBox team={rightTeam} players={rightPlayers} side="right" current={observed} />
      <Observed player={observed} />
    </div>
  );
};

export default GameHudPreview;
