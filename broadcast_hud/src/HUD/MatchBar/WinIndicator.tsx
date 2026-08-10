import type { RoundOutcome, Team } from 'csgogsi';
import { BombExplosion, Defuse, Skull, Timer } from '../../assets/Icons';

const reasonLabel: Record<RoundOutcome, string> = {
        ct_win_elimination: 'ENEMY ELIMINATED',
        t_win_elimination: 'ENEMY ELIMINATED',
        ct_win_time: 'TIME EXPIRED',
        ct_win_defuse: 'BOMB DEFUSED',
        t_win_bomb: 'BOMB EXPLODED',
};

const ReasonIcon = ({ outcome }: { outcome: RoundOutcome }) => {
        if (outcome === 'ct_win_defuse') return <Defuse fill="currentColor" />;
        if (outcome === 't_win_bomb') return <BombExplosion fill="currentColor" />;
        if (outcome === 'ct_win_time') return <Timer fill="currentColor" />;
        return <Skull fill="currentColor" />;
};

const WinAnnouncement = ({team, outcome}: { team: Team | null, outcome: RoundOutcome }) => {
        if(!team) return null;
        return <div className={`win_text show ${team.orientation} ${team.side}`} aria-live="polite">
                <span className="win_text_icon" aria-hidden="true"><ReasonIcon outcome={outcome} /></span>
                <span className="win_text_copy">
                        <strong>{team.name} WINS THE ROUND</strong>
                        <span>{reasonLabel[outcome]}</span>
                </span>
            </div>   
}


export default WinAnnouncement;
