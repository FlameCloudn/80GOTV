import { message as siteMessage } from '../../shared/i18n.js';
import { CSRF, MATCH_ID, adminLabel, apiJson, bundle, byId, clearError, esc, fmtBytes, fmtVal, mapDisplay, participantById, playerLabel, refreshBundle, runStatusBadge, showError, showFeedback, state } from './context.mjs';
import { FIELD_LABELS } from './stat-fields.mjs';

export function populateDemoUploadSelectors() {
  var mapSel = byId('demoUploadMapSelect');
  var runSel = byId('demoUploadRunSelect');
  var maps = bundle.overview.maps || [];
  var prevMap = mapSel.value;
  mapSel.innerHTML = '';
  if (!maps.length) {
    mapSel.innerHTML = ("<option value=\"\">" + siteMessage('client.ops_demos.no_scheduled_maps') + "</option>");
    runSel.innerHTML = ("<option value=\"\">" + siteMessage('client.ops_demos.no_recorded_map_runs') + "</option>");
    byId('demoUploadSubmitBtn').disabled = true;
    return;
  }
  maps.forEach(function (m) {
    var opt = document.createElement('option');
    opt.value = String(m.scheduled_map_id);
    opt.textContent = siteMessage('client.ops_demos.map_map_order_value3_scheduled_map', {map_order: m.map_order, value3: mapDisplay(m.map_name), scheduled_map_id: m.scheduled_map_id});
    mapSel.appendChild(opt);
  });
  if (prevMap && maps.some(function (m) { return String(m.scheduled_map_id) === prevMap; })) {
    mapSel.value = prevMap;
  }
  updateDemoUploadRuns();
}

function updateDemoUploadRuns() {
  var mapId = Number(byId('demoUploadMapSelect').value);
  var runSel = byId('demoUploadRunSelect');
  var btn = byId('demoUploadSubmitBtn');
  var mapObj = (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === mapId; });
  var runs = (mapObj && mapObj.runs) || [];
  runSel.innerHTML = '';
  if (!runs.length) {
    runSel.innerHTML = ("<option value=\"\">" + siteMessage('client.ops_demos.record_a_map_run_before_uploading') + "</option>");
    btn.disabled = true;
    return;
  }
  btn.disabled = false;
  runs.forEach(function (r) {
    var opt = document.createElement('option');
    opt.value = String(r.map_run_id);
    var suffix = r.status === 'void' ? siteMessage('client.ops_demos.void_archive_only') : ' [' + r.status + ']';
    opt.textContent = 'Run #' + r.map_run_id + ' · ' + siteMessage('client.ops_demos.attempt_attempt_no', {attempt_no: r.attempt_no}) + suffix;
    runSel.appendChild(opt);
  });
  var preferred = runs.find(function (r) { return r.status !== 'void'; }) || runs[runs.length - 1];
  if (preferred) runSel.value = String(preferred.map_run_id);
}

export function renderDemosList() {
  var originals = bundle.originals || [];
  var box = byId('opsDemosList');
  if (!originals.length) {
    box.innerHTML = ("<p class=\"empty-state\">" + siteMessage('client.ops_demos.no_demo_originals_uploaded_for_this') + "</p>");
    return;
  }
  var html = '<div class="table-wrap"><table class="table"><thead><tr>' +
    ("<th>Demo #</th><th>" + siteMessage('client.ops_demos.scheduled_map_run') + "</th><th>" + siteMessage('client.ops_demos.run_status') + "</th><th>" + siteMessage('client.ops_demos.size') + "</th><th>" + siteMessage('client.ops_demos.upload_info') + "</th><th class=\"num\">" + siteMessage('client.ops_demos.actions') + "</th>") +
  '</tr></thead><tbody>';

  originals.forEach(function (orig) {
    var cached = state.demoAnalysesCache[orig.demo_id] || null;
    var isVoid = orig.run_status === 'void';
    html += '<tr>' +
      '<td data-i18n-ignore>#' + esc(orig.demo_id) + '</td>' +
      '<td><span>' + esc(siteMessage('client.ops_demos.map_map_order', {map_order: orig.map_order})) + '</span> · <span data-i18n-ignore>' + esc(mapDisplay(orig.map_name)) + ' · Run #' + esc(orig.map_run_id) + '</span>' +
        (orig.download_default ? (" <span class=\"badge badge-accent\">" + siteMessage('client.ops_demos.selected_for_public_download') + "</span>") : '') + '</td>' +
      '<td>' + runStatusBadge(orig.run_status) + (isVoid ? ("<div class=\"cell-sub\">" + siteMessage('client.ops_demos.void_run_demos_are_archived_for') + "</div>") : '') + '</td>' +
      '<td class="mono">' + esc(fmtBytes(orig.byte_count)) + '</td>' +
      '<td><span data-i18n-ignore>' + esc(adminLabel(orig.uploaded_by)) + '</span><div class="cell-sub" data-i18n-ignore>' + esc(orig.uploaded_at || '-') + '</div></td>' +
      '<td class="num ops-row-btns">' +
        '<a class="btn btn-sm" href="/admin/matches/' + MATCH_ID + '/api/demos/' + orig.demo_id + ("/file\">" + siteMessage('client.ops_demos.download_original') + "</a> ") +
        '<button type="button" class="btn btn-sm" data-action="parse-demo" data-demo-id="' + orig.demo_id + '">' + (cached && cached.length ? siteMessage('client.ops_demos.parse_again') : siteMessage('client.ops_demos.parse_demo')) + '</button> ' +
        '<button type="button" class="btn btn-sm" data-action="toggle-analyses" data-demo-id="' + orig.demo_id + ("\">" + siteMessage('client.ops_demos.analysis_history') + "</button>") +
      '</td>' +
    '</tr>';

    if (cached) {
      html += '<tr class="ops-analyses-subrow"><td colspan="6">';
      if (!cached.length) {
        html += ("<span class=\"muted\">" + siteMessage('client.ops_demos.no_parse_runs_yet_click_parse') + "</span>");
      } else {
        html += '<div class="ops-analyses-list">';
        cached.forEach(function (job) {
          var stCls = job.status === 'ready' ? 'badge-accent' : (job.status === 'failed' ? 'badge-danger' : 'badge-gold');
          html += '<div class="ops-analysis-item">' +
            '<div>' +
              '<strong data-i18n-ignore>Analysis #' + esc(job.analysis_id) + '</strong> ' +
              '<span class="badge ' + stCls + '">' + esc(job.status) + '</span> ' +
              '<span class="muted" data-i18n-ignore>' + esc(job.requested_at || '') + '</span>' +
              (job.error ? '<div class="ops-err-text">' + esc(job.error) + '</div>' : '') +
            '</div>' +
            '<div>' +
              (job.status === 'ready'
                ? '<button type="button" class="btn btn-sm btn-primary" data-action="preview-analysis" data-analysis-id="' + job.analysis_id + ("\">" + siteMessage('client.ops_demos.preview_and_select_for_adoption') + "</button>")
                : '') +
            '</div>' +
          '</div>';
        });
        html += '</div>';
      }
      html += '</td></tr>';
    }
  });
  html += '</tbody></table></div>';
  box.innerHTML = html;
}

async function handleDemoUpload(e) {
  e.preventDefault();
  clearError('demoUploadError');
  var fileInput = byId('demoUploadFile');
  if (!fileInput.files || !fileInput.files.length) {
    showError('demoUploadError', siteMessage('client.ops_demos.select_a_dem_file'));
    return;
  }
  var fd = new FormData();
  fd.append('scheduled_map_id', byId('demoUploadMapSelect').value);
  fd.append('map_run_id', byId('demoUploadRunSelect').value);
  fd.append('demo', fileInput.files[0]);

  var btn = byId('demoUploadSubmitBtn');
  btn.disabled = true;
  try {
    var res = await fetch('/admin/matches/' + MATCH_ID + '/api/demos', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': CSRF, 'X-Requested-With': 'XMLHttpRequest' },
      body: fd
    });
    var data = await res.json();
    if (!res.ok || data.ok === false) {
      showError('demoUploadError', data.error || (siteMessage('client.ops_demos.upload_failed_http_status', {status: res.status})));
      return;
    }
    fileInput.value = '';
    showFeedback(
      data.duplicate
        ? siteMessage('client.ops_demos.this_demo_already_exists_demo_demo', {demo_id: data.original.demo_id})
        : siteMessage('client.ops_demos.original_demo_uploaded_demo_demo_id', {demo_id: data.original.demo_id}),
      'success'
    );
    await refreshBundle(true);
  } catch (_err) {
    showError('demoUploadError', siteMessage('client.ops_demos.network_request_failed_please_try_again'));
  } finally {
    btn.disabled = false;
  }
}

export async function loadDemoAnalyses(demoId) {
  var r = await apiJson('/admin/matches/' + MATCH_ID + '/api/demos/' + demoId, { method: 'GET' });
  if (!r.ok) {
    showFeedback(r.data.error || siteMessage('client.ops_demos.could_not_load_analysis_history'), 'error');
    return;
  }
  state.demoAnalysesCache[demoId] = (r.data.original && r.data.original.analyses) || [];
  renderDemosList();
}

export async function triggerDemoParse(demoId) {
  showFeedback(siteMessage('client.ops_demos.analyzing_demo_demoid', {demoid: demoId}), 'info');
  var r = await apiJson('/admin/matches/' + MATCH_ID + '/api/demos/' + demoId + '/parse', { method: 'POST', json: {} });
  await loadDemoAnalyses(demoId);
  if (!r.ok) {
    showFeedback(r.data.error || siteMessage('client.ops_demos.demo_analysis_failed_see_the_analysis'), 'error');
    return;
  }
  showFeedback(siteMessage('client.ops_demos.demo_demoid_analyzed_analysis_analysis_id', {demoid: demoId, analysis_id: r.data.analysis_id}), 'success');
  if (r.data.status === 'ready' && r.data.analysis_id) {
    await openAnalysisPreview(r.data.analysis_id);
  }
}

export async function openAnalysisPreview(analysisId, keepChoices) {
  var body = byId('opsDemoPreviewBody');
  var checked = keepChoices ? new Set(Array.from(body.querySelectorAll('input[data-review]:checked'), cb => cb.dataset.review)) : null;
  var reason = keepChoices ? byId('demoAdoptReason').value : '';
  var r = await apiJson('/admin/matches/' + MATCH_ID + '/api/demos/analyses/' + analysisId, { method: 'GET' });
  if (!r.ok) {
    showFeedback(r.data.error || siteMessage('client.ops_demos.could_not_load_the_analysis_preview'), 'error');
    return;
  }
  state.activeAnalysis = r.data.analysis;
  renderAnalysisPreview();
  if (keepChoices) {
    body.querySelectorAll('input[data-review]:not(:disabled)').forEach(cb => { cb.checked = checked.has(cb.dataset.review); });
    byId('demoAdoptReason').value = reason;
    showFeedback(siteMessage('client.ops_demos.differences_refreshed_only_unchanged_selections_were'), 'info');
  }
  var panel = byId('opsDemoPreviewPanel');
  panel.hidden = false;
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderAnalysisPreview() {
  var a = state.activeAnalysis;
  var panel = byId('opsDemoPreviewPanel');
  if (!a) {
    panel.hidden = true;
    return;
  }
  byId('opsDemoPreviewTitle').textContent =
    siteMessage('client.ops_demos.demo_analysis_preview_selective_adoption') + ' · Analysis #' + a.analysis_id + ' (Demo #' + a.original.demo_id + ')';

  var html = '';
  if (a.blocks && a.blocks.length) {
    html += ("<div class=\"ops-callout-danger\"><strong>" + siteMessage('client.ops_demos.blocked_from_adoption') + "</strong><ul>");
    a.blocks.forEach(function (b) { html += '<li>' + esc(b) + '</li>'; });
    html += '</ul></div>';
  }
  if (a.stats_block) {
    html += ("<div class=\"ops-callout-warn\"><strong>" + siteMessage('client.ops_demos.stats_default_download_blocked') + "</strong>") + esc(a.stats_block) + '</div>';
  }

  var cand = a.candidate_score || {};
  var off = a.official_result || null;
  var scoreMismatch = off && cand.score1 != null && cand.score2 != null &&
    (Number(cand.score1) !== Number(off.score1) || Number(cand.score2) !== Number(off.score2));

  var mapA = a.mapping && a.mapping.A ? participantById(a.mapping.A) : null;
  var mapB = a.mapping && a.mapping.B ? participantById(a.mapping.B) : null;

  html += '<div class="ops-preview-meta-grid">' +
    '<div class="ops-subcard">' +
      ("<div class=\"ops-subcard-head\"><strong>" + siteMessage('client.ops_demos.map_participant_mapping') + "</strong></div>") +
      ("<p>" + siteMessage('client.ops_demos.parsed_map') + "<strong data-i18n-ignore>") + esc(mapDisplay(a.map_name)) + ("</strong>" + siteMessage('client.ops_demos.linked_to') + "<span data-i18n-ignore>Run #") + esc(a.original.map_run_id) + '</span></p>' +
      ("<p>" + siteMessage('client.ops_demos.demo_team_a') + "<strong data-i18n-ignore>") + esc(mapA ? mapA.name : siteMessage('client.ops_demos.not_matched')) + '</strong></p>' +
      ("<p>" + siteMessage('client.ops_demos.demo_team_b') + "<strong data-i18n-ignore>") + esc(mapB ? mapB.name : siteMessage('client.ops_demos.not_matched')) + '</strong></p>' +
    '</div>' +
    '<div class="ops-subcard">' +
      ("<div class=\"ops-subcard-head\"><strong>" + siteMessage('client.ops_demos.score_check_demo_candidate_vs_official') + "</strong></div>") +
      ("<p>" + siteMessage('client.ops_demos.demo_score') + "<strong>") + esc(fmtVal(cand.score1)) + ' : ' + esc(fmtVal(cand.score2)) + '</strong></p>' +
      ("<p>" + siteMessage('client.ops_demos.current_official_result')) + (off
        ? '<strong>' + esc(off.score1) + ' : ' + esc(off.score2) + '</strong>（Rev ' + esc(off.revision) + '）'
        : ("<span class=\"muted\">" + siteMessage('client.ops_demos.no_official_map_result_confirmed') + "</span>")) + '</p>' +
      (scoreMismatch ? ("<p class=\"ops-err-text\">" + siteMessage('client.ops_demos.candidate_score_differs_from_the_official') + "</p>") : '') +
    '</div>' +
  '</div>';

  // Bulk selection buttons
  var blocked = Boolean(a.blocks && a.blocks.length);
  var statsBlocked = Boolean(a.stats_block);
  html += '<div class="ops-adopt-toolbar">' +
    '<button type="button" class="btn btn-sm" id="demoSelectSafeBtn"' + (blocked ? ' disabled' : '') + (">" + siteMessage('client.ops_demos.select_all_new_values_without_conflicts') + "</button>") +
    '<button type="button" class="btn btn-sm" id="demoSelectAllBtn"' + (blocked ? ' disabled' : '') + (">" + siteMessage('client.ops_demos.select_all_including_conflicting_values') + "</button>") +
    ("<button type=\"button\" class=\"btn btn-sm\" id=\"demoClearSelectBtn\">" + siteMessage('client.ops_demos.clear_selection') + "</button>") +
  '</div>';

  // Players diffs table
  var playersObj = a.players || {};
  var steamIds = Object.keys(playersObj);
  html += '<div class="ops-adopt-players">';
  steamIds.forEach(function (steamId) {
    var p = playersObj[steamId];
    var matched = p.lineup;
    var pname = matched ? playerLabel(matched.player_id) : siteMessage('client.ops_demos.not_matched_to_approved_lineup');
    var party = matched ? participantById(matched.match_participant_id) : null;
    var canRecord = Boolean(!blocked && matched && !p.withdrawn && p.rounds && p.rounds.length && !p.round_side_conflict);
    var canStats = Boolean(canRecord && !statsBlocked);
    var needsRecordForStats = p.participation_revision === null;
    var evidence = [steamId, matched && matched.player_id, matched && matched.match_participant_id, p.participation_revision, off && off.revision];

    html += '<div class="ops-adopt-player-card" data-steam-id="' + esc(steamId) + '">' +
      '<div class="ops-adopt-player-head">' +
        '<div>' +
          '<strong data-i18n-ignore>' + esc(pname) + '</strong> ' +
          (party ? '<span class="badge" data-i18n-ignore>' + esc(party.name) + '</span> ' : '') +
          '<code class="mono" data-i18n-ignore>' + esc(steamId) + '</code> ' +
          ("<span class=\"muted\">" + siteMessage('client.ops_demos.observed')) + esc((p.rounds || []).length) + (siteMessage('client.ops_demos.rounds') + "</span>") +
          (p.withdrawn ? (" <span class=\"badge badge-danger\">" + siteMessage('client.ops_demos.participation_withdrawn') + "</span>") : '') +
          (p.round_side_conflict ? (" <span class=\"badge badge-danger\">" + siteMessage('client.ops_demos.round_side_conflict') + "</span>") : '') +
        '</div>' +
        '<label class="ops-checkbox-inline">' +
          '<input type="checkbox" class="demo-record-cb" data-review="' + esc(JSON.stringify(evidence)) + '" data-steam-id="' + esc(steamId) + '"' + (canRecord ? '' : ' disabled') + '>' +
          ("<span>" + siteMessage('client.ops_demos.record_participation')) + (p.participation_revision != null ? siteMessage('client.ops_demos.recorded_rev_participation_revision', {participation_revision: p.participation_revision}) : '') + '</span>' +
        '</label>' +
      '</div>';

    if (matched && p.diffs) {
      html += '<div class="ops-adopt-scopes">';
      ['all', 'ct', 't'].forEach(function (sc) {
        var diff = p.diffs[sc] || {};
        var changes = diff.changes || {};
        var conflicts = diff.conflicts || {};
        var entries = [];
        Object.keys(changes).forEach(function (field) {
          entries.push({ field: field, ch: changes[field], isConflict: false });
        });
        Object.keys(conflicts).forEach(function (field) {
          if (!Object.prototype.hasOwnProperty.call(changes, field)) {
            entries.push({ field: field, ch: conflicts[field], isConflict: true });
          }
        });
        if (!entries.length) return;
        html += '<div class="ops-adopt-scope-block">' +
          '<div class="ops-adopt-scope-title">' + esc(sc.toUpperCase()) + siteMessage('client.ops_demos.field_differences') + entries.length + (siteMessage('client.ops_demos.label') + "</div>") +
          '<div class="ops-diff-chips">';
        entries.forEach(function (entry) {
          var field = entry.field;
          var ch = entry.ch;
          var isConflict = entry.isConflict;
          var action = isConflict ? 'replace' : 'accept';
          html += '<label class="ops-diff-chip' + (isConflict ? ' is-conflict' : '') + '">' +
            '<input type="checkbox" class="demo-field-cb" data-review="' + esc(JSON.stringify(evidence.concat(sc, field, action, ch.before, ch.after, ch.previous_source && ch.previous_source.revision))) + '" data-steam-id="' + esc(steamId) + '" data-scope="' + esc(sc) + '" data-field="' + esc(field) + '" data-action="' + action + '" data-needs-record="' + (needsRecordForStats ? '1' : '0') + '"' + (canStats ? '' : ' disabled') + '>' +
            '<span><b>' + esc(FIELD_LABELS[field] || field) + '</b>: ' +
            esc(fmtVal(ch.before)) + ' → ' + esc(fmtVal(ch.after)) +
            (isConflict ? (" <em>" + siteMessage('client.ops_demos.replace_conflict') + "</em>") : '') + '</span>' +
          '</label>';
        });
        html += '</div></div>';
      });
      html += '</div>';
    }
    html += '</div>';
  });
  html += '</div>';

  // Submit bar
  html += '<div class="ops-adopt-footer">' +
    '<label class="ops-checkbox-inline">' +
      '<input type="checkbox" id="demoDownloadDefaultCb"' + (blocked || statsBlocked ? ' disabled' : '') + '>' +
      ("<span>" + siteMessage('client.ops_demos.set_as_default_public_demo_download') + "</span>") +
    '</label>' +
    '<label class="field">' +
      ("<span class=\"field-label\">" + siteMessage('client.ops_demos.adoption_reason_required_max_500_chars') + "</span>") +
      ("<input type=\"text\" id=\"demoAdoptReason\" maxlength=\"500\" placeholder=\"" + siteMessage('client.ops_demos.e_g_verified_csda_score_and') + "\">") +
    '</label>' +
    '<div id="demoAdoptError" class="roster-inline-error" role="alert" hidden></div>' +
    '<div class="ops-adopt-submit-row">' +
      ("<button type=\"button\" class=\"btn\" id=\"demoReviewLatest\">" + siteMessage('client.ops_demos.review_latest_differences') + "</button>") +
      '<button type="button" class="btn btn-primary" id="demoAdoptSubmitBtn"' + (blocked ? ' disabled' : '') + (">" + siteMessage('client.ops_demos.adopt_selected_data') + "</button>") +
    '</div>' +
  '</div>';

  if (a.adoptions && a.adoptions.length) {
    html += ("<details class=\"ops-lineup-details\"><summary>" + siteMessage('client.ops_demos.adoption_history')) + a.adoptions.length + (siteMessage('client.ops_demos.label_2') + "</summary><ul class=\"ops-simple-list\">");
    a.adoptions.forEach(function (ad) {
      html += '<li><span data-i18n-ignore>#' + esc(ad.adoption_id) + ("</span>" + siteMessage('client.ops_demos.actor') + "<span data-i18n-ignore>") + esc(adminLabel(ad.actor)) + '</span> · <span data-i18n-ignore>' + esc(ad.adopted_at || '') + ("</span>" + siteMessage('client.ops_demos.reason') + "<span data-i18n-ignore>") + esc(ad.reason || '') + '</span></li>';
    });
    html += '</ul></details>';
  }

  byId('opsDemoPreviewBody').innerHTML = html;
  bindAnalysisPreviewEvents();
}

function bindAnalysisPreviewEvents() {
  var body = byId('opsDemoPreviewBody');
  var a = state.activeAnalysis;
  if (!body || !a) return;

  var safeBtn = byId('demoSelectSafeBtn');
  if (safeBtn) {
    safeBtn.addEventListener('click', function () {
      body.querySelectorAll('.demo-record-cb').forEach(function (c) { c.checked = false; });
      body.querySelectorAll('.demo-field-cb:not(:disabled)').forEach(function (c) {
        var sc = c.dataset.scope;
        var p = a.players[c.dataset.steamId];
        var deps = a.rate_inputs[c.dataset.field] || [];
        c.checked = c.dataset.action === 'accept' && !deps.some(dep => dep in p.diffs[sc].conflicts);
        if (c.checked && c.dataset.needsRecord === '1') c.closest('.ops-adopt-player-card').querySelector('.demo-record-cb').checked = true;
      });
    });
  }
  var allBtn = byId('demoSelectAllBtn');
  if (allBtn) {
    allBtn.addEventListener('click', function () {
      body.querySelectorAll('.demo-record-cb:not(:disabled), .demo-field-cb:not(:disabled)').forEach(function (c) {
        c.checked = true;
      });
    });
  }
  var clearBtn = byId('demoClearSelectBtn');
  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      body.querySelectorAll('.demo-record-cb, .demo-field-cb').forEach(function (c) { c.checked = false; });
      var dl = byId('demoDownloadDefaultCb');
      if (dl) dl.checked = false;
    });
  }
  var submitBtn = byId('demoAdoptSubmitBtn');
  byId('demoReviewLatest').addEventListener('click', function () { openAnalysisPreview(a.analysis_id, true); });
  if (submitBtn) {
    submitBtn.addEventListener('click', submitDemoAdoption);
  }
}

async function submitDemoAdoption() {
  clearError('demoAdoptError');
  var a = state.activeAnalysis;
  if (!a) return;
  var reason = (byId('demoAdoptReason').value || '').trim();
  if (!reason) {
    showError('demoAdoptError', siteMessage('client.ops_demos.enter_an_adoption_reason'));
    return;
  }
  var body = byId('opsDemoPreviewBody');
  var downloadDefault = Boolean((byId('demoDownloadDefaultCb') || {}).checked);
  var playersPayload = {};
  Object.keys(a.players || {}).forEach(function (steamId) {
    var p = a.players[steamId];
    if (!p.lineup) return;
    var recCb = body.querySelector('.demo-record-cb[data-steam-id="' + CSS.escape(steamId) + '"]');
    var record = Boolean(recCb && recCb.checked);
    var fieldsByScope = {};
    body.querySelectorAll('.demo-field-cb[data-steam-id="' + CSS.escape(steamId) + '"]:checked').forEach(function (cb) {
      var sc = cb.dataset.scope;
      if (!fieldsByScope[sc]) fieldsByScope[sc] = {};
      fieldsByScope[sc][cb.dataset.field] = cb.dataset.action;
    });
    var hasFields = Object.keys(fieldsByScope).length > 0;
    if (record || hasFields) {
      playersPayload[steamId] = {
        player_id: p.lineup.player_id,
        participation_revision: p.participation_revision,
        record: record,
        fields: fieldsByScope
      };
    }
  });

  if (!Object.keys(playersPayload).length && !downloadDefault) {
    showError('demoAdoptError', siteMessage('client.ops_demos.select_at_least_one_player_record'));
    return;
  }

  var approval = {
    analysis_id: a.analysis_id,
    mapping: a.mapping,
    result_revision: a.official_result ? a.official_result.revision : null,
    stats_revision: a.stats_revision,
    players: playersPayload,
    download_default: downloadDefault,
    reason: reason
  };

  byId('demoAdoptSubmitBtn').disabled = true;
  var r = await apiJson('/admin/matches/' + MATCH_ID + '/api/demos/adopt', {
    method: 'POST',
    json: { approvals: [approval] }
  });
  if (!r.ok) {
    byId('demoAdoptSubmitBtn').disabled = false;
    showError('demoAdoptError', r.data.error || (siteMessage('client.ops_demos.adoption_failed_http_status', {status: r.status})));
    return;
  }
  showFeedback(siteMessage('client.ops_demos.selected_items_adopted'), 'success');
  await refreshBundle(true);
  await openAnalysisPreview(a.analysis_id);
}

/* ==================== Tab 3: 赛果、结算、竞猜与历史 ==================== */
export function bindDemos() {
  byId('demoRefreshBtn').addEventListener('click', function () {
    refreshBundle(false);
  });
  byId('opsDemoPreviewCloseBtn').addEventListener('click', function () {
    state.activeAnalysis = null;
    byId('opsDemoPreviewPanel').hidden = true;
  });

  byId('demoUploadMapSelect').addEventListener('change', updateDemoUploadRuns);
  byId('opsDemoUploadForm').addEventListener('submit', handleDemoUpload);
}
