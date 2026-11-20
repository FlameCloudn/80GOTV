import { escapeHtml } from '../../shared/dom.mjs';
import { csrfToken } from '../../shared/site-http.mjs';

const config = JSON.parse(document.getElementById('bpRoomData').textContent);
const { matchId, myTeam, teamNames, teamOrder, isAdmin, maps: ALL_MAPS } = config;
let { bpVerified, bpCanStart, bpState } = config;
var MAP_DISPLAY = {'Dust2':'Dust2','Mirage':'Mirage','Inferno':'Inferno','Nuke':'Nuke','Cache':'Cache','Ancient':'Ancient','Anubis':'Anubis'};
var MAP_FILE = {'Dust2':'dust2','Mirage':'mirage','Inferno':'inferno','Nuke':'nuke','Cache':'cache','Ancient':'ancient','Anubis':'anubis'};
var actionPending = false;

function apiAction(data) {
  if (actionPending) {
    return Promise.resolve({ok: false, msg: window.siteMessage('client.inline_bp_room.submitting_please_wait')});
  }
  actionPending = true;
  if (bpState && bpState.revision != null && data.bp_revision == null) {
    data.bp_revision = bpState.revision;
  }
  return fetch('/api/bp/' + matchId + '/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()},
    body: JSON.stringify(data)
  }).then(function(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).catch(function(err) {
    console.error('BP API error:', err);
    showToast(window.siteMessage('client.inline_bp_room.action_failed_message_refresh_the_page', {message: err.message}), 'error');
    return {ok: false, msg: err.message};
  }).finally(function() {
    actionPending = false;
  });
}

function getActingTeam(stepIdx) {
  if (!bpState || stepIdx >= (bpState.steps||[]).length) return null;
  var step = bpState.steps[stepIdx];
  var fp = bpState.first_picker;
  if (!['t1', 't2'].includes(fp) || !['first', 'second'].includes(bpState.first_choice)) return null;
  if (step.team === 'first') {
    return bpState.first_choice === 'first' ? fp : (fp === 't1' ? 't2' : 't1');
  }
  return bpState.first_choice === 'first' ? (fp === 't1' ? 't2' : 't1') : fp;
}

function getTeamName(t) { return teamNames[t] || 'TBD'; }
function bpTeamSpan(t) { return '<span data-i18n-ignore>' + escapeHtml(getTeamName(t)) + '</span>'; }
function getSideTeam(p) {
  if (['t1', 't2'].includes(p.side_team)) return p.side_team;
  return p.picked_by === 't1' ? 't2' : (p.picked_by === 't2' ? 't1' : null);
}

function verifyBpPassword() {
  var input = document.getElementById('bp-password');
  if (!input) return;
  // 口令不对：输入框标红，原因用右上角提示（再次输入时去掉红框）
  function fail(text) {
    input.setAttribute('aria-invalid', 'true');
    input.addEventListener('input', function() { input.removeAttribute('aria-invalid'); }, { once: true });
    input.focus();
    window.showToast(text, 'error', { key: 'bp-password' });
  }
  input.removeAttribute('aria-invalid');
  window.dismissToast('bp-password');
  fetch('/bp/' + matchId + '/verify', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()},
    body: JSON.stringify({password: input.value})
  }).then(function(response) {
    return response.json().then(function(data) { return {status: response.status, data: data}; });
  }).then(function(result) {
    if (result.data && result.data.ok) {
      bpVerified = true;
      var gate = document.getElementById('bp-password-gate');
      if (gate) gate.remove();
      if (result.data.bp_state) bpState = result.data.bp_state;
      renderAll();
      sendHeartbeat();
    } else {
      fail((result.data && result.data.msg) || window.siteMessage('client.inline_bp_room.password_check_failed'));
    }
  }).catch(function() {
    fail(window.siteMessage('client.inline_bp_room.network_error_please_try_again_later'));
  });
}

function startBP() {
  apiAction({action: 'start'}).then(function(d) {
    if (d.ok) { bpState = d.state; renderAll(); }
    else { showToast(d.msg || window.siteMessage('client.inline_bp_room.could_not_start'), 'error'); }
  });
}
function getOpTeam() {
  // 管理员模式返回当前应操作的队伍，普通用户返回自己的队伍
  if (!bpState) return myTeam;
  if (bpState.status === 'bp' && bpState.first_choice !== null) {
    var idx = bpState.current_step;
    if (idx < (bpState.steps||[]).length) return getActingTeam(idx);
  }
  if (bpState.status === 'side_select') {
    // 选边阶段：后端会在 pending 中给出实际选边队伍。
    var picks = bpState.picks || [];
    for (var i = 0; i < picks.length; i++) {
      var p = picks[i];
      if (p.picked_by === 'remaining' && bpState.bo !== 'BO1') continue;
      if (!p.side) {
        if (getSideTeam(p)) return getSideTeam(p);
      }
    }
  }
  return myTeam;
}

function doRoll(team) {
  apiAction({action: 'roll', team: team}).then(function(d) {
    if (d.ok) { bpState = d.state; renderAll(); }
    else showToast(d.msg, 'error');
  });
}
function doChooseOrder(team, choice) {
  apiAction({action: 'choose_order', team: team, choice: choice}).then(function(d) {
    if (d.ok) { bpState = d.state; renderAll(); }
    else showToast(d.msg, 'error');
  });
}
function doBan(team, map) {
  apiAction({action: 'ban', team: team, map: map}).then(function(d) {
    if (d.ok) { bpState = d.state; renderAll(); }
    else showToast(d.msg, 'error');
  });
}
function doPick(team, map) {
  apiAction({action: 'pick', team: team, map: map}).then(function(d) {
    if (d.ok) { bpState = d.state; renderAll(); }
    else showToast(d.msg, 'error');
  });
}
function doChooseSide(team, mapName, side) {
  apiAction({action: 'choose_side', team: team, map: mapName, side: side}).then(function(d) {
    if (d.ok) { bpState = d.state; renderAll(); }
    else showToast(d.msg, 'error');
  });
}

// ======================== 渲染 ========================

function renderAll() {
  renderStepIndicator();
  renderPool();
  renderPicks();
  renderStatus();
  renderActions();
}

// 步骤点：B = Ban、P = Pick；做完的 Ban 红、Pick 绿，当前这一步闪烁
function renderStepIndicator() {
  var html = '';
  if (!bpState) { document.getElementById('bp-steps-indicator').innerHTML = ''; return; }
  var steps = bpState.steps || [];
  var cur = bpState.current_step || 0;
  for (var i = 0; i < steps.length; i++) {
    var s = steps[i];
    var cls = 'bp-step-dot';
    if (i < cur) cls += ' ' + s.action + '-dot done';
    else if (i === cur && bpState.status === 'bp') cls += ' current';
    var label = s.action === 'ban' ? 'B' : 'P';
    var progress = i === cur ? (bpState.current_step_progress || 0) : 0;
    var remaining = Math.max(0, s.count - progress);
    const title = window.siteMessage('client.inline_bp_room.maps_remaining', { action: s.action === 'ban' ? 'Ban' : 'Pick', count: remaining });
    html += '<div class="' + cls + '" title="' + escapeHtml(title) + '">' + label + '</div>';
  }
  document.getElementById('bp-steps-indicator').innerHTML = html;
}

// 地图池：HLTV 地图条做底，地图名居中，右下角一个状态小标
function renderPool() {
  var pool = bpState ? (bpState.pool || []) : ALL_MAPS;
  var bans = bpState ? (bpState.bans || []) : [];
  var picks = bpState ? (bpState.picks || []) : [];
  var pickMapNames = picks.map(function(p) { return p.map; });

  // 判断是否轮到我操作（管理员可以操作任意队伍）
  var myTurn = false, currentAction = null, actingTeam = null;
  if (bpState && bpState.status === 'bp' && bpState.first_choice !== null) {
    var idx = bpState.current_step;
    if (idx < (bpState.steps||[]).length) {
      actingTeam = getActingTeam(idx);
      if (bpVerified && (isAdmin || (myTeam && actingTeam === myTeam))) {
        myTurn = true;
        currentAction = bpState.steps[idx].action;
      }
    }
  }

  var html = '';
  for (var i = 0; i < ALL_MAPS.length; i++) {
    var map = ALL_MAPS[i];
    var imgUrl = '/resources/maps/' + (MAP_FILE[map] || map.toLowerCase()) + '.webp';
    var displayName = MAP_DISPLAY[map] || map;
    var cls = 'bp-map-card';
    var actionAttrs = '';
    var statusText = '';

    if (bans.indexOf(map) !== -1) {
      cls += ' banned';
      statusText = window.siteMessage('client.inline_bp_room.banned');
    } else if (pickMapNames.indexOf(map) !== -1) {
      var pick = picks.find(function(p) { return p.map === map; }) || {};
      cls += ' picked';
      if (pick.picked_by === 't1') { cls += ' t1'; statusText = window.siteMessage('client.inline_bp_room.picked_by_value0', {value0: getTeamName('t1')}); }
      else if (pick.picked_by === 't2') { cls += ' t2'; statusText = window.siteMessage('client.inline_bp_room.picked_by_value0', {value0: getTeamName('t2')}); }
      else { cls += ' remaining'; statusText = window.siteMessage('client.inline_bp_room.decider'); }
    } else if (myTurn && pool.indexOf(map) !== -1) {
      cls += ' clickable ' + (currentAction === 'ban' ? 'ban-action' : 'pick-action');
      var actTeam = isAdmin ? actingTeam : myTeam;
      actionAttrs = ' role="button" tabindex="0" data-bp-action="' + currentAction + '" data-bp-team="' + actTeam + '" data-bp-map="' + escapeHtml(map) + '"';
      statusText = (isAdmin ? getTeamName(actingTeam) + ' ' : '') + (currentAction === 'ban' ? 'Ban' : 'Pick');
    } else if (pool.indexOf(map) !== -1) {
      cls += ' available';
      statusText = bpState ? 'TBA' : window.siteMessage('client.inline_bp_room.map_pool');
    } else {
      cls += ' available';
      statusText = '';
    }

    html += '<div class="' + cls + '" style="background-image:url(' + imgUrl + ')"' + actionAttrs + '>';
    html += '<span class="map-name" data-i18n-ignore>' + displayName + '</span>';
    if (statusText) html += '<span class="map-status" data-i18n-ignore>' + escapeHtml(statusText) + '</span>';
    html += '</div>';
  }
  document.getElementById('map-pool').innerHTML = html;
}

function renderPicks() {
  var picks = bpState ? (bpState.picks || []) : [];
  if (picks.length === 0) {
    document.getElementById('picks-row').innerHTML = ("<span class=\"bp-empty\">" + window.siteMessage('client.inline_bp_room.none') + "</span>");
    return;
  }
  var html = '';
  for (var i = 0; i < picks.length; i++) {
    var p = picks[i];
    var cls = 'bp-pick-slot';
    if (p.picked_by === 't1') cls += ' t1';
    else if (p.picked_by === 't2') cls += ' t2';
    else cls += ' remaining';
    var label = p.map;
    if (p.side) {
      var sideTeam = getSideTeam(p);
      label += ' (' + (sideTeam ? getTeamName(sideTeam) + ' ' : '') + p.side + ')';
    }
    html += '<div class="' + cls + '"><span data-i18n-ignore>' + label + '</span><span class="pick-num">' + window.siteMessage('client.inline_bp_room.map_value1', {value1: (i+1)}) + '</span></div>';
  }
  document.getElementById('picks-row').innerHTML = html;
}

function renderStatus() {
  var el = document.getElementById('bp-status-bar');
  if (!bpState) {
    el.innerHTML = bpCanStart ? window.siteMessage('client.inline_bp_room.veto_has_not_started') : window.siteMessage('client.inline_bp_room.match_finished_or_cancelled_veto_is');
    return;
  }

  var status = bpState.status;
  var html = '';

  if (status === 'rolling') {
    var rolls = bpState.rolls || {};
    var t1r = rolls.t1, t2r = rolls.t2;
    var rollLabels = teamOrder.map(function(side) {
      return bpTeamSpan(side) + ' <b>' + (rolls[side] != null ? rolls[side] : '?') + '</b>';
    }).join(' : ');
    if (t1r == null && t2r == null) {
      html = window.siteMessage('client.inline_bp_room.both_teams_roll_the_higher_roll');
    } else if (bpState.first_picker) {
      html = window.siteMessage('client.inline_bp_room.roll') + rollLabels + ' → <span class="bp-good">' + bpTeamSpan(bpState.first_picker) + window.siteMessage('client.inline_bp_room.wins') + '</span>';
    } else {
      html = window.siteMessage('client.inline_bp_room.roll_rolllabels_waiting_for_the_other', {rolllabels: rollLabels});
    }
  } else if (status === 'bp') {
    if (bpState.first_choice === null && bpState.first_picker) {
      html = '<span class="bp-accent">' + bpTeamSpan(bpState.first_picker) + '</span>' + window.siteMessage('client.inline_bp_room.won_the_roll_choose_first_or');
    } else {
      var idx = bpState.current_step;
      var steps = bpState.steps;
      if (idx < steps.length) {
        var acting = getActingTeam(idx);
        var step = steps[idx];
        var act = step.action === 'ban' ? 'Ban' : 'Pick';
        var remaining = Math.max(1, step.count - (bpState.current_step_progress || 0));
        var isMe = acting === myTeam;
        html = '<span class="' + (isMe || isAdmin ? 'bp-good' : 'bp-accent') + '">' + bpTeamSpan(acting) + '</span> '
             + act + ' ' + remaining + window.siteMessage('client.inline_bp_room.maps') + (idx+1) + '/' + steps.length + ')'
             + (isMe ? (" <span class=\"bp-turn-tag bp-good\">" + window.siteMessage('client.inline_bp_room.your_turn') + "</span>") : '')
             + (isAdmin && !isMe ? (" <span class=\"bp-turn-tag bp-accent\">" + window.siteMessage('client.inline_bp_room.acting_for_the_other_team') + "</span>") : '');
      } else {
        html = window.siteMessage('client.inline_bp_room.veto_phase_complete');
      }
    }
  } else if (status === 'side_select') {
    html = bpState.bo === 'BO1'
      ? window.siteMessage('client.inline_bp_room.decider_side_the_team_that_did')
      : window.siteMessage('client.inline_bp_room.side_selection_for_each_picked_map');
  } else if (status === 'completed') {
    html = ("<span class=\"bp-good\">" + window.siteMessage('client.inline_bp_room.veto_complete_maps_have_been_synced') + "</span>");
  }
  el.innerHTML = html;
}

function renderActions() {
  var area = document.getElementById('action-area');
  if (!bpState) {
    if (bpCanStart && bpVerified && (myTeam || isAdmin)) {
      area.innerHTML = ("<button type=\"button\" class=\"btn btn-primary btn-lg\" data-bp-action=\"start\">" + window.siteMessage('client.inline_bp_room.start_veto') + "</button>");
    } else if (!bpCanStart) {
      area.innerHTML = ("<div class=\"bp-waiting\">" + window.siteMessage('client.inline_bp_room.cannot_start_map_veto_for_this') + "</div>");
    } else {
      area.innerHTML = ("<div class=\"bp-waiting\">" + window.siteMessage('client.inline_bp_room.verify_the_shared_passcode_to_start') + "</div>");
    }
    return;
  }

  var status = bpState.status;
  var html = '';

  if (status === 'rolling') {
    var rolls = bpState.rolls || {};
    var t1r = rolls.t1, t2r = rolls.t2;

    // 两个骰子：点数大的一方变绿
    html = '<div class="roll-dice-row">';
    teamOrder.forEach(function(side, index) {
      if (index) html += '<div class="roll-vs">VS</div>';
      var value = rolls[side];
      html += '<div class="roll-team-dice"><div class="dice-label">' + bpTeamSpan(side) + '</div>';
      html += '<div class="roll-dice' + (value != null ? ' rolled' : '') + (bpState.first_picker === side ? ' winner' : '') + '">' + (value != null ? value : '?') + '</div></div>';
    });
    html += '</div>';

    if (!bpState.first_picker) {
      html += '<div class="bp-btn-row">';
      if (isAdmin) {
        // 管理员可以替任意一方 Roll
        teamOrder.forEach(function(side) {
          if (rolls[side] == null) html += '<button class="btn btn-lg" type="button" data-bp-action="roll" data-bp-team="' + side + '">' + bpTeamSpan(side) + ' Roll</button>';
        });
      } else if (bpVerified && t1r == null && myTeam === 't1') {
        html += '<button class="btn btn-primary btn-lg" type="button" data-bp-action="roll" data-bp-team="t1">' + bpTeamSpan('t1') + ' Roll</button>';
      } else if (bpVerified && t2r == null && myTeam === 't2') {
        html += '<button class="btn btn-primary btn-lg" type="button" data-bp-action="roll" data-bp-team="t2">' + bpTeamSpan('t2') + ' Roll</button>';
      }
      html += '</div>';
      if (isAdmin && t1r != null && t2r == null) {
        html += '<div class="bp-waiting">' + window.siteMessage('client.inline_bp_room.waiting_for_value1_to_roll', {value1: bpTeamSpan('t2')}) + '</div>';
      } else if (isAdmin && t2r != null && t1r == null) {
        html += '<div class="bp-waiting">' + window.siteMessage('client.inline_bp_room.waiting_for_value1_to_roll', {value1: bpTeamSpan('t1')}) + '</div>';
      } else if (!isAdmin && !(bpVerified && ((t1r == null && myTeam === 't1') || (t2r == null && myTeam === 't2'))) && (t1r == null || t2r == null)) {
        html += ("<div class=\"bp-waiting\">" + window.siteMessage('client.inline_bp_room.waiting_for_the_other_team_to') + "</div>");
      }
    }
  } else if (status === 'bp' && bpState.first_choice === null && bpState.first_picker) {
    // Roll 胜方选择先手 / 后手
    if (bpVerified && (isAdmin || (myTeam && myTeam === bpState.first_picker))) {
      html = '<div class="bp-choice-title">';
      if (isAdmin) html += window.siteMessage('client.inline_bp_room.admin_choose_for_value1', {value1: bpTeamSpan(bpState.first_picker)});
      else html += window.siteMessage('client.inline_bp_room.you_won_the_roll_choose');
      html += '</div>';
      html += '<div class="bp-btn-row">';
      html += '<button class="btn btn-primary btn-lg" type="button" data-bp-action="choose_order" data-bp-team="' + bpState.first_picker + '" data-bp-choice="first">' + window.siteMessage('client.inline_bp_room.first') + '</button>';
      html += '<button class="btn btn-lg" type="button" data-bp-action="choose_order" data-bp-team="' + bpState.first_picker + '" data-bp-choice="second">' + window.siteMessage('client.inline_bp_room.second') + '</button>';
      html += '</div>';
      html += ("<div class=\"bp-hint\">" + window.siteMessage('client.inline_bp_room.first_ban_pick_first_second_ban') + "</div>");
    } else {
      html = '<div class="bp-waiting">' + window.siteMessage('client.inline_bp_room.waiting_for_value1_to_choose_first', {value1: bpTeamSpan(bpState.first_picker)}) + '</div>';
    }
  } else if (status === 'bp') {
    var idx = bpState.current_step;
    if (idx < (bpState.steps||[]).length) {
      var acting = getActingTeam(idx);
      if (isAdmin) {
        html = ("<div class=\"bp-admin-hint\"><span class=\"bp-accent\">" + window.siteMessage('client.inline_bp_room.admin') + "</span>");
        html += window.siteMessage('client.inline_bp_room.current_turn') + '<b>' + bpTeamSpan(acting) + '</b>' + window.siteMessage('client.inline_bp_room.click_a_map_above_to_act') + '</div>';
      } else if (!bpVerified || !myTeam || acting !== myTeam) {
        html = '<div class="bp-waiting">' + window.siteMessage('client.inline_bp_room.waiting_for_value1', {value1: bpTeamSpan(acting)}) + '</div>';
      } else {
        html = ("<div class=\"bp-hint\">" + window.siteMessage('client.inline_bp_room.click_a_map_card_above_to') + "</div>");
      }
    }
  } else if (status === 'side_select') {
    var picks = bpState.picks || [];
    for (var i = 0; i < picks.length; i++) {
      var p = picks[i];
      if (p.picked_by === 'remaining' && bpState.bo !== 'BO1') continue;
      if (p.side) continue;
      var sideTeam = getSideTeam(p);
      var sideLabel = p.picked_by === 'remaining' ? window.siteMessage('client.inline_bp_room.decider_2') : window.siteMessage('client.inline_bp_room.picked_map');
      html += '<div class="bp-side-item"><b>' + p.map + '</b> — ' + window.siteMessage('client.inline_bp_room.sidelabel_value2_selects_a_side', {sidelabel: sideLabel, value2: bpTeamSpan(sideTeam)});
      if (sideTeam && bpVerified && (isAdmin || (myTeam && myTeam === sideTeam))) {
        html += '<div class="side-btns">';
        html += '<button class="side-btn ct" type="button" data-bp-action="choose_side" data-bp-team="' + sideTeam + '" data-bp-map="' + p.map + ("\" data-bp-side=\"CT\">" + window.siteMessage('client.inline_bp_room.ct_side') + "</button>");
        html += '<button class="side-btn t" type="button" data-bp-action="choose_side" data-bp-team="' + sideTeam + '" data-bp-map="' + p.map + ("\" data-bp-side=\"T\">" + window.siteMessage('client.inline_bp_room.t_side') + "</button>");
        html += '</div>';
        if (isAdmin) html += '<div class="bp-hint">' + window.siteMessage('client.inline_bp_room.acting_for_value1', {value1: bpTeamSpan(sideTeam)}) + '</div>';
      } else {
        html += '<div class="bp-hint">' + window.siteMessage('client.inline_bp_room.waiting_for_value1_to_choose_a', {value1: bpTeamSpan(sideTeam)}) + '</div>';
      }
      html += '</div>';
    }
    if (!html) html = ("<div class=\"bp-waiting\">" + window.siteMessage('client.inline_bp_room.all_sides_have_been_chosen') + "</div>");
  } else if (status === 'completed') {
    html = '<a href="/matches/' + matchId + ("\" class=\"btn btn-primary btn-lg\">" + window.siteMessage('client.inline_bp_room.view_match_details') + "</a>");
  }

  area.innerHTML = html;
}


const board = document.querySelector('.main-col');

function handleAction(event) {
  const target = event.target.closest('[data-bp-action]');
  if (!target) return;
  const { bpAction, bpTeam, bpMap, bpSide, bpChoice } = target.dataset;
  if (bpAction === 'start') startBP();
  else if (bpAction === 'verify') verifyBpPassword();
  else if (bpAction === 'reset') resetBP();
  else if (bpAction === 'roll') doRoll(bpTeam);
  else if (bpAction === 'choose_order') doChooseOrder(bpTeam, bpChoice);
  else if (bpAction === 'choose_side') doChooseSide(bpTeam, bpMap, bpSide);
  else if (bpAction === 'ban') doBan(bpTeam, bpMap);
  else if (bpAction === 'pick') doPick(bpTeam, bpMap);
}

board.addEventListener('click', handleAction);
board.addEventListener('keydown', (event) => {
  if (!event.target.matches('[role="button"][data-bp-action]') || !['Enter', ' '].includes(event.key)) return;
  event.preventDefault();
  handleAction(event);
});

function pollState() {
  if (bpState && bpState.status === 'completed') return;
  fetch('/api/bp/' + matchId + '/state').then(function(r) { return r.json(); }).then(function(data) {
    if (data.ok && data.bp_can_start != null) bpCanStart = !!data.bp_can_start;
    if (data.ok && JSON.stringify(data.state) !== JSON.stringify(bpState)) {
      bpState = data.state || null;
      renderAll();
    }
  });
}

function sendHeartbeat() {
  if (!bpState || !bpVerified || (!myTeam && !isAdmin)) return;
  fetch('/api/bp/' + matchId + '/heartbeat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()}
  }).catch(function() {});
}

function resetBP() {
  showConfirm(window.siteMessage('client.inline_bp_room.reset_map_veto_this_clears_all'), window.siteMessage('client.inline_bp_room.reset_confirmation')).then(function(yes) {
    if (!yes) return;
    fetch('/api/bp/' + matchId + '/reset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()}
    }).then(function(r) { return r.json(); }).then(function(data) {
      if (data.ok) {
        bpState = null;
        renderAll();
      } else {
        showToast(data.msg, 'error');
      }
    });
  });
}

renderAll();
setInterval(pollState, 3000);
setInterval(sendHeartbeat, 10000);
