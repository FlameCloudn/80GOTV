import { csrfToken } from '../../shared/site-http.mjs';

const data = JSON.parse(document.getElementById('managedBracketData').textContent);

(function () {
  'use strict';

  var EVENT_ID = data.eventId;
  const CSRF = csrfToken();
  var matches = Array.isArray(data.eventMatches) ? data.eventMatches : [];
  var links = Array.isArray(data.managedLinks) ? data.managedLinks : [];
  var entrants = Array.isArray(data.entrants) ? data.entrants : [];


  function esc(val) {
    return String(val == null ? '' : val)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function entrantName(eid) {
    if (eid == null) return 'TBD';
    var found = entrants.find(function (e) { return Number(e.event_entrant_id) === Number(eid); });
    return found ? found.team_name : ('#' + eid);
  }

  function matchLabel(mid) {
    var m = matches.find(function (x) { return Number(x.id) === Number(mid); });
    if (!m) return '#' + mid;
    var left = m.t1_name || 'TBD';
    var right = m.t2_name || 'TBD';
    var stage = m.stage ? ('[' + m.stage + '] ') : '';
    return '#' + m.id + ' ' + stage + left + ' vs ' + right + ' (' + (m.bo_format || 'BO3') + ')';
  }

  function statusLabel(st) {
    return {
      upcoming: window.siteMessage('client.admin_bracket_managed.upcoming'),
      live: window.siteMessage('client.admin_bracket_managed.ongoing'),
      ongoing: window.siteMessage('client.admin_bracket_managed.ongoing'),
      completed: window.siteMessage('client.admin_bracket_managed.completed'),
      cancelled: window.siteMessage('client.admin_bracket_managed.cancelled')
    }[st] || st || '-';
  }

  function showFeedback(msg, kind) {
    var el = document.getElementById('bracketFeedback');
    if (!el) return;
    el.hidden = false;
    el.className = 'ops-feedback is-' + (kind || 'info');
    el.textContent = String(msg);
  }

  function showError(id, msg) {
    var el = document.getElementById(id);
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg ? String(msg) : '';
  }

  async function apiJson(url, options) {
    var opts = Object.assign({ credentials: 'same-origin' }, options || {});
    var headers = Object.assign({ 'X-Requested-With': 'XMLHttpRequest' }, opts.headers || {});
    if (opts.method && opts.method.toUpperCase() !== 'GET') {
      headers['X-CSRF-Token'] = CSRF;
    }
    if (opts.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    opts.headers = headers;
    try {
      var res = await fetch(url, opts);
      if (!(res.headers.get('Content-Type') || '').includes('application/json')) {
        return { ok: false, data: { error: window.siteMessage('client.admin_bracket_managed.no_valid_response_check_that_you') } };
      }
      var data = await res.json();
      return { ok: res.ok && data.ok === true, data: data };
    } catch (error) {
      return { ok: false, data: { error: window.siteMessage('client.admin_bracket_managed.network_request_failed_please_try_again') } };
    }
  }

  function populateSelects() {
    var srcSel = document.getElementById('linkSourceMatch');
    var tgtSel = document.getElementById('linkTargetMatch');
    var prevSrc = srcSel.value;
    var prevTgt = tgtSel.value;
    srcSel.innerHTML = '';
    tgtSel.innerHTML = '';
    if (!matches.length) {
      srcSel.innerHTML = ("<option value=\"\">" + window.siteMessage('client.admin_bracket_managed.no_matches') + "</option>");
      tgtSel.innerHTML = ("<option value=\"\">" + window.siteMessage('client.admin_bracket_managed.no_matches') + "</option>");
      document.getElementById('configLinkBtn').disabled = true;
      return;
    }
    document.getElementById('configLinkBtn').disabled = matches.length < 2;
    matches.forEach(function (m) {
      var label = matchLabel(m.id);
      var o1 = document.createElement('option');
      o1.value = String(m.id);
      o1.setAttribute('data-i18n-ignore', '');
      o1.textContent = label;
      srcSel.appendChild(o1);
      var o2 = document.createElement('option');
      o2.value = String(m.id);
      o2.setAttribute('data-i18n-ignore', '');
      o2.textContent = label;
      tgtSel.appendChild(o2);
    });
    if (prevSrc && matches.some(function (m) { return String(m.id) === prevSrc; })) srcSel.value = prevSrc;
    if (prevTgt && matches.some(function (m) { return String(m.id) === prevTgt; })) tgtSel.value = prevTgt;
    else if (matches.length >= 2) tgtSel.value = String(matches[matches.length - 1].id);
  }

  function renderLinks() {
    var box = document.getElementById('managedLinksContainer');
    if (!links.length) {
      box.innerHTML = ("<p class=\"empty-state\">" + window.siteMessage('client.admin_bracket_managed.no_advancement_links_configured_yet') + "</p>");
      return;
    }
    var html = '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>" + window.siteMessage('client.admin_bracket_managed.source_match') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.outcome') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.downstream_match') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.target_side') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.placed_entrant') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.link_status') + "</th>") +
    '</tr></thead><tbody>';
    links.forEach(function (lk) {
      html += '<tr>' +
        '<td><a href="/admin/matches/' + lk.source_match_id + '/operate" data-i18n-ignore>' + esc(matchLabel(lk.source_match_id)) + '</a></td>' +
        '<td><span class="badge ' + (lk.outcome === 'winner' ? 'badge-accent' : 'badge-gold') + '">' +
          (lk.outcome === 'winner' ? window.siteMessage('client.admin_bracket_managed.winner') : window.siteMessage('client.admin_bracket_managed.loser')) + '</span></td>' +
        '<td><a href="/admin/matches/' + lk.target_match_id + '/operate" data-i18n-ignore>' + esc(matchLabel(lk.target_match_id)) + '</a></td>' +
        '<td>' + (lk.target_side === 'home' ? window.siteMessage('client.admin_bracket_managed.home_side') : window.siteMessage('client.admin_bracket_managed.away_side')) + '</td>' +
        '<td data-i18n-ignore>' + esc(entrantName(lk.event_entrant_id)) + '</td>' +
        '<td>' + (lk.detached
          ? ("<span class=\"badge badge-gold\">" + window.siteMessage('client.admin_bracket_managed.retained_and_detached_settlement')) + esc(lk.detached_settlement_id) + '）</span>'
          : ("<span class=\"badge badge-accent\">" + window.siteMessage('client.admin_bracket_managed.active_link') + "</span>")) + '</td>' +
      '</tr>';
    });
    html += '</tbody></table></div>';
    box.innerHTML = html;
  }

  function renderMatches() {
    var box = document.getElementById('managedMatchesContainer');
    var countEl = document.getElementById('managedMatchesCount');
    if (countEl) countEl.textContent = window.siteMessage('client.admin_bracket_managed.length_matches', {length: matches.length});
    if (!matches.length) {
      box.innerHTML = ("<p class=\"empty-state\">" + window.siteMessage('client.admin_bracket_managed.no_matches_yet_create_downstream_matches') + "</p>");
      return;
    }
    var html = '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>ID</th><th>" + window.siteMessage('client.admin_bracket_managed.stage') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.format') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.matchup') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.series_score') + "</th><th>" + window.siteMessage('client.admin_bracket_managed.status') + "</th><th class=\"num\">" + window.siteMessage('client.admin_bracket_managed.actions') + "</th>") +
    '</tr></thead><tbody>';
    matches.forEach(function (m) {
      var scoreText = (m.status !== 'upcoming' && m.status !== 'cancelled' && m.team1_score != null && m.team2_score != null) ? (m.team1_score + ' : ' + m.team2_score) : '-';
      html += '<tr>' +
        '<td data-i18n-ignore>#' + esc(m.id) + '</td>' +
        '<td data-i18n-ignore>' + esc(m.stage || '-') + '</td>' +
        '<td>' + esc(m.bo_format || 'BO3') + '</td>' +
        '<td data-i18n-ignore><strong>' + esc(m.t1_name || 'TBD') + '</strong> vs <strong>' + esc(m.t2_name || 'TBD') + '</strong></td>' +
        '<td class="mono">' + esc(scoreText) + '</td>' +
        '<td><span class="badge">' + esc(statusLabel(m.status)) + '</span></td>' +
        '<td class="num ops-row-btns">' +
          '<a class="btn btn-sm btn-primary" href="/admin/matches/' + m.id + ("/operate\">" + window.siteMessage('client.admin_bracket_managed.match_operations') + "</a> ") +
          '<a class="btn btn-sm" href="/admin/matches/edit/' + m.id + ("\">" + window.siteMessage('client.admin_bracket_managed.pre_match_setup') + "</a>") +
        '</td>' +
      '</tr>';
    });
    html += '</tbody></table></div>';
    box.innerHTML = html;
  }

  async function refreshLinks() {
    var r = await apiJson('/admin/events/' + EVENT_ID + '/operations/bracket', { method: 'GET' });
    if (!r.ok) {
      showFeedback(r.data.error || window.siteMessage('client.admin_bracket_managed.could_not_load_advancement_links'), 'error');
      return false;
    }
    links = r.data.links || [];
    matches = r.data.matches;
    populateSelects();
    renderMatches();
    renderLinks();
    return true;
  }

  document.getElementById('createDownstreamForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    showError('createDownstreamError', '');
    var stage = (document.getElementById('newMatchStage').value || '').trim();
    var boFormat = document.getElementById('newMatchBo').value;
    var matchTime = (document.getElementById('newMatchTime').value || '').trim();
    if (!stage) {
      showError('createDownstreamError', window.siteMessage('client.admin_bracket_managed.enter_a_stage_name'));
      return;
    }
    var payload = { stage: stage, bo_format: boFormat };
    if (matchTime) payload.match_time = matchTime.replace('T', ' ');
    var button = document.getElementById('createDownstreamBtn');
    button.disabled = true;
    var r = await apiJson('/admin/events/' + EVENT_ID + '/operations/bracket', { method: 'POST', json: payload });
    if (!r.ok) {
      button.disabled = false;
      showError('createDownstreamError', r.data.error || window.siteMessage('client.admin_bracket_managed.failed_to_create_downstream_match'));
      return;
    }
    e.target.reset();
    if (await refreshLinks()) showFeedback(window.siteMessage('client.admin_bracket_managed.downstream_match_created') + ' #' + r.data.match_id, 'success');
    button.disabled = false;
  });

  document.getElementById('configBracketLinkForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    showError('configLinkError', '');
    var sourceId = Number(document.getElementById('linkSourceMatch').value);
    var outcome = document.getElementById('linkOutcome').value;
    var targetId = Number(document.getElementById('linkTargetMatch').value);
    var targetSide = document.getElementById('linkTargetSide').value;
    if (!sourceId || !targetId) {
      showError('configLinkError', window.siteMessage('client.admin_bracket_managed.select_valid_source_and_target_matches'));
      return;
    }
    if (sourceId === targetId) {
      showError('configLinkError', window.siteMessage('client.admin_bracket_managed.source_and_target_match_cannot_be'));
      return;
    }
    var r = await apiJson('/admin/matches/' + sourceId + '/operations/bracket-link', {
      method: 'POST',
      json: { outcome: outcome, target_match_id: targetId, target_side: targetSide }
    });
    if (!r.ok) {
      showError('configLinkError', r.data.error || window.siteMessage('client.admin_bracket_managed.failed_to_save_advancement_link'));
      return;
    }
    showFeedback(window.siteMessage('client.admin_bracket_managed.advancement_link_saved_match_sourceid_outcome', {sourceid: sourceId, outcome: outcome, targetid: targetId, targetside: targetSide}), 'success');
    await refreshLinks();
  });

  document.getElementById('bracketRefreshBtn').addEventListener('click', function () {
    refreshLinks().then(function (ok) {
      if (ok) showFeedback(window.siteMessage('client.admin_bracket_managed.advancement_links_refreshed'), 'info');
    });
  });

  document.querySelectorAll('[data-stage-chip]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var input = document.getElementById('newMatchStage');
      if (!input) return;
      input.value = String(chip.dataset.stageChip);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    });
  });

  populateSelects();
  renderLinks();
  renderMatches();
})();
