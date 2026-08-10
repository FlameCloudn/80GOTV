import Player from './Player'
import * as I from 'csgogsi';
import './players.scss';

interface Props {
  players: I.Player[],
  team: I.Team,
  side: 'right' | 'left',
  current: I.Player | null,
}
const TeamBox = ({players, team, side, current}: Props) => {
  // GSI updates do not guarantee player array order; keep the broadcast cards stable by slot.
  const slotOrder = (slot?: number) => slot === 0 ? 10 : slot ?? 99;
  const orderedPlayers = [...players].sort((first, second) => slotOrder(first.observer_slot) - slotOrder(second.observer_slot));

  return (
    <div className={`teambox ${team.side} ${side}`}>
      {orderedPlayers.map(player => <Player
        key={player.steamid}
        player={player}
        isObserved={!!(current && current.steamid === player.steamid)}
      />)}
    </div>
  );
}
export default TeamBox;
