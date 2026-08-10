import React, { useRef, useState } from 'react';

import { KillEvent, Player } from 'csgogsi';
import Kill from './Kill';
import './killfeed.scss';
import { onGSI } from '../../API/contexts/actions';


export interface ExtendedKillEvent extends KillEvent {
    type: 'kill'
}

export interface BombEvent {
    player: Player,
    type: 'plant' | 'defuse'
}

const Killfeed = () => {
    const [ events, setEvents ] = useState<(BombEvent | ExtendedKillEvent)[]>([]);
    const lastRoundKey = useRef<string | null>(null);
    onGSI("kill", kill => {
        setEvents(ev => [...ev.slice(-7), {...kill, type: 'kill'}]);
    }, []);
    onGSI("data", data => {
        const key = `${String(data.map?.name || '')}:${String(data.map?.round ?? '')}`;
        if (lastRoundKey.current && key !== lastRoundKey.current) {
            setEvents([]);
        }
        lastRoundKey.current = key;
        if(data.round && data.round.phase === "freezetime"){
            if(Number(data.phase_countdowns.phase_ends_in) < 10 && events.length > 0){
                setEvents([]);
            }
        }
    }, []);
    return (
        <div className="killfeed">
            {events.map(event => <Kill event={event}/>)}
        </div>
    );

}

export default React.memo(Killfeed);
