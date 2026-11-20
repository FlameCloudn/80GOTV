const icons = JSON.parse(document.getElementById('eventFormIcons').textContent);

(function bindManagedAwardsPanel() {
  var panel = document.getElementById('managedAwardsPanel');
  if (!panel) return;
  var eventId = panel.getAttribute('data-event-id');
  var champUrl = panel.getAttribute('data-championship-url');
  var medalsUrl = panel.getAttribute('data-player-awards-url');
  var champBadge = document.getElementById('managedChampBadge');
  var champBody = document.getElementById('managedChampBody');
  var medalsBody = document.getElementById('managedMedalsBody');
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.getAttribute('content') : '';

  function escHtml(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showAwardErr(id, message) {
    var el = document.getElementById(id);
    el.textContent = message ? message : '';
    el.hidden = !message;
  }

  async function awardRequest(url, payload) {
    var options = { credentials: 'same-origin', headers: { Accept: 'application/json' } };
    if (payload) {
      options.method = 'POST';
      options.headers['Content-Type'] = 'application/json';
      options.headers['X-CSRF-Token'] = csrf;
      options.body = JSON.stringify(payload);
    }
    var response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      throw new Error(window.siteMessage('client.inline_events_form.network_request_failed_please_try_again'));
    }
    if (!(response.headers.get('content-type') || '').includes('application/json')) {
      throw new Error(window.siteMessage('client.inline_events_form.no_valid_response_check_that_you'));
    }
    var data = await response.json();
    if (!response.ok || data.ok !== true) throw new Error(data.error || window.siteMessage('client.inline_events_form.operation_failed'));
    return data;
  }

  function renderChampionship(data) {
    var stored = data.championship;
    var team = stored || data.candidate;
    champBadge.textContent = stored ? (stored.needs_review ? window.siteMessage('client.inline_events_form.needs_review') : window.siteMessage('client.inline_events_form.awarded')) : '';
    if (!team) {
      champBody.textContent = (data.blocked_reason || window.siteMessage('client.inline_events_form.the_final_has_not_been_officially'));
      return;
    }
    var identity = team.club_id
      ? '<a href="/teams/' + encodeURIComponent(team.club_id) + '">' + escHtml(window.siteMessage('client.inline_events_form.club')) + '</a>'
      : escHtml(window.siteMessage('client.inline_events_form.temp_team'));
    champBody.innerHTML = '<p><strong data-i18n-ignore>' + escHtml(team.team_name) + '</strong> · ' + identity + '</p>' +
      '<ol class="managed-award-players">' + team.players.map(function (p) {
        return '<li value="' + escHtml(p.roster_slot) + '"><span data-i18n-ignore>' + escHtml(p.nickname) + '</span></li>';
      }).join('') + '</ol>' +
      '<p class="field-hint"><a href="/admin/matches/' + encodeURIComponent(team.match_id) + '/operate#results">' +
        escHtml(window.siteMessage('client.inline_events_form.final_result')) + ' #' + escHtml(team.match_id) + '</a> · ' +
        escHtml(window.siteMessage('client.inline_events_form.official_settlement')) + ' #' + escHtml(team.settlement_id) + '</p>' +
      (stored ? '' : '<button type="button" class="btn btn-primary" id="awardManagedChampBtn">' + escHtml(window.siteMessage('client.inline_events_form.award_championship')) + '</button>');
    if (stored && data.blocked_reason) showAwardErr('managedChampError', data.blocked_reason);
    var btn = document.getElementById('awardManagedChampBtn');
    if (btn) btn.addEventListener('click', async function () {
      if (!await window.adminConfirm(window.siteMessage('client.inline_events_form.award_the_championship_to_this_team'))) return;
      showAwardErr('managedChampError', '');
      btn.disabled = true;
      btn.textContent = window.siteMessage('client.inline_events_form.saving');
      try {
        var saved = await awardRequest(champUrl, {
          match_id: team.match_id, settlement_id: team.settlement_id,
          player_ids: team.players.map(function (p) { return p.player_id; })
        });
        renderChampionship(saved);
        window.showToast(window.siteMessage('client.inline_events_form.championship_awarded'), 'success');
      } catch (error) {
        showAwardErr('managedChampError', error.message);
        await loadAwardSection(champUrl, champBody, renderChampionship);
      }
    });
  }

  var medalState = {
    candidates: [],
    candidateMap: {},
    mvpId: null,
    evpIds: [],
    savedMvpId: null,
    savedEvpIds: [],
    blockedReason: null,
    needsReview: false,
    awards: []
  };

  function syncMedalStateFromServer(data) {
    medalState.candidates = data.candidates || [];
    medalState.candidateMap = {};
    medalState.candidates.forEach(function (c) {
      medalState.candidateMap[c.player_id] = c;
    });
    medalState.awards = data.awards || [];
    medalState.blockedReason = data.blocked_reason || null;
    medalState.needsReview = Boolean(data.needs_review);
    var mvpRow = medalState.awards.find(function (a) { return String(a.type).toUpperCase() === 'MVP'; });
    var evpRows = medalState.awards.filter(function (a) { return String(a.type).toUpperCase() === 'EVP'; });
    medalState.mvpId = mvpRow ? mvpRow.player_id : null;
    medalState.savedMvpId = medalState.mvpId;
    medalState.evpIds = evpRows.map(function (a) { return a.player_id; });
    medalState.savedEvpIds = medalState.evpIds.slice();
  }

  function candidateLabel(player) {
    return escHtml(player.nickname + ' (' + player.team_name + ' · ' + window.siteMessage('client.inline_events_form.maps_played') + ': ' + player.maps + ')');
  }

  function renderMedals() {
    var cands = medalState.candidates;
    var awards = medalState.awards;

    if (!cands.length) {
      var blockedHtml = '<div class="managed-award-blocked">' +
        '<p>' + escHtml((medalState.blockedReason || window.siteMessage('client.inline_events_form.the_event_has_unfinished_matches_or'))) + '</p>';
      if (awards.length) {
        blockedHtml += '<ul class="managed-saved-medals">' +
          awards.map(function (a) {
            var label = String(a.type).toUpperCase() === 'MVP' ? 'MVP' : ('EVP #' + (a.evp_rank || '?'));
            return '<li>' + escHtml(label) + ' · <a href="/players/' + encodeURIComponent(a.player_id) + '" data-i18n-ignore>' + escHtml(a.nickname || '#' + a.player_id) + '</a></li>';
          }).join('') + '</ul>';
      }
      blockedHtml += '</div>';
      medalsBody.innerHTML = blockedHtml;
      return;
    }

    var warnHtml = medalState.needsReview
      ? '<p class="managed-award-warn" role="status">' + escHtml(window.siteMessage('client.inline_events_form.some_award_recipients_are_no_longer')) + '</p>'
      : '';

    var priorMvp = awards.find(a => a.type === 'MVP');
    var unavailableMvp = priorMvp && medalState.mvpId === priorMvp.player_id && !medalState.candidateMap[priorMvp.player_id];
    var mvpOptions = '<option value="">' + escHtml(window.siteMessage('client.inline_events_form.not_specified')) + '</option>' +
      (unavailableMvp ? '<option selected disabled value="' + priorMvp.player_id + '" data-i18n-ignore>' + escHtml(priorMvp.nickname || '#' + priorMvp.player_id) + '</option>' : '') +
      cands.map(function (c) {
        var sel = medalState.mvpId === c.player_id ? ' selected' : '';
        return '<option value="' + escHtml(c.player_id) + '" data-i18n-ignore' + sel + '>' + candidateLabel(c) + '</option>';
      }).join('');

    var mvpPosterHtml = (medalState.mvpId && medalState.savedMvpId === medalState.mvpId)
      ? ' <a class="managed-poster-link" target="_blank" rel="noopener" href="/events/' + encodeURIComponent(eventId) + '/award-poster/MVP/' + encodeURIComponent(medalState.mvpId) + '.png">' + escHtml(window.siteMessage('client.inline_events_form.view_mvp_poster')) + '</a>'
      : '';

    var evpListHtml = '';
    if (medalState.evpIds.length) {
      evpListHtml = '<ol class="managed-evp-list" id="managedEvpOrderList">' +
        medalState.evpIds.map(function (pid, idx) {
          var info = medalState.candidateMap[pid];
          var saved = awards.find(a => a.player_id === pid);
          var nameText = escHtml((info && info.nickname) || (saved && saved.nickname) || '#' + pid);
          var posterLink = medalState.savedEvpIds.includes(pid)
            ? '<a class="btn btn-sm btn-icon" target="_blank" rel="noopener" href="/events/' + encodeURIComponent(eventId) + '/award-poster/EVP/' + encodeURIComponent(pid) + '.png" title="' + escHtml(window.siteMessage('client.inline_events_form.view_evp_poster')) + '" aria-label="' + escHtml(window.siteMessage('client.inline_events_form.view_evp_poster')) + '">' + icons.image + '</a>'
            : '';
          var upDisabled = idx === 0 ? ' disabled' : '';
          var downDisabled = idx === medalState.evpIds.length - 1 ? ' disabled' : '';
          return '<li class="managed-evp-item" data-player-id="' + escHtml(pid) + '">' +
            '<span class="managed-evp-rank" data-i18n-ignore>#' + (idx + 1) + '</span>' +
            '<span class="managed-evp-name" data-i18n-ignore>' + nameText + '</span>' +
            '<div class="managed-evp-item-actions">' +
              posterLink +
              '<button type="button" class="btn btn-sm btn-icon" data-evp-move="up" data-idx="' + idx + '"' + upDisabled + ' title="' + escHtml(window.siteMessage('client.inline_events_form.move_up')) + '" aria-label="' + escHtml(window.siteMessage('client.inline_events_form.move_up')) + '">↑</button>' +
              '<button type="button" class="btn btn-sm btn-icon" data-evp-move="down" data-idx="' + idx + '"' + downDisabled + ' title="' + escHtml(window.siteMessage('client.inline_events_form.move_down')) + '" aria-label="' + escHtml(window.siteMessage('client.inline_events_form.move_down')) + '">↓</button>' +
              '<button type="button" class="btn btn-sm btn-icon" data-evp-remove="' + escHtml(pid) + '" title="' + escHtml(window.siteMessage('client.inline_events_form.remove')) + '" aria-label="' + escHtml(window.siteMessage('client.inline_events_form.remove')) + '">' + icons.close + '</button>' +
            '</div>' +
          '</li>';
        }).join('') +
      '</ol>';
    }

    var availableForEvp = cands.filter(function (c) {
      return medalState.evpIds.indexOf(c.player_id) === -1;
    });
    var evpAddOptions = '<option value="">' + escHtml(window.siteMessage('client.inline_events_form.select_player')) + '</option>' +
      availableForEvp.map(function (c) {
        return '<option value="' + escHtml(c.player_id) + '" data-i18n-ignore>' + candidateLabel(c) + '</option>';
      }).join('');

    medalsBody.innerHTML = warnHtml +
      '<fieldset class="managed-medals-editor">' +
        '<div class="field">' +
          '<div class="managed-field-head"><label class="field-label" for="managedMvpSelect">' + escHtml(window.siteMessage('client.inline_events_form.event_mvp')) + '</label>' + mvpPosterHtml + '</div>' +
          '<select id="managedMvpSelect">' + mvpOptions + '</select>' +
        '</div>' +
        '<div class="field">' +
          '<label class="field-label" for="managedEvpAddSelect">' + escHtml(window.siteMessage('client.inline_events_form.evp_announcement_order')) + '</label>' +
          evpListHtml +
          '<div class="managed-evp-add-row">' +
            '<select id="managedEvpAddSelect"' + (availableForEvp.length ? '' : ' disabled') + '>' + evpAddOptions + '</select>' +
            '<button type="button" class="btn btn-sm" id="managedEvpAddBtn" disabled>' + icons.plus + '' + escHtml(window.siteMessage('client.inline_events_form.add_evp')) + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="managed-award-actions">' +
          '<button type="button" class="btn btn-primary" id="saveManagedMedalsBtn">' + escHtml(window.siteMessage('client.inline_events_form.save_player_awards')) + '</button>' +
        '</div>' +
      '</fieldset>';

    var mvpSelect = document.getElementById('managedMvpSelect');
    if (mvpSelect) {
      mvpSelect.addEventListener('change', function () {
        var val = mvpSelect.value ? Number(mvpSelect.value) : null;
        medalState.mvpId = val;
        renderMedals();
        document.getElementById('managedMvpSelect').focus();
      });
    }

    var addSelect = document.getElementById('managedEvpAddSelect');
    var addBtn = document.getElementById('managedEvpAddBtn');
    if (addBtn && addSelect) {
      addSelect.addEventListener('change', function () { addBtn.disabled = !addSelect.value; });
      addBtn.addEventListener('click', function () {
        var pid = addSelect.value ? Number(addSelect.value) : null;
        if (!pid || medalState.evpIds.indexOf(pid) !== -1) return;
        medalState.evpIds.push(pid);
        renderMedals();
        document.getElementById('managedEvpAddSelect').focus();
      });
    }

    medalsBody.querySelectorAll('[data-evp-move]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var idx = Number(btn.getAttribute('data-idx'));
        var dir = btn.getAttribute('data-evp-move');
        var targetIdx = dir === 'up' ? idx - 1 : idx + 1;
        if (targetIdx < 0 || targetIdx >= medalState.evpIds.length) return;
        var tmp = medalState.evpIds[idx];
        medalState.evpIds[idx] = medalState.evpIds[targetIdx];
        medalState.evpIds[targetIdx] = tmp;
        renderMedals();
        var row = medalsBody.querySelector('[data-player-id="' + tmp + '"]');
        (row.querySelector('[data-evp-move="' + dir + '"]:enabled') || row.querySelector('[data-evp-move]:enabled')).focus();
      });
    });

    medalsBody.querySelectorAll('[data-evp-remove]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var pid = Number(btn.getAttribute('data-evp-remove'));
        medalState.evpIds = medalState.evpIds.filter(function (id) { return id !== pid; });
        renderMedals();
        document.getElementById('managedEvpAddSelect').focus();
      });
    });

    var saveBtn = document.getElementById('saveManagedMedalsBtn');
    if (saveBtn) {
      saveBtn.disabled = medalState.mvpId === medalState.savedMvpId &&
        medalState.evpIds.length === medalState.savedEvpIds.length &&
        medalState.evpIds.every(function (id, index) { return id === medalState.savedEvpIds[index]; });
      saveBtn.addEventListener('click', function () {
        submitMedals(saveBtn);
      });
    }
  }

  async function submitMedals(btn) {
    var editor = btn.closest('fieldset');
    showAwardErr('managedMedalsError', '');
    editor.disabled = true;
    btn.textContent = window.siteMessage('client.inline_events_form.saving');
    try {
      var data = await awardRequest(medalsUrl, {
        mvp_player_id: medalState.mvpId, evp_player_ids: medalState.evpIds
      });
      syncMedalStateFromServer(data);
      renderMedals();
      document.getElementById('managedMvpSelect').focus();
      window.showToast(window.siteMessage('client.inline_events_form.player_awards_saved'), 'success');
    } catch (error) {
      showAwardErr('managedMedalsError', error.message);
      editor.disabled = false;
      btn.textContent = window.siteMessage('client.inline_events_form.save_player_awards');
      btn.focus();
    }
  }

  async function loadAwardSection(url, body, render) {
    var data;
    try {
      data = await awardRequest(url);
    } catch (error) {
      body.textContent = error.message + ' ';
      var retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'btn btn-sm';
      retry.textContent = window.siteMessage('client.inline_events_form.retry');
      retry.onclick = function () { retry.disabled = true; loadAwardSection(url, body, render); };
      body.appendChild(retry);
      return;
    }
    render(data);
  }

  loadAwardSection(champUrl, champBody, renderChampionship);
  loadAwardSection(medalsUrl, medalsBody, function (data) {
    syncMedalStateFromServer(data);
    renderMedals();
  });
})();
