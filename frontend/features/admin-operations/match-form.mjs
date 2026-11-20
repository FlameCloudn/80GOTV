import { message } from '../../shared/i18n.js';

const formData = JSON.parse(document.getElementById('matchFormData').textContent);

function switchMatchTab(tabKey) {
  document.querySelectorAll('.match-tabs .match-tab').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.tab === tabKey);
    btn.setAttribute('aria-selected', btn.dataset.tab === tabKey ? 'true' : 'false');
  });
  document.querySelectorAll('.tab-pane').forEach(function (pane) {
    pane.classList.toggle('active', pane.id === 'pane-' + tabKey);
  });
}
document.querySelectorAll('.match-tabs .match-tab').forEach(function (btn) {
  btn.addEventListener('click', function () { switchMatchTab(btn.dataset.tab); });
  btn.disabled = false;
});

function setMatchStatus(statusVal, btn) {
  var select = document.getElementById('statusSelect');
  if (select) select.value = statusVal;
  document.querySelectorAll('#statusPills .status-pill').forEach(function (p) {
    p.classList.toggle('active', p === btn);
  });
}

function syncMatchTime() {
  var d = document.getElementById('matchDate');
  var tm = document.getElementById('matchTime');
  var h = document.getElementById('hiddenMatchTime');
  var prev = document.getElementById('timePreview');
  if (!d || !tm || !h) return;
  var dVal = d.value.trim();
  var tVal = tm.value.trim() || '19:30';
  if (dVal) {
    h.value = dVal + 'T' + tVal;
    if (prev) prev.textContent = message('match.clock.setting', { time: dVal + ' ' + tVal });
  } else {
    h.value = '';
    if (prev) prev.textContent = message('match.clock.unset');
  }
}

function setTime(val, btn) {
  var tm = document.getElementById('matchTime');
  if (!tm) return;
  tm.value = val;
  document.querySelectorAll('.time-chip').forEach(function (c) { c.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  syncMatchTime();
}

function quickDate(offsetDays) {
  var now = new Date();
  now.setDate(now.getDate() + offsetDays);
  var dInput = document.getElementById('matchDate');
  if (!dInput) return;
  dInput.value = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
  syncMatchTime();
}

const { managedEvents: MANAGED_EVENTS_DATA, submittedSides: INITIAL_SUBMITTED_SIDES, managedEdit: IS_MANAGED_EDIT, isNew } = formData;

function currentSelectedEventId() {
  var sel = document.getElementById('eventIdSelect');
  return sel ? String(sel.value || '') : '';
}

function isManagedEventSelected(eventId) {
  var eid = eventId != null ? String(eventId) : currentSelectedEventId();
  return !!(eid && Object.prototype.hasOwnProperty.call(MANAGED_EVENTS_DATA, eid));
}

function renderEntrantPreview(side, eventId) {
  var preview = document.getElementById('side' + side + '_entrant_preview');
  var sel = document.getElementById('side' + side + '_entrant_select');
  if (!preview || !sel) return;
  var ev = MANAGED_EVENTS_DATA[eventId];
  var eid = sel.value;
  if (!ev || !eid) {
    preview.innerHTML = '';
    return;
  }
  var found = null;
  for (var i = 0; i < ev.entrants.length; i += 1) {
    if (String(ev.entrants[i].event_entrant_id) === String(eid)) { found = ev.entrants[i]; break; }
  }
  if (!found) { preview.innerHTML = ''; return; }
  var wrap = document.createElement('div');
  wrap.className = 'entrant-preview-card';
  var meta = document.createElement('div');
  meta.className = 'entrant-preview-meta';
  var tag = document.createElement('span');
  tag.className = 'badge ' + (found.club_name ? 'badge-accent' : 'badge-done');
  if (found.club_name) {
    tag.textContent = '';
    tag.appendChild(document.createTextNode(window.siteMessage('client.inline_matches_form.club')));
    var clubSpan = document.createElement('span');
    clubSpan.setAttribute('data-i18n-ignore', '');
    clubSpan.textContent = found.club_name;
    tag.appendChild(clubSpan);
  } else {
    tag.textContent = window.siteMessage('client.inline_matches_form.temp_team');
  }
  meta.appendChild(tag);
  var origin = document.createElement('span');
  origin.className = 'muted';
  origin.textContent = found.origin_label;
  meta.appendChild(origin);
  wrap.appendChild(meta);

  var playersWrap = document.createElement('div');
  playersWrap.className = 'readonly-teams';
  playersWrap.setAttribute('data-i18n-ignore', '');
  found.players.forEach(function (p) {
    var span = document.createElement('span');
    span.className = 'player-tag';
    span.textContent = p.nickname + (p.is_added_sub ? window.siteMessage('client.inline_matches_form.sub') : '');
    playersWrap.appendChild(span);
  });
  wrap.appendChild(playersWrap);
  preview.innerHTML = '';
  preview.appendChild(wrap);
}

function checkEntrantDuplicates() {
  var s1 = document.getElementById('side1_entrant_select');
  var s2 = document.getElementById('side2_entrant_select');
  if (!s1 || !s2) return;
  if (s1.disabled || s2.disabled) {
    s1.setCustomValidity('');
    s2.setCustomValidity('');
    return;
  }
  if (s1.value && s2.value && s1.value === s2.value) {
    s2.setCustomValidity(window.siteMessage('client.inline_matches_form.the_two_sides_must_be_different'));
  } else {
    s1.setCustomValidity('');
    s2.setCustomValidity('');
  }
}

function syncManagedEventSides(overrideEventId) {
  if (IS_MANAGED_EDIT) return;
  var eventId = overrideEventId != null ? String(overrideEventId) : currentSelectedEventId();
  var managed = isManagedEventSelected(eventId);
  var finalHint = document.getElementById('managedFinalHint');
  if (finalHint) finalHint.hidden = !managed;
  var testWrap = document.getElementById('testModeControl');
  var testCheck = document.getElementById('testMode');
  if (testWrap) testWrap.hidden = managed;
  if (testCheck && managed) testCheck.checked = false;

  var rosterTab = document.querySelector('.match-tabs .match-tab[data-tab="roster"]');
  if (rosterTab) rosterTab.hidden = managed;

  var notice = document.getElementById('managedEntrantNotice');
  var rosterLink = document.getElementById('managedEntrantRosterLink');
  var evData = managed ? MANAGED_EVENTS_DATA[eventId] : null;
  var hasReady = false;
  if (evData) {
    hasReady = evData.entrants.some(function (e) { return e.ready; });
    if (notice) notice.hidden = hasReady;
    if (rosterLink) rosterLink.href = evData.roster_url || '#';
  } else if (notice) {
    notice.hidden = true;
  }

  var sideHint = document.getElementById('matchupSideHint');
  if (sideHint) {
    sideHint.textContent = managed
      ? window.siteMessage('client.inline_matches_form.select_both_entrants_with_confirmed_initial')
      : window.siteMessage('client.inline_matches_form.starting_ct_t_sides_follow_the');
  }

  ['1', '2'].forEach(function (side) {
    var legacyWrap = document.getElementById('side' + side + '_legacy');
    var entrantWrap = document.getElementById('side' + side + '_entrant');
    var entrantType = document.getElementById('side' + side + '_entrant_type');
    var entrantSelect = document.getElementById('side' + side + '_entrant_select');
    var teamSelect = document.getElementById('side' + side + '_select');
    if (teamSelect && entrantSelect) {
      (managed ? teamSelect : entrantSelect).removeAttribute('name');
      (managed ? entrantSelect : teamSelect).name = 'side' + side + '_id';
    }

    if (legacyWrap) {
      legacyWrap.hidden = managed;
      legacyWrap.querySelectorAll('input, select').forEach(function (el) {
        el.disabled = managed;
        if (managed) el.required = false;
      });
    }
    if (entrantWrap && entrantType && entrantSelect) {
      entrantWrap.hidden = !managed;
      entrantType.disabled = !managed;
      entrantSelect.disabled = !managed;
      entrantSelect.required = managed;
      if (managed && evData) {
        var prevVal = entrantSelect.value || (INITIAL_SUBMITTED_SIDES[side] && INITIAL_SUBMITTED_SIDES[side].type === 'entrant' ? INITIAL_SUBMITTED_SIDES[side].id : '');
        entrantSelect.innerHTML = '';
        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = (evData.entrants.length ? window.siteMessage('client.inline_matches_form.select_event_entrant') : window.siteMessage('client.inline_matches_form.no_formed_entrants_available'));
        entrantSelect.appendChild(blank);
        evData.entrants.forEach(function (ent) {
          var opt = document.createElement('option');
          opt.value = String(ent.event_entrant_id);
          opt.textContent = ent.name + ' · ' + (ent.ready ? window.siteMessage('client.inline_matches_form.ready') : ent.not_ready_reason);
          opt.disabled = !ent.ready;
          opt.setAttribute('data-i18n-ignore', '');
          if (String(prevVal) === opt.value && ent.ready) opt.selected = true;
          entrantSelect.appendChild(opt);
        });
        renderEntrantPreview(side, eventId);
      } else {
        entrantSelect.innerHTML = ("<option value=\"\">" + window.siteMessage('client.inline_matches_form.select_event_entrant') + "</option>");
        renderEntrantPreview(side, '');
      }
    }
  });
  checkEntrantDuplicates();
}

function swapSides() {
  if (IS_MANAGED_EDIT) return;
  function notifyChanged(control) {
    if (!control) return;
    control.dispatchEvent(new Event('input', { bubbles: true }));
    control.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function swapSelectState(first, second, swapOptions) {
    if (!first || !second) return;
    var firstValue = first.value;
    var secondValue = second.value;
    if (swapOptions) {
      var firstOptions = Array.prototype.slice.call(first.options);
      var secondOptions = Array.prototype.slice.call(second.options);
      secondOptions.forEach(function (option) { first.appendChild(option); });
      firstOptions.forEach(function (option) { second.appendChild(option); });
    }
    first.value = secondValue;
    second.value = firstValue;
    notifyChanged(first);
    notifyChanged(second);
  }

  if (isManagedEventSelected()) {
    swapSelectState(document.getElementById('side1_entrant_select'), document.getElementById('side2_entrant_select'));
    return;
  }

  var firstType = document.querySelector('input[name="side1_type"]:checked');
  var secondType = document.querySelector('input[name="side2_type"]:checked');
  if (firstType && secondType) {
    var firstChoice = firstType.value;
    var secondChoice = secondType.value;
    var newFirstType = document.querySelector('input[name="side1_type"][value="' + secondChoice + '"]');
    var newSecondType = document.querySelector('input[name="side2_type"][value="' + firstChoice + '"]');
    newFirstType.checked = true;
    newSecondType.checked = true;
    notifyChanged(newFirstType);
    notifyChanged(newSecondType);
  }

  swapSelectState(document.getElementById('side1_select'), document.getElementById('side2_select'));
  for (var i = 0; i < 5; i++) {
    swapSelectState(
      document.querySelector('[name="side1_p' + i + '"]'),
      document.querySelector('[name="side2_p' + i + '"]')
    );
    swapSelectState(
      document.querySelector('[name="match_team1_p' + i + '"]'),
      document.querySelector('[name="match_team2_p' + i + '"]'),
      true
    );
  }
  toggleSide('1');
  toggleSide('2');
}

// 按赛制显示几张图：BO1 一张、BO3 三张、BO5 五张
function updateMapFields() {
  var bo = document.getElementById('boFormat').value;
  var max = bo === 'BO1' ? 1 : (bo === 'BO3' ? 3 : 5);
  for (var i = 2; i <= 5; i++) {
    var row = document.getElementById('map' + i + 'Row');
    if (row) row.hidden = max < i;
  }
}

// 是否测试比赛：新建页看“测试模式”勾选框，编辑页看隐藏的 is_test_mode 标记
function isTestMatch() {
  var testMode = document.getElementById('testMode');
  if (testMode && !isManagedEventSelected()) return testMode.checked;
  return !!document.querySelector('input[type="hidden"][name="is_test_mode"][value="1"]');
}

function toggleSide(num) {
  if (IS_MANAGED_EDIT || isManagedEventSelected()) return;
  var checked = document.querySelector('input[name="side' + num + '_type"]:checked');
  if (!checked) return;
  var isTeam = checked.value === 'team';
  var teamEl = document.getElementById('side' + num + '_team');
  var playersEl = document.getElementById('side' + num + '_players');
  if (teamEl) teamEl.hidden = !isTeam;
  if (playersEl) playersEl.hidden = isTeam;
  var sel = document.getElementById('side' + num + '_select');
  if (sel) sel.required = isTeam && !isTestMatch();
}

function toggleTestMode() {
  toggleSide('1');
  toggleSide('2');
}

// 观赛平台链接：每行“平台名 + 地址 + 删除”
const watchUrls = formData.watchUrls;
let watchUrlIndex = watchUrls.length;

function escapeWatchAttr(value) {
  return String(value).replace(/[&<>"']/g, function (ch) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch];
  });
}

function addWatchUrl(name, url, fixedIdx) {
  name = name || '';
  url = url || '';
  var idx = fixedIdx != null ? fixedIdx : watchUrlIndex++;
  if (fixedIdx != null && fixedIdx >= watchUrlIndex) watchUrlIndex = fixedIdx + 1;
  var row = document.createElement('div');
  row.className = 'watch-url-row';
  row.innerHTML = '<input type="text" name="watch_name_' + idx + '" value="' + escapeWatchAttr(name) + '" placeholder="' + escapeWatchAttr(window.siteMessage('client.inline_matches_form.platform_name_e_g_bilibili')) + '" aria-label="' + escapeWatchAttr(window.siteMessage('client.inline_matches_form.platform_name')) + '">' +
    '<input type="url" name="watch_url_' + idx + '" value="' + escapeWatchAttr(url) + '" placeholder="https://..." aria-label="' + escapeWatchAttr(window.siteMessage('client.inline_matches_form.platform_url')) + '">' +
    '<button type="button" class="btn watch-url-remove" aria-label="' + escapeWatchAttr(window.siteMessage('client.inline_matches_form.remove_this_platform')) + '">&times;</button>';
  row.querySelector('.watch-url-remove').addEventListener('click', function () { row.remove(); });
  document.getElementById('watchUrlContainer').appendChild(row);
}

watchUrls.forEach(function (w) { addWatchUrl(w.name, w.url); });

function switchMapMode(mode) {
  document.querySelectorAll('#mapModeTabs .mode-tab').forEach(function (tab) {
    tab.classList.toggle('active', tab.dataset.mapMode === mode);
  });
  var manual = document.getElementById('manualMapSection');
  var bp = document.getElementById('bpModeSection');
  if (manual) manual.hidden = mode !== 'manual';
  if (bp) bp.hidden = mode !== 'bp';
}

// 提交时：先同步比赛时间；防止连点两次；返回页面时恢复按钮
(function bindMatchSaveState() {
  var form = document.getElementById('matchForm');
  var button = document.getElementById('submitBtn');
  var status = document.getElementById('saveStatus');
  if (!form || !button) return;
  var idleText = button.querySelector('.btn-label').textContent;
  form.addEventListener('submit', function (event) {
    syncMatchTime();
    if (form.dataset.submitting === '1') {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = '1';
    button.disabled = true;
    button.querySelector('.btn-label').textContent = window.siteMessage('client.inline_matches_form.saving');
    if (status) status.hidden = false;
  });
  window.addEventListener('pageshow', function () {
    form.dataset.submitting = '';
    button.disabled = false;
    button.querySelector('.btn-label').textContent = idleText;
    if (status) status.hidden = true;
  });
})();

// 恢复草稿：先按草稿补齐观赛平台行与本届参赛队；填回后同步状态按钮、比赛时间、参赛方显示
(function bindDraftRestore() {
  var form = document.getElementById('matchForm');
  form.addEventListener('admin-draft:before-restore', function (event) {
    var detail = event.detail || {};
    Object.keys(detail).forEach(function (name) {
      var m = /^watch_name_(\d+)$/.exec(name);
      if (m && !form.elements[name]) addWatchUrl('', '', Number(m[1]));
    });
    if (detail.event_id && isManagedEventSelected(detail.event_id)) {
      syncManagedEventSides(detail.event_id);
    }
  });
  form.addEventListener('admin-draft:restored', function () {
    var select = document.getElementById('statusSelect');
    var pill = select && document.querySelector('#statusPills [data-status="' + select.value + '"]');
    if (pill) setMatchStatus(select.value, pill);
    syncMatchTime();
    updateMapFields();
    syncManagedEventSides();
    toggleTestMode();
    toggleSide('1');
    toggleSide('2');
  });
})();

// 新建比赛：所属赛事与参赛队下拉联动
(function bindEntrantMatchup() {
  var evSel = document.getElementById('eventIdSelect');
  if (evSel && !IS_MANAGED_EDIT) {
    evSel.addEventListener('change', function () { syncManagedEventSides(); });
  }
  ['1', '2'].forEach(function (side) {
    var sel = document.getElementById('side' + side + '_entrant_select');
    if (sel) {
      sel.addEventListener('change', function () {
        renderEntrantPreview(side, currentSelectedEventId());
        checkEntrantDuplicates();
      });
    }
  });
  document.querySelectorAll('[data-match-stage]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var input = document.getElementById('matchStageInput');
      if (!input || input.disabled) return;
      input.value = chip.dataset.matchStage;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    });
  });
})();

// 编辑比赛：独立的「确认冻结本场阵容」操作
(function bindFreezeMatchRosters() {
  var btn = document.getElementById('freezeMatchRostersBtn');
  var errBox = document.getElementById('freezeRosterError');
  var form = document.getElementById('matchForm');
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.getAttribute('content') : '';

  try {
    var pendingSuccess = sessionStorage.getItem('gotv_match_freeze_success');
    if (pendingSuccess) {
      sessionStorage.removeItem('gotv_match_freeze_success');
      if (window.showToast) window.showToast(pendingSuccess, 'success');
      switchMatchTab('roster');
    }
  } catch (e) {}

  if (window.location.hash === '#pane-roster' && document.querySelector('.match-tab[data-tab="roster"]')) {
    switchMatchTab('roster');
  }
  if (!btn) return;

  btn.addEventListener('click', function () {
    if (errBox) { errBox.hidden = true; errBox.textContent = ''; }
    var dirty = form && form._adminState && form._adminState.check();
    var msg = dirty
      ? window.siteMessage('client.inline_matches_form.you_have_unsaved_match_settings_time')
      : window.siteMessage('client.inline_matches_form.lock_both_5_player_rosters_names');
    var confirmFn = window.adminConfirm || window.showConfirm;
    confirmFn(msg).then(async function (yes) {
      if (!yes) return;
      var oldHtml = btn.innerHTML;
      btn.disabled = true;
      btn.textContent = window.siteMessage('client.inline_matches_form.locking');
      try {
        var resp = await fetch(btn.getAttribute('data-freeze-url'), {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRF-Token': csrf, 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (!resp.ok) {
          var rawErr = (await resp.text()).trim();
          var errText = rawErr ? rawErr : (window.siteMessage('client.inline_matches_form.action_failed_http') + resp.status + ')');
          if (errBox) { errBox.textContent = errText; errBox.hidden = false; }
          if (window.showToast) window.showToast(errText, 'error');
          btn.disabled = false;
          btn.innerHTML = oldHtml;
          return;
        }
        if (resp.url && resp.url.indexOf('/admin/login') !== -1) {
          if (window.showToast) window.showToast(window.siteMessage('client.inline_matches_form.session_expired_please_log_in_again'), 'error');
          window.location.href = resp.url;
          return;
        }
        try { sessionStorage.setItem('gotv_match_freeze_success', window.siteMessage('client.inline_matches_form.match_rosters_locked')); } catch (e) {}
        if (form && form._adminState) form._adminState.submitting = true;
        window.location.hash = '#pane-roster';
        window.location.reload();
      } catch (e) {
        var netErr = window.siteMessage('client.inline_matches_form.network_error_could_not_lock_match');
        if (errBox) { errBox.textContent = netErr; errBox.hidden = false; }
        if (window.showToast) window.showToast(netErr, 'error');
        btn.disabled = false;
        btn.innerHTML = oldHtml;
      }
    });
  });
})();

// 初始化
syncMatchTime();
updateMapFields();
syncManagedEventSides();
toggleTestMode();
toggleSide('1');
toggleSide('2');
if (isNew) switchMapMode('manual');


const setupForm = document.getElementById('matchForm');
setupForm.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  if (button.matches('#statusPills [data-status]')) setMatchStatus(button.dataset.status, button);
  if (button.hasAttribute('data-quick-date')) quickDate(Number(button.dataset.quickDate));
  if (button.hasAttribute('data-match-time')) setTime(button.dataset.matchTime, button);
  if (button.hasAttribute('data-swap-sides')) swapSides();
  if (button.hasAttribute('data-map-mode')) switchMapMode(button.dataset.mapMode);
  if (button.hasAttribute('data-add-watch-url')) addWatchUrl();
});
setupForm.addEventListener('change', event => {
  const control = event.target;
  if (control.matches('#matchDate, #matchTime')) syncMatchTime();
  if (control.matches('#testMode')) toggleTestMode();
  if (control.matches('#boFormat')) updateMapFields();
  if (control.hasAttribute('data-lineup-side')) toggleSide(control.dataset.lineupSide);
});
