import { message as siteMessage } from '../../shared/i18n.js';
import { MATCH_ID, adminLabel, apiJson, awayName, bundle, byId, entrantLabel, esc, fmtVal, homeName, mapDisplay, root } from './context.mjs';

export async function loadLiveReference() {
  var box = root.querySelector('[data-live-run]');
  if (!box || box.dataset.loading) return;
  box.dataset.loading = '1';
  var reply = await apiJson('/api/live/' + MATCH_ID, { cache: 'no-store' });
  var frame = reply.data;
  delete box.dataset.loading;
  if (!box.isConnected) return;
  var sameRun = reply.ok && String(frame.map_run_id) === box.dataset.liveRun && frame.source;
  box.querySelector('strong').textContent = sameRun
    ? fmtVal(frame.team1 && frame.team1.score) + ' : ' + fmtVal(frame.team2 && frame.team2.score) : '-';
  box.querySelector('small').textContent = sameRun
    ? (/^stale_/.test(frame.source) ? siteMessage('client.ops_results.last_observation_before_disconnect') + ' · ' + frame.source.slice(6).toUpperCase() : frame.source.toUpperCase())
    : (frame.reason === 'map_run_void' ? siteMessage('client.ops_results.run_voided_waiting_for_the_next') : siteMessage('client.ops_results.no_live_snapshot_for_this_map'));
}

export function renderResultsTab() {
  var ov = bundle.overview;
  var res = ov.results || {};
  var mapsById = {};
  (ov.maps || []).forEach(function (m) { mapsById[m.scheduled_map_id] = m; });

  // 1. Official map results
  var mapHtml = '';
  var mapResults = res.maps || [];
  if (!mapResults.length) {
    mapHtml = ("<p class=\"empty-state\">" + siteMessage('client.ops_results.no_scheduled_maps') + "</p>");
  } else {
    mapHtml = '<div class="ops-results-grid">';
    mapResults.forEach(function (rm) {
      var mapObj = mapsById[rm.scheduled_map_id] || { runs: [] };
      var validRuns = (mapObj.runs || []).filter(function (r) { return r.status !== 'void'; });
      var hasOfficial = rm.official_map_result_id != null;

      mapHtml += '<div class="ops-result-card">' +
        '<div class="ops-subcard-head">' +
          ("<div><span class=\"ops-map-order\">" + siteMessage('client.ops_results.map')) + esc(rm.map_order) + '</span> <strong data-i18n-ignore>' + esc(mapDisplay(rm.map_name)) + '</strong></div>' +
          '<span class="badge ' + (hasOfficial ? 'badge-accent' : '') + '">' + (hasOfficial ? 'Rev ' + rm.revision : siteMessage('client.ops_results.unconfirmed')) + '</span>' +
        '</div>' +
        '<div class="ops-score-compare">' +
          '<div class="ops-score-box">' +
            ("<span class=\"ops-score-box-label\">" + siteMessage('client.ops_results.official_result') + "</span>") +
            '<strong>' + (hasOfficial ? (esc(rm.score1) + ' : ' + esc(rm.score2)) : siteMessage('client.ops_results.unconfirmed_2')) + '</strong>' +
            (hasOfficial
              ? '<small data-i18n-ignore>Run #' + esc(rm.map_run_id) + ' · ' + esc(rm.source) + (rm.terminal_receipt ? siteMessage('client.ops_results.receipt_value1', {value1: esc(rm.terminal_receipt)}) : '') + '</small>'
              : ("<small>" + siteMessage('client.ops_results.requires_an_active_or_closed_map') + "</small>")) +
          '</div>' +
          '<div class="ops-score-box is-ref"' + (rm.run_status === 'active' ? ' data-live-run="' + rm.map_run_id + '"' : '') + '>' +
            ("<span class=\"ops-score-box-label\">" + siteMessage('client.ops_results.live_feed_reference') + "</span>") +
            ("<strong>-</strong><small>" + siteMessage('client.ops_results.no_live_snapshot_for_this_map') + "</small>") +
            (rm.run_status === 'active' ? '<a href="' + esc(bundle.context.match.public_url) + ("#data-live\" target=\"_blank\" rel=\"noopener\">" + siteMessage('client.ops_results.view_live_data') + "</a>") : '') +
          '</div>' +
        '</div>' +
        (hasOfficial && rm.reason ? ("<p class=\"ops-mini-note\">" + siteMessage('client.ops_results.note') + "<span data-i18n-ignore>") + esc(rm.reason) + '</span></p>' : '') +
        '<div class="ops-card-foot">' +
          '<button type="button" class="btn btn-sm ' + (hasOfficial ? '' : 'btn-primary') + '" data-action="open-confirm-map" data-map-id="' + rm.scheduled_map_id + '"' + (validRuns.length ? '' : ' disabled') + '>' +
            (hasOfficial ? siteMessage('client.ops_results.override_official_result') : siteMessage('client.ops_results.confirm_map_result')) +
          '</button>' +
          (!validRuns.length ? ("<span class=\"muted\">" + siteMessage('client.ops_results.start_a_valid_map_run_first') + "</span>") : '') +
        '</div>' +
      '</div>';
    });
    mapHtml += '</div>';
  }
  byId('opsMapResultsContainer').innerHTML = mapHtml;

  // 2. Series settlement & downstream links
  var settled = Boolean(res.series && res.series.state === 'settled');
  var bo = (res.bo_format || 'BO3').toUpperCase();
  var winsNeeded = { BO1: 1, BO3: 2, BO5: 3 }[bo] || 2;
  var reachedWin = bundle.context.series_decided;

  var revBadge = byId('opsSeriesRevBadge');
  revBadge.className = 'badge ' + (settled ? 'badge-done' : 'badge-gold');
  revBadge.textContent = (settled ? siteMessage('client.ops_results.settled') : siteMessage('client.ops_results.unsettled')) + ' · Rev ' + (res.revision || 0);

  var seriesHtml =
    '<div class="ops-series-box">' +
      '<div class="ops-series-main">' +
        '<div class="ops-series-score-line">' +
          '<span data-i18n-ignore>' + esc(homeName()) + '</span> ' +
          '<strong>' + esc(fmtVal(res.score1)) + ' : ' + esc(fmtVal(res.score2)) + '</strong> ' +
          '<span data-i18n-ignore>' + esc(awayName()) + '</span>' +
        '</div>' +
        '<p class="muted">' + esc(bo) + siteMessage('client.ops_results.requires') + winsNeeded + (siteMessage('client.ops_results.map_wins_reaching_the_win_target') + "<strong>" + siteMessage('client.ops_results.does_not_auto_settle') + "</strong>" + siteMessage('client.ops_results.an_admin_must_explicitly_click_settle') + "</p>") +
        (res.series
          ? ("<p class=\"ops-mini-note\">" + siteMessage('client.ops_results.latest_series_decision') + "<strong>") + (res.series.state === 'settled' ? siteMessage('client.ops_results.settled_2') : siteMessage('client.ops_results.reopened')) + ("</strong>" + siteMessage('client.ops_results.actor') + "<span data-i18n-ignore>") + esc(adminLabel(res.series.actor)) + '</span> · <span data-i18n-ignore>' + esc(res.series.recorded_at || '') + '</span>' + (res.series.reason ? (siteMessage('client.ops_results.reason') + "<span data-i18n-ignore>") + esc(res.series.reason) + '</span>' : '') + '</p>'
          : '') +
      '</div>' +
      '<div class="ops-series-actions">' +
        (!settled
          ? '<button type="button" class="btn btn-primary" data-action="open-series-settle"' + (reachedWin ? '' : ' disabled title="' + esc(siteMessage('client.ops_results.win_target_not_reached')) + '"') + (">" + siteMessage('client.ops_results.confirm_and_settle_series') + "</button>")
          : ("<button type=\"button\" class=\"btn btn-danger\" data-action=\"open-series-reopen\">" + siteMessage('client.ops_results.reopen_series') + "</button>")) +
      '</div>' +
    '</div>';

  // Outgoing downstream links
  var links = bundle.context.downstream_links || [];
  seriesHtml += '<div class="ops-downstream-block">' +
    '<div class="ops-subcard-head">' +
      ("<strong>" + siteMessage('client.ops_results.downstream_bracket_links_from_this_match') + "</strong>") +
      '<a class="btn btn-sm" href="' + esc(bundle.context.match.event_bracket_url) + ("\">" + siteMessage('client.ops_results.manage_event_bracket') + "</a>") +
    '</div>';
  if (!links.length) {
    seriesHtml += ("<p class=\"muted\">" + siteMessage('client.ops_results.no_downstream_bracket_links_configured_for') + "</p>");
  } else {
    seriesHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>" + siteMessage('client.ops_results.outcome') + "</th><th>" + siteMessage('client.ops_results.downstream_match') + "</th><th>" + siteMessage('client.ops_results.target_side') + "</th><th>" + siteMessage('client.ops_results.current_entrant') + "</th><th>" + siteMessage('client.ops_results.protection') + "</th>") +
    '</tr></thead><tbody>';
    links.forEach(function (lk) {
      seriesHtml += '<tr>' +
        '<td>' + (lk.outcome === 'winner' ? siteMessage('client.ops_results.winner') : siteMessage('client.ops_results.loser')) + '</td>' +
        '<td><a href="/admin/matches/' + lk.target_match_id + '/operate" data-i18n-ignore>' + esc(lk.target_label) + '</a></td>' +
        '<td>' + (lk.target_side === 'home' ? siteMessage('client.ops_results.home_side') : siteMessage('client.ops_results.away_side')) + '</td>' +
        '<td data-i18n-ignore>' + esc(lk.current_entrant_name || 'TBD') + '</td>' +
        '<td>' +
          (lk.detached ? ("<span class=\"badge badge-gold\">" + siteMessage('client.ops_results.retained_and_detached_settlement')) + esc(lk.detached_settlement_id) + '）</span>'
            : lk.protected ? '<span class="badge badge-danger">' + esc(String(lk.protection_reason)) + '</span>'
            : ("<span class=\"badge badge-accent\">" + siteMessage('client.ops_results.updates_with_settlement') + "</span>")) +
        '</td>' +
      '</tr>';
    });
    seriesHtml += '</tbody></table></div>';
  }
  seriesHtml += '</div>';
  byId('opsSeriesContainer').innerHTML = seriesHtml;

  // 3. Predictions status
  var pred = bundle.context.predictions || {};
  var predBadge = byId('opsPredStateBadge');
  predBadge.className = 'badge ' + (pred.vote_open ? 'badge-accent' : 'badge-done');
  predBadge.textContent = pred.vote_open ? siteMessage('client.ops_results.voting_open') : siteMessage('client.ops_results.voting_closed');

  var predHtml =
    '<div class="ops-pred-stats">' +
      ("<div class=\"ops-pred-stat\"><span>" + siteMessage('client.ops_results.total_votes') + "</span><strong>") + esc(pred.total_votes || 0) + '</strong></div>' +
      '<div class="ops-pred-stat"><span data-i18n-ignore>' + esc(homeName()) + '</span><strong>' + esc(pred.t1_votes || 0) + (siteMessage('client.ops_results.votes') + "</strong></div>") +
      '<div class="ops-pred-stat"><span data-i18n-ignore>' + esc(awayName()) + '</span><strong>' + esc(pred.t2_votes || 0) + (siteMessage('client.ops_results.votes') + "</strong></div>") +
      ("<div class=\"ops-pred-stat\"><span>" + siteMessage('client.ops_results.settled_3') + "</span><strong>") + esc(pred.settled_count || 0) + ' / ' + esc(pred.total_votes || 0) + '</strong></div>' +
    '</div>';

  var votes = pred.votes || [];
  if (votes.length) {
    predHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>" + siteMessage('client.ops_results.user') + "</th><th>" + siteMessage('client.ops_results.predicted_winner') + "</th><th>" + siteMessage('client.ops_results.predicted_score') + "</th><th>" + siteMessage('client.ops_results.status') + "</th><th class=\"num\">" + siteMessage('client.ops_results.points') + "</th>") +
    '</tr></thead><tbody>';
    votes.forEach(function (v) {
      var pickName = v.voted_for === 't1' ? homeName() : (v.voted_for === 't2' ? awayName() : v.voted_for);
      var scoreGuess = (v.score1_guess != null && v.score2_guess != null) ? (v.score1_guess + ' : ' + v.score2_guess) : '-';
      predHtml += '<tr>' +
        '<td data-i18n-ignore>' + esc(v.username || ('User #' + v.user_id)) + '</td>' +
        '<td data-i18n-ignore>' + esc(pickName) + '</td>' +
        '<td>' + esc(scoreGuess) + '</td>' +
        '<td>' + (v.scored ? ("<span class=\"badge badge-accent\">" + siteMessage('client.ops_results.settled_3') + "</span>") : ("<span class=\"badge\">" + siteMessage('client.ops_results.unsettled_2') + "</span>")) + '</td>' +
        '<td class="num"><strong>' + (v.scored ? siteMessage('client.ops_results.value0_pts', {value0: esc(v.points_earned)}) : '-') + '</strong></td>' +
      '</tr>';
    });
    predHtml += '</tbody></table></div>';
  } else {
    predHtml += ("<p class=\"ops-empty-inline\">" + siteMessage('client.ops_results.no_prediction_votes_recorded_for_this') + "</p>");
  }

  var predChanges = (bundle.history && bundle.history.predictions) || [];
  if (predChanges.length) {
    predHtml += ("<details class=\"ops-lineup-details\"><summary>" + siteMessage('client.ops_results.prediction_settlement_changes')) + predChanges.length + (siteMessage('client.ops_results.label') + "</summary>") +
      '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        ("<th>" + siteMessage('client.ops_results.settlement') + "</th><th>" + siteMessage('client.ops_results.vote') + "</th><th>" + siteMessage('client.ops_results.user') + "</th><th>" + siteMessage('client.ops_results.previous_new_points') + "</th>") +
      '</tr></thead><tbody>';
    predChanges.forEach(function (pc) {
      predHtml += '<tr>' +
        '<td data-i18n-ignore>#' + esc(pc.settlement_id) + '</td>' +
        '<td data-i18n-ignore>#' + esc(pc.vote_id) + '</td>' +
        '<td data-i18n-ignore>User #' + esc(pc.user_id) + '</td>' +
        '<td>' + esc(fmtVal(pc.previous_points)) + ' → <strong>' + esc(fmtVal(pc.new_points)) + '</strong></td>' +
      '</tr>';
    });
    predHtml += '</tbody></table></div></details>';
  }
  byId('opsPredictionsContainer').innerHTML = predHtml;

  // 4. Full audit history
  var hist = bundle.history || {};
  var hHtml = '';

  hHtml += ("<details class=\"ops-lineup-details\"><summary>" + siteMessage('client.ops_results.official_map_result_history')) + (hist.maps || []).length + (siteMessage('client.ops_results.label') + "</summary>");
  if ((hist.maps || []).length) {
    hHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>" + siteMessage('client.ops_results.map_2') + "</th><th>Rev</th><th>" + siteMessage('client.ops_results.run') + "</th><th>" + siteMessage('client.ops_results.score') + "</th><th>" + siteMessage('client.ops_results.source_actor') + "</th><th>" + siteMessage('client.ops_results.note_2') + "</th><th>" + siteMessage('client.ops_results.time') + "</th>") +
    '</tr></thead><tbody>';
    hist.maps.forEach(function (hm) {
      hHtml += '<tr>' +
        ("<td>" + siteMessage('client.ops_results.map')) + esc(hm.map_order) + '</td>' +
        '<td>Rev ' + esc(hm.revision) + '</td>' +
        '<td data-i18n-ignore>Run #' + esc(hm.map_run_id) + '</td>' +
        '<td><strong>' + esc(hm.score1) + ' : ' + esc(hm.score2) + '</strong></td>' +
        '<td data-i18n-ignore>' + esc(hm.source) + ' / ' + esc(adminLabel(hm.actor)) + '</td>' +
        '<td data-i18n-ignore>' + esc(hm.reason || '-') + '</td>' +
        '<td data-i18n-ignore>' + esc(hm.recorded_at || '-') + '</td>' +
      '</tr>';
    });
    hHtml += '</tbody></table></div>';
  } else {
    hHtml += ("<p class=\"ops-empty-inline\">" + siteMessage('client.ops_results.no_map_result_history_yet') + "</p>");
  }
  hHtml += '</details>';

  hHtml += ("<details class=\"ops-lineup-details\"><summary>" + siteMessage('client.ops_results.series_settlement_reopen_history')) + (hist.series || []).length + (siteMessage('client.ops_results.label') + "</summary>");
  if ((hist.series || []).length) {
    hHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>Rev</th><th>" + siteMessage('client.ops_results.status_2') + "</th><th>" + siteMessage('client.ops_results.series_score') + "</th><th>" + siteMessage('client.ops_results.actor_2') + "</th><th>" + siteMessage('client.ops_results.reason_2') + "</th><th>" + siteMessage('client.ops_results.time') + "</th>") +
    '</tr></thead><tbody>';
    hist.series.forEach(function (hs) {
      hHtml += '<tr>' +
        '<td>Rev ' + esc(hs.revision) + '</td>' +
        '<td>' + (hs.state === 'settled' ? ("<span class=\"badge badge-done\">" + siteMessage('client.ops_results.settled_2') + "</span>") : ("<span class=\"badge badge-gold\">" + siteMessage('client.ops_results.reopened_2') + "</span>")) + '</td>' +
        '<td><strong>' + esc(hs.score1) + ' : ' + esc(hs.score2) + '</strong></td>' +
        '<td data-i18n-ignore>' + esc(adminLabel(hs.actor)) + '</td>' +
        '<td data-i18n-ignore>' + esc(hs.reason || '-') + '</td>' +
        '<td data-i18n-ignore>' + esc(hs.recorded_at || '-') + '</td>' +
      '</tr>';
    });
    hHtml += '</tbody></table></div>';
  } else {
    hHtml += ("<p class=\"ops-empty-inline\">" + siteMessage('client.ops_results.no_series_settlement_history_yet') + "</p>");
  }
  hHtml += '</details>';

  hHtml += ("<details class=\"ops-lineup-details\"><summary>" + siteMessage('client.ops_results.bracket_changes_and_retention_decisions_changes')) + (hist.bracket || []).length + siteMessage('client.ops_results.retained') + (hist.retained || []).length + '）</summary>';
  if ((hist.bracket || []).length) {
    hHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>" + siteMessage('client.ops_results.settlement') + "</th><th>" + siteMessage('client.ops_results.downstream_match') + "</th><th>" + siteMessage('client.ops_results.side') + "</th><th>" + siteMessage('client.ops_results.previous_new_entrant') + "</th>") +
    '</tr></thead><tbody>';
    hist.bracket.forEach(function (hb) {
      hHtml += '<tr>' +
        '<td data-i18n-ignore>#' + esc(hb.settlement_id) + '</td>' +
        '<td data-i18n-ignore>Match #' + esc(hb.target_match_id) + '</td>' +
        '<td>' + (hb.target_side === 'home' ? siteMessage('client.ops_results.home_side_2') : siteMessage('client.ops_results.away_side_2')) + '</td>' +
        '<td data-i18n-ignore>' + esc(entrantLabel(hb.previous_entrant_id)) + ' → ' + esc(entrantLabel(hb.new_entrant_id)) + '</td>' +
      '</tr>';
    });
    hHtml += '</tbody></table></div>';
  }
  if ((hist.retained || []).length) {
    hHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>Rev</th><th>" + siteMessage('client.ops_results.downstream_match_side') + "</th><th>" + siteMessage('client.ops_results.retained_entrant') + "</th><th>" + siteMessage('client.ops_results.proposed_entrant') + "</th><th>" + siteMessage('client.ops_results.actor_reason') + "</th>") +
    '</tr></thead><tbody>';
    hist.retained.forEach(function (hr) {
      hHtml += '<tr>' +
        '<td>Rev ' + esc(hr.revision) + '</td>' +
        '<td data-i18n-ignore>Match #' + esc(hr.target_match_id) + ' (' + esc(hr.target_side) + ')</td>' +
        '<td data-i18n-ignore>' + esc(entrantLabel(hr.retained_entrant_id)) + '</td>' +
        '<td data-i18n-ignore>' + esc(entrantLabel(hr.proposed_entrant_id)) + '</td>' +
        '<td data-i18n-ignore>' + esc(adminLabel(hr.actor)) + ' · ' + esc(hr.reason || '-') + '</td>' +
      '</tr>';
    });
    hHtml += '</tbody></table></div>';
  }
  if (!(hist.bracket || []).length && !(hist.retained || []).length) {
    hHtml += ("<p class=\"ops-empty-inline\">" + siteMessage('client.ops_results.no_downstream_bracket_changes_or_retention') + "</p>");
  }
  hHtml += '</details>';

  byId('opsHistoryContainer').innerHTML = hHtml;
}

/* ==================== Tab 4: 统计修订工作台 ==================== */
