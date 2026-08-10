import * as I from "csgogsi";
import { Match } from "../../API/types";

interface Props {
  map: I.Map;
  match: Match | null;
}

const SeriesBox = ({ map, match }: Props) => {
    const bo = (match && Number(String(match.matchType).replace(/\D/g, ""))) || 0;
    const amountOfMaps = bo === 3 ? 2 : bo === 5 ? 3 : 0;
    const left = map.team_ct.orientation === "left" ? map.team_ct : map.team_t;
    const right = map.team_ct.orientation === "left" ? map.team_t : map.team_ct;
    const winsFor = (team: I.Team) => {
      if (!match || !team.id) return 0;
      if (match.left.id === team.id) return Math.max(0, Number(match.left.wins) || 0);
      if (match.right.id === team.id) return Math.max(0, Number(match.right.wins) || 0);
      return 0;
    };
    const leftWins = Math.min(amountOfMaps, winsFor(left));
    const rightWins = Math.min(amountOfMaps, winsFor(right));
    return (
      <div id="encapsulator">
        <div className="container left">
          <div className={`series_wins left `}>
            <div className={`wins_box_container`}>
              {new Array(amountOfMaps).fill(0).map((_, i) => (
                <div key={i} className={`wins_box ${leftWins > i ? "win" : ""} ${left.side}`} />
              ))}
            </div>
          </div>
        </div>
        <div id="series_container">
          <div id="series_text">{ bo ? `BEST OF ${bo}` : '' }</div>
        </div>
        <div className="container right">
          <div className={`series_wins right `}>
            <div className={`wins_box_container`}>
              {new Array(amountOfMaps).fill(0).map((_, i) => (
                <div key={i} className={`wins_box ${rightWins > i ? "win" : ""} ${right.side}`} />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
}

export default SeriesBox;
