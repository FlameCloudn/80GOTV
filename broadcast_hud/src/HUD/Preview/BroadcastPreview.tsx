import BroadcastMeta from "../BroadcastMeta/BroadcastMeta";
import Weapon from "../Weapon/Weapon";
import { Headshot } from "../../assets/Icons";

type Props = {
  leftName?: string;
  rightName?: string;
  leftScore?: number;
  rightScore?: number;
  timer?: string;
  roundLabel?: string;
  mapName?: string;
  mapNumber?: string;
};

const leftPlayers = [
  ["1", "False Emperor", "100", "$4750", "18", "8", "m4a1_silencer"],
  ["2", "Matsubara Kanon", "74", "$3200", "14", "10", "awp"],
  ["3", "Zirc0n", "46", "$1850", "12", "11", "m4a1"],
  ["4", "FlameCloud", "22", "$900", "10", "13", "famas"],
  ["5", "lan1193", "0", "$150", "9", "14", "deagle"],
];

const rightPlayers = [
  ["6", "AAA'钢板批发", "86", "$4100", "16", "9", "ak47"],
  ["7", "Aurora", "63", "$2750", "13", "10", "awp"],
  ["8", "Northwind", "38", "$1600", "11", "12", "galilar"],
  ["9", "Mirage", "15", "$650", "8", "15", "ak47"],
  ["0", "Overtime", "0", "$100", "7", "16", "deagle"],
];

const PreviewTeam = ({ side, players }: { side: "left" | "right"; players: string[][] }) => (
  <div className={`preview-teambox ${side}`}>
    {players.map(([slot, name, hp, money, kills, deaths, weapon]) => (
      <div className={`preview-player ${Number(hp) === 0 ? "dead" : ""}`} key={name}>
        <div className="preview-player-avatar">{slot}</div>
        <div className="preview-player-main">
          <div className="preview-player-top">
            <strong>{name}</strong>
            <span className="preview-weapon" title={weapon}><Weapon weapon={weapon} active /></span>
          </div>
          <div className="preview-player-bottom">
            <span className="preview-hp">{hp} HP</span>
            <span>{money}</span>
            <span>K {kills}</span>
            <span>D {deaths}</span>
          </div>
          <div className="preview-hp-track"><i style={{ width: `${hp}%` }} /></div>
        </div>
      </div>
    ))}
  </div>
);

const BroadcastPreview = ({
  leftName = "TEAM 80",
  rightName = "SUMMER FIVE",
  leftScore = 10,
  rightScore = 9,
  timer = "1:12",
  roundLabel = "ROUND 21 / 24",
  mapName = "MIRAGE",
  mapNumber = "MAP 2 / 3",
}: Props = {}) => (
  <div className="layout broadcast-preview">
    <div className="preview-game-background">
      <div className="preview-game-label">GAME FEED</div>
    </div>
    <BroadcastMeta />
    <div id="matchbar" className="preview-matchbar">
      <div className="preview-team left CT"><span>{leftName}</span><b>{leftScore}</b></div>
      <div className="preview-timer"><strong>{timer}</strong><span>{roundLabel}</span></div>
      <div className="preview-team right T"><b>{rightScore}</b><span>{rightName}</span></div>
    </div>
    <div className="preview-radar">
      <div className="preview-radar-head"><strong>{mapName}</strong><span>{mapNumber}</span></div>
      <img src="./mock/mirage.svg" alt="" />
      <i className="preview-radar-dot ct one">1</i>
      <i className="preview-radar-dot ct two">2</i>
      <i className="preview-radar-dot t three">6</i>
      <i className="preview-radar-dot t four">7</i>
    </div>
    <div className="players_alive preview-alive">
      <div className="title_container">PLAYERS ALIVE</div>
      <div className="counter_container"><div className="team_counter CT">4</div><div className="vs_counter">VS</div><div className="team_counter T">4</div></div>
    </div>
    <div className="preview-killfeed">
      <div><strong className="CT">False Emperor</strong><span className="preview-kill-weapon"><Weapon weapon="m4a1_silencer" active /><Headshot /></span><strong className="T">Aurora</strong></div>
      <div><strong className="T">AAA'钢板批发</strong><span className="preview-kill-weapon"><Weapon weapon="awp" active /></span><strong className="CT">Zirc0n</strong></div>
    </div>
    <PreviewTeam side="left" players={leftPlayers} />
    <PreviewTeam side="right" players={rightPlayers} />
    <div className="observed preview-observed CT">
      <div className="preview-observed-avatar">1</div>
      <div className="preview-observed-name"><span>NOW OBSERVING</span><strong>FALSE EMPEROR</strong></div>
      <div className="preview-observed-stats"><span><small>HP</small>100</span><span><small>ARMOR</small>96</span><span><small>K / A / D</small>18 / 4 / 8</span><span><small>AMMO</small>24 / 90</span></div>
    </div>
    <div className="broadcast-footer"><span>80GOTV.CN</span><span className="broadcast-footer-dot" /><span>八十中 CS2 赛事直播</span></div>
  </div>
);

export default BroadcastPreview;
