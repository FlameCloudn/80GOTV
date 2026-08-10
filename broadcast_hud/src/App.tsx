import { useEffect, useState } from 'react'
import './App.css'
import { CSGO } from 'csgogsi'
import { SettingsProvider, onGSI } from './API/contexts/actions'
import Layout from './HUD/Layout/Layout';
import BroadcastPreview from './HUD/Preview/BroadcastPreview';
import './HUD/styles/80gotv.scss';
import { setActiveMatch } from './API/socket';
import { Match } from './API/types';
import api from './API';
import { GSI } from './API/HUD';
import { socket } from './API/socket';
import BpShowcase from './HUD/BpShowcase/BpShowcase';
import PauseShowcase from './HUD/PauseShowcase/PauseShowcase';
import VictoryShowcase from './HUD/VictoryShowcase/VictoryShowcase';
import HalftimeShowcase from './HUD/HalftimeShowcase/HalftimeShowcase';
import FormalFlowPreview from './HUD/FormalFlowPreview/FormalFlowPreview';
import GameHudPreview from './HUD/Preview/GameHudPreview';

function App() {
  const [ game, setGame ] = useState<CSGO | null>(null);
  const [ match, setMatch ] = useState<Match | null>(null);

  useEffect(() => {
    const onMatchPing = () => {
      api.match.getCurrent().then(match => {
          if (!match) {
              GSI.teams.left = null;
              GSI.teams.right = null;
              setMatch(null);
              return;
          }
          const matchTeamIdsChanged =
            GSI.teams.left?.id !== match.left.id || GSI.teams.right?.id !== match.right.id;
          if (matchTeamIdsChanged) {
              // Do not render a frame with the previous match's colors while
              // the new match team metadata is loading.
              GSI.teams.left = null;
              GSI.teams.right = null;
              setGame(null);
          }
          setMatch(match);
          setActiveMatch(match);
  
          if (match.left.id) {
              api.teams.getOne(match.left.id).then(left => {
              // The live GSI frame supplies the current series score. Starting
              // at zero avoids briefly showing a previous run when a match id
              // is reused; socket.ts replaces this on the first frame.
              const gsiTeamData = { id: left._id, name: left.name, country: left.country, logo: left.logo, map_score: 0, extra: left.extra };
  
                  // Keep the scheduled match positions fixed. Halftime only
                  // changes the live CT/T color and label, never the team
                  // logo, name, or score position.
                  GSI.teams.left = gsiTeamData;
              });
          }
          if (match.right.id) {
              api.teams.getOne(match.right.id).then(right => {
              const gsiTeamData = { id: right._id, name: right.name, country: right.country, logo: right.logo, map_score: 0, extra: right.extra };
  
                  GSI.teams.right = gsiTeamData;
              });
          }
  
  
  
      }).catch(() => {
        GSI.teams.left = null;
        GSI.teams.right = null;
        setActiveMatch(null);
        setMatch(null);
      });
    }
    socket.on("match", onMatchPing);
    onMatchPing();

    return () => {
      socket.off("match", onMatchPing);
    }
  }, [])

  onGSI('data', game => {
    // The first GSI frame can arrive before the website roster has loaded.
    // Waiting for both fixed team identities prevents a one-frame CT/T flash.
    if (!GSI.teams.left || !GSI.teams.right) return;
    setGame(game);
  }, []);

  const preview = new URLSearchParams(window.location.search).get('preview') === '1';
  const bpPreview = new URLSearchParams(window.location.search).get('bpPreview') === '1';
  const pausePreview = new URLSearchParams(window.location.search).get('pausePreview');
  const victoryPreview = new URLSearchParams(window.location.search).get('victoryPreview') === '1';
  const seriesPreview = new URLSearchParams(window.location.search).get('seriesPreview') === '1';
  const halftimePreview = new URLSearchParams(window.location.search).get('halftimePreview') === '1';
  const formalFlowPreview = new URLSearchParams(window.location.search).get('formalFlowPreview') === '1';
  const gameHudPreview = new URLSearchParams(window.location.search).get('gameHudPreview') === '1';

  if (gameHudPreview) {
    return <SettingsProvider><GameHudPreview /></SettingsProvider>;
  }

  if (formalFlowPreview) {
    return <SettingsProvider><FormalFlowPreview /></SettingsProvider>;
  }

  if (halftimePreview) {
    return <HalftimeShowcase demo />;
  }

  if (seriesPreview) {
    return <VictoryShowcase demo seriesSummaryOnly />;
  }

  if (victoryPreview) {
    return <VictoryShowcase demo />;
  }

  if (pausePreview === 'tactical' || pausePreview === 'technical') {
    return <PauseShowcase demoKind={pausePreview === 'technical' ? 'technical' : 'tactical_t'} />;
  }

  if (bpPreview) {
    return (
      <SettingsProvider>
        <BpShowcase demo />
      </SettingsProvider>
    );
  }

  if (preview) {
    return (
      <SettingsProvider>
        <BroadcastPreview />
      </SettingsProvider>
    );
  }

  if (!game) return null;
  return (
    <SettingsProvider>
      <Layout game={game} match={match} />
    </SettingsProvider>
  );
}

export default App
