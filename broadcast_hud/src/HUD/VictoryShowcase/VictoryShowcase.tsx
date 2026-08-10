import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSGO, Player, Team } from "csgogsi";
import type { MapPlayerData, Match, Veto } from "../../API/types";
import { onGSI } from "../../API/contexts/actions";
import { fadeInAudio, fadeOutAudio } from "../audioFade";
import TeamLogoImage from "../TeamLogoImage";
import steamAvatarDefault from "../../assets/images/steam_avatar_default.jpg";
import "./victory-showcase.scss";

type Props = {
  game?: CSGO | null;
  match?: Match | null;
  demo?: boolean;
  seriesSummaryOnly?: boolean;
  manualMode?: "map" | "series" | null;
};

const SHOW_DELAY_MS = 1000;

type DisplayTeam = {
  id: string;
  name: string;
  logo: string;
  score: number;
  series: number;
};

type DisplayPlayer = {
  name: string;
  avatar: string;
  kills: number;
  deaths: number;
  assists: number;
  rating: number;
  adr: number;
};

type DisplayMap = {
  name: string;
  pickedBy: string;
  leftScore: number | null;
  rightScore: number | null;
  active: boolean;
};

type VictoryModel = {
  left: DisplayTeam;
  right: DisplayTeam;
  winner: DisplayTeam;
  loser: DisplayTeam;
  leftPlayers: DisplayPlayer[];
  rightPlayers: DisplayPlayer[];
  seriesLeftPlayers: DisplayPlayer[];
  seriesRightPlayers: DisplayPlayer[];
  seriesStatsComplete: boolean;
  maps: DisplayMap[];
  format: string;
  seriesComplete: boolean;
};

const publicAsset = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, "")}`;
const cleanMap = (name: string) =>
  String(name || "").split("/").pop()?.replace(/^de_/i, "").toLowerCase() || "tbd";
const mapLabel = (name: string) => cleanMap(name).toUpperCase();

const displayTeam = (team: Team, series: number): DisplayTeam => ({
  id: String(team.id || team.side),
  name: team.name || "TEAM",
  logo: team.logo || "",
  score: Number(team.score) || 0,
  series,
});

const ratingFromLine = (kills: number, deaths: number, assists: number, adr: number, rounds: number) => {
  if (!rounds) return 0;
  const rating = 0.25
    + 0.6 * (kills / rounds)
    - 0.3 * (deaths / rounds)
    + 0.2 * (assists / rounds)
    + 0.006 * adr;
  return Number(Math.max(0, Math.min(3, rating)).toFixed(2));
};

const playerRows = (players: Player[], team: Team, rounds: number): DisplayPlayer[] =>
  players
    .filter((player) => player.team.id === team.id || player.team.side === team.side)
    .sort((a, b) => (a.observer_slot || 99) - (b.observer_slot || 99))
    .slice(0, 5)
    .map((player) => {
      const kills = Number(player.stats.kills) || 0;
      const deaths = Number(player.stats.deaths) || 0;
      const assists = Number(player.stats.assists) || 0;
      const adr = Number(player.state.adr) || 0;
      return {
        name: player.name || "PLAYER",
        avatar: player.avatar || "",
        kills,
        deaths,
        assists,
        rating: ratingFromLine(kills, deaths, assists, adr, rounds),
        adr,
      };
    });

const ratingFromTotals = ({
  kills,
  deaths,
  damage,
  rounds,
  kastRounds,
  firstKills,
  firstDeaths,
  multiKills,
  clutches,
}: {
  kills: number;
  deaths: number;
  damage: number;
  rounds: number;
  kastRounds: number;
  firstKills: number;
  firstDeaths: number;
  multiKills: number;
  clutches: number;
}) => {
  if (!rounds) return { rating: 0, adr: 0 };
  const adr = damage / rounds;
  const kpr = kills / rounds;
  const dpr = deaths / rounds;
  const kast = kastRounds * 100 / rounds;
  const impact = (firstKills * 1.5 - firstDeaths * 0.7 + multiKills * 0.5 + clutches * 2) / rounds;
  const effectiveImpact = impact;
  const rating = 0.0073 * kast + 0.3591 * kpr - 0.5329 * dpr
    + 0.2372 * effectiveImpact + 0.0032 * adr + 0.2698;
  return {
    rating: Number(Math.max(0, Math.min(3, rating)).toFixed(2)),
    adr: Number(adr.toFixed(1)),
  };
};

const fallbackRatingFromBoxScore = (player: MapPlayerData) => {
  const kills = Number(player.kills) || 0;
  const deaths = Number(player.deaths) || 0;
  const assists = Number(player.assists) || 0;
  const adr = Number(player.adr) || 0;
  const rounds = Math.max(1, Number(player.roundsPlayed) || 1);
  const kastRounds = Math.min(rounds, Math.max(kills, assists, rounds - deaths));
  const kast = kastRounds * 100 / rounds;
  const kpr = kills / rounds;
  const dpr = deaths / rounds;
  const effectiveImpact = kpr * 0.5 + adr / 200;
  return Number(Math.max(0, Math.min(3, 0.0073 * kast + 0.3591 * kpr - 0.5329 * dpr
    + 0.2372 * effectiveImpact + 0.0032 * adr + 0.2698)).toFixed(2));
};

const displayStoredPlayer = (player: MapPlayerData): DisplayPlayer => {
  const storedRating = Number(player.rating);
  const hasRoundBreakdown = Number(player.kastRounds) > 0 ||
    Number(player.firstKills) > 0 || Number(player.firstDeaths) > 0 ||
    Number(player.multi2k) > 0 || Number(player.clutchesWon) > 0;
  return {
    name: player.name || "PLAYER",
    avatar: player.avatar || "",
    kills: Number(player.kills) || 0,
    deaths: Number(player.deaths) || 0,
    assists: Number(player.assists) || 0,
    // Old records created while the round buffer was empty have rating/kast
    // set to zero-based placeholders. Rebuild that rating from the official
    // K/D/A + ADR line instead of preserving the misleading low value.
    rating: hasRoundBreakdown && Number.isFinite(storedRating)
      ? storedRating
      : fallbackRatingFromBoxScore(player),
    adr: Number(player.adr) || 0,
  };
};

const vetoPlayerRows = (veto: Veto | undefined, team: Team, fallback: DisplayPlayer[]) => {
  if (!veto?.playerStats) return fallback;
  const stored = Object.values(veto.playerStats)
    .filter((player) => player.teamId === team.id)
    .map(displayStoredPlayer)
    .sort((a, b) => b.rating - a.rating || b.kills - a.kills)
    .slice(0, 5);
  return stored.length ? stored : fallback;
};

const seriesPlayerRows = (
  match: Match | null | undefined,
  team: Team,
  fallback: DisplayPlayer[],
) => {
  const completedMaps = (match?.vetos || []).filter((veto) => veto.type !== "ban" && veto.mapEnd);
  const storedMaps = completedMaps.filter((veto) => veto.playerStats && Object.keys(veto.playerStats).length);
  const detailedMaps = storedMaps.filter((veto) =>
    Object.values(veto.playerStats || {}).some((player) =>
      Number(player.roundsPlayed) > 0 && Number.isFinite(Number(player.damage)),
    ),
  );
  const totals = new Map<string, DisplayPlayer & {
    damage: number;
    rounds: number;
    kastRounds: number;
    firstKills: number;
    firstDeaths: number;
    multiKills: number;
    clutches: number;
  }>();

  storedMaps.forEach((veto) => {
    Object.entries(veto.playerStats || {}).forEach(([steamid, player]) => {
      if (player.teamId !== team.id) return;
      const existing = totals.get(steamid);
      totals.set(steamid, {
        name: player.name || existing?.name || "PLAYER",
        avatar: player.avatar || existing?.avatar || "",
        kills: (existing?.kills || 0) + (Number(player.kills) || 0),
        deaths: (existing?.deaths || 0) + (Number(player.deaths) || 0),
        assists: (existing?.assists || 0) + (Number(player.assists) || 0),
        rating: 0,
        adr: 0,
        damage: (existing?.damage || 0) + (Number(player.damage) || 0),
        rounds: (existing?.rounds || 0) + (Number(player.roundsPlayed) || 0),
        kastRounds: (existing?.kastRounds || 0) + (Number(player.kastRounds) || 0),
        firstKills: (existing?.firstKills || 0) + (Number(player.firstKills) || 0),
        firstDeaths: (existing?.firstDeaths || 0) + (Number(player.firstDeaths) || 0),
        multiKills: (existing?.multiKills || 0)
          + (Number(player.multi2k) || 0) + (Number(player.multi3k) || 0)
          + (Number(player.multi4k) || 0) + (Number(player.multi5k) || 0),
        clutches: (existing?.clutches || 0) + (Number(player.clutchesWon) || 0),
      });
    });
  });

  const players = [...totals.values()].map((player) => ({
    ...player,
    ...ratingFromTotals(player),
  }))
    .sort((a, b) => b.kills - a.kills || a.deaths - b.deaths)
    .slice(0, 5);
  return {
    players: players.length ? players : fallback,
    complete: completedMaps.length > 0 && detailedMaps.length === completedMaps.length,
  };
};

const seriesScore = (match: Match | null | undefined, team: Team) => {
  // Website-synced map wins are authoritative. TGPro's raw series fields are
  // often zero/default and can be attached to the wrong observer side.
  if (team.id && match?.left.id === team.id) return Number(match.left.wins) || 0;
  if (team.id && match?.right.id === team.id) return Number(match.right.wins) || 0;
  if (match) return 0;
  const live = Number(team.matches_won_this_series);
  if (Number.isFinite(live) && live >= 0) return live;
  return 0;
};

const vetoScore = (veto: Veto, team: Team) => {
  if (!team.id || !veto.score) return null;
  const value = veto.score[team.id];
  return Number.isFinite(value) ? Number(value) : null;
};

const liveModel = (game?: CSGO | null, match?: Match | null): VictoryModel | null => {
  if (!game) return null;
  const leftRaw = game.map.team_ct.orientation === "left" ? game.map.team_ct : game.map.team_t;
  const rightRaw = leftRaw.side === game.map.team_ct.side ? game.map.team_t : game.map.team_ct;
  const left = displayTeam(leftRaw, seriesScore(match, leftRaw));
  const right = displayTeam(rightRaw, seriesScore(match, rightRaw));
  const winner = left.score >= right.score ? left : right;
  const loser = winner.id === left.id ? right : left;
  const currentMap = cleanMap(game.map.name);
  const vetos = (match?.vetos || []).filter((veto) => veto.type !== "ban" && veto.mapName);
  const maps: DisplayMap[] = vetos.map((veto) => {
    const active = cleanMap(veto.mapName) === currentMap;
    const pickedBy = veto.type === "decider"
      ? "DECIDER"
      : veto.teamId === leftRaw.id
        ? `${left.name} PICK`
        : veto.teamId === rightRaw.id
          ? `${right.name} PICK`
          : "PICK";
    return {
      name: veto.mapName,
      pickedBy,
      leftScore: active ? left.score : vetoScore(veto, leftRaw),
      rightScore: active ? right.score : vetoScore(veto, rightRaw),
      active,
    };
  });
  if (!maps.length) {
    maps.push({
      name: game.map.name,
      pickedBy: "CURRENT MAP",
      leftScore: left.score,
      rightScore: right.score,
      active: true,
    });
  }
  const bestOf = Number(match?.matchType?.slice(-1)) || 1;
  const winsNeeded = Math.floor(bestOf / 2) + 1;
  const roundsPlayed = Math.max(1, left.score + right.score);
  const leftPlayers = playerRows(game.players, leftRaw, roundsPlayed);
  const rightPlayers = playerRows(game.players, rightRaw, roundsPlayed);
  const activeVeto = vetos.find((veto) => cleanMap(veto.mapName) === currentMap);
  const mapLeftPlayers = vetoPlayerRows(activeVeto, leftRaw, leftPlayers);
  const mapRightPlayers = vetoPlayerRows(activeVeto, rightRaw, rightPlayers);
  const leftSeries = seriesPlayerRows(match, leftRaw, leftPlayers);
  const rightSeries = seriesPlayerRows(match, rightRaw, rightPlayers);
  return {
    left,
    right,
    winner,
    loser,
    leftPlayers: mapLeftPlayers,
    rightPlayers: mapRightPlayers,
    seriesLeftPlayers: leftSeries.players,
    seriesRightPlayers: rightSeries.players,
    seriesStatsComplete: leftSeries.complete && rightSeries.complete,
    maps,
    format: `BO${bestOf}`,
    seriesComplete: Math.max(left.series, right.series) >= winsNeeded,
  };
};

const demoAvatarByName: Record<string, string> = {
  cmdrJacob: publicAsset("demo-assets/cmdrJacob.jpg"),
  "False Emperor": publicAsset("demo-assets/false-emperor.jpg"),
  ZZJ: publicAsset("demo-assets/zzj.jpg"),
  franklinwqf: publicAsset("demo-assets/franklinwqf.jpg"),
  yonix: publicAsset("demo-assets/yonix.jpg"),
  dongsi666: publicAsset("demo-assets/dongsi666.jpg"),
  Nightmire: publicAsset("demo-assets/nightmire.jpg"),
  "AAA'钢板批发可师傅": publicAsset("demo-assets/aaa.jpg"),
  "上杉绘梨衣": publicAsset("demo-assets/uesugi.jpg"),
  "小米果": publicAsset("demo-assets/xiaomiguo.jpg"),
};

const demoPlayers = (names: string[], scores: Array<[number, number]>): DisplayPlayer[] =>
  scores.map(([kills, deaths], index) => ({
    name: names[index] || "PLAYER",
    avatar: demoAvatarByName[names[index]] || "",
    kills,
    deaths,
    assists: Math.max(0, Math.round(kills / 4)),
    rating: Number((0.72 + kills / Math.max(1, deaths) * 0.28).toFixed(2)),
    adr: Number((58 + kills * 1.15).toFixed(1)),
  }));

const demoModel: VictoryModel = {
  left: { id: "a", name: "G8 Esports", logo: publicAsset("demo-assets/g8.png"), score: 13, series: 2 },
  right: { id: "b", name: "U8", logo: publicAsset("demo-assets/u8.png"), score: 11, series: 1 },
  winner: { id: "a", name: "G8 Esports", logo: publicAsset("demo-assets/g8.png"), score: 13, series: 2 },
  loser: { id: "b", name: "U8", logo: publicAsset("demo-assets/u8.png"), score: 11, series: 1 },
  leftPlayers: demoPlayers(["cmdrJacob", "False Emperor", "ZZJ", "franklinwqf", "yonix"], [[21, 12], [18, 14], [16, 13], [14, 15], [11, 16]]),
  rightPlayers: demoPlayers(["dongsi666", "Nightmire", "AAA'钢板批发可师傅", "上杉绘梨衣", "小米果"], [[19, 16], [16, 17], [14, 18], [12, 18], [9, 20]]),
  seriesLeftPlayers: demoPlayers(["cmdrJacob", "False Emperor", "ZZJ", "franklinwqf", "yonix"], [[58, 42], [54, 45], [50, 47], [46, 50], [42, 53]]),
  seriesRightPlayers: demoPlayers(["dongsi666", "Nightmire", "AAA'钢板批发可师傅", "上杉绘梨衣", "小米果"], [[55, 44], [51, 48], [47, 50], [44, 53], [40, 55]]),
  seriesStatsComplete: true,
  maps: [
    { name: "Nuke", pickedBy: "G8 PICK", leftScore: 13, rightScore: 9, active: false },
    { name: "Mirage", pickedBy: "U8 PICK", leftScore: 10, rightScore: 13, active: false },
    { name: "Dust2", pickedBy: "DECIDER", leftScore: 13, rightScore: 11, active: true },
  ],
  format: "BO3",
  seriesComplete: true,
};

const demoMapModel: VictoryModel = {
  ...demoModel,
  left: { ...demoModel.left, score: 13, series: 1 },
  right: { ...demoModel.right, score: 9, series: 0 },
  winner: { ...demoModel.left, score: 13, series: 1 },
  loser: { ...demoModel.right, score: 9, series: 0 },
  maps: [
    { name: "Nuke", pickedBy: "G8 PICK", leftScore: 13, rightScore: 9, active: true },
    { name: "Mirage", pickedBy: "U8 PICK", leftScore: null, rightScore: null, active: false },
    { name: "Dust2", pickedBy: "DECIDER", leftScore: null, rightScore: null, active: false },
  ],
  seriesComplete: false,
};

const TeamLogo = ({ team }: { team: DisplayTeam }) => {
  const [failed, setFailed] = useState(false);
  const handleError = useCallback(() => setFailed(true), []);
  const initials = team.name.split(/\s+/).map((part) => part[0]).join("").slice(0, 3).toUpperCase();
  return <span className="victory-team-logo">
    {team.logo && !failed ? <TeamLogoImage src={team.logo} onError={handleError} /> : <b>{initials}</b>}
  </span>;
};

const PlayerRow = ({ player, side }: { player: DisplayPlayer; side: "left" | "right" }) => {
  const [failed, setFailed] = useState(false);
  const ratingTier = !player.rating ? "missing" : player.rating >= 1.05 ? "good" : player.rating < 0.95 ? "bad" : "neutral";
  return <div className={`victory-player-row ${side}`}>
    <span className="victory-player-avatar">
      <img src={player.avatar && !failed ? player.avatar : steamAvatarDefault} alt="" onError={() => setFailed(true)} />
    </span>
    <strong>{player.name}</strong>
    <span className="victory-player-metrics">
      <span className="victory-stat"><small>K</small><b>{player.kills}</b></span>
      <span className="victory-stat"><small>D</small><b>{player.deaths}</b></span>
      <span className="victory-stat"><small>A</small><b>{player.assists}</b></span>
      <span className="victory-stat"><small>ADR</small><b>{player.adr ? player.adr.toFixed(1) : "-"}</b></span>
      <span className={`victory-stat rating ${ratingTier}`}><small>RATING</small><b>{player.rating ? player.rating.toFixed(2) : "-"}</b></span>
    </span>
  </div>;
};

const VictoryShowcase = ({ game, match, demo = false, seriesSummaryOnly = false, manualMode }: Props) => {
  const [visible, setVisible] = useState(demo);
  const [closing, setClosing] = useState(false);
  const [showSeries, setShowSeries] = useState(seriesSummaryOnly);
  const lastMatchEndKey = useRef("");
  const automaticEndArmed = useRef(false);
  const delayedShowTimer = useRef<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const model = useMemo(
    () => demo ? (seriesSummaryOnly ? demoModel : demoMapModel) : liveModel(game, match),
    [demo, game, match, seriesSummaryOnly],
  );

  const showAfterDelay = useCallback((series: boolean) => {
    if (delayedShowTimer.current !== null) window.clearTimeout(delayedShowTimer.current);
    setVisible(false);
    setClosing(false);
    setShowSeries(series);
    delayedShowTimer.current = window.setTimeout(() => {
      delayedShowTimer.current = null;
      setVisible(true);
    }, SHOW_DELAY_MS);
  }, []);

  useEffect(() => () => {
    if (delayedShowTimer.current !== null) window.clearTimeout(delayedShowTimer.current);
  }, []);

  useEffect(() => {
    if (manualMode !== undefined || demo || !game) return;
    if (game.map.phase === "gameover") return;
    if (delayedShowTimer.current !== null) {
      window.clearTimeout(delayedShowTimer.current);
      delayedShowTimer.current = null;
    }
    automaticEndArmed.current = true;
    setVisible(false);
    setClosing(false);
  }, [demo, game?.map.phase, game?.map.name, match?.id, manualMode]);

  onGSI("matchEnd", result => {
    if (manualMode !== undefined || demo || !automaticEndArmed.current) return;
    const eventKey = [
      match?.id || "live",
      result.map.name,
      result.map.round,
      result.winner.side,
      result.winner.score,
      result.loser.score,
    ].join(":");
    if (eventKey === lastMatchEndKey.current) return;
    lastMatchEndKey.current = eventKey;
    automaticEndArmed.current = false;
    const bestOf = Math.max(1, Number(String(match?.matchType || '').replace(/\D/g, '')) || 1);
    const winsNeeded = Math.floor(bestOf / 2) + 1;
    const winnerSeriesScore = match
      ? Math.max(Number(match.left.wins) || 0, Number(match.right.wins) || 0)
      : Number(model?.winner.series) || 0;
    showAfterDelay(Boolean(model?.seriesComplete) || winnerSeriesScore >= winsNeeded);
  }, [demo, manualMode, match?.id, model?.seriesComplete, showAfterDelay]);

  useEffect(() => {
    if (manualMode === undefined) return;
    if (manualMode === null) {
      if (delayedShowTimer.current !== null) {
        window.clearTimeout(delayedShowTimer.current);
        delayedShowTimer.current = null;
      }
      setVisible(false);
      setClosing(false);
      return;
    }
    showAfterDelay(manualMode === "series");
  }, [manualMode, showAfterDelay]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (visible) return fadeInAudio(audio, { duration: 1500, target: 0.11 });
    return fadeOutAudio(audio, { duration: 1300 });
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    const closeTimer = window.setTimeout(() => {
      setClosing(true);
      if (audioRef.current) fadeOutAudio(audioRef.current, { duration: 1500 });
    }, 13500);
    const hideTimer = window.setTimeout(() => {
      setVisible(false);
    }, 15000);
    return () => {
      window.clearTimeout(closeTimer);
      window.clearTimeout(hideTimer);
    };
  }, [showSeries, visible]);

  const seriesWinner = model && model.left.series !== model.right.series
    ? (model.left.series > model.right.series ? model.left : model.right)
    : null;

  return <>
    <audio ref={audioRef} src={publicAsset("audio/victory-theme.mp3")} preload="auto" />
    {visible && model ? <section className={`victory-showcase ${closing ? "closing" : ""}`}>
      <div className="victory-grid" />
      <header className="victory-header">
        <div className="victory-side-team left"><TeamLogo team={model.left} /><span>{model.left.name}</span></div>
        <div className="victory-result">
          <small>{showSeries ? "SERIES COMPLETE" : "MAP COMPLETE"}</small>
          <strong>{showSeries ? (seriesWinner ? `${seriesWinner.name} \u8d62\u4e0b ${model.format}` : "系列赛结果待确认") : `${model.winner.name} \u80dc\u5229`}</strong>
          <div><b>{showSeries ? model.left.series : model.left.score}</b><i>:</i><b>{showSeries ? model.right.series : model.right.score}</b></div>
          <span>SERIES {model.left.series} - {model.right.series}</span>
        </div>
        <div className="victory-side-team right"><span>{model.right.name}</span><TeamLogo team={model.right} /></div>
      </header>

      <div className="victory-map-strip">
        {model.maps.slice(0, 5).map((map) => <article className={map.active ? "active" : ""} key={map.name}>
          <img src={publicAsset(`maps/${cleanMap(map.name)}.png`)} alt="" />
          <div><strong>{mapLabel(map.name)}</strong><span>{map.pickedBy}</span></div>
          <b>{map.leftScore == null || map.rightScore == null ? "- : -" : `${map.leftScore} : ${map.rightScore}`}</b>
        </article>)}
      </div>

      {showSeries ? <main className="victory-series-summary">
        <div className="victory-series-record">
          <small>{model.format} 最终战绩</small>
          <div><span>{model.left.name}</span><strong>{model.left.series} : {model.right.series}</strong><span>{model.right.name}</span></div>
        </div>
        <div className="victory-series-kd-title">
          {model.seriesStatsComplete ? `${model.maps.filter((map) => map.leftScore != null && map.rightScore != null).length} 张地图累计数据` : "已记录地图累计数据"}
        </div>
        <div className="victory-players victory-series-players">
          <div>{model.seriesLeftPlayers.map((player) => <PlayerRow key={player.name} player={player} side="left" />)}</div>
          <div className="victory-kd-label">STATS</div>
          <div>{model.seriesRightPlayers.map((player) => <PlayerRow key={player.name} player={player} side="right" />)}</div>
        </div>
      </main> : <main className="victory-players">
        <div>{model.leftPlayers.map((player) => <PlayerRow key={player.name} player={player} side="left" />)}</div>
        <div className="victory-kd-label">STATS</div>
        <div>{model.rightPlayers.map((player) => <PlayerRow key={player.name} player={player} side="right" />)}</div>
      </main>}

      <footer><span>80GOTV.CN</span><i /><span>POST MATCH REPORT</span></footer>
    </section> : null}
  </>;
};

export default VictoryShowcase;
