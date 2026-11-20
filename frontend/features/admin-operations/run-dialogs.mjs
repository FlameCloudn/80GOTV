import { message as siteMessage } from '../../shared/i18n.js';
import { MATCH_ID, apiJson, buildRetentionUI, bundle, byId, clearError, closeDialog, esc, findRunById, fmtVal, mapDisplay, openDialog, participantById, playerLabel, readRetentionDecisions, refreshBundle, root, showError, showFeedback, state } from './context.mjs';
import { FIELD_LABELS } from './stat-fields.mjs';

export function openStartRunModal(mapId, prevRunId) {
  clearError('startRunError');
  var mapObj = (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === mapId; });
  if (!mapObj) return;
  state.dialogPayload.startRun = { scheduled_map_id: mapId, previous_map_run_id: prevRunId || null };
  byId('startRunDialogTitle').textContent =
    (prevRunId ? siteMessage('client.ops_run-dialogs.start_rematch_run') : siteMessage('client.ops_run-dialogs.record_map_run'));
  byId('startRunContext').textContent =
    siteMessage('client.ops_run-dialogs.map_map_order_value3_scheduledmap_mapid', {map_order: mapObj.map_order, value3: mapDisplay(mapObj.map_name), mapid: mapId});
  var note = byId('startRunReplayNote');
  if (prevRunId) {
    note.hidden = false;
    note.textContent = siteMessage('client.ops_run-dialogs.start_a_new_run_after_voided', {prevrunid: prevRunId, value3: prevRunId});
  } else {
    note.hidden = true;
  }
  byId('startRunEvidence').value = '';
  openDialog('startRunDialog');
}

export function openBindDirectorModal(runId, mapId) {
  clearError('bindDirectorError');
  state.dialogPayload.bindDirector = { map_run_id: runId, scheduled_map_id: mapId };
  byId('bindDirectorContext').textContent = 'Run #' + runId + ' (ScheduledMap #' + mapId + ')';
  byId('bindDirectorSessionId').value = '';
  byId('bindDirectorReason').value = '';
  openDialog('bindDirectorDialog');
}

export async function openDirectorReceiptsModal(runId) {
  var body = byId('directorReceiptsBody');
  body.innerHTML = ("<p class=\"muted\">" + siteMessage('client.ops_run-dialogs.loading_director_receipts') + "</p>");
  openDialog('directorReceiptsDialog');
  var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/runs/' + runId + '/director-receipts', { method: 'GET' });
  if (!r.ok) {
    body.innerHTML = '<p class="ops-err-text">' + esc(r.data.error || siteMessage('client.ops_run-dialogs.failed_to_load_director_receipts')) + '</p>';
    return;
  }
  var receipts = r.data.receipts || [];
  if (!receipts.length) {
    body.innerHTML = '<p class="empty-state">Run #' + esc(runId) + (siteMessage('client.ops_run-dialogs.no_final_map_receipt_from_the') + "</p>");
    return;
  }
  var html = '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
    ("<th>" + siteMessage('client.ops_run-dialogs.receipt_id') + "</th><th>" + siteMessage('client.ops_run-dialogs.director_session') + "</th><th>" + siteMessage('client.ops_run-dialogs.frame_seq') + "</th><th>" + siteMessage('client.ops_run-dialogs.received_at') + "</th><th>" + siteMessage('client.ops_run-dialogs.candidate_players') + "</th>") +
  '</tr></thead><tbody>';
  receipts.forEach(function (rc) {
    var pCount = Array.isArray(rc.players_candidate) ? rc.players_candidate.length
      : (rc.players_candidate && typeof rc.players_candidate === 'object' ? Object.keys(rc.players_candidate).length : 0);
    html += '<tr>' +
      '<td class="mono" data-i18n-ignore>' + esc(rc.result_id) + '</td>' +
      '<td class="mono" data-i18n-ignore>' + esc(rc.session_id || '-') + '</td>' +
      '<td class="mono">' + esc(fmtVal(rc.frame_seq)) + '</td>' +
      '<td data-i18n-ignore>' + esc(rc.received_at || '-') + '</td>' +
      '<td>' + esc(pCount) + '</td>' +
    '</tr>';
    if (rc.statistics && rc.statistics.length) {
      html += ("<tr><td colspan=\"5\"><details><summary>" + siteMessage('client.ops_run-dialogs.reported_player_stats') + "</summary><ul class=\"ops-simple-list\">");
      rc.statistics.forEach(function (item) {
        var applied = item.applied_fields.map(key => String(FIELD_LABELS[key] || key));
        html += '<li><strong data-i18n-ignore>' + esc(playerLabel(item.player_id)) + '</strong> · ' +
          ("<span>" + siteMessage('client.ops_run-dialogs.added') + "</span>：") + esc(applied.join(', ') || '-');
        Object.entries(item.conflicts).forEach(function (entry) {
          var diff = entry[1];
          html += ' · <span>' + esc(FIELD_LABELS[entry[0]] || entry[0]) + '</span>：' +
            ("<span>" + siteMessage('client.ops_run-dialogs.kept_value') + "</span> ") + esc(fmtVal(diff.current)) + (" / <span>" + siteMessage('client.ops_run-dialogs.director_reported') + "</span> ") + esc(fmtVal(diff.reported));
        });
        if (item.status === 'participation_protected') html += (" · <span>" + siteMessage('client.ops_run-dialogs.participation_withdrawn') + "</span>");
        if (item.status === 'participation_unproven') html += (" · <span>" + siteMessage('client.ops_run-dialogs.participation_not_established') + "</span>");
        html += '</li>';
      });
      html += '</ul></details></td></tr>';
    }
  });
  html += '</tbody></table></div>';
  body.innerHTML = html;
}

export function openRecordParticipationModal(runId, prePlayerId, prePartyId) {
  clearError('recordPartError');
  var info = findRunById(runId);
  if (!info) return;
  state.dialogPayload.recordPart = { map_run_id: runId };
  byId('recordPartContext').textContent =
    siteMessage('client.ops_run-dialogs.map_map_order_value3_run_runid', {map_order: info.map.map_order, value3: mapDisplay(info.map.map_name), runid: runId});
  var sel = byId('recordPartPlayerSelect');
  sel.innerHTML = '';
  (info.run.lineup || []).forEach(function (lp) {
    var party = participantById(lp.match_participant_id);
    var opt = document.createElement('option');
    opt.value = lp.player_id + ':' + lp.match_participant_id;
    opt.textContent = (party ? '[' + party.name + '] ' : '') + playerLabel(lp.player_id);
    sel.appendChild(opt);
  });
  if (prePlayerId && prePartyId) {
    sel.value = prePlayerId + ':' + prePartyId;
  }
  byId('recordPartRound').value = '';
  byId('recordPartSide').value = '';
  byId('recordPartReason').value = '';
  openDialog('recordPartDialog');
}

export function openBatchParticipationModal(runId) {
  clearError('batchPartError');
  var info = findRunById(runId);
  if (!info) return;
  state.dialogPayload.batchPart = { map_run_id: runId };
  byId('batchPartContext').textContent =
    siteMessage('client.ops_run-dialogs.map_map_order', {map_order: info.map.map_order}) + ' ' + mapDisplay(info.map.map_name) + ' · ' + siteMessage('client.ops_run-dialogs.map_run') + ' #' + runId;
  var partByPlayer = {};
  (info.run.participations || []).forEach(function (rp) {
    partByPlayer[rp.player_id] = rp;
  });
  var listEl = byId('batchPartPlayerList');
  listEl.innerHTML = bundle.context.participants.map(function (party) {
    var players = info.run.lineup.filter(function (lp) {
      return lp.match_participant_id === party.match_participant_id && !partByPlayer[lp.player_id];
    });
    if (!players.length) return '';
    return '<fieldset class="batch-part-team"><legend data-i18n-ignore>' + esc(party.name) + '</legend>' +
      players.map(function (lp) {
        return '<label class="check-row"><input type="checkbox" class="batch-part-cb" value="' + esc(lp.player_id + ':' + lp.match_participant_id) +
          '"><span data-i18n-ignore>' + esc(playerLabel(lp.player_id)) + '</span></label>';
      }).join('') + '</fieldset>';
  }).join('');
  byId('batchPartReason').value = '';
  syncBatchSelection();
  openDialog('batchPartDialog');
}

function syncBatchSelection() {
  var choices = root.querySelectorAll('#batchPartPlayerList input');
  var count = Array.from(choices).filter(function (cb) { return cb.checked; }).length;
  var all = byId('batchPartAll');
  all.checked = count > 0 && count === choices.length;
  all.indeterminate = count > 0 && count < choices.length;
  byId('batchPartSubmitBtn').disabled = !count || !byId('batchPartReason').value.trim();
}

export function openReviewParticipationModal(partId, present, rev, playerName) {
  clearError('reviewPartError');
  state.dialogPayload.reviewPart = { participation_id: partId, present: present, expected_revision: rev };
  byId('reviewPartDialogTitle').textContent = (present ? siteMessage('client.ops_run-dialogs.restore_participation') : siteMessage('client.ops_run-dialogs.withdraw_participation'));
  byId('reviewPartContext').textContent =
    siteMessage('client.ops_run-dialogs.playername_participation_partid_rev_rev', {playername: playerName, partid: partId, rev: rev});
  byId('reviewPartSubmitBtn').textContent = (present ? siteMessage('client.ops_run-dialogs.confirm_restoration') : siteMessage('client.ops_run-dialogs.confirm_withdrawal'));
  byId('reviewPartReason').value = '';
  openDialog('reviewPartDialog');
}

export function openTechReplayModal(runId, mapId) {
  clearError('techReplayError');
  byId('techReplayReload').hidden = true;
  buildRetentionUI('techReplayRetentionBox', null);
  var info = findRunById(runId);
  if (!info) return;
  var mapRes = ((bundle.overview.results || {}).maps || []).find(function (rm) {
    return rm.scheduled_map_id === mapId;
  }) || null;
  var seriesRev = (bundle.overview.results || {}).revision || 0;
  var settled = Boolean(bundle.overview.results && bundle.overview.results.series && bundle.overview.results.series.state === 'settled');

  state.dialogPayload.techReplay = {
    map_run_id: runId,
    scheduled_map_id: mapId,
    expected_revision: mapRes ? mapRes.revision : 0,
    expected_series_revision: seriesRev
  };

  byId('techReplayContext').textContent =
    siteMessage('client.ops_run-dialogs.map_map_order_value3_run_runid_2', {map_order: info.map.map_order, value3: mapDisplay(info.map.map_name), runid: runId, attempt_no: info.run.attempt_no});
  byId('techReplayReason').value = '';
  var toggle = byId('techReplaySubToggle');
  toggle.checked = false;
  byId('techReplaySubFields').hidden = true;

  // Populate outgoing from effective_roster
  var outSel = byId('techReplayOutgoing');
  outSel.innerHTML = '';
  (info.map.effective_roster || []).forEach(function (ep) {
    var party = participantById(ep.match_participant_id);
    var opt = document.createElement('option');
    opt.value = String(ep.player_id);
    opt.dataset.entrantId = String(ep.event_entrant_id);
    opt.dataset.partyId = String(ep.match_participant_id);
    opt.setAttribute('data-i18n-ignore', '');
    opt.textContent = (party ? '[' + party.name + '] ' : '') + playerLabel(ep.player_id);
    outSel.appendChild(opt);
  });
  updateTechReplayIncomingOptions(info.map);

  if (settled) {
    buildRetentionUI('techReplayRetentionBox', { winner: null, loser: null });
  } else {
    byId('techReplayRetentionBox').hidden = true;
  }
  openDialog('techReplayDialog');
}

function updateTechReplayIncomingOptions(mapObj, reviewedSelection) {
  var outSel = byId('techReplayOutgoing');
  var inSel = byId('techReplayIncoming');
  var checkBox = byId('techReplaySubCheck');
  var opt = outSel.selectedOptions[0];
  var previous = inSel.value;
  inSel.innerHTML = '';
  if (!opt) {
    checkBox.textContent = '';
    return;
  }
  var outgoingId = Number(opt.value);
  var entrantId = Number(opt.dataset.entrantId);
  var partyId = Number(opt.dataset.partyId);
  var eff = mapObj.effective_roster || [];
  var activeIds = new Set(eff.map(function (x) { return x.player_id; }));
  var side = (bundle.context.participants || []).find(function (p) { return p.event_entrant_id === entrantId; });
  var reserves = ((side && side.assigned_reserves) || []).filter(function (r) {
    return !activeIds.has(r.player_id);
  });

  if (!reserves.length) {
    inSel.innerHTML = ("<option value=\"\">" + siteMessage('client.ops_run-dialogs.no_eligible_assigned_reserves_for_this') + "</option>");
    checkBox.className = 'ops-sub-check is-warn';
    checkBox.textContent = siteMessage('client.ops_run-dialogs.no_eligible_assigned_reserves_found_for');
    return;
  }
  reserves.forEach(function (r) {
    var o = document.createElement('option');
    o.value = String(r.player_id);
    o.setAttribute('data-i18n-ignore', '');
    o.textContent = r.nickname + (r.steam_id ? ' (' + r.steam_id + ')' : siteMessage('client.ops_run-dialogs.no_steam_id'));
    inSel.appendChild(o);
  });
  if (reviewedSelection !== undefined) inSel.value = reviewedSelection;
  else if (reserves.some(function (r) { return String(r.player_id) === previous; })) inSel.value = previous;

  // Live >= 3 Initial Roster preview
  var initialSet = new Set((side && side.initial_player_ids) || []);
  var incomingId = Number(inSel.value);
  var sidePlayers = eff.filter(function (x) { return x.match_participant_id === partyId; }).map(function (x) {
    return x.player_id === outgoingId ? incomingId : x.player_id;
  });
  var kept = sidePlayers.filter(function (pid) { return initialSet.has(pid); }).length;
  checkBox.className = 'ops-sub-check ' + (kept >= 3 ? 'is-ok' : 'is-warn');
  checkBox.textContent = siteMessage(kept >= 3 ? 'client.ops_run-dialogs.initial_members_eligible' : 'client.ops_run-dialogs.initial_members_below_minimum', { count: kept });
}

export function bindRunDialogs() {
  // Tech replay sub toggle & select change
  byId('techReplaySubToggle').addEventListener('change', function (e) {
    byId('techReplaySubFields').hidden = !e.target.checked;
  });
  byId('techReplayOutgoing').addEventListener('change', function () {
    var p = state.dialogPayload.techReplay;
    var mapObj = p && (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === p.scheduled_map_id; });
    if (mapObj) updateTechReplayIncomingOptions(mapObj);
  });
  byId('techReplayIncoming').addEventListener('change', function () {
    var p = state.dialogPayload.techReplay;
    var mapObj = p && (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === p.scheduled_map_id; });
    if (mapObj) updateTechReplayIncomingOptions(mapObj);
  });
  byId('techReplayReload').addEventListener('click', async function () {
    if (!await refreshBundle(true)) return;
    var p = state.dialogPayload.techReplay;
    if (!root.querySelector('[data-action="open-tech-replay"][data-run-id="' + p.map_run_id + '"]')) {
      showError('techReplayError', siteMessage('client.ops_run-dialogs.the_map_run_has_changed_go'));
      return;
    }
    var reason = byId('techReplayReason').value;
    var withSub = byId('techReplaySubToggle').checked;
    var out = byId('techReplayOutgoing').value;
    var incoming = byId('techReplayIncoming').value;
    openTechReplayModal(p.map_run_id, p.scheduled_map_id);
    byId('techReplayReason').value = reason;
    if (withSub) {
      byId('techReplaySubToggle').checked = true;
      byId('techReplaySubFields').hidden = false;
      byId('techReplayOutgoing').value = out;
      updateTechReplayIncomingOptions(findRunById(p.map_run_id).map, incoming);
    }
    var map = bundle.overview.results.maps.find(m => m.scheduled_map_id === p.scheduled_map_id);
    byId('techReplayContext').textContent += ' · ' + siteMessage('client.ops_run-dialogs.latest_official_result') + ' ' +
      fmtVal(map.score1) + ' : ' + fmtVal(map.score2) + ' · Rev ' + map.revision;
  });
  byId('startRunForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError('startRunError');
    var p = state.dialogPayload.startRun || {};
    var evidence = (byId('startRunEvidence').value || '').trim();
    if (!evidence) {
      showError('startRunError', siteMessage('client.ops_run-dialogs.enter_start_evidence'));
      return;
    }
    var body = { scheduled_map_id: p.scheduled_map_id, evidence: evidence };
    if (p.previous_map_run_id) body.previous_map_run_id = p.previous_map_run_id;
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/start', { method: 'POST', json: body });
    if (!r.ok) {
      showError('startRunError', r.data.error || siteMessage('client.ops_run-dialogs.failed_to_start_map_run'));
      return;
    }
    closeDialog('startRunDialog');
    showFeedback(siteMessage('client.ops_run-dialogs.map_run_recorded_run_map_run', {map_run_id: r.data.map_run_id}), 'success');
    await refreshBundle(true);
  });

  byId('bindDirectorForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError('bindDirectorError');
    var p = state.dialogPayload.bindDirector || {};
    var sessionId = (byId('bindDirectorSessionId').value || '').trim();
    var reason = (byId('bindDirectorReason').value || '').trim();
    if (!sessionId || !reason) {
      showError('bindDirectorError', siteMessage('client.ops_run-dialogs.enter_both_session_id_and_verification'));
      return;
    }
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/bind-director-session', {
      method: 'POST',
      json: { map_run_id: p.map_run_id, session_id: sessionId, reason: reason }
    });
    if (!r.ok) {
      showError('bindDirectorError', r.data.error || siteMessage('client.ops_run-dialogs.failed_to_bind_director_session'));
      return;
    }
    closeDialog('bindDirectorDialog');
    showFeedback(siteMessage('client.ops_run-dialogs.director_session_sessionid_linked_to_run', {sessionid: sessionId, map_run_id: p.map_run_id}), 'success');
    await refreshBundle(true);
  });

  byId('recordPartForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError('recordPartError');
    var p = state.dialogPayload.recordPart || {};
    var pair = (byId('recordPartPlayerSelect').value || '').split(':');
    var reason = (byId('recordPartReason').value || '').trim();
    var roundRaw = (byId('recordPartRound').value || '').trim();
    var sideVal = byId('recordPartSide').value;
    if (pair.length !== 2 || !reason) {
      showError('recordPartError', siteMessage('client.ops_run-dialogs.select_a_player_and_enter_a'));
      return;
    }
    var body = {
      map_run_id: p.map_run_id,
      player_id: Number(pair[0]),
      match_participant_id: Number(pair[1]),
      reason: reason
    };
    if (roundRaw !== '') {
      body.round_number = Number(roundRaw);
      if (sideVal) body.side = sideVal;
    }
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/participation', { method: 'POST', json: body });
    if (!r.ok) {
      showError('recordPartError', r.data.error || siteMessage('client.ops_run-dialogs.failed_to_record_participation'));
      return;
    }
    closeDialog('recordPartDialog');
    showFeedback(siteMessage('client.ops_run-dialogs.participation_recorded_participation_id', {participation_id: r.data.participation_id}), 'success');
    await refreshBundle(true);
  });

  var batchPartForm = byId('batchPartForm');
  if (batchPartForm) {
    var batchFields = byId('batchPartFields');
    var batchClose = batchPartForm.querySelectorAll('[data-close-dialog]');
    byId('batchPartDialog').addEventListener('cancel', function (e) {
      if (batchFields.disabled) e.preventDefault();
    });
    batchPartForm.addEventListener('input', function (e) {
      if (e.target.id === 'batchPartAll') {
        batchPartForm.querySelectorAll('.batch-part-cb').forEach(function (cb) { cb.checked = e.target.checked; });
      }
      syncBatchSelection();
    });
    batchPartForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      if (batchFields.disabled) return;
      clearError('batchPartError');
      var p = state.dialogPayload.batchPart || {};
      var reason = (byId('batchPartReason').value || '').trim();
      var checked = Array.from(root.querySelectorAll('#batchPartPlayerList .batch-part-cb:checked'));
      if (!checked.length || !reason) {
        return;
      }
      var submitBtn = byId('batchPartSubmitBtn');
      submitBtn.disabled = true;
      submitBtn.textContent = siteMessage('client.ops_run-dialogs.submitting');
      batchFields.disabled = true;
      batchClose.forEach(function (btn) { btn.disabled = true; });
      try {
        for (var i = 0; i < checked.length; i++) {
          var pair = (checked[i].value || '').split(':');
          var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/participation', {
            method: 'POST',
            json: {
              map_run_id: p.map_run_id,
              player_id: Number(pair[0]),
              match_participant_id: Number(pair[1]),
              reason: reason
            }
          });
          if (!r.ok) {
            var message = (r.data.error || siteMessage('client.ops_run-dialogs.could_not_record_the_selected_appearances'));
            if (i) message = siteMessage('client.ops_run-dialogs.recorded_i_appearances', {i: i}) + ' ' + message;
            showError('batchPartError', message);
            await refreshBundle(true);
            return;
          }
          var team = checked[i].closest('fieldset');
          checked[i].closest('label').remove();
          if (!team.querySelector('input')) team.remove();
        }
        closeDialog('batchPartDialog');
        showFeedback(siteMessage('client.ops_run-dialogs.recorded_length_appearances', {length: checked.length}), 'success');
        await refreshBundle(true);
      } finally {
        batchFields.disabled = false;
        submitBtn.textContent = siteMessage('client.ops_run-dialogs.confirm_participation');
        batchClose.forEach(function (btn) { btn.disabled = false; });
        syncBatchSelection();
      }
    });
  }

  byId('reviewPartForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError('reviewPartError');
    var p = state.dialogPayload.reviewPart || {};
    var reason = (byId('reviewPartReason').value || '').trim();
    if (!reason) {
      showError('reviewPartError', siteMessage('client.ops_run-dialogs.enter_a_reason'));
      return;
    }
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/review-participation', {
      method: 'POST',
      json: {
        participation_id: p.participation_id,
        present: p.present,
        expected_revision: p.expected_revision,
        reason: reason
      }
    });
    if (!r.ok) {
      showError('reviewPartError', r.data.error || siteMessage('client.ops_run-dialogs.failed_to_update_participation'));
      return;
    }
    closeDialog('reviewPartDialog');
    showFeedback(p.present ? siteMessage('client.ops_run-dialogs.player_participation_restored') : siteMessage('client.ops_run-dialogs.player_participation_withdrawn'), 'success');
    await refreshBundle(true);
  });

  byId('techReplayForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError('techReplayError');
    var p = state.dialogPayload.techReplay || {};
    var reason = (byId('techReplayReason').value || '').trim();
    if (!reason) {
      showError('techReplayError', siteMessage('client.ops_run-dialogs.enter_the_fault_reason'));
      return;
    }
    var body = { map_run_id: p.map_run_id, reason: reason };
    if (p.expected_revision != null) body.expected_revision = p.expected_revision;
    if (p.expected_series_revision != null) body.expected_series_revision = p.expected_series_revision;

    if (byId('techReplaySubToggle').checked) {
      var outId = Number(byId('techReplayOutgoing').value);
      var inId = Number(byId('techReplayIncoming').value);
      if (!outId || !inId) {
        showError('techReplayError', siteMessage('client.ops_run-dialogs.select_a_valid_outgoing_player_and'));
        return;
      }
      body.outgoing_player_id = outId;
      body.incoming_player_id = inId;
    }
    var retained = readRetentionDecisions('techReplayRetentionBox');
    if (retained) body.retain_downstream = retained;

    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/technical-replay', { method: 'POST', json: body });
    if (!r.ok) {
      if (r.status === 409) byId('techReplayReload').hidden = false;
      showError('techReplayError', r.data.error || siteMessage('client.ops_run-dialogs.failed_to_approve_technical_rematch'));
      return;
    }
    closeDialog('techReplayDialog');
    showFeedback(siteMessage('client.ops_run-dialogs.technical_rematch_approved_run_void_map', {void_map_run_id: r.data.void_map_run_id}), 'success');
    await refreshBundle(true);
  });
}
