import { message as siteMessage } from '../../shared/i18n.js';
import { MATCH_ID, adminLabel, apiJson, awayName, bundle, byId, esc, fmtVal, homeName, mapDisplay, participantById, playerLabel, refreshBundle, runStatusBadge, showFeedback, statusLabel } from './context.mjs';

/* ==================== 顶部状态总览 ==================== */
export function renderSummary() {
  var ctx = bundle.context;
  var ov = bundle.overview;
  var res = ov.results || {};
  var match = ctx.match || {};
  var allRuns = [];
  (ov.maps || []).forEach(function (m) {
    (m.runs || []).forEach(function (r) { allRuns.push(r); });
  });
  var activeCount = allRuns.filter(function (r) { return r.status !== 'void'; }).length;
  var voidCount = allRuns.filter(function (r) { return r.status === 'void'; }).length;
  var settled = res.series && res.series.state === 'settled';

  var statusCls = match.status === 'completed' ? 'badge-done'
    : (match.status === 'live' ? 'badge-live'
    : (match.status === 'cancelled' ? 'badge-danger' : 'badge-gold'));

  byId('opsSummaryTop').innerHTML =
    '<div class="ops-score-banner">' +
      '<span class="ops-score-team" data-i18n-ignore>' + esc(homeName()) + '</span>' +
      ("<strong class=\"ops-score-num\" title=\"" + siteMessage('client.ops_runs.official_map_wins') + "\">") + esc(fmtVal(res.score1)) + ' : ' + esc(fmtVal(res.score2)) + '</strong>' +
      '<span class="ops-score-team" data-i18n-ignore>' + esc(awayName()) + '</span>' +
    '</div>' +
    '<div class="ops-summary-badges">' +
      '<span class="badge ' + statusCls + '">' + esc(statusLabel(match.status)) + '</span>' +
      '<span class="badge">' + esc(match.bo_format || 'BO3') + '</span>' +
      '<span class="badge">' + (settled ? siteMessage('client.ops_runs.settled') : siteMessage('client.ops_runs.unsettled')) + '</span>' +
      '<span class="badge" data-i18n-ignore>Series Rev ' + esc(res.revision || 0) + '</span>' +
    '</div>';

  var bpLabel = match.bp_status === 'completed' ? siteMessage('client.ops_runs.completed')
    : (match.bp_status === 'in_progress' ? siteMessage('client.ops_runs.ongoing') : siteMessage('client.ops_runs.not_complete'));
  var bpCls = match.bp_status === 'completed' ? 'is-ok' : 'is-warn';
  var rosterCls = match.rosters_frozen ? 'is-ok' : 'is-warn';
  var authLabel = ov.ready_for_start ? siteMessage('client.ops_runs.authorized_ready')
    : (ov.eligible && !ov.authorized ? siteMessage('client.ops_runs.eligible_awaiting_authorization')
    : (ov.authorized ? siteMessage('client.ops_runs.authorized_new_runs_closed') : siteMessage('client.ops_runs.not_eligible')));
  var authCls = ov.ready_for_start ? 'is-ok' : (ov.eligible ? 'is-pending' : 'is-warn');
  var runsText = allRuns.length
    ? (siteMessage('client.ops_runs.length_run_s_activecount_valid_voidcount', {length: allRuns.length, activecount: activeCount, voidcount: voidCount}))
    : siteMessage('client.ops_runs.no_map_runs_yet');

  byId('opsGateGrid').innerHTML =
    '<div class="ops-gate-item ' + rosterCls + '">' +
      ("<span class=\"ops-gate-label\">" + siteMessage('client.ops_runs.1_match_roster') + "</span>") +
      '<strong>' + (match.rosters_frozen ? siteMessage('client.ops_runs.locked_10_players') : siteMessage('client.ops_runs.unlocked')) + '</strong>' +
    '</div>' +
    '<div class="ops-gate-item ' + bpCls + '">' +
      ("<span class=\"ops-gate-label\">" + siteMessage('client.ops_runs.2_map_veto') + "</span>") +
      '<strong>' + esc(bpLabel) + '</strong>' +
    '</div>' +
    '<div class="ops-gate-item ' + authCls + '">' +
      ("<span class=\"ops-gate-label\">" + siteMessage('client.ops_runs.3_eligibility_authorization') + "</span>") +
      '<strong>' + esc(authLabel) + '</strong>' +
    '</div>' +
    '<div class="ops-gate-item ' + (allRuns.length ? 'is-ok' : 'is-neutral') + '">' +
      ("<span class=\"ops-gate-label\">" + siteMessage('client.ops_runs.4_map_runs') + "</span>") +
      '<strong>' + esc(runsText) + '</strong>' +
    '</div>';
}

/* ==================== Tab 1: 开赛授权、阵容与局次 ==================== */
export function renderAuthCard() {
  var ov = bundle.overview;
  var match = bundle.context.match;
  var badge = byId('opsAuthBadge');
  if (ov.ready_for_start) {
    badge.className = 'badge badge-accent';
    badge.textContent = siteMessage('client.ops_runs.authorized_to_start');
  } else if (ov.eligible && !ov.authorized) {
    badge.className = 'badge badge-gold';
    badge.textContent = siteMessage('client.ops_runs.pending_authorization');
  } else if (ov.authorized) {
    badge.className = 'badge';
    badge.textContent = siteMessage('client.ops_runs.authorized');
  } else {
    badge.className = 'badge badge-danger';
    badge.textContent = siteMessage('client.ops_runs.not_ready');
  }

  var authInfo = match.authorized_at
    ? ((siteMessage('client.ops_runs.authorized_at') + "<span data-i18n-ignore>") + esc(match.authorized_at) + ("</span>" + siteMessage('client.ops_runs.by') + "<strong data-i18n-ignore>") + esc(match.authorized_by_name || '-') + ("</strong>" + siteMessage('client.ops_runs.pre_match_predictions_are_closed_director')))
    : (ov.eligible
      ? siteMessage('client.ops_runs.match_rosters_are_locked_and_map')
      : (siteMessage('client.ops_runs.not_eligible_to_start_yet') + "<strong>") + esc(ov.reason || siteMessage('client.ops_runs.lock_the_match_roster_and_complete')) + '</strong>');

  var btnHtml = '';
  if (!ov.authorized) {
    btnHtml = '<button type="button" class="btn btn-primary" id="opsAuthorizeBtn"' +
      (ov.eligible ? '' : ' disabled') + (">" + siteMessage('client.ops_runs.authorize_match_start') + "</button>");
  }

  byId('opsAuthBody').innerHTML =
    '<div class="ops-auth-row">' +
      '<div>' +
        '<p class="ops-auth-desc">' + authInfo + '</p>' +
        '<div class="ops-flag-list">' +
          '<span class="ops-flag ' + (ov.eligible ? 'is-true' : 'is-false') + ("\">" + siteMessage('client.ops_runs.eligible')) + (ov.eligible ? siteMessage('client.ops_runs.yes') : siteMessage('client.ops_runs.no')) + '</span>' +
          '<span class="ops-flag ' + (ov.authorized ? 'is-true' : 'is-false') + ("\">" + siteMessage('client.ops_runs.authorized_2')) + (ov.authorized ? siteMessage('client.ops_runs.authorized') : siteMessage('client.ops_runs.not_authorized')) + '</span>' +
          '<span class="ops-flag ' + (ov.ready_for_start ? 'is-true' : 'is-false') + ("\">" + siteMessage('client.ops_runs.ready_to_record_a_map_run')) + (ov.ready_for_start ? siteMessage('client.ops_runs.yes_2') : siteMessage('client.ops_runs.no_2')) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="ops-auth-actions">' + btnHtml + '</div>' +
    '</div>';

  var authBtn = byId('opsAuthorizeBtn');
  if (authBtn) {
    authBtn.addEventListener('click', handleAuthorize);
  }
}

async function handleAuthorize() {
  var ok = await window.showConfirm(siteMessage('client.ops_runs.authorize_this_match_to_start_pre'), siteMessage('client.ops_runs.authorize_start'));
  if (!ok) return;
  var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/authorize', { method: 'POST', json: {} });
  if (!r.ok) {
    showFeedback(r.data.error || siteMessage('client.ops_runs.failed_to_authorize_start'), 'error');
    return;
  }
  showFeedback(siteMessage('client.ops_runs.match_authorized_to_start_you_can'), 'success');
  await refreshBundle(true);
}

export function renderFrozenRoster() {
  var parts = bundle.context.participants || [];
  if (!parts.length) {
    byId('opsFrozenRosterBody').innerHTML = ("<p class=\"empty-state\">" + siteMessage('client.ops_runs.match_entrants_have_not_been_assigned') + "</p>");
    return;
  }
  var html = '<div class="ops-two-col">';
  parts.forEach(function (side) {
    var initialSet = new Set(side.initial_player_ids || []);
    html += '<div class="ops-subcard">' +
      '<div class="ops-subcard-head">' +
        '<strong data-i18n-ignore>' + esc(side.name) + '</strong>' +
        '<span class="badge ' + (side.frozen ? 'badge-accent' : 'badge-gold') + '">' +
          (side.frozen ? siteMessage('client.ops_runs.locked') : siteMessage('client.ops_runs.unlocked')) +
        '</span>' +
      '</div>' +
      '<ol class="ops-mini-roster">';
    (side.players || []).forEach(function (p) {
      var isInit = initialSet.has(p.id);
      html += '<li>' +
        '<span class="ops-slot">' + esc(p.slot) + '</span>' +
        '<span class="ops-pname" data-i18n-ignore>' + esc(p.nickname) + '</span>' +
        '<span class="ops-steam" data-i18n-ignore>' + esc(p.steam_id || '-') + '</span>' +
        '<span class="badge">' + (isInit ? siteMessage('client.ops_runs.initial_roster') : siteMessage('client.ops_runs.pre_match_sub')) + '</span>' +
      '</li>';
    });
    html += '</ol>';
    var reserves = side.assigned_reserves || [];
    html += ("<div class=\"ops-reserves-line\"><span>" + siteMessage('client.ops_runs.available_team_reserves') + "</span>");
    if (reserves.length) {
      reserves.forEach(function (res) {
        html += '<span class="badge" data-i18n-ignore>' + esc(res.nickname) + '</span> ';
      });
    } else {
      html += ("<span class=\"muted\">" + siteMessage('client.ops_runs.none') + "</span>");
    }
    html += '</div></div>';
  });
  html += '</div>';
  byId('opsFrozenRosterBody').innerHTML = html;
}

export function renderMapsAndRuns() {
  var maps = bundle.overview.maps || [];
  var resultsByMap = {};
  ((bundle.overview.results || {}).maps || []).forEach(function (rm) {
    resultsByMap[rm.scheduled_map_id] = rm;
  });

  if (!maps.length) {
    byId('opsMapsContainer').innerHTML =
      ("<p class=\"empty-state\">" + siteMessage('client.ops_runs.no_scheduled_maps_yet_configure_maps') + "</p>");
    return;
  }

  var frozenIds = new Set();
  (bundle.context.participants || []).forEach(function (s) {
    (s.players || []).forEach(function (p) { frozenIds.add(p.id); });
  });

  var html = '';
  var nextMap = maps.find(function (m) {
    return !(resultsByMap[m.scheduled_map_id] || {}).official_map_result_id;
  });
  maps.forEach(function (m) {
    var resInfo = resultsByMap[m.scheduled_map_id] || {};
    var runs = m.runs || [];
    var activeOrClosed = runs.filter(function (r) { return r.status !== 'void'; });
    var latestRun = runs.length ? runs[runs.length - 1] : null;
    var needsReplayStart = latestRun && latestRun.status === 'void' && activeOrClosed.length === 0;
    var canStartFirst = runs.length === 0 && m === nextMap && !bundle.context.series_decided && bundle.overview.ready_for_start;
    var canStartReplay = needsReplayStart && bundle.overview.ready_for_start;

    var officialBadge = resInfo.official_map_result_id
      ? ("<span class=\"badge badge-accent\">" + siteMessage('client.ops_runs.official_result')) + esc(resInfo.score1) + ' : ' + esc(resInfo.score2) + '（Rev ' + esc(resInfo.revision) + '）</span>'
      : ("<span class=\"badge\">" + siteMessage('client.ops_runs.no_official_result') + "</span>");

    // Build Effective Roster summary grouped by side
    var effHome = (m.effective_roster || []).filter(function (r) { return r.side_key === 'home'; });
    var effAway = (m.effective_roster || []).filter(function (r) { return r.side_key === 'away'; });

    html += '<article class="ops-map-card" data-scheduled-map-id="' + m.scheduled_map_id + '">' +
      '<div class="ops-map-head">' +
        '<div class="ops-map-title-group">' +
          ("<span class=\"ops-map-order\">" + siteMessage('client.ops_runs.map')) + esc(m.map_order) + '</span>' +
          '<h3 data-i18n-ignore>' + esc(mapDisplay(m.map_name)) + '</h3>' +
          '<span class="muted" data-i18n-ignore>ScheduledMap #' + esc(m.scheduled_map_id) + '</span>' +
          officialBadge +
        '</div>' +
        '<div class="ops-map-actions">';

    if (canStartFirst) {
      html += '<button type="button" class="btn btn-sm btn-primary" data-action="open-start-run" data-map-id="' + m.scheduled_map_id + ("\">" + siteMessage('client.ops_runs.record_map_run') + "</button>");
    } else if (canStartReplay) {
      html += '<button type="button" class="btn btn-sm btn-primary" data-action="open-start-run" data-map-id="' + m.scheduled_map_id + '" data-prev-run-id="' + latestRun.map_run_id + ("\">" + siteMessage('client.ops_runs.start_rematch_run_from')) + latestRun.map_run_id + '）</button>';
    } else if (!activeOrClosed.length && !bundle.overview.ready_for_start) {
      html += ("<span class=\"muted\">" + siteMessage('client.ops_runs.complete_eligibility_checks_and_authorize_start') + "</span>");
    }

    html += '</div></div>';

    // Effective roster strip
    html += '<div class="ops-effective-strip">' +
      ("<div class=\"ops-effective-label\">" + siteMessage('client.ops_runs.effective_roster_for_this_map') + "</div>") +
      '<div class="ops-effective-sides">';
    [[homeName(), effHome], [awayName(), effAway]].forEach(function (pair) {
      html += '<div class="ops-eff-side"><strong data-i18n-ignore>' + esc(pair[0]) + '</strong>：';
      if (pair[1].length) {
        pair[1].forEach(function (ep) {
          var isTechSub = !frozenIds.has(ep.player_id);
          html += '<span class="ops-eff-chip' + (isTechSub ? ' is-sub' : '') + '">' +
            '<span data-i18n-ignore>' + esc(playerLabel(ep.player_id)) + '</span>' +
            (isTechSub ? (" <em>" + siteMessage('client.ops_runs.tech_sub') + "</em>") : '') +
            '</span>';
        });
      } else {
        html += ("<span class=\"muted\">" + siteMessage('client.ops_runs.roster_not_locked') + "</span>");
      }
      html += '</div>';
    });
    html += '</div></div>';

    if (needsReplayStart) {
      html += ("<div class=\"ops-callout-warn\">" + siteMessage('client.ops_runs.the_previous_run')) + esc(latestRun.map_run_id) + (siteMessage('client.ops_runs.was_voided_for_a_technical_rematch') + "</div>");
    }

    // Runs list
    if (!runs.length) {
      html += ("<p class=\"ops-empty-inline\">" + siteMessage('client.ops_runs.no_map_runs_recorded_for_this') + "</p>");
    } else {
      html += '<div class="ops-runs-list">';
      runs.forEach(function (run) {
        var isVoid = run.status === 'void';
        var sessions = (bundle.context.director_sessions || {})[String(run.map_run_id)] || [];
        var partByPlayer = {};
        (run.participations || []).forEach(function (rp) {
          partByPlayer[rp.player_id] = rp;
        });

        html += '<div class="ops-run-card' + (isVoid ? ' is-void' : '') + '">' +
          '<div class="ops-run-head">' +
            '<div class="ops-run-title">' +
              '<strong data-i18n-ignore>Run #' + esc(run.map_run_id) + '</strong>' +
              '<span class="badge">' + esc(siteMessage('client.ops_runs.attempt_number', { attempt: run.attempt_no })) + '</span>' +
              runStatusBadge(run.status) +
              (run.previous_map_run_id
                ? ("<span class=\"badge badge-gold\">" + siteMessage('client.ops_runs.rematch_of')) + esc(run.previous_map_run_id) + '</span>'
                : '') +
            '</div>' +
            '<div class="ops-run-actions">' +
              '<button type="button" class="btn btn-sm" data-action="view-receipts" data-run-id="' + run.map_run_id + ("\">" + siteMessage('client.ops_runs.director_receipt') + "</button>");
        var writable = !isVoid && !bundle.context.match.event_archived && bundle.context.match.status !== 'cancelled';
        var unrecordedCount = (run.lineup || []).filter(function (lp) { return !partByPlayer[lp.player_id]; }).length;
        if (writable) {
          if (run.status === 'active') html += '<button type="button" class="btn btn-sm" data-action="bind-director" data-run-id="' + run.map_run_id + '" data-map-id="' + m.scheduled_map_id + ("\">" + siteMessage('client.ops_runs.link_director_session') + "</button>");
          html += '<button type="button" class="btn btn-sm" data-action="open-participation" data-run-id="' + run.map_run_id + ("\">" + siteMessage('client.ops_runs.record_participation') + "</button>");
          if (unrecordedCount > 1) {
            html += '<button type="button" class="btn btn-sm" data-action="open-batch-participation" data-run-id="' + run.map_run_id + ("\">" + siteMessage('client.ops_runs.record_participation_in_bulk') + "</button>");
          }
          if (!maps.some(function (later) { return later.map_order > m.map_order && later.runs.length; })) {
            html += '<button type="button" class="btn btn-sm btn-danger" data-action="open-tech-replay" data-run-id="' + run.map_run_id + '" data-map-id="' + m.scheduled_map_id + ("\">" + siteMessage('client.ops_runs.approve_technical_rematch') + "</button>");
          }
        }
        html += '</div></div>';

        html += '<div class="ops-run-meta">' +
          ("<span>" + siteMessage('client.ops_runs.source') + "<strong data-i18n-ignore>") + esc(run.source || '-') + '</strong></span>' +
          ("<span>" + siteMessage('client.ops_runs.started') + "<span data-i18n-ignore>") + esc(run.started_at || '-') + '</span></span>' +
          ("<span>" + siteMessage('client.ops_runs.evidence') + "<span data-i18n-ignore>") + esc(run.start_evidence || '-') + '</span></span>' +
        '</div>';

        if (sessions.length) {
          html += ("<div class=\"ops-director-bar\"><span>" + siteMessage('client.ops_runs.bound_director_sessions') + "</span>");
          sessions.forEach(function (ds) {
            html += '<span class="ops-session-chip" title="' + esc(ds.reason || '') + '">' +
              '<code data-i18n-ignore>' + esc(ds.session_id) + '</code>' +
              ' <small data-i18n-ignore>(' + esc(ds.bound_at || '') + ')</small></span>';
          });
          html += '</div>';
        }

        if (run.replay) {
          html += '<div class="ops-replay-callout">' +
            ("<strong>" + siteMessage('client.ops_runs.technical_rematch_void_record') + "</strong>") +
            '<span data-i18n-ignore>' + esc(run.replay.reason || '-') + '</span>' +
            (siteMessage('client.ops_runs.actor') + "<span data-i18n-ignore>") + esc(adminLabel(run.replay.admin_id)) + '</span>';
          if (run.replay.outgoing_player_id && run.replay.incoming_player_id) {
            html += ("<br><strong>" + siteMessage('client.ops_runs.technical_substitute') + "</strong><span data-i18n-ignore>") +
              esc(playerLabel(run.replay.outgoing_player_id)) + ' → ' +
              esc(playerLabel(run.replay.incoming_player_id)) +
              ("</span>" + siteMessage('client.ops_runs.carried_over_to_rematch_run_and'));
          }
          html += '</div>';
        }

        // Lineup vs actual participations table
        html += '<details class="ops-lineup-details"' + (isVoid ? '' : ' open') + '>' +
          ("<summary>" + siteMessage('client.ops_runs.approved_lineup_and_participation')) +
            (run.participations || []).filter(function (rp) { return rp.is_current; }).length +
            ' / ' + (run.lineup || []).length + (siteMessage('client.ops_runs.confirmed') + "</summary>") +
          '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
            ("<th>" + siteMessage('client.ops_runs.side_entrant') + "</th><th>" + siteMessage('client.ops_runs.players') + "</th><th>Steam ID</th><th>" + siteMessage('client.ops_runs.participation') + "</th><th>" + siteMessage('client.ops_runs.source_revision_reason') + "</th><th class=\"num\">" + siteMessage('client.ops_runs.actions') + "</th>") +
          '</tr></thead><tbody>';

        (run.lineup || []).forEach(function (lp) {
          var party = participantById(lp.match_participant_id);
          var rp = partByPlayer[lp.player_id] || null;
          var statusHtml = !rp
            ? ("<span class=\"badge\">" + siteMessage('client.ops_runs.not_recorded') + "</span>")
            : (rp.is_current
              ? ("<span class=\"badge badge-accent\">" + siteMessage('client.ops_runs.confirmed_2') + "</span>")
              : ("<span class=\"badge badge-danger\">" + siteMessage('client.ops_runs.withdrawn') + "</span>"));
          var detailText = rp
            ? ('<span data-i18n-ignore>' + esc(rp.source) + ' · Rev ' + esc(rp.revision) + '</span>' +
               (rp.reason ? ' · <span data-i18n-ignore>' + esc(rp.reason) + '</span>' : ''))
            : ("<span class=\"muted\">" + siteMessage('client.ops_runs.on_approved_lineup_only_participation_not') + "</span>");

          var rowActions = '';
          if (writable) {
            if (!rp) {
              rowActions = '<button type="button" class="btn btn-sm" data-action="quick-participation" data-run-id="' + run.map_run_id + '" data-player-id="' + lp.player_id + '" data-party-id="' + lp.match_participant_id + ("\">" + siteMessage('client.ops_runs.record_participation') + "</button>");
            } else if (rp.is_current) {
              rowActions =
                '<button type="button" class="btn btn-sm" data-action="jump-stats" data-run-id="' + run.map_run_id + '" data-player-id="' + lp.player_id + ("\">" + siteMessage('client.ops_runs.revise_stats') + "</button> ") +
                '<button type="button" class="btn btn-sm btn-warning" data-action="review-participation" data-part-id="' + rp.participation_id + '" data-present="0" data-rev="' + rp.revision + '" data-player-name="' + esc(playerLabel(lp.player_id)) + ("\">" + siteMessage('client.ops_runs.withdraw') + "</button>");
            } else {
              rowActions = '<button type="button" class="btn btn-sm" data-action="review-participation" data-part-id="' + rp.participation_id + '" data-present="1" data-rev="' + rp.revision + '" data-player-name="' + esc(playerLabel(lp.player_id)) + ("\">" + siteMessage('client.ops_runs.restore_participation') + "</button>");
            }
          } else {
            rowActions = ("<span class=\"muted\">" + siteMessage('client.ops_runs.read_only') + "</span>");
          }

          html += '<tr>' +
            '<td data-i18n-ignore>' + esc(party ? party.name : '#' + lp.match_participant_id) + '</td>' +
            '<td data-i18n-ignore>' + esc(playerLabel(lp.player_id)) + '</td>' +
            '<td class="mono" data-i18n-ignore>' + esc(lp.steam_id || '-') + '</td>' +
            '<td>' + statusHtml + '</td>' +
            '<td>' + detailText + '</td>' +
            '<td class="num ops-row-btns">' + rowActions + '</td>' +
          '</tr>';
        });
        html += '</tbody></table></div></details></div>';
      });
      html += '</div>';
    }

    html += '</article>';
  });
  byId('opsMapsContainer').innerHTML = html;
}

/* ==================== Tab 2: Demo 上传、解析与选择性采纳 ==================== */
