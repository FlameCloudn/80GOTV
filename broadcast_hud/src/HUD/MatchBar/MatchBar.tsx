import * as I from "csgogsi";
import "./matchbar.scss";
import TeamScore from "./TeamScore";
import Bomb from "./../Timers/BombTimer";
import { useBombTimer } from "./../Timers/Countdown";
import { Match } from './../../API/types';
import { useEffect, useRef, useState } from "react";
import { onGSI } from "../../API/contexts/actions";
import WinAnnouncement from "./WinIndicator";


function stringToClock(time: string | number) {
  const parsed = typeof time === "string" ? parseFloat(time) : time;
  const countdown = Number.isFinite(parsed) ? Math.max(0, Math.ceil(parsed)) : 0;
  const minutes = Math.floor(countdown / 60);
  const seconds = countdown - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

interface IProps {
  match: Match | null;
  map: I.Map;
  phase: I.CSGO["phase_countdowns"],
  bomb: I.Bomb | null,
}

export interface Timer {
  time: number;
  active: boolean;
  side: "left"|"right";
  type: "defusing" | "planting";
  player: I.Player | null;
}
const getRoundLabel = (mapRound: number) => {
  const round = mapRound + 1;
  if (round <= 24) {
    return `Round ${round}/24`;
  }
  const additionalRounds = round - 24;
  const OT = Math.ceil(additionalRounds/6);
  return `OT ${OT} (${additionalRounds - (OT - 1)*6}/6)`;
}

const ROUND_WIN_DURATION = 4600;

const seriesSlotCount = (match: Match | null) => {
  const bo = Number(String(match?.matchType || "").replace(/\D/g, ""));
  if (bo === 3) return 2;
  if (bo === 5) return 3;
  return 0;
};

// Only the website-confirmed series score may fill these markers. Live
// observer fields can still belong to an earlier map.
const websiteSeriesWins = (match: Match | null, team: I.Team) => {
  if (!match || !team.id) return 0;
  if (match.left.id === team.id) return Math.max(0, Number(match.left.wins) || 0);
  if (match.right.id === team.id) return Math.max(0, Number(match.right.wins) || 0);
  return 0;
};

const getRoundOutcome = (result: I.Score): I.RoundOutcome => {
  const completedRounds = result.map.rounds || [];
  const latestRound = completedRounds[completedRounds.length - 1];
  if (latestRound?.outcome) return latestRound.outcome;
  return result.winner.side === "CT" ? "ct_win_elimination" : "t_win_elimination";
};

const Matchbar = (props: IProps) => {
    const { bomb, match, map, phase } = props;
    const phaseName = String(phase.phase || "").toLowerCase();
    const isWarmup = phaseName === "warmup";
    const rawPhaseSeconds = Number(phase.phase_ends_in);
    const time = isWarmup || rawPhaseSeconds > 3600
      ? "WARMUP"
      : stringToClock(phase.phase_ends_in);
    const left = map.team_ct.orientation === "left" ? map.team_ct : map.team_t;
    const right = map.team_ct.orientation === "left" ? map.team_t : map.team_ct;
    const bo = (match && Number(String(match.matchType).replace(/\D/g, ""))) || 0;
    const seriesSlots = seriesSlotCount(match);

    const bombData = useBombTimer();
    const isPlanted = bomb?.state === "defusing" || bomb?.state === "planted"
      || bombData.state === "defusing" || bombData.state === "planted";
    const plantTimer: Timer | null = bombData.state === "planting" ? { time:bombData.plantTime, active: true, side: bombData.player?.team.orientation || "right", player: bombData.player, type: "planting"} : null;
    const defuseTimer: Timer | null = bombData.state === "defusing" ? { time:bombData.defuseTime, active: true, side: bombData.player?.team.orientation || "left", player: bombData.player, type: "defusing"} : null;
    const [roundWin, setRoundWin] = useState<{ key: string, team: I.Team, outcome: I.RoundOutcome } | null>(null);
    const lastRoundWinKey = useRef("");
    const winTimeout = useRef<number | null>(null);

    onGSI("roundEnd", result => {
      const eventKey = [
        result.map.name,
        result.map.round,
        result.winner.side,
        result.winner.score,
        result.loser.score,
      ].join(":");
      if (eventKey === lastRoundWinKey.current) return;
      lastRoundWinKey.current = eventKey;
      if (winTimeout.current !== null) window.clearTimeout(winTimeout.current);
      setRoundWin({ key: eventKey, team: result.winner, outcome: getRoundOutcome(result) });
      winTimeout.current = window.setTimeout(() => {
        setRoundWin(current => current?.key === eventKey ? null : current);
        winTimeout.current = null;
      }, ROUND_WIN_DURATION);
    }, []);

    useEffect(() => () => {
      if (winTimeout.current !== null) window.clearTimeout(winTimeout.current);
    }, []);

    return (
      <>
        <div id={`matchbar`}>
          <TeamScore team={left} orientation={"left"} timer={left.side === "CT" ? defuseTimer : plantTimer}/>
          <div className={`score left ${left.side} series-slots-${seriesSlots}`}>
            {seriesSlots > 0 && <span className="series-markers" aria-hidden="true">
              {Array.from({ length: seriesSlots }, (_, index) => <i key={index} className={websiteSeriesWins(match, left) > index ? "win" : ""} />)}
            </span>}
            {left.score}
          </div>
          <div id="timer" className={bo === 0 ? 'no-bo' : ''}>
            <div id="round_now" className={isPlanted ? "hide":""}>{getRoundLabel(map.round)}</div>
            <div id={`round_timer_text`} className={`${isPlanted ? "hide" : ""} ${isWarmup ? "warmup" : ""}`.trim()}>{time}</div>
            <Bomb bombData={bombData} />
          </div>
          <div className={`score right ${right.side} series-slots-${seriesSlots}`}>
            {seriesSlots > 0 && <span className="series-markers" aria-hidden="true">
              {Array.from({ length: seriesSlots }, (_, index) => <i key={index} className={websiteSeriesWins(match, right) > index ? "win" : ""} />)}
            </span>}
            {right.score}
          </div>
          <TeamScore team={right} orientation={"right"} timer={right.side === "CT" ? defuseTimer : plantTimer} />
        </div>
        {roundWin ? <WinAnnouncement key={roundWin.key} team={roundWin.team} outcome={roundWin.outcome} /> : null}
      </>
    );
}

export default Matchbar;
