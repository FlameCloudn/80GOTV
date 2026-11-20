import { message as siteMessage } from '../../shared/i18n.js';
import { ICON_BASE, MAP_METADATA, SUPPORTED_MAPS, mapDisplay, mapKey, weaponAsset } from './assets.mjs';

export function mountScoreboard(root) {
  const byId = id => root.querySelector('#' + id);

  const feedNodes = new Map();
  let roundSignature = '';
  let markerSignature = '';
  let currentRadarKey = '';
  let initialFeedRendered = false;
  let lastScores = null;
  let currentMapRunId = null;

  function liveMetric(value){
    if(value===null||value===undefined||value===''||value==='-')return '-';
    const num=Number(value);
    return Number.isFinite(num)?num:'-';
  }

  function liveLocale(){return document.documentElement.lang==='en'?'en-US':'zh-CN'}
  function setText(id,value){
    const el=typeof id==='string'?byId(id):id,text=String(value??'');
    if(el&&el.textContent!==text)el.textContent=text;
  }
  function sideClass(value){
    const side=String(value||'').toLowerCase();
    return side==='ct'||side==='t'?side:'';
  }
  // 换图片：地址没变就不动（避免每秒重新请求）；加载失败就藏起来
  function setImage(img,src){
    if(!img)return;
    if(!src){img.hidden=true;img.removeAttribute('src');img.dataset.src='';return}
    if(img.dataset.src===src)return;
    img.dataset.src=src;
    img.hidden=false;
    img.onerror=function(){img.hidden=true};
    img.src=src;
  }
  function createPlayerRow(){
    return byId('livePlayerRowTemplate').content.firstElementChild.cloneNode(true);
  }
  // 每队固定 5 行：页面上已经有 5 行（报名阵容）就直接用，不重建
  function ensurePlayerRows(target){
    const container=byId(target);
    if(container.children.length===5)return Array.from(container.children);
    const fragment=document.createDocumentFragment();
    for(let index=0;index<5;index+=1)fragment.appendChild(createPlayerRow());
    container.replaceChildren(fragment);
    return Array.from(container.children);
  }
  function updateWeapon(slot,name){
    setImage(slot.querySelector('img'),weaponAsset(name));
    slot.title=name&&name!=='-'?String(name).replace('weapon_',''):'';
  }
  function updatePlayerName(row,player){
    const empty=!player;
    const name=empty?'-':(player.name||'-');
    const avatarImg=row.querySelector('.p-avatar img');
    const avatarFallback=row.querySelector('[data-avatar-fallback]');
    setImage(avatarImg,empty?'':player.avatar);
    avatarImg.onerror=function(){avatarImg.hidden=true;avatarFallback.hidden=false};
    avatarFallback.hidden=Boolean(!empty&&player.avatar);
    setText(avatarFallback,empty?'-':String(name).charAt(0));
    const nameEl=row.querySelector('.p-nick');
    setText(nameEl,name);
    nameEl.title=empty?'':name;
  }
  // 血量：数字 + 一根条；60 以上绿、30 以上黄、更低红
  function updatePlayerHealth(row,player){
    const rawHp=player?player.hp:null;
    const hp=rawHp===null||rawHp===undefined||rawHp===''||rawHp==='-'?NaN:Number(rawHp);
    const known=Number.isFinite(hp);
    const fill=row.querySelector('.hp-fill');
    const width=(known?Math.max(0,Math.min(100,hp)):0)+'%';
    if(fill.style.width!==width)fill.style.width=width;
    fill.className='hp-fill'+(!known||hp>60?'':(hp>30?' low':' crit'));
    setText(row.querySelector('.hp-num'),known?hp:'-');
  }
  function updatePlayerRow(row,player){
    const empty=!player;
    row.classList.toggle('dead',empty||player.alive===false);
    row.classList.toggle('missing',Boolean(player&&player.missing));
    updatePlayerName(row,player);
    updatePlayerHealth(row,player);
    updateWeapon(row.querySelector('.p-pistol'),empty?'':player.secondary);
    updateWeapon(row.querySelector('.p-weapon'),empty?'':player.primary);
    const armorSrc=empty?'':(player.helmet?ICON_BASE+'kevlar_helmet.webp':(Number(player.armor)>0?ICON_BASE+'kevlar.webp':''));
    setImage(row.querySelector('.p-armor img'),armorSrc);
    const moneyVal=empty?'-':liveMetric(player.money);
    setText(row.querySelector('.p-money'),moneyVal==='-'?'-':'$'+Number(moneyVal).toLocaleString('en-US'));
    setText(row.querySelector('.p-stat.k'),empty?'-':liveMetric(player.kills));
    setText(row.querySelector('.p-stat.a'),empty?'-':liveMetric(player.assists));
    setText(row.querySelector('.p-stat.d'),empty?'-':liveMetric(player.deaths));
    setText(row.querySelector('.p-adr'),empty?'-':liveMetric(player.adr));
  }
  function renderTeam(target,players){
    const rows=ensurePlayerRows(target);
    for(let index=0;index<5;index+=1)updatePlayerRow(rows[index],(players||[])[index]||null);
  }
  function radarPoint(x,y,mapName){
    const key=mapKey(mapName),meta=MAP_METADATA[key];
    if(meta){
      return {left:Math.max(2,Math.min(98,(Number(x)+meta.x)/(meta.resolution*1024)*100)),top:Math.max(2,Math.min(98,100-(Number(y)+meta.y)/(meta.resolution*1024)*100))};
    }
    return {left:50,top:50};
  }
  function renderRadarMap(mapName){
    const requested=mapKey(mapName),key=SUPPORTED_MAPS.has(requested)?requested:'';
    if(key===currentRadarKey)return;
    currentRadarKey=key;
    setImage(byId('radarImage'),key?'/resources/radars/'+encodeURIComponent(key)+'.svg':'');
  }
  // 小地图：只画当前回合的阵亡点（最多 10 个），颜色是阵亡者的阵营
  function renderMarkers(data){
    const round=Number(data.round||0);
    const markers=(data.death_markers||data.kill_markers||[]).filter(function(item){return Number(item.round_number??item.round)===round}).slice(-10);
    const signature=JSON.stringify(markers.map(function(item){return [item.id,item.x,item.y,item.z,item.side]}));
    if(signature===markerSignature)return;
    markerSignature=signature;
    const fragment=document.createDocumentFragment();
    markers.forEach(function(marker){
      const point=Number.isFinite(Number(marker.radar_x))&&Number.isFinite(Number(marker.radar_y))
        ? {left:Number(marker.radar_x),top:Number(marker.radar_y)}
        : radarPoint(marker.x,marker.y,data.map_name);
      const node=document.createElement('span');
      node.className='kill-marker '+sideClass(marker.side);
      node.style.left=point.left+'%';
      node.style.top=point.top+'%';
      const floor=marker.z==null?null:MAP_METADATA[mapKey(data.map_name)]?.floors?.find(function(item){return Number(marker.z)>=item[1]&&Number(marker.z)<=item[2]});
      node.title=(marker.name||siteMessage('client.scoreboard.unknown_player'))+(floor?' · '+floor[0]:'');
      fragment.appendChild(node);
    });
    byId('killMarkers').replaceChildren(fragment);
  }
  function reasonCode(round){
    if(round.reason_code)return round.reason_code;
    const reason=String(round.reason||'').toLowerCase();
    if(reason.includes('bombed')||reason.includes('explode'))return 'bomb_exploded';
    if(reason.includes('defus'))return 'bomb_defused';
    if(reason.includes('saved')||reason.includes('time'))return 'time_expired';
    if(reason.includes('elimin'))return 'elimination';
    return 'completed';
  }
  function reasonLabel(code){
    return ({bomb_exploded:siteMessage('client.scoreboard.c4_exploded'),bomb_defused:siteMessage('client.scoreboard.c4_defused'),time_expired:siteMessage('client.scoreboard.time_ran_out'),elimination:siteMessage('client.scoreboard.enemy_eliminated'),completed:siteMessage('client.scoreboard.round_over')}[code]||siteMessage('client.scoreboard.round_over'));
  }
  function reasonIcon(code,side){
    if(code==='bomb_exploded')return ICON_BASE+'bomb_exploded.svg';
    if(code==='bomb_defused')return ICON_BASE+'bomb_defused.svg';
    if(code==='time_expired')return ICON_BASE+'stopwatch.svg';
    return side==='ct'||side==='t'?ICON_BASE+(side==='ct'?'ct_win.svg':'t_win.svg'):'';
  }
  // 一格回合：这一队赢了就放胜利方式的图标，没赢留空
  function roundCell(round,roundIndex,teamKey,winnerTeam){
    const won=Boolean(round)&&teamKey===winnerTeam;
    const winnerSide=sideClass(round&&round.side);
    const code=round?reasonCode(round):'completed';
    const cell=document.createElement('span');
    cell.className='round-cell'+(won?' won '+winnerSide:' empty');
    cell.title=siteMessage('client.scoreboard.round_value1', {value1: (roundIndex+1)})+(won?' · '+winnerSide.toUpperCase()+' · '+reasonLabel(code):'');
    if(won){
      const img=document.createElement('img');
      img.loading='lazy';img.className='round-result';img.alt='';
      const icon=reasonIcon(code,winnerSide);
      if(icon){img.src=icon;cell.appendChild(img)}else{cell.textContent='?'}
    }
    return cell;
  }
  // 常规 24 回合（MR12）：每队一排，固定 24 格
  function renderRounds(rounds){
    const safe=(Array.isArray(rounds)?rounds:[]).filter(function(round){
      const roundNumber=Number(round.round_number??round.round);
      return Number.isFinite(roundNumber)&&roundNumber>=0&&(roundNumber<24||roundNumber===24);
    });
    const signature=JSON.stringify(safe.map(function(round){return [round.id,round.round_number??round.round,round.side,round.winner,round.reason_code,round.reason]}));
    if(signature===roundSignature)return;
    roundSignature=signature;
    const team1Rounds=document.createDocumentFragment(),team2Rounds=document.createDocumentFragment();
    const roundByNumber=new Map(safe.map(function(round){
      const number=Number(round.round_number??round.round);
      return [number<1?number+1:number,round];
    }));
    for(let roundIndex=0;roundIndex<24;roundIndex+=1){
      const round=roundByNumber.get(roundIndex+1);
      const winnerTeam=round&&['t1','t2'].includes(String(round.winner||'').toLowerCase())?String(round.winner).toLowerCase():'';
      team1Rounds.appendChild(roundCell(round,roundIndex,'t1',winnerTeam));
      team2Rounds.appendChild(roundCell(round,roundIndex,'t2',winnerTeam));
    }
    byId('roundTeam1').replaceChildren(team1Rounds);
    byId('roundTeam2').replaceChildren(team2Rounds);
  }
  // 加时：每 6 回合一段（OT1、OT2……），只画打过的
  function renderOvertime(rounds){
    const board=byId('overtimeBoard');
    const safe=(Array.isArray(rounds)?rounds:[]).filter(function(round){
      const number=Number(round.round_number??round.round);
      return Number.isFinite(number)&&number>24&&number<=48;
    }).sort(function(a,b){return Number(a.round_number??a.round)-Number(b.round_number??b.round)});
    board.classList.toggle('active',safe.length>0);
    board.replaceChildren();
    const groups=new Map();
    safe.forEach(function(round){
      const group=Math.floor((Number(round.round_number??round.round)-25)/6)+1;
      if(!groups.has(group))groups.set(group,[]);
      groups.get(group).push(round);
    });
    groups.forEach(function(groupRounds,group){
      const strip=document.createElement('div');strip.className='overtime-strip';
      addText(strip,'overtime-title','OT'+group);
      const byOffset=new Map(groupRounds.map(function(round){return [Number(round.round_number??round.round)-25-(group-1)*6,round]}));
      for(let index=0;index<6;index+=1){
        const round=byOffset.get(index);
        const cell=document.createElement('span');cell.className='ot-round-cell';
        if(round){
          const side=sideClass(round.side);
          const img=document.createElement('img');img.className='ot-round-result';img.alt='';
          const icon=reasonIcon(reasonCode(round),side);
          if(icon){img.src=icon;cell.appendChild(img)}else{cell.textContent='?'}
          cell.title=siteMessage('client.scoreboard.round_value1', {value1: Number(round.round_number??round.round)});
        }
        strip.appendChild(cell);
      }
      board.appendChild(strip);
    });
  }
  function eventOrder(event,type,index){
    const exact=Number(event.captured_at_epoch);
    if(Number.isFinite(exact)&&exact>0)return exact;
    const parsed=Date.parse(event.captured_at||'');
    if(Number.isFinite(parsed))return parsed/1000;
    const typeOffset=type==='round'?0.8:(type==='plant'?0.4:0);
    return Number((event.round_number??event.round) || 0)*1000+index+typeOffset;
  }
  function collectFeedEvents(data){
    const items=[];
    (data.bomb_events||[]).forEach(function(event,index){
      items.push({id:'plant:'+(event.id||event.round+':'+index+':'+event.player),type:'plant',data:event,order:eventOrder(event,'plant',index)});
    });
    [...(data.round_history||[]),...(data.overtime_history||[])].forEach(function(event,index){
      items.push({id:'round:'+(event.id??event.round_number??event.round),type:'round',data:event,order:eventOrder(event,'round',index)});
    });
    return items.sort(function(a,b){return b.order-a.order}).slice(0,36);
  }
  function addText(parent,className,text){
    const node=document.createElement('span');
    node.className=className;
    node.textContent=String(text??'');
    parent.appendChild(node);
    return node;
  }
  function addIcon(parent,className,src){
    if(!src)return;
    const icon=document.createElement('img');
    icon.loading='lazy';icon.className=className;icon.src=src;icon.alt='';
    parent.appendChild(icon);
  }
  // 日志一行：下包 = “谁在哪个点下了包（几对几）”；回合结束 = “哪边赢了（比分）· 怎么赢的”
  function updateFeedNode(node,item){
    const event=item.data||{};
    const round=event.round_number??event.round;
    const signature=JSON.stringify(event);
    if(node.dataset.signature===signature)return;
    node.dataset.signature=signature;
    node.replaceChildren();
    if(item.type==='plant'){
      node.className='kill-line bomb-planted';
      addIcon(node,'plant-icon sb-mono',ICON_BASE+'bombplant.webp');
      addText(node,'kill-name t',event.player||'T Player');
      const aliveKnown=event.alive_t!=null&&event.alive_ct!=null;
      addText(node,'event-text',siteMessage('client.scoreboard.planted_the_c4_at_value1', {value1: (event.site||'?')})+(aliveKnown?' · '+Number(event.alive_t)+'v'+Number(event.alive_ct):''));
      if(round!=null)addText(node,'kill-round','R'+round);
      return;
    }
    const side=sideClass(event.side||event.winner),code=reasonCode(event);
    node.className='kill-line round-over '+side+' reason-'+code.replace(/_/g,'-');
    addIcon(node,'reason-icon',reasonIcon(code,side));
    addText(node,'event-text',siteMessage('client.scoreboard.round_over')+' · '+siteMessage('client.scoreboard.winner')+' ');
    addText(node,'round-winner '+side,side.toUpperCase()||'?');
    const scoreKnown=event.score_ct!=null&&event.score_t!=null;
    addText(node,'event-text',(scoreKnown?' ('+liveMetric(event.score_ct)+' - '+liveMetric(event.score_t)+')':'')+' · '+reasonLabel(code));
    if(round!=null)addText(node,'kill-round','R'+round);
  }
  function syncKillFeed(data){
    const feed=byId('killFeed');
    const items=collectFeedEvents(data);
    if(!items.length){
      if(!initialFeedRendered)return;
      if(!feedNodes.size){
        const placeholder=document.createElement('div');
        placeholder.className='kill-line';placeholder.dataset.feedPlaceholder='1';
        addText(placeholder,'kill-round',siteMessage('client.scoreboard.waiting_for_data'));
        feed.replaceChildren(placeholder);
      }
      return;
    }
    const wanted=new Set(items.map(function(item){return item.id}));
    Array.from(feedNodes.entries()).forEach(function(entry){
      if(!wanted.has(entry[0])){entry[1].remove();feedNodes.delete(entry[0])}
    });
    const missing=[];
    items.forEach(function(item){
      let node=feedNodes.get(item.id);
      if(!node){
        node=document.createElement('div');
        node.dataset.eventId=item.id;
        feedNodes.set(item.id,node);
        missing.push({item:item,node:node});
      }
      updateFeedNode(node,item);
    });
    if(!initialFeedRendered){
      const fragment=document.createDocumentFragment();
      items.forEach(function(item){fragment.appendChild(feedNodes.get(item.id))});
      feed.replaceChildren(fragment);
      initialFeedRendered=true;
      return;
    }
    const placeholder=feed.querySelector('[data-feed-placeholder]');
    if(placeholder)placeholder.remove();
    missing.sort(function(a,b){return a.item.order-b.item.order}).forEach(function(entry){
      feed.prepend(entry.node);
    });
  }
  function bombIcon(bomb){
    const state=String(bomb&&bomb.state||'');
    if(state==='exploded')return ICON_BASE+'bomb_exploded.svg';
    if(state==='defused')return ICON_BASE+'bomb_defused.svg';
    return ICON_BASE+'bombplant.webp';
  }
  function bombLabel(bomb){
    const states={planted:siteMessage('client.scoreboard.planted'),carried:siteMessage('client.scoreboard.carried'),dropped:siteMessage('client.scoreboard.dropped'),defused:siteMessage('client.scoreboard.defused'),exploded:siteMessage('client.scoreboard.exploded'),planting:siteMessage('client.scoreboard.planting'),defusing:siteMessage('client.scoreboard.defusing')};
    if(!bomb||!bomb.state)return siteMessage('client.scoreboard.bomb')+'-';
    const seconds=bomb.countdown==null?NaN:Number(bomb.countdown);
    return siteMessage('client.scoreboard.bomb')+String(states[bomb.state]||bomb.state)+(Number.isFinite(seconds)?' '+seconds.toFixed(1)+'s':'');
  }
  function formatUpdatedAt(value){
    if(!value)return siteMessage('client.scoreboard.no_data_received');
    const date=new Date(value);
    if(Number.isNaN(date.getTime()))return siteMessage('client.scoreboard.updated')+String(value).replace('T',' ').slice(0,16);
    return siteMessage('client.scoreboard.updated')+date.toLocaleString(liveLocale(),{hour12:false,month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  function currentTeamSides(team1,team2){
    const first=String(team1&&team1.side||'').toUpperCase();
    const second=String(team2&&team2.side||'').toUpperCase();
    if((first==='CT'||first==='T')&&(second==='CT'||second==='T')&&first!==second)return [first,second];
    if(first==='CT'||first==='T')return [first,first==='CT'?'T':'CT'];
    if(second==='CT'||second==='T')return [second==='CT'?'T':'CT',second];
    return ['',''];
  }
  // 阵营：选手表头的底色、表格左边的色条、比分颜色（CT 蓝 / T 橙）；不确定时用中性色
  function applyTeamSide(teamNumber,side){
    const sideKey=String(side||'').toLowerCase()||'unknown';
    byId('team'+teamNumber+'Block').className='sb-team-block side-'+sideKey;
    byId('liveScore'+teamNumber).className='side-score '+sideKey;
  }
  // 比分变了闪一下
  function renderScores(team1,team2){
    const s1=team1.score==null?'-':team1.score,s2=team2.score==null?'-':team2.score;
    const changed=lastScores&&(s1!==lastScores[0]||s2!==lastScores[1]);
    ['liveScore1','liveScore2'].forEach(function(id,index){
      const el=byId(id);
      setText(el,index?s2:s1);
      if(changed){el.classList.remove('score-flash');void el.offsetWidth;el.classList.add('score-flash')}
    });
    lastScores=[s1,s2];
  }
  // 右上角的状态牌：连接情况；暂停时显示“战术暂停 · 哪队”或“技术暂停”
  function renderStatus(data,team1,team2){
    const sourceText={gsi:siteMessage('client.scoreboard.observer_account_connected'),gotv:siteMessage('client.scoreboard.gotv_data_connected'),a2s:siteMessage('client.scoreboard.match_server_connected_waiting_for_observer'),stale_gsi:siteMessage('client.scoreboard.observer_account_disconnected'),stale_gotv:siteMessage('client.scoreboard.gotv_data_interrupted')};
    let text=(sourceText[data.source]||siteMessage('client.scoreboard.waiting_for_observer_account'));
    let state=data.source==='gsi'||data.source==='gotv'||data.source==='a2s'?'online':'';
    if(data.side_uncertain||data.source==='stale_gsi'||data.source==='stale_gotv'||data.source==='')state='offline';
    if(data.paused){
      state='paused';
      if(data.pause_type==='tactical'){
        const timeoutSide=String(data.phase_countdown||'').endsWith('_t')?'T':'CT';
        const timeoutTeam=team1.side===timeoutSide?team1.name:(team2.side===timeoutSide?team2.name:'');
        text=siteMessage('client.scoreboard.tactical_timeout')+(timeoutTeam?' · '+timeoutTeam:'');
      }else{
        text=siteMessage('client.scoreboard.technical_timeout');
      }
    }
    const badge=byId('sourceBadge');
    setText(badge,text);
    badge.className='sb-status'+(state?' '+state:'');
  }
  function render(data){
    const team1=data.team1||{};
    const team2=data.team2||{};
    const sides=currentTeamSides(team1,team2);
    renderStatus(data,team1,team2);
    renderScores(team1,team2);
    setText('team1Name',team1.name||'TBD');
    setText('team2Name',team2.name||'TBD');
    applyTeamSide(1,sides[0]);
    applyTeamSide(2,sides[1]);
    setText('roundNum',data.round?siteMessage('client.scoreboard.round_round', {round: data.round}):siteMessage('client.scoreboard.waiting_for_round_data'));
    setText('mapName',mapDisplay(data.map_name)||'-');
    setText('timer',data.timer||'-');
    setText('radarMap',mapDisplay(data.map_name)||'-');
    setText('updatedAt',formatUpdatedAt(data.updated_at));
    setImage(byId('bombStateIcon'),bombIcon(data.bomb));
    setText('bombStateText',bombLabel(data.bomb));
    byId('bombState').classList.toggle('active',Boolean(data.bomb&&data.bomb.state));
    renderTeam('team1Players',data.players_t1);
    renderTeam('team2Players',data.players_t2);
    renderRounds(data.round_history);
    renderOvertime(data.overtime_history);
    renderRadarMap(data.map_name);
    renderMarkers(data);
    syncKillFeed(data);
  }
  function resetLiveFeedAndMarkers(){
    feedNodes.clear();
    initialFeedRendered=false;
    roundSignature='';
    markerSignature='';
    lastScores=null;
    const markers=byId('killMarkers');
    if(markers)markers.replaceChildren();
    const feed=byId('killFeed');
    if(feed){
      const placeholder=document.createElement('div');
      placeholder.className='kill-line';
      placeholder.dataset.feedPlaceholder='1';
      addText(placeholder,'kill-round',siteMessage('client.scoreboard.waiting_for_data'));
      feed.replaceChildren(placeholder);
    }
  }
  function clearLiveForVoid(message){
    currentMapRunId=null;
    resetLiveFeedAndMarkers();
    setText('liveScore1','-');
    setText('liveScore2','-');
    applyTeamSide(1,'');
    applyTeamSide(2,'');
    setText('roundNum',siteMessage('client.scoreboard.awaiting_new_map_run'));
    setText('mapName','-');
    setText('timer','-');
    setText('radarMap','-');
    renderRadarMap('');
    setText('updatedAt',siteMessage('client.scoreboard.no_data_received'));
    setImage(byId('bombStateIcon'),bombIcon(null));
    setText('bombStateText',bombLabel(null));
    const bombEl=byId('bombState');
    if(bombEl)bombEl.classList.remove('active');
    renderTeam('team1Players',[]);
    renderTeam('team2Players',[]);
    renderRounds([]);
    renderOvertime([]);
    const badge=byId('sourceBadge');
    if(badge){
      badge.className='sb-status paused';
      setText(badge,(message||siteMessage('client.scoreboard.current_map_run_voided_for_technical')));
    }
  }
  function markLiveUnavailable(message){
    const badge=byId('sourceBadge');
    if(!badge)return;
    badge.className='sb-status offline';
    setText(badge,(message||siteMessage('client.scoreboard.live_data_interrupted')));
  }

  ensurePlayerRows('team1Players');
  ensurePlayerRows('team2Players');
  renderRounds([]);
  return {
    render(data) {
      const nextRunId = data.map_run_id ?? null;
      if (nextRunId !== null && currentMapRunId !== null && nextRunId !== currentMapRunId) {
        resetLiveFeedAndMarkers();
      }
      if (nextRunId !== null) currentMapRunId = nextRunId;
      render(data);
    },
    clearLiveForVoid,
    markLiveUnavailable,
  };
}
