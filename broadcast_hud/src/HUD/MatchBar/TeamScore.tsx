import * as I from "csgogsi";
import { Timer } from "./MatchBar";
import TeamLogo from './TeamLogo';
import PlantDefuse from "../Timers/PlantDefuse"

interface IProps {
  orientation: "left" | "right";
  timer: Timer | null;
  team: I.Team;
}

const TeamScore = ({orientation, timer, team }: IProps) => {
    return (
      <>
        <div className={`team ${orientation} ${team.side || ''}`}>
          <div className="team-name">{team?.name || null}</div>
          <TeamLogo team={team} />
          <div className="round-thingy"><div className="inner"></div></div>
        </div>
        <PlantDefuse timer={timer} side={orientation} />
      </>
    );
}

export default TeamScore;
