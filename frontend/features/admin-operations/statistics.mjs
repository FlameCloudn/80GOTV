import { message as siteMessage } from '../../shared/i18n.js';
import { MATCH_ID, adminLabel, apiJson, bundle, byId, clearError, esc, findRunById, fmtVal, mapDisplay, participantById, playerLabel, root, showError, showFeedback, sourceKindLabel, state } from './context.mjs';
import { FIELD_LABELS, STAT_GROUPS } from './stat-fields.mjs';

export function populateStatsSelectors() {
  var runSel = byId('statsRunSelect');
  var playerSel = byId('statsPlayerSelect');
  var runs = [];
  (bundle.overview.maps || []).forEach(function (m) {
    (m.runs || []).forEach(function (r) {
      runs.push({ map: m, run: r });
    });
  });

  runSel.innerHTML = '';
  if (!runs.length) {
    runSel.innerHTML = ("<option value=\"\">" + siteMessage('client.ops_statistics.no_map_runs_yet') + "</option>");
    playerSel.innerHTML = ("<option value=\"\">" + siteMessage('client.ops_statistics.no_players_available') + "</option>");
    byId('statsEditorArea').innerHTML = ("<p class=\"empty-state\">" + siteMessage('client.ops_statistics.record_a_map_run_and_player') + "</p>");
    byId('statsHistoryArea').innerHTML = '';
    return;
  }

  runs.forEach(function (item) {
    var opt = document.createElement('option');
    opt.value = String(item.run.map_run_id);
    opt.setAttribute('data-i18n-ignore', '');
    opt.textContent = 'Map ' + item.map.map_order + ' ' + mapDisplay(item.map.map_name) +
      ' · Run #' + item.run.map_run_id + ' (#' + item.run.attempt_no + ' · ' + item.run.status + ')';
    runSel.appendChild(opt);
  });

  if (state.statsTarget.runId && runs.some(function (x) { return x.run.map_run_id === state.statsTarget.runId; })) {
    runSel.value = String(state.statsTarget.runId);
  } else {
    var preferred = runs.find(function (x) { return x.run.status !== 'void'; }) || runs[0];
    state.statsTarget.runId = preferred.run.map_run_id;
    runSel.value = String(preferred.run.map_run_id);
  }
  populateStatsPlayers();
}

function populateStatsPlayers() {
  var runId = Number(byId('statsRunSelect').value);
  state.statsTarget.runId = runId || null;
  var playerSel = byId('statsPlayerSelect');
  playerSel.innerHTML = '';
  var info = findRunById(runId);
  var parts = (info && info.run.participations) || [];
  if (!parts.length) {
    playerSel.innerHTML = ("<option value=\"\">" + siteMessage('client.ops_statistics.no_participation_recorded_for_this_run') + "</option>");
    state.statsTarget.playerId = null;
    state.statsLoaded = null;
    state.statsPreview = null;
    renderStatsEditor();
    byId('statsRevBadge').textContent = siteMessage('client.ops_statistics.not_loaded');
    byId('statsEditorArea').innerHTML = ("<p class=\"empty-state\">" + siteMessage('client.ops_statistics.no_participated_players_recorded_for_this') + "</p>");
    byId('statsHistoryArea').innerHTML = '';
    return;
  }
  parts.forEach(function (rp) {
    var party = participantById(rp.match_participant_id);
    var opt = document.createElement('option');
    opt.value = String(rp.player_id);
    opt.setAttribute('data-i18n-ignore', '');
    opt.textContent = playerLabel(rp.player_id) +
      (party ? ' (' + party.name + ')' : '') +
      (rp.is_current ? '' : siteMessage('client.ops_statistics.withdrawn_read_only'));
    playerSel.appendChild(opt);
  });
  if (state.statsTarget.playerId && parts.some(function (rp) { return rp.player_id === state.statsTarget.playerId; })) {
    playerSel.value = String(state.statsTarget.playerId);
  } else {
    var prefP = parts.find(function (rp) { return rp.is_current; }) || parts[0];
    state.statsTarget.playerId = prefP.player_id;
    playerSel.value = String(prefP.player_id);
  }
}

export async function loadStatsTarget(preserveDraft) {
  clearError('statsInlineError');
  var runId = Number(byId('statsRunSelect').value);
  var playerId = Number(byId('statsPlayerSelect').value);
  var scope = state.statsTarget.scope || 'all';
  var requestId = ++state.statsRequest;
  var prior = state.statsLoaded;
  if (!preserveDraft || (prior && (prior.run_id !== runId || prior.player_id !== playerId || prior.scope !== scope))) {
    state.statsDraft = {};
    state.statsReason = '';
  }
  state.statsPreview = null;
  state.statsLoaded = null;
  if (!runId || !playerId) return;
  renderStatsEditor();
  byId('statsRevBadge').textContent = siteMessage('client.ops_statistics.loading');

  state.statsTarget.runId = runId;
  state.statsTarget.playerId = playerId;

  var url = '/admin/matches/' + MATCH_ID + '/operations/runs/' + runId +
    '/players/' + playerId + '/stats?scope=' + encodeURIComponent(scope) + '&history=1';
  var r = await apiJson(url, { method: 'GET' });
  if (requestId !== state.statsRequest) return;
  if (!r.ok) {
    byId('statsRevBadge').textContent = siteMessage('client.ops_statistics.not_loaded');
    showError('statsInlineError', r.data.error || siteMessage('client.ops_statistics.could_not_load_stat_fields'));
    return;
  }
  state.statsLoaded = r.data;
  renderStatsEditor();
}

function renderStatsEditor() {
  var data = state.statsLoaded;
  var badge = byId('statsRevBadge');
  var statusBanner = byId('statsStatusBanner');
  var editor = byId('statsEditorArea');
  var previewArea = byId('statsPreviewArea');
  var historyArea = byId('statsHistoryArea');

  if (!data) {
    badge.textContent = siteMessage('client.ops_statistics.not_loaded');
    statusBanner.hidden = true;
    editor.innerHTML = '';
    previewArea.hidden = true;
    historyArea.innerHTML = '';
    return;
  }

  badge.className = 'badge ' + (data.editable ? 'badge-accent' : 'badge-danger');
  badge.textContent = siteMessage(data.editable ? 'client.ops_statistics.revision_editable' : 'client.ops_statistics.revision_read_only', { revision: data.revision });

  if (!data.editable) {
    statusBanner.hidden = false;
    statusBanner.className = 'ops-status-banner is-warn';
    statusBanner.textContent = siteMessage('client.ops_statistics.read_only_run_status_run_status', {
      run_status: data.run_status,
      value3: siteMessage(data.participation_current ? 'client.ops_statistics.participation_yes' : 'client.ops_statistics.participation_no'),
    });
  } else {
    statusBanner.hidden = true;
  }

  var countSet = new Set(bundle.context.count_fields || []);
  var fields = data.fields || {};
  var sources = data.field_sources || {};

  var html = '<div class="ops-stat-groups">';
  STAT_GROUPS.forEach(function (group) {
    html += '<div class="ops-stat-group">' +
      '<h3>' + esc(group.title) + '</h3>' +
      '<div class="ops-stat-table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        ("<th>" + siteMessage('client.ops_statistics.metric') + "</th><th>" + siteMessage('client.ops_statistics.adopted_value') + "</th><th>" + siteMessage('client.ops_statistics.source') + "</th><th>" + siteMessage('client.ops_statistics.revised_value_blank_unknown') + "</th><th class=\"num\">" + siteMessage('client.ops_statistics.quick') + "</th>") +
      '</tr></thead><tbody>';

    group.fields.forEach(function (pair) {
      var key = pair[0];
      var label = pair[1];
      var currentVal = Object.prototype.hasOwnProperty.call(fields, key) ? fields[key] : null;
      var src = sources[key] || null;
      var touched = Object.prototype.hasOwnProperty.call(state.statsDraft, key);
      var draftVal = touched ? state.statsDraft[key] : currentVal;
      var inputVal = (draftVal === null || draftVal === undefined) ? '' : String(draftVal);
      var isInt = countSet.has(key);

      var srcKind = src ? (src.source || src.kind) : null;
      var srcLabel = sourceKindLabel(srcKind);
      var srcTitle = src ? [String(srcLabel), adminLabel(src.actor), src.source_ref, src.method, src.reason].filter(Boolean).join(' · ') : '';
      var srcHtml = src
        ? '<span class="badge" title="' + esc(srcTitle) + '">' + esc(srcLabel) + '</span> <small class="muted" data-i18n-ignore>Rev ' + esc(src.revision) + '</small>'
        : '<span class="muted">-</span>';

      html += '<tr class="' + (touched ? 'is-dirty-row' : '') + '" data-stat-row="' + esc(key) + '">' +
        '<td><strong>' + esc(label) + '</strong> <code class="ops-field-code" data-i18n-ignore>' + esc(key) + '</code></td>' +
        ("<td class=\"mono\"><span class=\"ops-mobile-stat-label\" aria-hidden=\"true\">" + siteMessage('client.ops_statistics.adopted_value') + "</span><strong>") + esc(fmtVal(currentVal)) + '</strong></td>' +
        ("<td><span class=\"ops-mobile-stat-label\" aria-hidden=\"true\">" + siteMessage('client.ops_statistics.source') + "</span>") + srcHtml + '</td>' +
        ("<td><span class=\"ops-mobile-stat-label\" aria-hidden=\"true\">" + siteMessage('client.ops_statistics.revised_value') + "</span>") +
          '<input type="number" class="ops-stat-input" aria-label="' + esc(String(label)) + '" data-stat-field="' + esc(key) + '" data-stat-int="' + (isInt ? '1' : '0') + '" ' +
            'step="' + (isInt ? '1' : 'any') + '" placeholder="-" value="' + esc(inputVal) + '"' + (data.editable ? '' : ' disabled') + '>' +
        '</td>' +
        '<td class="num ops-row-btns">' +
          (data.editable
            ? '<button type="button" class="btn btn-sm" data-stat-clear="' + esc(key) + ("\" title=\"" + siteMessage('client.ops_statistics.set_to_unknown') + "\">" + siteMessage('client.ops_statistics.set_to_unknown_2') + "</button>") +
              ' <button type="button" class="btn btn-sm" data-stat-reset="' + esc(key) + '"' + (touched ? '' : ' hidden') + (">" + siteMessage('client.ops_statistics.restore') + "</button>")
            : ("<span class=\"muted\">" + siteMessage('client.ops_statistics.read_only') + "</span>")) +
        '</td>' +
      '</tr>';
    });
    html += '</tbody></table></div></div>';
  });
  html += '</div>';

  if (data.editable) {
    var touchedKeys = Object.keys(state.statsDraft);
    html += '<div class="ops-stats-commit-bar">' +
      ("<div class=\"ops-stats-dirty-summary\">" + siteMessage('client.ops_statistics.modified_fields') + "<strong id=\"statsDirtyCount\">") + touchedKeys.length + ("</strong>" + siteMessage('client.ops_statistics.field_s_only_modified_fields_will') + "</div>") +
      '<label class="field">' +
        ("<span class=\"field-label\">" + siteMessage('client.ops_statistics.revision_reason_required') + "</span>") +
        '<input type="text" id="statsReasonInput" maxlength="2000" value="' + esc(state.statsReason) + ("\" placeholder=\"" + siteMessage('client.ops_statistics.for_example_corrected_after_checking_the') + "\">") +
      '</label>' +
      '<div class="ops-stats-commit-btns">' +
        ("<button type=\"button\" class=\"btn\" id=\"statsPreviewBtn\">" + siteMessage('client.ops_statistics.preview_changes') + "</button>") +
        ("<button type=\"button\" class=\"btn btn-primary\" id=\"statsApplyBtn\" disabled>" + siteMessage('client.ops_statistics.save_revision') + "</button>") +
        ("<button type=\"button\" class=\"btn\" id=\"statsResetAllBtn\">" + siteMessage('client.ops_statistics.discard_unsaved_edits') + "</button>") +
      '</div>' +
    '</div>';
  }

  editor.innerHTML = html;
  bindStatsEditorEvents();
  renderStatsPreview();
  renderStatsHistory(data.history || []);
}

function collectStatsDraftPayload() {
  var countSet = new Set(bundle.context.count_fields || []);
  var payload = {};
  var keys = Object.keys(state.statsDraft);
  for (var i = 0; i < keys.length; i += 1) {
    var key = keys[i];
    var val = state.statsDraft[key];
    var input = root.querySelector('.ops-stat-input[data-stat-field="' + key + '"]');
    if (input && !input.validity.valid) {
      throw new Error(String(FIELD_LABELS[key] || key) + ': ' + input.validationMessage);
    }
    if (val === null || val === '') {
      payload[key] = null;
    } else {
      var num = Number(val);
      if (!Number.isFinite(num)) {
        throw new Error(siteMessage('client.ops_statistics.field_value1_is_not_a_valid', {value1: (FIELD_LABELS[key] || key)}));
      }
      if (countSet.has(key) && !Number.isInteger(num)) {
        throw new Error(siteMessage('client.ops_statistics.field_value1_must_be_an_integer', {value1: (FIELD_LABELS[key] || key)}));
      }
      payload[key] = num;
    }
  }
  return payload;
}

function bindStatsEditorEvents() {
  var editor = byId('statsEditorArea');
  if (!editor || !state.statsLoaded) return;
  var currentFields = state.statsLoaded.fields || {};

  function updateDirtyVisual(key) {
    state.statsPreview = null;
    renderStatsPreview();
    var row = editor.querySelector('[data-stat-row="' + key + '"]');
    var touched = Object.prototype.hasOwnProperty.call(state.statsDraft, key);
    if (row) row.classList.toggle('is-dirty-row', touched);
    var reset = row.querySelector('[data-stat-reset]');
    if (reset) reset.hidden = !touched;
    var cnt = byId('statsDirtyCount');
    if (cnt) cnt.textContent = String(Object.keys(state.statsDraft).length);
  }

  editor.querySelectorAll('.ops-stat-input').forEach(function (inp) {
    inp.addEventListener('input', function () {
      var key = inp.dataset.statField;
      var raw = inp.value.trim();
      var nextVal = raw === '' ? null : raw;
      var origVal = Object.prototype.hasOwnProperty.call(currentFields, key) ? currentFields[key] : null;
      if (inp.validity.valid && ((origVal === null && nextVal === null) || (origVal !== null && nextVal !== null && Number(origVal) === Number(nextVal)))) {
        delete state.statsDraft[key];
      } else {
        state.statsDraft[key] = nextVal;
      }
      updateDirtyVisual(key);
    });
  });

  editor.querySelectorAll('[data-stat-clear]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var key = btn.dataset.statClear;
      var inp = editor.querySelector('.ops-stat-input[data-stat-field="' + key + '"]');
      if (inp) inp.value = '';
      var origVal = Object.prototype.hasOwnProperty.call(currentFields, key) ? currentFields[key] : null;
      if (origVal === null) delete state.statsDraft[key];
      else state.statsDraft[key] = null;
      updateDirtyVisual(key);
    });
  });

  editor.querySelectorAll('[data-stat-reset]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      delete state.statsDraft[btn.dataset.statReset];
      state.statsPreview = null;
      renderStatsEditor();
    });
  });

  var previewBtn = byId('statsPreviewBtn');
  var reasonInput = byId('statsReasonInput');
  if (reasonInput) reasonInput.addEventListener('input', function () { state.statsReason = reasonInput.value; });
  if (previewBtn) previewBtn.addEventListener('click', handleStatsPreview);
  var applyBtn = byId('statsApplyBtn');
  if (applyBtn) applyBtn.addEventListener('click', handleStatsApply);
  var resetAllBtn = byId('statsResetAllBtn');
  if (resetAllBtn) {
    resetAllBtn.addEventListener('click', function () {
      state.statsDraft = {};
      state.statsPreview = null;
      renderStatsEditor();
    });
  }
}

function renderStatsPreview() {
  var box = byId('statsPreviewArea');
  var p = state.statsPreview;
  var save = byId('statsApplyBtn');
  if (save) save.disabled = !p || !Object.keys(p.changes).length;
  if (!p) {
    box.hidden = true;
    box.innerHTML = '';
    return;
  }
  box.hidden = false;
  var changes = p.changes || {};
  var conflicts = p.conflicts || {};
  var keys = Object.keys(changes);

  var html = '<div class="ops-subcard ops-preview-box">' +
    ("<div class=\"ops-subcard-head\"><strong>" + siteMessage('client.ops_statistics.change_preview_run_rev')) + esc(p.revision) + '）</strong>' +
    (p.status === 'stale' ? ("<span class=\"badge badge-danger\">" + siteMessage('client.ops_statistics.revision_is_out_of_date') + "</span>") : '<span class="badge badge-accent">' + keys.length + (siteMessage('client.ops_statistics.changes') + "</span>")) +
    '</div>';

  if (!keys.length) {
    html += ("<p class=\"muted\">" + siteMessage('client.ops_statistics.values_match_current_adopted_stats_no') + "</p>");
  } else {
    html += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>" + siteMessage('client.ops_statistics.field') + "</th><th>" + siteMessage('client.ops_statistics.before') + "</th><th>" + siteMessage('client.ops_statistics.after') + "</th><th>" + siteMessage('client.ops_statistics.note') + "</th>") +
    '</tr></thead><tbody>';
    keys.forEach(function (k) {
      var ch = changes[k];
      var isConf = Object.prototype.hasOwnProperty.call(conflicts, k) || ch.before != null;
      html += '<tr class="' + (isConf ? 'is-conflict-row' : '') + '">' +
        '<td><strong>' + esc(FIELD_LABELS[k] || k) + '</strong> <code data-i18n-ignore>' + esc(k) + '</code></td>' +
        '<td class="mono">' + esc(fmtVal(ch.before)) + '</td>' +
        '<td class="mono"><strong>' + esc(fmtVal(ch.after)) + '</strong></td>' +
        '<td>' + (isConf ? ("<span class=\"badge badge-gold\">" + siteMessage('client.ops_statistics.overwrites_existing_value') + "</span>") : ("<span class=\"badge badge-accent\">" + siteMessage('client.ops_statistics.fills_unknown_regular_update') + "</span>")) + '</td>' +
      '</tr>';
    });
    html += '</tbody></table></div>';
  }
  html += '</div>';
  box.innerHTML = html;
}

function renderStatsHistory(history) {
  var area = byId('statsHistoryArea');
  if (!history.length) {
    area.innerHTML = ("<details class=\"ops-lineup-details\"><summary>" + siteMessage('client.ops_statistics.field_revision_history_0') + "</summary><p class=\"ops-empty-inline\">" + siteMessage('client.ops_statistics.no_stat_revisions_for_this_player') + "</p></details>");
    return;
  }
  var html = ("<details class=\"ops-lineup-details\"><summary>" + siteMessage('client.ops_statistics.field_revision_history')) + history.length + (siteMessage('client.ops_statistics.label') + "</summary>") +
    '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      ("<th>Rev</th><th>" + siteMessage('client.ops_statistics.source_actor') + "</th><th>" + siteMessage('client.ops_statistics.changed_fields') + "</th><th>" + siteMessage('client.ops_statistics.reason') + "</th><th>" + siteMessage('client.ops_statistics.time') + "</th>") +
    '</tr></thead><tbody>';
  history.forEach(function (h) {
    var parts = [];
    Object.keys(h.changes || {}).forEach(function (k) {
      var c = h.changes[k];
      parts.push(String(FIELD_LABELS[k] || k) + ': ' + fmtVal(c.before) + ' → ' + fmtVal(c.after));
    });
    html += '<tr>' +
      '<td>Rev ' + esc(h.revision) + '</td>' +
      '<td>' + esc(String(sourceKindLabel(h.source))) + ' / <span data-i18n-ignore>' + esc(adminLabel(h.actor)) + '</span></td>' +
      '<td class="mono" data-i18n-ignore>' + esc(parts.join('；') || '-') + '</td>' +
      '<td data-i18n-ignore>' + esc(h.reason || '-') + '</td>' +
      '<td data-i18n-ignore>' + esc(h.created_at || '-') + '</td>' +
    '</tr>';
  });
  html += '</tbody></table></div></details>';
  area.innerHTML = html;
}

async function handleStatsPreview() {
  clearError('statsInlineError');
  if (!state.statsLoaded) return;
  var fieldsPayload;
  try {
    fieldsPayload = collectStatsDraftPayload();
  } catch (err) {
    showError('statsInlineError', err.message);
    return;
  }
  if (!Object.keys(fieldsPayload).length) {
    showError('statsInlineError', siteMessage('client.ops_statistics.modify_at_least_one_field_before'));
    return;
  }
  var target = state.statsLoaded;
  var draft = JSON.stringify(state.statsDraft);
  var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/preview-stats', {
    method: 'POST',
    json: {
      map_run_id: state.statsTarget.runId,
      player_id: state.statsTarget.playerId,
      scope: state.statsTarget.scope,
      fields: fieldsPayload,
      expected_revision: state.statsLoaded.revision,
      reason: ((byId('statsReasonInput') || {}).value || '').trim()
    }
  });
  if (target !== state.statsLoaded || draft !== JSON.stringify(state.statsDraft)) return;
  if (!r.ok) {
    if (r.status === 409 && r.data && r.data.status === 'stale') {
      await loadStatsTarget(true);
      showError('statsInlineError', siteMessage('client.ops_statistics.stats_have_changed_your_edits_and'));
      return;
    }
    showError('statsInlineError', r.data.error || siteMessage('client.ops_statistics.could_not_preview_changes'));
    return;
  }
  state.statsPreview = r.data;
  renderStatsPreview();
}

async function handleStatsApply() {
  clearError('statsInlineError');
  if (!state.statsLoaded || !state.statsPreview) return;
  var target = state.statsLoaded;
  var reason = ((byId('statsReasonInput') || {}).value || '').trim();
  if (!reason) {
    showError('statsInlineError', siteMessage('client.ops_statistics.enter_a_revision_reason'));
    return;
  }
  var fieldsPayload;
  try {
    fieldsPayload = collectStatsDraftPayload();
  } catch (err) {
    showError('statsInlineError', err.message);
    return;
  }
  if (!Object.keys(fieldsPayload).length) {
    showError('statsInlineError', siteMessage('client.ops_statistics.no_modified_fields_to_submit'));
    return;
  }
  byId('statsApplyBtn').disabled = true;
  var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/stats', {
    method: 'POST',
    json: {
      map_run_id: state.statsTarget.runId,
      player_id: state.statsTarget.playerId,
      scope: state.statsTarget.scope,
      fields: fieldsPayload,
      expected_revision: state.statsLoaded.revision,
      reason: reason
    }
  });
  if (state.statsLoaded !== target) return;
  if (!r.ok) {
    if (r.status === 409 && r.data.status === 'stale') {
      await loadStatsTarget(true);
      showError('statsInlineError', siteMessage('client.ops_statistics.stats_have_changed_your_edits_and'));
      return;
    }
    renderStatsPreview();
    showError('statsInlineError', r.data.error || siteMessage('client.ops_statistics.could_not_save_revision'));
    return;
  }
  showFeedback(siteMessage('client.ops_statistics.stats_revision_saved_run_rev_revision', {revision: r.data.revision}), 'success');
  await loadStatsTarget(false);
}

/* ==================== 下游保护槽位保留裁定 UI 构建 ==================== */
export function bindStatistics() {
  // Stats toolbar events
  byId('statsRunSelect').addEventListener('change', function () {
    populateStatsPlayers();
    loadStatsTarget(false);
  });
  byId('statsPlayerSelect').addEventListener('change', function () {
    loadStatsTarget(false);
  });
  root.querySelectorAll('[data-stats-scope]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      state.statsTarget.scope = btn.dataset.statsScope;
      root.querySelectorAll('[data-stats-scope]').forEach(function (b) {
        var active = b.dataset.statsScope === state.statsTarget.scope;
        b.classList.toggle('active', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      loadStatsTarget(false);
    });
  });
  byId('statsReloadBtn').addEventListener('click', function () {
    loadStatsTarget(true);
  });
}
