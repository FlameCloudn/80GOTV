(function () {
  'use strict';

  var EVENT_ID = window._eventId;
  var CSRF = window._csrfToken || (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var matches = Array.isArray(window._eventMatches) ? window._eventMatches : [];
  var links = Array.isArray(window._managedLinks) ? window._managedLinks : [];
  var entrants = Array.isArray(window._managedEntrants) ? window._managedEntrants : [];

  function tr(text) {
    return window.siteTranslate ? window.siteTranslate(String(text)) : String(text);
  }

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
      upcoming: '未开始',
      live: '进行中',
      ongoing: '进行中',
      completed: '已结束',
      cancelled: '已取消'
    }[st] || st || '-';
  }

  function showFeedback(msg, kind) {
    var el = document.getElementById('bracketFeedback');
    if (!el) return;
    el.hidden = false;
    el.className = 'ops-feedback is-' + (kind || 'info');
    el.textContent = tr(msg);
  }

  function showError(id, msg) {
    var el = document.getElementById(id);
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg ? tr(msg) : '';
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
        return { ok: false, data: { error: '未收到有效回复，请检查登录状态后重试' } };
      }
      var data = await res.json();
      return { ok: res.ok && data.ok === true, data: data };
    } catch (error) {
      return { ok: false, data: { error: '网络请求失败，请稍后重试' } };
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
      srcSel.innerHTML = '<option value="">暂无比赛</option>';
      tgtSel.innerHTML = '<option value="">暂无比赛</option>';
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
      box.innerHTML = '<p class="empty-state">尚未配置任何上下游晋级联动。</p>';
      return;
    }
    var html = '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      '<th>上游比赛</th><th>结果出口</th><th>下游比赛</th><th>目标签位</th><th>当前已晋级参赛队</th><th>联动状态</th>' +
    '</tr></thead><tbody>';
    links.forEach(function (lk) {
      html += '<tr>' +
        '<td><a href="/admin/matches/' + lk.source_match_id + '/operate" data-i18n-ignore>' + esc(matchLabel(lk.source_match_id)) + '</a></td>' +
        '<td><span class="badge ' + (lk.outcome === 'winner' ? 'badge-accent' : 'badge-gold') + '">' +
          (lk.outcome === 'winner' ? '胜者' : '败者') + '</span></td>' +
        '<td><a href="/admin/matches/' + lk.target_match_id + '/operate" data-i18n-ignore>' + esc(matchLabel(lk.target_match_id)) + '</a></td>' +
        '<td>' + (lk.target_side === 'home' ? '主队侧 (home)' : '客队侧 (away)') + '</td>' +
        '<td data-i18n-ignore>' + esc(entrantName(lk.event_entrant_id)) + '</td>' +
        '<td>' + (lk.detached
          ? '<span class="badge badge-gold">已保留脱离（结算 #' + esc(lk.detached_settlement_id) + '）</span>'
          : '<span class="badge badge-accent">正常联动</span>') + '</td>' +
      '</tr>';
    });
    html += '</tbody></table></div>';
    box.innerHTML = html;
  }

  function renderMatches() {
    var box = document.getElementById('managedMatchesContainer');
    var countEl = document.getElementById('managedMatchesCount');
    if (countEl) countEl.textContent = matches.length + ' 场';
    if (!matches.length) {
      box.innerHTML = '<p class="empty-state">本赛事尚无比赛。你可以在上方创建下游比赛，或前往比赛管理添加首轮比赛。</p>';
      return;
    }
    var html = '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      '<th>ID</th><th>阶段</th><th>赛制</th><th>对阵双方</th><th>大比分</th><th>状态</th><th class="num">操作</th>' +
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
          '<a class="btn btn-sm btn-primary" href="/admin/matches/' + m.id + '/operate">比赛运营</a> ' +
          '<a class="btn btn-sm" href="/admin/matches/edit/' + m.id + '">赛前配置</a>' +
        '</td>' +
      '</tr>';
    });
    html += '</tbody></table></div>';
    box.innerHTML = html;
  }

  async function refreshLinks() {
    var r = await apiJson('/admin/events/' + EVENT_ID + '/operations/bracket', { method: 'GET' });
    if (!r.ok) {
      showFeedback(r.data.error || '读取晋级联动失败', 'error');
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
      showError('createDownstreamError', '请填写阶段名称');
      return;
    }
    var payload = { stage: stage, bo_format: boFormat };
    if (matchTime) payload.match_time = matchTime.replace('T', ' ');
    var button = document.getElementById('createDownstreamBtn');
    button.disabled = true;
    var r = await apiJson('/admin/events/' + EVENT_ID + '/operations/bracket', { method: 'POST', json: payload });
    if (!r.ok) {
      button.disabled = false;
      showError('createDownstreamError', r.data.error || '创建下游比赛失败');
      return;
    }
    e.target.reset();
    if (await refreshLinks()) showFeedback(tr('已创建下游比赛') + ' #' + r.data.match_id, 'success');
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
      showError('configLinkError', '请选择有效的上下游比赛');
      return;
    }
    if (sourceId === targetId) {
      showError('configLinkError', '上游比赛和下游目标比赛不能是同一场');
      return;
    }
    var r = await apiJson('/admin/matches/' + sourceId + '/operations/bracket-link', {
      method: 'POST',
      json: { outcome: outcome, target_match_id: targetId, target_side: targetSide }
    });
    if (!r.ok) {
      showError('configLinkError', r.data.error || '配置晋级联动失败');
      return;
    }
    showFeedback('已保存晋级联动：Match #' + sourceId + ' (' + outcome + ') → Match #' + targetId + ' (' + targetSide + ')。', 'success');
    await refreshLinks();
  });

  document.getElementById('bracketRefreshBtn').addEventListener('click', function () {
    refreshLinks().then(function (ok) {
      if (ok) showFeedback('已刷新最新晋级联动状态', 'info');
    });
  });

  document.querySelectorAll('[data-stage-chip]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var input = document.getElementById('newMatchStage');
      if (!input) return;
      input.value = tr(chip.dataset.stageChip);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    });
  });

  populateSelects();
  renderLinks();
  renderMatches();
})();
