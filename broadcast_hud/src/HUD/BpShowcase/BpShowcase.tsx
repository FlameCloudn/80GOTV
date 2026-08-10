import { useEffect, useMemo, useRef, useState } from "react";
import { useAction, useConfig } from "../../API/contexts/actions";
import ctSideIcon from "../../assets/images/logo_CT_default.png";
import tSideIcon from "../../assets/images/logo_T_default.png";
import { fadeInAudio, fadeOutAudio } from "../audioFade";
import TeamLogoImage from "../TeamLogoImage";
import "./bp-showcase.scss";

type TeamKey = "t1" | "t2";
type BpAction = "ban" | "pick" | "decider";

type WebsiteTeam = {
  name: string;
  short_name: string;
  logo: string;
};

type BpLogEntry = {
  team?: TeamKey;
  action?: "ban" | "pick";
  map?: string;
};

type BpPick = {
  map?: string;
  picked_by?: TeamKey | "remaining";
  side?: "CT" | "T" | null;
  side_team?: TeamKey | null;
};

type BpState = {
  status?: "rolling" | "bp" | "side_select" | "completed";
  bo?: string;
  action_log?: BpLogEntry[];
  picks?: BpPick[];
  steps?: Array<{ action?: "ban" | "pick"; team?: "first" | "second" }>;
  current_step?: number;
  first_picker?: TeamKey | null;
  first_choice?: "first" | "second" | null;
};

type DeciderResult = {
  knife_winner?: TeamKey | "";
  start_side?: "CT" | "T" | "";
  side_team?: TeamKey | "";
};

type WebsiteMatch = {
  id: number;
  bo: string;
  team1: WebsiteTeam;
  team2: WebsiteTeam;
  bp?: BpState | null;
  decider?: DeciderResult;
};

type ShowcaseEntry = {
  team: TeamKey | "remaining";
  action: BpAction;
  map: string;
  side?: "CT" | "T" | null;
  sideTeam?: TeamKey | null;
};

type BroadcastResponse = {
  ok: boolean;
  match?: WebsiteMatch;
};

const demoEntries: ShowcaseEntry[] = [
  { team: "t1", action: "ban", map: "Anubis" },
  { team: "t2", action: "ban", map: "Cache" },
  { team: "t1", action: "pick", map: "Nuke", side: "CT" },
  { team: "t2", action: "pick", map: "Mirage", side: "T" },
  { team: "t1", action: "ban", map: "Ancient" },
  { team: "t2", action: "ban", map: "Inferno" },
  { team: "remaining", action: "decider", map: "Dust2", side: "CT", sideTeam: "t1" },
];

const demoMatch: WebsiteMatch = {
  id: 80,
  bo: "BO3",
  team1: { name: "G8", short_name: "G8", logo: "" },
  team2: { name: "U8", short_name: "U8", logo: "" },
  bp: { status: "completed", bo: "BO3" },
  decider: { knife_winner: "t1", start_side: "CT" },
};

const cleanBase = (value: string) => value.trim().replace(/\/+$/, "");
const publicAsset = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, "")}`;

const mapKey = (name: string) =>
  String(name || "")
    .trim()
    .toLowerCase()
    .replace(/^de_/, "")
    .replace(/[^a-z0-9]/g, "");

const mapLabel = (name: string) => {
  const clean = String(name || "").trim().replace(/^de_/i, "");
  return clean ? clean.toUpperCase() : "TBD";
};

const assetUrl = (base: string, value: string) => {
  if (!value) return "";
  try {
    return new URL(value, `${base}/`).toString();
  } catch {
    return value;
  }
};

const oppositeTeam = (team: TeamKey): TeamKey => (team === "t1" ? "t2" : "t1");

const currentActingTeam = (state?: BpState | null): TeamKey | null => {
  if (!state || state.status !== "bp" || state.first_choice == null || !state.first_picker) {
    return null;
  }
  const step = state.steps?.[state.current_step || 0];
  if (!step) return null;
  const firstTeam = state.first_choice === "first" ? state.first_picker : oppositeTeam(state.first_picker);
  return step.team === "second" ? oppositeTeam(firstTeam) : firstTeam;
};

const buildEntries = (state?: BpState | null, decider?: DeciderResult): ShowcaseEntry[] => {
  if (!state) return [];
  const entries: ShowcaseEntry[] = (state.action_log || [])
    .filter((entry) => entry.map && (entry.action === "ban" || entry.action === "pick"))
    .map((entry) => ({
      team: entry.team === "t2" ? "t2" : "t1",
      action: entry.action === "pick" ? "pick" : "ban",
      map: String(entry.map),
      side: (state.picks || []).find((pick) => mapKey(String(pick.map)) === mapKey(String(entry.map)))?.side,
    }));

  const remaining = (state.picks || []).find((pick) => pick.picked_by === "remaining" && pick.map);
  if (remaining && !entries.some((entry) => mapKey(entry.map) === mapKey(String(remaining.map)))) {
    const deciderSide = decider?.start_side === "CT" || decider?.start_side === "T"
      ? decider.start_side
      : remaining.side;
    const sideTeam = remaining.side_team === "t1" || remaining.side_team === "t2"
      ? remaining.side_team
      : decider?.side_team === "t1" || decider?.side_team === "t2"
        ? decider.side_team
        : decider?.knife_winner === "t1" || decider?.knife_winner === "t2"
          ? decider.knife_winner
          : null;
    entries.push({
      team: "remaining",
      action: "decider",
      map: String(remaining.map),
      side: deciderSide,
      sideTeam,
    });
  }
  return entries;
};

const TeamMark = ({ team, apiBase, monochrome = false }: { team: WebsiteTeam; apiBase: string; monochrome?: boolean }) => {
  const [logoFailed, setLogoFailed] = useState(false);
  const logo = assetUrl(apiBase, team.logo);
  const initials = (team.short_name || team.name || "T").slice(0, 3).toUpperCase();
  return (
    <span className="bp-team-mark">
      {logo && !logoFailed ? (
        <TeamLogoImage src={logo} monochrome={monochrome} onError={() => setLogoFailed(true)} />
      ) : (
        <span>{initials}</span>
      )}
    </span>
  );
};

const actionText: Record<BpAction, string> = {
  ban: "BAN",
  pick: "PICK",
  decider: "DECIDER",
};

const CARD_RISE_DURATION_MS = 620;
const CARD_VISUAL_LEAD_MS = 150;
const CARD_LAND_TIMES_MS = [1544, 2879, 4214, 5538, 6873, 8208, 9543];
const SHOWCASE_VISUAL_DELAY_MS = 300;

const BpShowcase = ({ demo = false }: { demo?: boolean }) => {
  const settings = useConfig("broadcast_settings");
  const query = new URLSearchParams(window.location.search);
  const apiBase = cleanBase(settings?.api_base || query.get("apiBase") || "https://80gotv.cn");
  const matchId = String(settings?.match_id || query.get("matchId") || "").trim();
  const forcedVisible = demo || query.get("bpShow") === "1";
  const [visible, setVisible] = useState(forcedVisible);
  const [visualVisible, setVisualVisible] = useState(false);
  const [match, setMatch] = useState<WebsiteMatch | null>(demo ? demoMatch : null);
  const [animationComplete, setAnimationComplete] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const showcaseVisible = visible && (demo || match?.bp?.status === "completed");

  useAction("bpShowcaseState", (state) => setVisible(state === "show"), []);

  useEffect(() => {
    if (!showcaseVisible) {
      setVisualVisible(false);
      return;
    }
    setVisualVisible(false);
    const timer = window.setTimeout(() => setVisualVisible(true), SHOWCASE_VISUAL_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [showcaseVisible]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (showcaseVisible) {
      return fadeInAudio(audio, { duration: 1500, target: 0.18 });
    }
    return fadeOutAudio(audio, { duration: 1300 });
  }, [showcaseVisible]);

  useEffect(() => {
    if (demo || !apiBase) return;
    let cancelled = false;
    const load = async () => {
      const endpoint = matchId
        ? `${apiBase}/api/broadcast/matches/${encodeURIComponent(matchId)}`
        : `${apiBase}/api/broadcast/current`;
      try {
        const response = await fetch(endpoint, { cache: "no-store" });
        const payload = (await response.json()) as BroadcastResponse;
        if (!cancelled) setMatch(response.ok && payload.ok && payload.match ? payload.match : null);
      } catch {
        if (!cancelled) setMatch(null);
      }
    };
    load();
    const interval = window.setInterval(load, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [apiBase, demo, matchId]);

  const entries = useMemo(
    () => (demo ? demoEntries : buildEntries(match?.bp, match?.decider)),
    [demo, match?.bp, match?.decider]
  );

  useEffect(() => {
    if (!visualVisible || !match || entries.length === 0) return;
    const replaying = demo || match.bp?.status === "completed";
    if (!replaying) {
      setAnimationComplete(true);
      return;
    }
    setAnimationComplete(false);
    const completeTimer = window.setTimeout(() => setAnimationComplete(true), 10000);
    return () => window.clearTimeout(completeTimer);
  }, [demo, entries.length, match?.bp?.status, match?.id, visualVisible]);

  useEffect(() => {
    if (!visualVisible || !match || !animationComplete) return;
    const finished = demo || match.bp?.status === "completed";
    if (!finished) return;
    const fadeTimer = window.setTimeout(() => {
      if (audioRef.current) fadeOutAudio(audioRef.current, { duration: 1300 });
    }, 3500);
    const hideTimer = window.setTimeout(() => setVisible(false), 5000);
    return () => {
      window.clearTimeout(fadeTimer);
      window.clearTimeout(hideTimer);
    };
  }, [animationComplete, demo, match?.bp?.status, match?.id, visualVisible]);

  const teams = match ? { t1: match.team1, t2: match.team2 } : null;
  const actingTeam = currentActingTeam(match?.bp);
  const currentAction = match?.bp?.steps?.[match.bp.current_step || 0]?.action;
  const status = demo
    ? !animationComplete
      ? "BP LOCKED"
      : "BP COMPLETE"
      : match?.bp?.status === "rolling"
      ? "ROLL FOR ORDER"
        : match?.bp?.status === "side_select"
        ? "SELECTING START SIDE"
        : match?.bp?.status === "completed"
          ? animationComplete ? "BP COMPLETE" : "BP LOCKED"
          : actingTeam && currentAction
            ? `${teams?.[actingTeam].name || "TEAM"}  ${currentAction.toUpperCase()}`
            : "WAITING FOR BP";

  return <>
      <audio ref={audioRef} src={publicAsset("audio/bp-theme.flac")} preload="auto" />
      {visualVisible && match && teams ? <section className="bp-showcase" aria-label="Ban Pick showcase">
      <div className="bp-showcase-grid" />
      <header className="bp-showcase-header">
        <div className="bp-showcase-team left">
          <TeamMark team={match.team1} apiBase={apiBase} />
          <strong>{match.team1.name}</strong>
        </div>
        <div className="bp-showcase-versus">
          <b>VS</b>
          <span>{String(match.bp?.bo || match.bo || "BO3").toUpperCase()}</span>
        </div>
        <div className="bp-showcase-team right">
          <strong>{match.team2.name}</strong>
          <TeamMark team={match.team2} apiBase={apiBase} />
        </div>
      </header>

      <div className="bp-showcase-status"><span />{status}<span /></div>

      <div className="bp-card-row">
        {entries.map((entry, index) => {
          const team = entry.team === "remaining" ? null : teams[entry.team];
          const sideTeamKey = entry.sideTeam || (
            entry.action === "pick" && entry.side && entry.team !== "remaining"
              ? oppositeTeam(entry.team)
              : null
          );
          const sideTeam = sideTeamKey ? teams[sideTeamKey] : null;
          return (
            <article
              className={`bp-map-card ${entry.action} ${entry.team}${sideTeam ? " has-side" : ""}`}
              style={{
                animationDelay: demo || match.bp?.status === "completed"
                  ? `${Math.max(
                      0,
                      CARD_LAND_TIMES_MS[Math.min(index, 6)] - CARD_RISE_DURATION_MS - CARD_VISUAL_LEAD_MS
                    )}ms`
                  : "0ms",
              }}
              key={`${index}-${entry.action}-${mapKey(entry.map)}`}
            >
              <div className="bp-map-scene">
                <img src={publicAsset(`maps/${mapKey(entry.map)}.png`)} alt="" />
                <div className="bp-map-tone" />
                {entry.action === "ban" ? <span className="bp-ban-cross"><i /><i /></span> : null}
                {team ? <span className="bp-map-center-logo"><TeamMark team={team} apiBase={apiBase} /></span> : null}
                <span className="bp-map-name">{mapLabel(entry.map)}</span>
              </div>
              {sideTeam && entry.side ? (
                <div className={`bp-side-choice ${entry.side.toLowerCase()}`}>
                  <TeamMark team={sideTeam} apiBase={apiBase} />
                  <span>{sideTeam.short_name || sideTeam.name}</span>
                  <small>STARTS</small>
                  <img src={entry.side === "CT" ? ctSideIcon : tSideIcon} alt="" />
                  <strong>{entry.side}</strong>
                </div>
              ) : null}
              <div className="bp-map-action">
                {team ? <TeamMark team={team} apiBase={apiBase} /> : <i className="bp-decider-mark">D</i>}
                <strong>{actionText[entry.action]}</strong>
              </div>
            </article>
          );
        })}
      </div>

      <footer className="bp-showcase-footer">
        <span>80GOTV.CN</span>
        <i />
        <span>MAP VETO</span>
      </footer>
    </section> : null}
  </>;
};

export default BpShowcase;
