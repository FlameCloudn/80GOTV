// 80GOTV 报名与阵容工作台交互脚本：
// 负责预留核实、到期正式分队、分队调整、初始五人确认、候补分配、赛前换人、队伍归档与版本冲突提示。
(function () {
  'use strict';

  var dataEl = document.getElementById('eventRosterData');
  if (!dataEl) return;
  var DATA = JSON.parse(dataEl.textContent || '{}');
  var EVENT_ID = DATA.event_id;
  var REVISION = Number(DATA.revision || 0);
  var ENTRANTS = DATA.entrants || [];
  var RESERVES = DATA.reserves || [];
  var POOL_CANDIDATES = DATA.pool_candidates || [];
  var FLASH_KEY = 'gotv_roster_flash_' + EVENT_ID;

  function byId(id) { return document.getElementById(id); }
  function isEn() { return (document.documentElement.lang || '').indexOf('en') === 0; }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function confirmAction(message, danger) {
    if (window.adminConfirm) return window.adminConfirm(message, { danger: !!danger });
    if (window.showConfirm) return window.showConfirm(message);
    return Promise.resolve(window.confirm(message));
  }

  function toast(message, kind) {
    if (window.showToast) window.showToast(message, kind || 'info');
  }

  function findEntrant(entrantId) {
    var target = Number(entrantId);
    for (var i = 0; i < ENTRANTS.length; i += 1) {
      if (Number(ENTRANTS[i].id) === target) return ENTRANTS[i];
    }
    return null;
  }

  function findReserve(playerId) {
    var target = Number(playerId);
    for (var i = 0; i < RESERVES.length; i += 1) {
      if (Number(RESERVES[i].id) === target) return RESERVES[i];
    }
    return null;
  }

  function showError(el, msg) {
    if (!el) return;
    el.textContent = msg ? String(msg) : '';
    el.hidden = !msg;
  }

  function triggerVersionConflict() {
    var banner = byId('revisionConflictBanner');
    if (banner) {
      banner.hidden = false;
      banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    document.querySelectorAll('[data-roster-mutator]').forEach(function (btn) {
      btn.disabled = true;
    });
  }

  async function postAction(action, payload, submitBtn, busyText, errEl) {
    showError(errEl, '');
    var oldHtml = submitBtn ? submitBtn.innerHTML : '';
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = (busyText || window.siteMessage('client.admin_event_roster.submitting'));
    }
    try {
      var resp = await fetch('/admin/events/' + encodeURIComponent(EVENT_ID) + '/registration-control/' + encodeURIComponent(action), {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrfToken()
        },
        body: JSON.stringify(payload || {})
      });
      var parsed = (resp.headers.get('Content-Type') || '').includes('application/json') ? await resp.json() : null;
      if (!parsed || !resp.ok || parsed.success === false) {
        var code = resp.headers.get('X-80GOTV-Error');
        var conflict = code === 'roster_revision_conflict' || code === 'initial_roster_revision_conflict';
        var msg = conflict
          ? window.siteMessage('client.admin_event_roster.' + code)
          : parsed ? (parsed.error || window.siteMessage('client.admin_event_roster.operation_failed')) : window.siteMessage('client.admin_event_roster.no_valid_response_check_that_you');
        showError(errEl, msg);
        toast(msg, 'error');
        if (conflict) triggerVersionConflict();
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = oldHtml;
        }
        return { ok: false, error: msg };
      }
      return { ok: true, data: parsed };
    } catch (e) {
      var netErr = window.siteMessage('client.admin_event_roster.network_error_please_try_again_later');
      showError(errEl, netErr);
      toast(netErr, 'error');
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = oldHtml;
      }
      return { ok: false, error: netErr };
    }
  }

  function reloadWithFlash(msg, scrollId) {
    try {
      sessionStorage.setItem(FLASH_KEY, JSON.stringify({ msg: msg, scrollId: scrollId || '' }));
    } catch (e) {}
    window.location.reload();
  }

  // 页面刷新后恢复提示并滚动到对应队伍卡片
  (function restoreFlash() {
    try {
      var raw = sessionStorage.getItem(FLASH_KEY);
      if (!raw) return;
      sessionStorage.removeItem(FLASH_KEY);
      var info = JSON.parse(raw);
      if (info && info.msg) toast(info.msg, 'success');
      if (info && info.scrollId) {
        var target = byId(info.scrollId);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    } catch (e) {}
  })();

  // 通用关闭弹窗绑定
  document.querySelectorAll('[data-dialog-close]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var dialog = btn.closest('dialog');
      if (dialog && dialog.open) dialog.close();
    });
  });

  // 1. 到期正式分队
  (function bindFormDue() {
    var btn = byId('formDueBtn');
    var resultBox = byId('formDueResult');
    if (!btn) return;
    btn.addEventListener('click', function () {
      confirmAction(window.siteMessage('client.admin_event_roster.run_official_team_formation_from_the')).then(async function (yes) {
        if (!yes) return;
        var res = await postAction('form-due', {}, btn, window.siteMessage('client.admin_event_roster.forming_teams'), resultBox);
        if (res.ok) reloadWithFlash(window.siteMessage('client.admin_event_roster.teams_formed_review_and_confirm_each'));
      });
    });
  })();

  // 2. 预留席位认领 / 释放
  (function bindReviewReservation() {
    var dialog = byId('dialogReviewReservation');
    var form = byId('reviewReservationForm');
    if (!dialog || !form) return;
    var titleEl = byId('reviewDialogTitle');
    var summaryEl = byId('reviewDialogSummary');
    var reasonEl = byId('reviewReasonInput');
    var errEl = byId('reviewDialogError');
    var submitBtn = byId('reviewSubmitBtn');
    var current = null;

    function syncSubmit() {
      submitBtn.disabled = !reasonEl.value.trim();
    }
    reasonEl.addEventListener('input', syncSubmit);

    document.querySelectorAll('[data-open-review]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var mode = btn.getAttribute('data-open-review');
        var regId = Number(btn.getAttribute('data-reg-id'));
        var slot = Number(btn.getAttribute('data-slot'));
        var teamName = btn.getAttribute('data-team-name') || '';
        var label = btn.getAttribute('data-label') || '';
        var accountId = btn.getAttribute('data-account-id');
        var accountDisplay = btn.getAttribute('data-account-display') || '';
        current = {
          mode: mode,
          registration_id: regId,
          roster_slot: slot,
          verified_account_id: mode === 'claim' && accountId ? Number(accountId) : null
        };
        titleEl.textContent = (mode === 'claim' ? window.siteMessage('client.admin_event_roster.claim_reserved_slot') : window.siteMessage('client.admin_event_roster.release_reserved_slot'));
        summaryEl.textContent = mode === 'claim'
          ? (isEn()
            ? ('Assign approved account ' + accountDisplay + ' to “' + teamName + '” slot ' + (slot + 1) + ' (reserved for: ' + label + ').')
            : (window.siteMessage('client.admin_event_roster.assign_approved_account_accountdisplay_to_slot', {accountdisplay: accountDisplay, teamname: teamName, value5: (slot + 1), label: label})))
          : (isEn()
            ? ('Release slot ' + (slot + 1) + ' on “' + teamName + '” (reserved for: ' + label + ')? Once released, the slot becomes empty and will be filled from solo signups during team formation.')
            : (window.siteMessage('client.admin_event_roster.release_slot_value3_in_teamname_previously', {teamname: teamName, value3: (slot + 1), label: label})));
        submitBtn.className = 'btn ' + (mode === 'claim' ? 'btn-primary' : 'btn-danger');
        submitBtn.textContent = (mode === 'claim' ? window.siteMessage('client.admin_event_roster.confirm_claim') : window.siteMessage('client.admin_event_roster.confirm_release'));
        reasonEl.value = '';
        showError(errEl, '');
        syncSubmit();
        dialog.showModal();
      });
    });

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      if (!current || !reasonEl.value.trim()) return;
      var payload = {
        registration_id: current.registration_id,
        roster_slot: current.roster_slot,
        reason: reasonEl.value.trim()
      };
      if (current.verified_account_id !== null) payload.verified_account_id = current.verified_account_id;
      var res = await postAction('review-reservation', payload, submitBtn, window.siteMessage('client.admin_event_roster.submitting'), errEl);
      if (res.ok) {
        dialog.close();
        reloadWithFlash(current.mode === 'claim' ? window.siteMessage('client.admin_event_roster.reserved_slot_claimed') : window.siteMessage('client.admin_event_roster.reserved_slot_released'));
      }
    });
  })();

  // 3. 批量选择 & 确认初始五人
  (function bindConfirmInitial() {
    var selectAll = byId('selectAllUnconfirmed');
    var confirmBtn = byId('confirmSelectedInitialBtn');
    var dialog = byId('dialogConfirmInitial');
    var form = byId('confirmInitialForm');
    if (!confirmBtn || !dialog || !form) return;
    var previewEl = byId('confirmInitialPreview');
    var errEl = byId('confirmInitialError');
    var submitBtn = byId('confirmInitialSubmitBtn');
    var checks = Array.prototype.slice.call(document.querySelectorAll('.confirm-entrant-check'));
    var chosenIds = [];

    function syncChecks() {
      var selected = checks.filter(function (c) { return c.checked; });
      confirmBtn.disabled = selected.length === 0;
      if (selectAll) {
        selectAll.checked = checks.length > 0 && selected.length === checks.length;
        selectAll.indeterminate = selected.length > 0 && selected.length < checks.length;
      }
    }

    if (selectAll) {
      selectAll.addEventListener('change', function () {
        checks.forEach(function (c) { c.checked = selectAll.checked; });
        syncChecks();
      });
    }
    checks.forEach(function (c) { c.addEventListener('change', syncChecks); });
    syncChecks();

    confirmBtn.addEventListener('click', function () {
      chosenIds = checks.filter(function (c) { return c.checked; }).map(function (c) { return Number(c.value); });
      if (!chosenIds.length) return;
      previewEl.innerHTML = '';
      chosenIds.forEach(function (eid) {
        var team = findEntrant(eid);
        if (!team) return;
        var card = document.createElement('div');
        card.className = 'confirm-initial-item';
        var title = document.createElement('strong');
        title.setAttribute('data-i18n-ignore', '');
        title.textContent = team.team_name || team.name;
        card.appendChild(title);
        var list = document.createElement('div');
        list.className = 'readonly-teams';
        list.setAttribute('data-i18n-ignore', '');
        (team.current_players || []).forEach(function (p) {
          var tag = document.createElement('span');
          tag.className = 'player-tag';
          tag.textContent = p.nickname;
          list.appendChild(tag);
        });
        card.appendChild(list);
        previewEl.appendChild(card);
      });
      showError(errEl, '');
      submitBtn.disabled = false;
      dialog.showModal();
    });

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      if (!chosenIds.length) return;
      var res = await postAction(
        'confirm-initial',
        { event_entrant_ids: chosenIds, expected_revision: REVISION },
        submitBtn,
        window.siteMessage('client.admin_event_roster.confirming'),
        errEl
      );
      if (res.ok) {
        dialog.close();
        reloadWithFlash(window.siteMessage('client.admin_event_roster.initial_roster_confirmed_for_selected_team'), 'entrant-' + chosenIds[0]);
      }
    });
  })();

  // 4. 调整分队（支持勾选多队互换与从非独立候补池补入）
  (function bindAdjustFormation() {
    var dialog = byId('dialogAdjustFormation');
    var form = byId('adjustFormationForm');
    if (!dialog || !form) return;
    var checksWrap = byId('adjustTeamChecks');
    var editorsWrap = byId('adjustTeamEditors');
    var returnedEl = byId('adjustReturnedPreview');
    var reasonEl = byId('adjustReasonInput');
    var errEl = byId('adjustDialogError');
    var submitBtn = byId('adjustSubmitBtn');

    var editableTeams = ENTRANTS.filter(function (t) { return !t.is_frozen && !t.team_archived; });
    var selectedTeams = new Set();
    var currentAssignments = {};

    function poolPlayers() {
      var map = {};
      editableTeams.forEach(function (t) {
        if (!selectedTeams.has(t.id)) return;
        (t.current_players || []).forEach(function (p) {
          map[p.id] = {
            id: p.id,
            nickname: p.nickname,
            label: p.nickname + (isEn() ? (' (from ' + t.name + ')') : (window.siteMessage('client.admin_event_roster.previously_with_name', {name: t.name})))
          };
        });
      });
      POOL_CANDIDATES.forEach(function (p) {
        map[p.id] = {
          id: p.id,
          nickname: p.nickname,
          label: window.siteMessage('roster.reserve.player_label', { nickname: p.nickname, origin: p.origin_label })
        };
      });
      return Object.keys(map).map(function (k) { return map[k]; });
    }

    function syncAdjustValidation() {
      var selects = Array.prototype.slice.call(editorsWrap.querySelectorAll('select[data-adjust-entrant]'));
      var counts = {};
      var chosenSet = new Set();
      var hasMissing = false;
      selects.forEach(function (sel) {
        var val = sel.value;
        if (!val) {
          hasMissing = true;
          return;
        }
        chosenSet.add(Number(val));
        counts[val] = (counts[val] || 0) + 1;
      });
      var hasDup = false;
      selects.forEach(function (sel) {
        var dup = !!(sel.value && counts[sel.value] > 1);
        if (dup) hasDup = true;
        if (dup) sel.setAttribute('aria-invalid', 'true');
        else sel.removeAttribute('aria-invalid');
      });

      var returning = [];
      editableTeams.forEach(function (t) {
        if (!selectedTeams.has(t.id)) return;
        (t.current_players || []).forEach(function (p) {
          if (!chosenSet.has(Number(p.id))) returning.push(p.nickname);
        });
      });
      returnedEl.textContent = returning.length
        ? (isEn()
          ? ('Returning to the reserve pool on save: ' + returning.join(', '))
          : (window.siteMessage('client.admin_event_roster.will_return_to_the_reserve_list', {value1: returning.join('、')})))
        : window.siteMessage('client.admin_event_roster.all_existing_players_from_selected_teams');

      if (hasDup) {
        showError(errEl, window.siteMessage('client.admin_event_roster.a_player_cannot_be_assigned_to'));
      } else {
        showError(errEl, '');
      }
      submitBtn.disabled = selectedTeams.size === 0 || hasMissing || hasDup || !reasonEl.value.trim();
    }

    function renderEditors() {
      // 保留当前已选状态
      editorsWrap.querySelectorAll('select[data-adjust-entrant]').forEach(function (sel) {
        var eid = Number(sel.getAttribute('data-adjust-entrant'));
        var slot = Number(sel.getAttribute('data-adjust-slot'));
        if (!currentAssignments[eid]) currentAssignments[eid] = [];
        currentAssignments[eid][slot] = sel.value ? Number(sel.value) : '';
      });

      editorsWrap.innerHTML = '';
      var pool = poolPlayers();
      editableTeams.forEach(function (t) {
        if (!selectedTeams.has(t.id)) return;
        if (!currentAssignments[t.id]) {
          currentAssignments[t.id] = (t.current_players || []).map(function (p) { return p.id; });
        }
        var box = document.createElement('div');
        box.className = 'adjust-team-box';
        var heading = document.createElement('strong');
        heading.setAttribute('data-i18n-ignore', '');
        heading.textContent = t.name;
        box.appendChild(heading);

        var row = document.createElement('div');
        row.className = 'adjust-slots-grid';
        for (var slot = 0; slot < 5; slot += 1) {
          var label = document.createElement('label');
          label.className = 'roster-slot';
          var span = document.createElement('span');
          span.textContent = window.siteMessage('client.admin_event_roster.slot_value1', {value1: (slot + 1)});
          var sel = document.createElement('select');
          sel.setAttribute('data-adjust-entrant', String(t.id));
          sel.setAttribute('data-adjust-slot', String(slot));
          var blank = document.createElement('option');
          blank.value = '';
          blank.textContent = window.siteMessage('client.admin_event_roster.select');
          sel.appendChild(blank);

          var chosen = currentAssignments[t.id][slot];
          pool.forEach(function (optPlayer) {
            var opt = document.createElement('option');
            opt.value = String(optPlayer.id);
            opt.textContent = optPlayer.label;
            opt.setAttribute('data-i18n-ignore', '');
            if (Number(chosen) === Number(optPlayer.id)) opt.selected = true;
            sel.appendChild(opt);
          });
          sel.addEventListener('change', syncAdjustValidation);
          label.appendChild(span);
          label.appendChild(sel);
          row.appendChild(label);
        }
        box.appendChild(row);
        editorsWrap.appendChild(box);
      });
      syncAdjustValidation();
    }

    reasonEl.addEventListener('input', syncAdjustValidation);

    document.querySelectorAll('[data-open-adjust]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var initialId = Number(btn.getAttribute('data-open-adjust'));
        selectedTeams = new Set([initialId]);
        currentAssignments = {};
        editableTeams.forEach(function (t) {
          currentAssignments[t.id] = (t.current_players || []).map(function (p) { return p.id; });
        });
        checksWrap.innerHTML = '';
        editableTeams.forEach(function (t) {
          var lbl = document.createElement('label');
          lbl.className = 'check-row';
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.checked = selectedTeams.has(t.id);
          cb.addEventListener('change', function () {
            if (cb.checked) selectedTeams.add(t.id);
            else selectedTeams.delete(t.id);
            renderEditors();
          });
          var txt = document.createElement('span');
          txt.setAttribute('data-i18n-ignore', '');
          txt.textContent = t.name;
          lbl.appendChild(cb);
          lbl.appendChild(txt);
          checksWrap.appendChild(lbl);
        });
        reasonEl.value = '';
        showError(errEl, '');
        renderEditors();
        dialog.showModal();
      });
    });

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var assignments = {};
      var selects = editorsWrap.querySelectorAll('select[data-adjust-entrant]');
      selects.forEach(function (sel) {
        var eid = sel.getAttribute('data-adjust-entrant');
        var slot = Number(sel.getAttribute('data-adjust-slot'));
        if (!assignments[eid]) assignments[eid] = [];
        assignments[eid][slot] = Number(sel.value);
      });
      var res = await postAction(
        'adjust-formation',
        { assignments: assignments, expected_revision: REVISION, reason: reasonEl.value.trim() },
        submitBtn,
        window.siteMessage('client.admin_event_roster.submitting'),
        errEl
      );
      if (res.ok) {
        dialog.close();
        var firstKey = Object.keys(assignments)[0];
        reloadWithFlash(window.siteMessage('client.admin_event_roster.team_formation_updated'), firstKey ? ('entrant-' + firstKey) : '');
      }
    });
  })();

  // 5. 分配候补（强制记录未用独立候补原因；同级候补支持可选记录原因）
  (function bindAssignReserve() {
    var dialog = byId('dialogAssignReserve');
    var form = byId('assignReserveForm');
    if (!dialog || !form) return;
    var entrantSel = byId('assignEntrantSelect');
    var candidateSel = byId('assignCandidateSelect');
    var reasonEl = byId('assignReasonInput');
    var excludedWrap = byId('assignExcludedWrap');
    var errEl = byId('assignDialogError');
    var submitBtn = byId('assignSubmitBtn');

    var activeTeams = ENTRANTS.filter(function (t) { return !t.team_archived; });
    var availableReserves = RESERVES.filter(function (r) { return r.assigned_entrant_id === null; });

    function syncAssignSubmit() {
      var missingRequired = false;
      excludedWrap.querySelectorAll('input[data-excluded-required="1"]').forEach(function (inp) {
        if (!inp.value.trim()) missingRequired = true;
      });
      submitBtn.disabled = !entrantSel.value || !candidateSel.value || !reasonEl.value.trim() || missingRequired;
    }

    function renderExcludedInputs() {
      excludedWrap.innerHTML = '';
      var chosenId = Number(candidateSel.value);
      var chosen = findReserve(chosenId);
      if (!chosen) {
        excludedWrap.hidden = true;
        syncAssignSubmit();
        return;
      }
      var otherUnassigned = availableReserves.filter(function (r) { return Number(r.id) !== chosenId; });
      var unassignedInd = otherUnassigned.filter(function (r) { return r.is_independent; });

      var hasContent = false;
      if (!chosen.is_independent && unassignedInd.length > 0) {
        hasContent = true;
        var warn = document.createElement('p');
        warn.className = 'lock-note';
        warn.textContent = isEn()
          ? ('Independent reserves have priority. Before choosing “' + chosen.nickname + ' (' + String(chosen.origin_label) + ')”, record why each independent reserve below was not selected:')
          : (window.siteMessage('client.admin_event_roster.independently_registered_reserves_have_priority_before', {nickname: chosen.nickname, origin_label: chosen.origin_label}));
        excludedWrap.appendChild(warn);

        unassignedInd.forEach(function (cand) {
          var row = document.createElement('label');
          row.className = 'field';
          var lbl = document.createElement('span');
          lbl.className = 'field-label';
          lbl.innerHTML = '<span data-i18n-ignore></span> <span class="field-required">*</span>';
          lbl.firstChild.textContent = cand.nickname + window.siteMessage('client.admin_event_roster.exclusion_reason');
          var inp = document.createElement('input');
          inp.type = 'text';
          inp.maxLength = 300;
          inp.required = true;
          inp.placeholder = window.siteMessage('client.admin_event_roster.e_g_schedule_conflict_declined_offer');
          inp.setAttribute('data-excluded-player-id', String(cand.id));
          inp.setAttribute('data-excluded-required', '1');
          inp.addEventListener('input', syncAssignSubmit);
          row.appendChild(lbl);
          row.appendChild(inp);
          excludedWrap.appendChild(row);
        });
      }

      var optionalPeers = (!chosen.is_independent && unassignedInd.length > 0)
        ? otherUnassigned.filter(function (r) { return !r.is_independent; })
        : otherUnassigned;
      if (optionalPeers.length > 0) {
        hasContent = true;
        var det = document.createElement('details');
        det.className = 'optional';
        var sum = document.createElement('summary');
        sum.textContent = window.siteMessage('client.admin_event_roster.optional_log_why_other_peer_reserves');
        det.appendChild(sum);
        var body = document.createElement('div');
        body.className = 'details-body';
        optionalPeers.forEach(function (cand) {
          var row = document.createElement('label');
          row.className = 'field';
          var lbl = document.createElement('span');
          lbl.className = 'field-label';
          lbl.setAttribute('data-i18n-ignore', '');
          lbl.textContent = window.siteMessage('roster.reserve.player_label', { nickname: cand.nickname, origin: cand.origin_label });
          var inp = document.createElement('input');
          inp.type = 'text';
          inp.maxLength = 300;
          inp.placeholder = window.siteMessage('client.admin_event_roster.leave_blank_to_skip');
          inp.setAttribute('data-excluded-player-id', String(cand.id));
          inp.setAttribute('data-excluded-required', '0');
          row.appendChild(lbl);
          row.appendChild(inp);
          body.appendChild(row);
        });
        det.appendChild(body);
        excludedWrap.appendChild(det);
      }

      excludedWrap.hidden = !hasContent;
      syncAssignSubmit();
    }

    function openAssignDialog(presetEntrantId, presetCandidateId) {
      entrantSel.innerHTML = '';
      activeTeams.forEach(function (t) {
        var opt = document.createElement('option');
        opt.value = String(t.id);
        opt.textContent = t.name + (t.is_frozen ? window.siteMessage('client.admin_event_roster.initial_confirmed') : window.siteMessage('client.admin_event_roster.initial_pending'));
        opt.setAttribute('data-i18n-ignore', '');
        if (presetEntrantId && Number(presetEntrantId) === Number(t.id)) opt.selected = true;
        entrantSel.appendChild(opt);
      });

      candidateSel.innerHTML = '';
      availableReserves.forEach(function (c) {
        var opt = document.createElement('option');
        opt.value = String(c.id);
        opt.textContent = window.siteMessage('roster.reserve.player_label', { nickname: c.nickname, origin: c.origin_label });
        opt.setAttribute('data-i18n-ignore', '');
        if (presetCandidateId && Number(presetCandidateId) === Number(c.id)) opt.selected = true;
        candidateSel.appendChild(opt);
      });

      reasonEl.value = '';
      showError(errEl, '');
      renderExcludedInputs();
      dialog.showModal();
    }

    entrantSel.addEventListener('change', syncAssignSubmit);
    candidateSel.addEventListener('change', renderExcludedInputs);
    reasonEl.addEventListener('input', syncAssignSubmit);

    document.querySelectorAll('[data-open-assign-team]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openAssignDialog(btn.getAttribute('data-open-assign-team'), null);
      });
    });
    document.querySelectorAll('[data-open-assign-candidate]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openAssignDialog(null, btn.getAttribute('data-open-assign-candidate'));
      });
    });

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var excluded = {};
      excludedWrap.querySelectorAll('input[data-excluded-player-id]').forEach(function (inp) {
        var val = inp.value.trim();
        if (val) excluded[inp.getAttribute('data-excluded-player-id')] = val;
      });
      var entrantId = Number(entrantSel.value);
      var res = await postAction(
        'assign-reserve',
        {
          event_entrant_id: entrantId,
          player_id: Number(candidateSel.value),
          expected_revision: REVISION,
          reason: reasonEl.value.trim(),
          excluded_candidates: excluded
        },
        submitBtn,
        window.siteMessage('client.admin_event_roster.assigning'),
        errEl
      );
      if (res.ok) {
        dialog.close();
        reloadWithFlash(window.siteMessage('client.admin_event_roster.substitute_slot_assigned_run_a_pre'), 'entrant-' + entrantId);
      }
    });
  })();

  // 6. 赛前换人（至少保留三名初始成员校验）
  (function bindReplaceBeforeSeries() {
    var dialog = byId('dialogReplaceBeforeSeries');
    var form = byId('replaceForm');
    if (!dialog || !form) return;
    var titleEl = byId('replaceTitle');
    var outSel = byId('replaceOutgoingSelect');
    var inSel = byId('replaceIncomingSelect');
    var majorityEl = byId('replaceMajorityHint');
    var reasonEl = byId('replaceReasonInput');
    var errEl = byId('replaceDialogError');
    var submitBtn = byId('replaceSubmitBtn');
    var activeTeam = null;

    function syncReplaceState() {
      if (!activeTeam) return;
      var initialSet = new Set((activeTeam.initial_player_ids || []).map(Number));
      var outId = Number(outSel.value);
      var inId = Number(inSel.value);
      var proposed = (activeTeam.current_players || []).map(function (p) {
        return Number(p.id) === outId ? inId : Number(p.id);
      });
      var kept = proposed.filter(function (pid) { return initialSet.has(pid); }).length;
      var okMajority = kept >= 3;
      majorityEl.textContent = isEn()
        ? ('Initial Roster retained after change: ' + kept + ' / 5 (at least 3 required)')
        : (window.siteMessage('client.admin_event_roster.initial_roster_members_retained_after_the', {kept: kept}));
      majorityEl.className = 'roster-majority-hint ' + (okMajority ? 'is-ok' : 'is-bad');
      submitBtn.disabled = !outSel.value || !inSel.value || !okMajority || !reasonEl.value.trim();
    }

    outSel.addEventListener('change', syncReplaceState);
    inSel.addEventListener('change', syncReplaceState);
    reasonEl.addEventListener('input', syncReplaceState);

    document.querySelectorAll('[data-open-replace]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var team = findEntrant(btn.getAttribute('data-open-replace'));
        if (!team) return;
        activeTeam = team;
        titleEl.textContent = (isEn() ? 'Pre-match roster change · ' : window.siteMessage('client.admin_event_roster.pre_match_roster_change')) + team.name;
        var initialSet = new Set((team.initial_player_ids || []).map(Number));

        outSel.innerHTML = '';
        (team.current_players || []).forEach(function (p) {
          var opt = document.createElement('option');
          opt.value = String(p.id);
          opt.textContent = p.nickname + (initialSet.has(Number(p.id)) ? window.siteMessage('client.admin_event_roster.initial') : window.siteMessage('client.admin_event_roster.subbed_in'));
          opt.setAttribute('data-i18n-ignore', '');
          outSel.appendChild(opt);
        });

        inSel.innerHTML = '';
        (team.assigned_reserves || []).forEach(function (r) {
          var opt = document.createElement('option');
          opt.value = String(r.id);
          opt.textContent = window.siteMessage('roster.reserve.player_label', { nickname: r.nickname, origin: r.origin_label });
          opt.setAttribute('data-i18n-ignore', '');
          inSel.appendChild(opt);
        });

        reasonEl.value = '';
        showError(errEl, '');
        syncReplaceState();
        dialog.showModal();
      });
    });

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      if (!activeTeam) return;
      var res = await postAction(
        'replace-before-series',
        {
          event_entrant_id: activeTeam.id,
          outgoing_player_id: Number(outSel.value),
          incoming_player_id: Number(inSel.value),
          expected_revision: REVISION,
          reason: reasonEl.value.trim()
        },
        submitBtn,
        window.siteMessage('client.admin_event_roster.submitting'),
        errEl
      );
      if (res.ok) {
        dialog.close();
        reloadWithFlash(window.siteMessage('client.admin_event_roster.pre_match_roster_change_saved'), 'entrant-' + activeTeam.id);
      }
    });
  })();

  // 7. 归档队伍
  (function bindArchiveTeam() {
    var dialog = byId('dialogArchiveTeam');
    var form = byId('archiveTeamForm');
    if (!dialog || !form) return;
    var summaryEl = byId('archiveTeamSummary');
    var reasonEl = byId('archiveReasonInput');
    var errEl = byId('archiveDialogError');
    var submitBtn = byId('archiveSubmitBtn');
    var targetEntrantId = null;

    function syncArchive() {
      submitBtn.disabled = !reasonEl.value.trim();
    }
    reasonEl.addEventListener('input', syncArchive);

    document.querySelectorAll('[data-open-archive]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        targetEntrantId = Number(btn.getAttribute('data-open-archive'));
        var teamName = btn.getAttribute('data-team-name') || ('#' + targetEntrantId);
        summaryEl.textContent = isEn()
          ? ('Archive “' + teamName + '”? Once archived, this team can no longer confirm its Initial Roster, change players, or enter new matches.')
          : (window.siteMessage('client.admin_event_roster.archive_teamname_you_will_no_longer', {teamname: teamName}));
        reasonEl.value = '';
        showError(errEl, '');
        syncArchive();
        dialog.showModal();
      });
    });

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      if (!targetEntrantId || !reasonEl.value.trim()) return;
      var res = await postAction(
        'archive-team',
        { event_entrant_id: targetEntrantId, reason: reasonEl.value.trim() },
        submitBtn,
        window.siteMessage('client.admin_event_roster.archiving'),
        errEl
      );
      if (res.ok) {
        dialog.close();
        reloadWithFlash(window.siteMessage('client.admin_event_roster.entrant_archived'), 'entrant-' + targetEntrantId);
      }
    });
  })();

  // 8. 截止前关联长期俱乐部
  (function bindLinkClub() {
    var dialog = byId('dialogLinkClub');
    var form = byId('linkClubForm');
    if (!dialog || !form) return;
    var summaryEl = byId('linkClubSummary');
    var selectEl = byId('linkClubSelect');
    var errEl = byId('linkClubDialogError');
    var submitBtn = byId('linkClubSubmitBtn');
    var targetRegId = null;
    var currentClubId = '';

    function syncLinkClub() {
      submitBtn.disabled = !targetRegId || !selectEl.value || selectEl.value === currentClubId;
    }
    selectEl.addEventListener('change', syncLinkClub);

    document.querySelectorAll('[data-open-link-club]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        targetRegId = Number(btn.getAttribute('data-reg-id'));
        var teamName = btn.getAttribute('data-team-name') || ('#' + targetRegId);
        currentClubId = btn.getAttribute('data-club-id') || '';
        summaryEl.textContent = teamName;
        selectEl.value = currentClubId;
        showError(errEl, '');
        syncLinkClub();
        dialog.showModal();
      });
    });

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      if (submitBtn.disabled) return;
      var res = await postAction(
        'link-club',
        { registration_id: targetRegId, club_id: Number(selectEl.value) },
        submitBtn,
        window.siteMessage('client.admin_event_roster.linking'),
        errEl
      );
      if (res.ok) {
        dialog.close();
        reloadWithFlash(window.siteMessage('client.admin_event_roster.club_linked'), 'sectionFormation');
      }
    });
  })();
})();
