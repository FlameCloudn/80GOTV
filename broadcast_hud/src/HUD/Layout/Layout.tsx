import { useRef, useState } from "react";
import TeamBox from "./../Players/TeamBox";
import MatchBar from "../MatchBar/MatchBar";
import SeriesBox from "../MatchBar/SeriesBox";
import Observed from "./../Players/Observed";
import RadarMaps from "./../Radar/RadarMaps";
import Trivia from "../Trivia/Trivia";
import SideBox from '../SideBoxes/SideBox';
import MoneyBox from '../SideBoxes/Money';
import UtilityLevel from '../SideBoxes/UtilityLevel';
import Killfeed from "../Killfeed/Killfeed";
import MapSeries from "../MapSeries/MapSeries";
import Overview from "../Overview/Overview";
import PauseShowcase from "../PauseShowcase/PauseShowcase";
import { CSGO } from "csgogsi";
import { Match } from "../../API/types";
import { useAction } from "../../API/contexts/actions";
import { Scout } from "../Scout";
import BroadcastMeta from "../BroadcastMeta/BroadcastMeta";
import BpShowcase from "../BpShowcase/BpShowcase";
import VictoryShowcase from "../VictoryShowcase/VictoryShowcase";
import HalftimeShowcase from "../HalftimeShowcase/HalftimeShowcase";
import { automaticDirectorScene, DirectorScene, getPauseKind, isRegulationHalftime } from "./sceneState";

interface Props {
  game: CSGO,
  match: Match | null
}
/*
interface State {
  winner: Team | null,
  showWin: boolean,
  forceHide: boolean
}*/

const Layout = ({game,match}: Props) => {
  const [ forceHide, setForceHide ] = useState(false);
  const [directorScene, setDirectorScene] = useState<DirectorScene>("auto");
  const [directorVisible, setDirectorVisible] = useState(true);
  const sceneTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const countdownPause = getPauseKind(game.phase_countdowns?.phase);
  const broadPause = getPauseKind(game.round?.phase) || getPauseKind(game.map.phase);

  // A timeout counter can decrease before the pause actually starts. Only use
  // the explicit CS2 phase here so the tactical pause overlay waits for the
  // server-confirmed timeout state.
  const detectedPause = isRegulationHalftime(game)
    ? null
    : countdownPause || broadPause;

  useAction('boxesState', (state) => {
    console.log("UPDATE STATE UMC", state);
    if (state === "show") {
       setForceHide(false);
    } else if (state === "hide") {
      setForceHide(true);
    }
  });

  useAction('directorScene', (scene) => {
    const nextScene = String(scene || "auto") as DirectorScene;
    if (sceneTimer.current) clearTimeout(sceneTimer.current);
    if (nextScene === "auto") {
      setDirectorScene("auto");
      return;
    }
    setDirectorScene("game");
    sceneTimer.current = setTimeout(() => setDirectorScene(nextScene), 0);
  }, [], true);

  useAction('directorVisibility', (state) => {
    setDirectorVisible(state !== "hide");
  }, [], true);

  const left = game.map.team_ct.orientation === "left" ? game.map.team_ct : game.map.team_t;
  const right = game.map.team_ct.orientation === "left" ? game.map.team_t : game.map.team_ct;

  const leftPlayers = game.players.filter(player => player.team.side === left.side);
  const rightPlayers = game.players.filter(player => player.team.side === right.side);
  const isFreezetime = (game.round && game.round.phase === "freezetime") || game.phase_countdowns.phase === "freezetime";
  const activeScene = directorScene === "auto" ? automaticDirectorScene(game, detectedPause) : directorScene;
  const showGameHud = activeScene === "game";
  if (!directorVisible) return null;

  return (
    <div className="layout live-hud">
      <BpShowcase />
      <HalftimeShowcase game={game} match={match} manualActive={activeScene === "halftime"} />
      <VictoryShowcase
        game={game}
        match={match}
        manualMode={directorScene === "auto"
          ? undefined
          : activeScene === "map_end"
            ? "map"
            : activeScene === "series_end"
              ? "series"
              : null}
      />
      <PauseShowcase
        map={game.map}
        phase={game.phase_countdowns}
        sessionKey={`${match?.id || "local"}:${game.map.name || "unknown"}`}
        detectedKind={detectedPause}
        manualMode={activeScene === "pause_current" ? "current" : activeScene === "pause_technical" ? "technical" : null}
      />
      <div className={`game-hud-layer ${showGameHud ? "show" : "hide"}`} aria-hidden={!showGameHud}>
      <BroadcastMeta />
      <div className={`players_alive`}>
        <div className="title_container">Players alive</div>
        <div className="counter_container">
          <div className={`team_counter ${left.side}`}>{leftPlayers.filter(player => player.state.health > 0).length}</div>
          <div className={`vs_counter`}>VS</div>
          <div className={`team_counter ${right.side}`}>{rightPlayers.filter(player => player.state.health > 0).length}</div>
        </div>
      </div>
      <Killfeed />
      <Overview match={match} map={game.map} players={game.players || []} />
      <RadarMaps match={match} map={game.map} game={game} />
      <MatchBar map={game.map} phase={game.phase_countdowns} bomb={game.bomb} match={match} />
      <SeriesBox map={game.map} match={match} />

      <Observed player={game.player} />

      <TeamBox team={left} players={leftPlayers} side="left" current={game.player} />
      <TeamBox team={right} players={rightPlayers} side="right" current={game.player} />

      <Trivia />
      <Scout left={left.side} right={right.side} />
      <MapSeries teams={[left, right]} match={match} isFreezetime={isFreezetime} map={game.map} />
      <div className={"boxes left"}>
        <UtilityLevel side={left.side} players={game.players} show={isFreezetime && !forceHide} />
        <SideBox side="left" hide={forceHide} />
        <MoneyBox
          team={left.side}
          side="left"
          loss={Math.min(left.consecutive_round_losses * 500 + 1400, 3400)}
          equipment={leftPlayers.map(player => player.state.equip_value).reduce((pre, now) => pre + now, 0)}
          money={leftPlayers.map(player => player.state.money).reduce((pre, now) => pre + now, 0)}
          show={isFreezetime && !forceHide}
        />
      </div>
      <div className={"boxes right"}>
        <UtilityLevel side={right.side} players={game.players} show={isFreezetime && !forceHide} />
        <SideBox side="right" hide={forceHide} />
        <MoneyBox
          team={right.side}
          side="right"
          loss={Math.min(right.consecutive_round_losses * 500 + 1400, 3400)}
          equipment={rightPlayers.map(player => player.state.equip_value).reduce((pre, now) => pre + now, 0)}
          money={rightPlayers.map(player => player.state.money).reduce((pre, now) => pre + now, 0)}
          show={isFreezetime && !forceHide}
        />
      </div>
      <div className="broadcast-footer">
        <span>80GOTV.CN</span>
        <span className="broadcast-footer-dot" />
        <span>八十中 CS2 赛事直播</span>
      </div>
      </div>
    </div>
  );
}
export default Layout;
