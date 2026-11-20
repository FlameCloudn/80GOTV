import { message as siteMessage } from '../../shared/i18n.js';
import { MATCH_ID, apiJson, awayName, buildRetentionUI, bundle, byId, clearError, closeDialog, fmtVal, homeName, mapDisplay, openDialog, readRetentionDecisions, refreshBundle, root, showError, showFeedback, state, urls } from './context.mjs';

export function openConfirmMapModal(mapId) {
  clearError('confirmMapError');
  byId('confirmMapReload').hidden = true;
  buildRetentionUI('confirmMapRetentionBox', null);
  var mapObj = (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === mapId; });
  var rm = ((bundle.overview.results || {}).maps || []).find(function (x) { return x.scheduled_map_id === mapId; });
  if (!mapObj || !rm) return;
  var validRuns = (mapObj.runs || []).filter(function (r) { return r.status !== 'void'; });
  var settled = Boolean(bundle.overview.results && bundle.overview.results.series && bundle.overview.results.series.state === 'settled');

  state.dialogPayload.confirmMap = {
    scheduled_map_id: mapId,
    expected_revision: rm.revision || 0,
    expected_series_revision: bundle.overview.results.revision,
    settled: settled
  };

  byId('confirmMapDialogTitle').textContent =
    (rm.official_map_result_id ? siteMessage('client.ops_result-dialogs.override_official_map_result') : siteMessage('client.ops_result-dialogs.confirm_official_map_result'));
  byId('confirmMapContext').textContent =
    siteMessage('client.ops_result-dialogs.map_map_order_value3_official_rev', {map_order: rm.map_order, value3: mapDisplay(rm.map_name), value5: (rm.revision || 0)});
  byId('confirmMapScore1Label').textContent = siteMessage('client.ops_result-dialogs.value0_round_score', {value0: homeName()});
  byId('confirmMapScore2Label').textContent = siteMessage('client.ops_result-dialogs.value0_round_score', {value0: awayName()});

  var runSel = byId('confirmMapRunSelect');
  runSel.innerHTML = '';
  validRuns.forEach(function (r) {
    var opt = document.createElement('option');
    opt.value = String(r.map_run_id);
    opt.textContent = siteMessage('client.ops_result-dialogs.run_map_run_id_attempt_attempt', {map_run_id: r.map_run_id, attempt_no: r.attempt_no, status: r.status});
    runSel.appendChild(opt);
  });
  if (rm.map_run_id && validRuns.some(function (r) { return r.map_run_id === rm.map_run_id; })) {
    runSel.value = String(rm.map_run_id);
  }

  byId('confirmMapScore1').value = rm.score1 != null ? String(rm.score1) : '';
  byId('confirmMapScore2').value = rm.score2 != null ? String(rm.score2) : '';
  byId('confirmMapReason').value = '';
  refreshConfirmMapRetentionBox();
  openDialog('confirmMapDialog');
}

function refreshConfirmMapRetentionBox() {
  var payload = state.dialogPayload.confirmMap;
  if (!payload || !payload.settled) {
    byId('confirmMapRetentionBox').hidden = true;
    return;
  }
  var s1 = byId('confirmMapScore1').valueAsNumber;
  var s2 = byId('confirmMapScore2').valueAsNumber;
  var options = bundle.context.map_change_options[payload.scheduled_map_id] || {};
  var proposed = (Number.isInteger(s1) && Number.isInteger(s2) && s1 !== s2)
    ? options[s1 > s2 ? 'home' : 'away'] : null;
  buildRetentionUI('confirmMapRetentionBox', proposed);
}

export function openSeriesActionModal(mode) {
  clearError('seriesActionError');
  byId('seriesActionReload').hidden = true;
  buildRetentionUI('seriesRetentionBox', null);
  var res = bundle.overview.results || {};
  state.dialogPayload.seriesAction = { mode: mode, expected_revision: res.revision || 0 };
  var titleEl = byId('seriesActionDialogTitle');
  var warnEl = byId('seriesActionWarn');
  var submitBtn = byId('seriesActionSubmitBtn');
  var reasonLabel = byId('seriesActionReasonLabel');

  byId('seriesActionContext').textContent =
    siteMessage('client.ops_result-dialogs.value0_value2_value4_value6_value8_series', {value0: homeName(), value2: fmtVal(res.score1), value4: fmtVal(res.score2), value6: awayName(), value8: (res.bo_format || 'BO3'), value10: (res.revision || 0)});
  byId('seriesActionReason').value = '';

  if (mode === 'settle') {
    titleEl.textContent = siteMessage('client.ops_result-dialogs.settle_series');
    warnEl.className = 'ops-callout-note';
    warnEl.textContent = siteMessage('client.ops_result-dialogs.settling_records_the_final_series_result');
    reasonLabel.textContent = siteMessage('client.ops_result-dialogs.settlement_note_optional');
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = siteMessage('client.ops_result-dialogs.confirm_settlement');
    byId('seriesRetentionBox').hidden = true;
  } else {
    titleEl.textContent = siteMessage('client.ops_result-dialogs.reopen_series');
    warnEl.className = 'ops-callout-warn';
    warnEl.textContent = siteMessage('client.ops_result-dialogs.reopening_restores_the_match_to_live');
    reasonLabel.textContent = siteMessage('client.ops_result-dialogs.reopen_reason_required');
    submitBtn.className = 'btn btn-danger';
    submitBtn.textContent = siteMessage('client.ops_result-dialogs.confirm_reopen');
    buildRetentionUI('seriesRetentionBox', { winner: null, loser: null });
  }
  openDialog('seriesActionDialog');
}

export function bindResultDialogs() {
  byId('confirmMapScore1').addEventListener('input', refreshConfirmMapRetentionBox);
  byId('confirmMapScore2').addEventListener('input', refreshConfirmMapRetentionBox);
  byId('confirmMapReload').addEventListener('click', async function () {
    if (!await refreshBundle(true)) return;
    var p = state.dialogPayload.confirmMap;
    var res = bundle.overview.results;
    var map = res.maps.find(m => m.scheduled_map_id === p.scheduled_map_id);
    if (!map || map.map_run_id !== Number(byId('confirmMapRunSelect').value)) {
      showError('confirmMapError', siteMessage('client.ops_result-dialogs.the_map_run_has_changed_go'));
      return;
    }
    p.expected_revision = map.revision;
    p.settled = Boolean(res.series && res.series.state === 'settled');
    p.expected_series_revision = res.revision;
    byId('confirmMapContext').textContent = siteMessage('client.ops_result-dialogs.latest_official_result') + ' ' + fmtVal(map.score1) + ' : ' + fmtVal(map.score2) + ' · Rev ' + map.revision;
    buildRetentionUI('confirmMapRetentionBox', null);
    refreshConfirmMapRetentionBox();
    clearError('confirmMapError');
    this.hidden = true;
  });
  byId('seriesActionReload').addEventListener('click', async function () {
    if (!await refreshBundle(true)) return;
    var mode = state.dialogPayload.seriesAction.mode;
    if (!root.querySelector('[data-action="open-series-' + mode + '"]:not(:disabled)')) {
      showError('seriesActionError', siteMessage('client.ops_result-dialogs.the_series_has_changed_return_to'));
      return;
    }
    var reason = byId('seriesActionReason').value;
    openSeriesActionModal(mode);
    byId('seriesActionReason').value = reason;
  });
  byId('confirmMapForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    const submit = this.querySelector('[type="submit"]');
    if (submit.disabled) return;
    clearError('confirmMapError');
    var p = state.dialogPayload.confirmMap || {};
    var runId = Number(byId('confirmMapRunSelect').value);
    var s1 = Number(byId('confirmMapScore1').value);
    var s2 = Number(byId('confirmMapScore2').value);
    var reason = (byId('confirmMapReason').value || '').trim();
    if (!Number.isInteger(s1) || !Number.isInteger(s2) || s1 === s2) {
      showError('confirmMapError', siteMessage('client.ops_result-dialogs.round_scores_must_be_non_tied'));
      return;
    }
    var body = {
      scheduled_map_id: p.scheduled_map_id,
      map_run_id: runId,
      score1: s1,
      score2: s2,
      expected_revision: p.expected_revision,
      reason: reason
    };
    if (p.expected_series_revision != null) body.expected_series_revision = p.expected_series_revision;
    var retained = readRetentionDecisions('confirmMapRetentionBox');
    if (retained) body.retain_downstream = retained;

    submit.disabled = true;
    try {
      var r = await apiJson(urls.confirmMapUrl, { method: 'POST', json: body });
      if (!r.ok) {
        if (r.status === 409) byId('confirmMapReload').hidden = false;
        showError('confirmMapError', r.data.error || siteMessage('client.ops_result-dialogs.failed_to_save_official_map_result'));
        return;
      }
      closeDialog('confirmMapDialog');
      showFeedback(siteMessage('client.ops_result-dialogs.official_map_result_confirmed_s1_s2', {s1: s1, s2: s2}), 'success');
      await refreshBundle(true);
    } finally {
      submit.disabled = false;
    }
  });

  byId('seriesActionForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError('seriesActionError');
    var p = state.dialogPayload.seriesAction || {};
    var reason = (byId('seriesActionReason').value || '').trim();
    if (p.mode === 'reopen' && !reason) {
      showError('seriesActionError', siteMessage('client.ops_result-dialogs.enter_a_reason_for_reopening_the'));
      return;
    }
    var body = { expected_revision: p.expected_revision, reason: reason };
    if (p.mode === 'reopen') {
      var retained = readRetentionDecisions('seriesRetentionBox');
      if (retained) body.retain_downstream = retained;
    }
    var endpoint = p.mode === 'settle' ? 'settle' : 'reopen';
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/' + endpoint, { method: 'POST', json: body });
    if (!r.ok) {
      if (r.status === 409) byId('seriesActionReload').hidden = false;
      showError('seriesActionError', r.data.error || siteMessage('client.ops_result-dialogs.series_action_failed'));
      return;
    }
    closeDialog('seriesActionDialog');
    showFeedback(p.mode === 'settle' ? siteMessage('client.ops_result-dialogs.series_settled_bracket_advancement_and_predictions') : siteMessage('client.ops_result-dialogs.settlement_revoked_match_reopened_as_live'), 'success');
    await refreshBundle(true);
  });
}
