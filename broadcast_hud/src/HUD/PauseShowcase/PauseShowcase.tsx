import { useEffect, useRef, useState } from "react";
import type { CSGO, Map } from "csgogsi";
import { fadeInAudio, fadeOutAudio } from "../audioFade";
import TeamLogoImage from "../TeamLogoImage";
import { getPauseKind, PauseKind } from "../Layout/sceneState";
import "./pause-showcase.scss";

type Props = {
  phase?: CSGO["phase_countdowns"] | null;
  map?: Map | null;
  sessionKey?: string;
  demoKind?: Exclude<PauseKind, null>;
  detectedKind?: PauseKind;
  manualMode?: "current" | "technical" | null;
};

type PauseTeam = {
  name: string;
  logo: string | null;
  timeouts_remaining?: number;
};

const publicAsset = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, "")}`;
const formatElapsed = (seconds: number) => {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = safeSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
};

const demoTeam: PauseTeam = {
  name: "TEAM A",
  logo: null,
  timeouts_remaining: 2,
};

const PauseLogo = ({ team }: { team: PauseTeam }) => {
  const [failed, setFailed] = useState(false);
  const initials = (team.name || "TEAM").split(/\s+/).map((part) => part[0]).join("").slice(0, 3).toUpperCase();
  return (
    <span className="pause-team-logo">
      {team.logo && !failed ? <TeamLogoImage src={team.logo} onError={() => setFailed(true)} /> : <b>{initials}</b>}
    </span>
  );
};

const TECHNICAL_PAUSE_STORAGE_KEY = "80gotv:technical-pause";
const TECHNICAL_PAUSE_GRACE_MS = 8000;
const TECHNICAL_PAUSE_MAX_AGE_MS = 6 * 60 * 60 * 1000;

const PauseShowcase = ({ phase, map, sessionKey = "preview", demoKind, detectedKind, manualMode }: Props) => {
  const currentKind = detectedKind === undefined ? getPauseKind(phase?.phase) : detectedKind;
  const kind = demoKind || (manualMode === undefined
    ? currentKind
    : manualMode === "technical"
      ? "technical"
      : manualMode === "current"
        ? currentKind
        : null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const technicalStartedAt = useRef<number | null>(null);
  const technicalClearTimer = useRef<number | null>(null);
  const [technicalElapsed, setTechnicalElapsed] = useState(0);
  const tacticalSide = kind === "tactical_t" ? "t" : kind === "tactical_ct" ? "ct" : null;
  const team: PauseTeam | null = demoKind && tacticalSide
    ? demoTeam
    : tacticalSide === "t"
      ? map?.team_t || null
      : tacticalSide === "ct"
        ? map?.team_ct || null
        : null;
  const serverSeconds = Number(phase?.phase_ends_in);
  const seconds = demoKind ? 24 : Math.max(0, Math.ceil(serverSeconds || 0));

  useEffect(() => {
    if (kind !== "technical") {
      if (technicalClearTimer.current !== null) window.clearTimeout(technicalClearTimer.current);
      technicalClearTimer.current = window.setTimeout(() => {
        technicalStartedAt.current = null;
        setTechnicalElapsed(0);
        if (!demoKind) window.localStorage.removeItem(TECHNICAL_PAUSE_STORAGE_KEY);
        technicalClearTimer.current = null;
      }, TECHNICAL_PAUSE_GRACE_MS);
      return;
    }

    if (technicalClearTimer.current !== null) {
      window.clearTimeout(technicalClearTimer.current);
      technicalClearTimer.current = null;
    }
    if (technicalStartedAt.current === null) {
      const now = Date.now();
      let restored = 0;
      if (!demoKind) {
        try {
          const saved = JSON.parse(window.localStorage.getItem(TECHNICAL_PAUSE_STORAGE_KEY) || "null");
          if (saved?.sessionKey === sessionKey && now - Number(saved.startedAt) <= TECHNICAL_PAUSE_MAX_AGE_MS) {
            restored = Number(saved.startedAt);
          }
        } catch {
          window.localStorage.removeItem(TECHNICAL_PAUSE_STORAGE_KEY);
        }
      }
      technicalStartedAt.current = restored || now;
      if (!demoKind) {
        window.localStorage.setItem(TECHNICAL_PAUSE_STORAGE_KEY, JSON.stringify({ sessionKey, startedAt: technicalStartedAt.current }));
      }
    }
    const updateElapsed = () => {
      const startedAt = technicalStartedAt.current;
      if (startedAt !== null) setTechnicalElapsed((Date.now() - startedAt) / 1000);
    };
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [demoKind, kind, sessionKey]);

  useEffect(() => () => {
    if (technicalClearTimer.current !== null) window.clearTimeout(technicalClearTimer.current);
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (kind) {
      return fadeInAudio(audio, { duration: 1500, target: 0.31 });
    }
    return fadeOutAudio(audio, { duration: 1300 });
  }, [kind]);

  const tactical = kind !== "technical";
  return <>
      <audio ref={audioRef} src={publicAsset("audio/pause-theme.ogg")} preload="auto" />
      {kind ? <section className={`pause-showcase ${tactical ? `tactical ${tacticalSide}` : "technical"}`}>
      <div className="pause-backdrop" />
      <div className="pause-panel">
        <div className="pause-kicker">80GOTV OFFICIAL BROADCAST</div>
        {tactical && team ? (
          <>
            <PauseLogo team={team} />
            <h2>战术暂停</h2>
            <strong className="pause-team-name">{team.name}</strong>
            <div className="pause-time"><span>{seconds}</span><small>SEC</small></div>
            <p>剩余暂停次数 {Math.max(0, Number(team.timeouts_remaining ?? 0))}</p>
          </>
        ) : (
          <>
            <div className="pause-tech-symbol"><i /><i /><i /></div>
            <h2>技术暂停</h2>
            <strong className="pause-team-name">TECHNICAL PAUSE</strong>
            <div className="pause-initiator">
              <span>已暂停 {formatElapsed(technicalElapsed)}</span>
            </div>
            <p>比赛暂时中断，正在处理技术问题</p>
          </>
        )}
      </div>
      <footer><span>80GOTV.CN</span><i /><span>{tactical ? "TACTICAL TIMEOUT" : "TECHNICAL PAUSE"}</span></footer>
    </section> : null}
  </>;
};

export default PauseShowcase;
