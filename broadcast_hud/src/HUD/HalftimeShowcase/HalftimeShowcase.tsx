import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSGO } from "csgogsi";
import type { Match } from "../../API/types";
import { fadeInAudio, fadeOutAudio } from "../audioFade";
import TeamLogoImage from "../TeamLogoImage";
import steamAvatarDefault from "../../assets/images/steam_avatar_default.jpg";
import "./halftime-showcase.scss";

type Props = {
  game?: CSGO | null;
  match?: Match | null;
  demo?: boolean;
  manualActive?: boolean;
};

type Scene = "score" | "stats" | "countdown";
type Side = "left" | "right";
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
  assists: number;
  deaths: number;
  adr: number;
};

type HalftimeModel = {
  left: DisplayTeam;
  right: DisplayTeam;
  leftPlayers: DisplayPlayer[];
  rightPlayers: DisplayPlayer[];
  mapName: string;
  mapNumber: number;
};

const SCORE_DURATION_MS = 4000;
const STATS_DURATION_MS = 5000;
const DEMO_COUNTDOWN_SECONDS = 10;
const DEMO_TOTAL_MS = SCORE_DURATION_MS + STATS_DURATION_MS + DEMO_COUNTDOWN_SECONDS * 1000;

const publicAsset = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, "")}`;
const cleanMap = (name: string) =>
  String(name || "").split("/").pop()?.replace(/^de_/i, "").toLowerCase() || "cache";
const mapLabel = (name: string) => cleanMap(name).toUpperCase();

const teamSeriesScore = (match: Match | null | undefined, teamId: string | null) => {
  if (!match || !teamId) return 0;
  if (match.left.id === teamId) return Number(match.left.wins) || 0;
  if (match.right.id === teamId) return Number(match.right.wins) || 0;
  return 0;
};

const displayPlayers = (game: CSGO, side: string): DisplayPlayer[] =>
  game.players
    .filter((player) => player.team.side === side)
    .sort((a, b) => (a.observer_slot || 99) - (b.observer_slot || 99))
    .slice(0, 5)
    .map((player) => {
      const kills = Number(player.stats.kills) || 0;
      const assists = Number(player.stats.assists) || 0;
      const deaths = Number(player.stats.deaths) || 0;
      const adr = Math.round(Number(player.state.adr) || 0);
      return {
        name: player.name || "PLAYER",
        avatar: player.avatar || "",
        kills,
        assists,
        deaths,
        adr,
      };
    });

const liveModel = (game?: CSGO | null, match?: Match | null): HalftimeModel | null => {
  if (!game) return null;
  const leftRaw = game.map.team_ct.orientation === "left" ? game.map.team_ct : game.map.team_t;
  const rightRaw = leftRaw.side === game.map.team_ct.side ? game.map.team_t : game.map.team_ct;
  const leftSeries = teamSeriesScore(match, leftRaw.id);
  const rightSeries = teamSeriesScore(match, rightRaw.id);
  return {
    left: {
      id: String(leftRaw.id || leftRaw.side),
      name: leftRaw.name || "TEAM A",
      logo: leftRaw.logo || "",
      score: Number(leftRaw.score) || 0,
      series: leftSeries,
    },
    right: {
      id: String(rightRaw.id || rightRaw.side),
      name: rightRaw.name || "TEAM B",
      logo: rightRaw.logo || "",
      score: Number(rightRaw.score) || 0,
      series: rightSeries,
    },
    leftPlayers: displayPlayers(game, leftRaw.side),
    rightPlayers: displayPlayers(game, rightRaw.side),
    mapName: game.map.name,
    mapNumber: Math.max(1, leftSeries + rightSeries + 1),
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

const demoPlayers = (names: string[], stats: Array<[number, number, number, number]>): DisplayPlayer[] =>
  stats.map(([kills, assists, deaths, adr], index) => ({
    name: names[index] || "PLAYER",
    avatar: demoAvatarByName[names[index]] || "",
    kills,
    assists,
    deaths,
    adr,
  }));

const demoModel: HalftimeModel = {
  left: { id: "a", name: "G8 Esports", logo: publicAsset("demo-assets/g8.png"), score: 5, series: 0 },
  right: { id: "b", name: "U8", logo: publicAsset("demo-assets/u8.png"), score: 7, series: 0 },
  leftPlayers: demoPlayers(["cmdrJacob", "False Emperor", "ZZJ", "franklinwqf", "yonix"], [[11, 3, 7, 92], [9, 2, 8, 84], [8, 4, 8, 79], [6, 1, 9, 67], [5, 2, 10, 61]]),
  rightPlayers: demoPlayers(["dongsi666", "Nightmire", "AAA'钢板批发可师傅", "上杉绘梨衣", "小米果"], [[13, 2, 6, 104], [10, 4, 7, 91], [8, 3, 8, 82], [7, 2, 8, 74], [6, 5, 9, 69]]),
  mapName: "Mirage",
  mapNumber: 1,
};

const TeamLogo = ({ team }: { team: DisplayTeam }) => {
  const [failed, setFailed] = useState(false);
  const handleError = useCallback(() => setFailed(true), []);
  const initials = team.name.split(/\s+/).map((part) => part[0]).join("").slice(0, 3).toUpperCase();
  return <span className="halftime-team-logo">
    {team.logo && !failed ? <TeamLogoImage src={team.logo} onError={handleError} /> : <b>{initials}</b>}
  </span>;
};

const PlayerRow = ({ player, side }: { player: DisplayPlayer; side: Side }) => {
  const [failed, setFailed] = useState(false);
  return <div className={`halftime-player-row ${side}`}>
    <span className="halftime-player-avatar">
      <img src={player.avatar && !failed ? player.avatar : steamAvatarDefault} alt="" onError={() => setFailed(true)} />
    </span>
    <strong>{player.name}</strong>
    <span>{player.kills}</span>
    <span>{player.deaths}</span>
    <span>{player.assists}</span>
    <span>{player.adr}</span>
  </div>;
};

const HalftimeShowcase = ({ game, match, demo = false, manualActive }: Props) => {
  const requestedActive = manualActive !== undefined ? manualActive : game?.map.phase === "intermission";
  const [delayedActive, setDelayedActive] = useState(demo);
  const active = demo || delayedActive;
  const [scene, setScene] = useState<Scene>("score");
  const [demoSeconds, setDemoSeconds] = useState(DEMO_COUNTDOWN_SECONDS);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const model = useMemo(() => demo ? demoModel : liveModel(game, match), [demo, game, match]);

  useEffect(() => {
    if (demo) {
      setDelayedActive(true);
      return;
    }
    if (!requestedActive) {
      setDelayedActive(false);
      return;
    }
    const showTimer = window.setTimeout(() => setDelayedActive(true), SHOW_DELAY_MS);
    return () => window.clearTimeout(showTimer);
  }, [demo, requestedActive]);

  useEffect(() => {
    if (!active) {
      setScene("score");
      return;
    }
    setScene("score");
    setDemoSeconds(DEMO_COUNTDOWN_SECONDS);
    const statsTimer = window.setTimeout(() => setScene("stats"), SCORE_DURATION_MS);
    const countdownTimer = window.setTimeout(() => setScene("countdown"), SCORE_DURATION_MS + STATS_DURATION_MS);
    return () => {
      window.clearTimeout(statsTimer);
      window.clearTimeout(countdownTimer);
    };
  }, [active]);

  useEffect(() => {
    if (!demo || scene !== "countdown") return;
    const timer = window.setInterval(() => {
      setDemoSeconds((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [demo, scene]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!active) return fadeOutAudio(audio, { duration: 1300 });
    const cleanupFade = fadeInAudio(audio, { duration: 1600, target: 0.095 });
    if (!demo) return cleanupFade;
    const fadeTimer = window.setTimeout(() => fadeOutAudio(audio, { duration: 1500 }), DEMO_TOTAL_MS - 1500);
    return () => {
      cleanupFade?.();
      window.clearTimeout(fadeTimer);
    };
  }, [active, demo]);

  if (!active || !model) return <audio ref={audioRef} src={publicAsset("audio/halftime-theme.flac")} preload="auto" />;

  const liveSeconds = Math.max(0, Math.ceil(Number(game?.phase_countdowns.phase_ends_in) || 0));
  const seconds = demo ? demoSeconds : liveSeconds;
  const clock = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

  return <>
    <audio ref={audioRef} src={publicAsset("audio/halftime-theme.flac")} preload="auto" />
    <section className={`halftime-showcase ${scene}`} aria-label="Halftime showcase">
      {scene === "score" ? <div className="halftime-score-scene">
        <img className="halftime-map-background" src={publicAsset(`maps/${cleanMap(model.mapName)}.png`)} alt="" />
        <div className="halftime-score-grid" />
        <header><strong>MAP {model.mapNumber}</strong><span>{mapLabel(model.mapName)}</span></header>
        <main>
          <div className="halftime-score-side left"><b>{model.left.score}</b><strong>{model.left.name}</strong></div>
          <div className="halftime-matchup">
            <div><TeamLogo team={model.left} /><span>{model.left.series}</span></div>
            <strong>VS</strong>
            <div><TeamLogo team={model.right} /><span>{model.right.series}</span></div>
          </div>
          <div className="halftime-score-side right"><b>{model.right.score}</b><strong>{model.right.name}</strong></div>
        </main>
        <footer><span>80GOTV.CN</span><i /><span>HALFTIME</span></footer>
      </div> : null}

      {scene === "stats" ? <div className="halftime-stats-scene">
        <header>
          <div><TeamLogo team={model.left} /><strong>{model.left.name}</strong></div>
          <section><small>HALFTIME</small><b>{model.left.score}<i>:</i>{model.right.score}</b><span>MAP {model.mapNumber} · {mapLabel(model.mapName)}</span></section>
          <div className="right"><strong>{model.right.name}</strong><TeamLogo team={model.right} /></div>
        </header>
        <main>
          <div className="halftime-stat-team">
            <div className="halftime-stat-head"><span>PLAYER</span><span>K</span><span>D</span><span>A</span><span>ADR</span></div>
            {model.leftPlayers.map((player) => <PlayerRow key={player.name} player={player} side="left" />)}
          </div>
          <div className="halftime-stat-team">
            <div className="halftime-stat-head"><span>PLAYER</span><span>K</span><span>D</span><span>A</span><span>ADR</span></div>
            {model.rightPlayers.map((player) => <PlayerRow key={player.name} player={player} side="right" />)}
          </div>
        </main>
        <footer><span>80GOTV.CN</span><i /><span>FIRST HALF REPORT</span></footer>
      </div> : null}

      {scene === "countdown" ? <div className="halftime-countdown-scene">
        <div className="halftime-countdown-grid" />
        <small>HALFTIME</small>
        <strong>{clock}</strong>
        <span>SECOND HALF STARTS IN</span>
        <div><b>{model.left.name}</b><i>{model.left.score} : {model.right.score}</i><b>{model.right.name}</b></div>
        <footer><span>80GOTV.CN</span><i /><span>OFFICIAL BROADCAST</span></footer>
      </div> : null}
    </section>
  </>;
};

export default HalftimeShowcase;
