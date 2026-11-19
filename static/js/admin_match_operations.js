(function () {
  'use strict';

  var MATCH_ID = window.MATCH_OPS_MATCH_ID;
  var bundle = window.MATCH_OPS_BUNDLE || null;
  if (!MATCH_ID || !bundle) return;

  var CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  var STAT_GROUPS = [
    {
      title: '核心表现',
      fields: [
        ['rounds_played', '回合数'],
        ['kills', '击杀'],
        ['deaths', '死亡'],
        ['assists', '助攻'],
        ['damage', '总伤害'],
        ['adr', 'ADR'],
        ['kast', 'KAST (%)'],
        ['kast_rounds', 'KAST 回合数'],
        ['impact', 'Impact'],
        ['rating_impact', 'Rating Impact'],
        ['rating', 'Rating 2.0'],
        ['rws_basic', 'RWS'],
        ['damage_delta_per_round', '每回合净伤害']
      ]
    },
    {
      title: '开局与对枪',
      fields: [
        ['headshot_kills', '爆头击杀'],
        ['headshot_percentage', '爆头率 (%)'],
        ['first_kills', '首杀'],
        ['first_deaths', '首死'],
        ['trade_kills', '补枪击杀'],
        ['trade_deaths', '被补死亡'],
        ['mvp_count', '回合 MVP']
      ]
    },
    {
      title: '多杀与残局',
      fields: [
        ['multi1k', '1K'],
        ['multi2k', '2K'],
        ['multi3k', '3K'],
        ['multi4k', '4K'],
        ['multi5k', '5K'],
        ['clutches_won', '残局总胜'],
        ['clutch_1v1', '1v1'],
        ['clutch_1v2', '1v2'],
        ['clutch_1v3', '1v3'],
        ['clutch_1v4', '1v4'],
        ['clutch_1v5', '1v5']
      ]
    },
    {
      title: '道具与目标',
      fields: [
        ['utility_damage', '道具伤害'],
        ['utility_damage_per_round', '每回合道具伤害'],
        ['enemies_flashed', '致盲敌人数'],
        ['flash_assists', '闪光助攻'],
        ['flash_count', '投掷闪光数'],
        ['flash_enemy_seconds', '致盲敌人总时长(秒)'],
        ['flash_blinded_seconds', '被致盲总时长(秒)'],
        ['he_count', '手雷数'],
        ['smoke_count', '烟雾数'],
        ['molotov_count', '燃烧弹数'],
        ['bomb_plants', '下包次数'],
        ['bomb_defuses', '拆包次数']
      ]
    }
  ];

  var FIELD_LABELS = {};
  STAT_GROUPS.forEach(function (g) {
    g.fields.forEach(function (item) {
      FIELD_LABELS[item[0]] = item[1];
    });
  });

  var state = {
    tab: 'runs',
    demoAnalysesCache: {},
    activeAnalysis: null,
    statsTarget: { runId: null, playerId: null, scope: 'all' },
    statsLoaded: null,
    statsDraft: {},
    statsReason: '',
    statsRequest: 0,
    statsPreview: null,
    dialogPayload: {}
  };

  function tr(text) {
    return window.siteTranslate ? window.siteTranslate(String(text)) : String(text);
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtVal(value) {
    if (value === null || value === undefined || value === '') return '-';
    return String(value);
  }

  function fmtBytes(n) {
    var num = Number(n || 0);
    if (!Number.isFinite(num) || num <= 0) return '0 B';
    if (num < 1024) return num + ' B';
    if (num < 1024 * 1024) return (num / 1024).toFixed(1) + ' KB';
    return (num / (1024 * 1024)).toFixed(2) + ' MB';
  }

  function mapDisplay(name) {
    if (!name) return '-';
    return String(name).replace(/^(de_|cs_)/i, '').replace(/_/g, ' ').replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  function playerLabel(playerId) {
    var p = (bundle.context.players || {})[String(playerId)];
    return p ? p.nickname : '#' + playerId;
  }

  function playerSteam(playerId) {
    var p = (bundle.context.players || {})[String(playerId)];
    return p && p.steam_id ? p.steam_id : '';
  }

  function adminLabel(actor) {
    if (actor === null || actor === undefined || actor === '') return '-';
    var name = (bundle.context.admins || {})[String(actor)];
    return name || '#' + actor;
  }

  function entrantLabel(entrantId) {
    if (entrantId === null || entrantId === undefined || entrantId === '') return 'TBD';
    var e = (bundle.context.entrants || {})[String(entrantId)];
    return e ? e.name : '#' + entrantId;
  }

  function participantById(pid) {
    return (bundle.context.participants || []).find(function (p) {
      return Number(p.match_participant_id) === Number(pid);
    }) || null;
  }

  function sideName(sideKey) {
    var list = bundle.context.participants || [];
    var found = list.find(function (p) { return p.side_key === sideKey; });
    return found ? found.name : (sideKey === 'home' ? '主队' : '客队');
  }

  function homeName() { return sideName('home'); }
  function awayName() { return sideName('away'); }

  function statusLabel(st) {
    return {
      upcoming: '未开始',
      live: '进行中',
      ongoing: '进行中',
      completed: '已结束',
      cancelled: '已取消'
    }[st] || st || '-';
  }

  function runStatusBadge(st) {
    if (st === 'active') return '<span class="badge badge-live">进行中 (active)</span>';
    if (st === 'closed') return '<span class="badge badge-accent">已结束 (closed)</span>';
    if (st === 'void') return '<span class="badge badge-danger">已作废 (void)</span>';
    return '<span class="badge">' + esc(st) + '</span>';
  }

  function sourceKindLabel(kind) {
    return { demo: 'Demo', director: '导播', admin: '管理员' }[kind] || kind || '-';
  }

  function showFeedback(message, kind) {
    var el = document.getElementById('opsFeedback');
    if (!el) return;
    el.hidden = false;
    el.className = 'ops-feedback is-' + (kind || 'info');
    el.textContent = tr(message);
    if (kind === 'success') {
      window.clearTimeout(showFeedback._timer);
      showFeedback._timer = window.setTimeout(function () {
        el.hidden = true;
      }, 6000);
    }
  }

  function clearError(id) {
    var el = document.getElementById(id);
    if (el) {
      el.hidden = true;
      el.textContent = '';
    }
  }

  function showError(id, msg) {
    var el = document.getElementById(id);
    if (el) {
      el.hidden = false;
      el.textContent = tr(msg || '操作失败');
    }
  }

  function openDialog(id) {
    var dlg = document.getElementById(id);
    if (dlg && typeof dlg.showModal === 'function') {
      if (!dlg.open) dlg.showModal();
    }
  }

  function closeDialog(id) {
    var dlg = document.getElementById(id);
    if (dlg && dlg.open) dlg.close();
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
        return { ok: false, status: res.status, data: { error: '未收到有效回复，请检查登录状态后重试' } };
      }
      var data = await res.json();
      return { status: res.status, ok: res.ok && data.ok !== false, data: data };
    } catch (error) {
      return { ok: false, status: 0, data: { error: '网络请求失败，请稍后重试' } };
    }
  }

  async function refreshBundle(quiet) {
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/panel-context', { method: 'GET' });
    if (!r.ok) {
      showFeedback(r.data.error || '刷新比赛状态失败', 'error');
      return false;
    }
    bundle = {
      context: r.data.context,
      overview: r.data.overview,
      history: r.data.history,
      originals: r.data.originals
    };
    renderAll();
    if (!quiet) showFeedback('已刷新比赛最新状态', 'info');
    return true;
  }

  /* ==================== Tab 切换 ==================== */
  function setActiveTab(tabName, updateHash) {
    var valid = ['runs', 'demos', 'results', 'stats'];
    if (valid.indexOf(tabName) === -1) tabName = 'runs';
    state.tab = tabName;
    document.querySelectorAll('[data-ops-tab]').forEach(function (btn) {
      var active = btn.dataset.opsTab === tabName;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
      btn.tabIndex = active ? 0 : -1;
    });
    document.querySelectorAll('[data-ops-pane]').forEach(function (pane) {
      var active = pane.dataset.opsPane === tabName;
      pane.hidden = !active;
      pane.classList.toggle('active', active);
    });
    if (updateHash) {
      try {
        history.replaceState(null, '', '#' + tabName);
      } catch (_e) {}
    }
    if (tabName === 'stats' && !state.statsLoaded && state.statsTarget.runId && state.statsTarget.playerId) {
      loadStatsTarget();
    }
    if (tabName === 'results') loadLiveReference();
  }

  /* ==================== 顶部状态总览 ==================== */
  function renderSummary() {
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

    document.getElementById('opsSummaryTop').innerHTML =
      '<div class="ops-score-banner">' +
        '<span class="ops-score-team" data-i18n-ignore>' + esc(homeName()) + '</span>' +
        '<strong class="ops-score-num" title="已确认地图胜场">' + esc(fmtVal(res.score1)) + ' : ' + esc(fmtVal(res.score2)) + '</strong>' +
        '<span class="ops-score-team" data-i18n-ignore>' + esc(awayName()) + '</span>' +
      '</div>' +
      '<div class="ops-summary-badges">' +
        '<span class="badge ' + statusCls + '">' + esc(statusLabel(match.status)) + '</span>' +
        '<span class="badge">' + esc(match.bo_format || 'BO3') + '</span>' +
        '<span class="badge">' + (settled ? '已正式完赛' : '尚未完赛') + '</span>' +
        '<span class="badge" data-i18n-ignore>Series Rev ' + esc(res.revision || 0) + '</span>' +
      '</div>';

    var bpLabel = match.bp_status === 'completed' ? '已完成'
      : (match.bp_status === 'in_progress' ? '进行中' : '未完成');
    var bpCls = match.bp_status === 'completed' ? 'is-ok' : 'is-warn';
    var rosterCls = match.rosters_frozen ? 'is-ok' : 'is-warn';
    var authLabel = ov.ready_for_start ? '已授权，可开赛'
      : (ov.eligible && !ov.authorized ? '已具备资格，待管理员授权'
      : (ov.authorized ? '已授权（当前不可开新局）' : '未达开赛条件'));
    var authCls = ov.ready_for_start ? 'is-ok' : (ov.eligible ? 'is-pending' : 'is-warn');
    var runsText = allRuns.length
      ? ('共 ' + allRuns.length + ' 局（有效 ' + activeCount + ' / 作废 ' + voidCount + '）')
      : '尚无实际开局';

    document.getElementById('opsGateGrid').innerHTML =
      '<div class="ops-gate-item ' + rosterCls + '">' +
        '<span class="ops-gate-label">1. 本场阵容</span>' +
        '<strong>' + (match.rosters_frozen ? '已冻结（10 人）' : '未冻结') + '</strong>' +
      '</div>' +
      '<div class="ops-gate-item ' + bpCls + '">' +
        '<span class="ops-gate-label">2. 地图 BP</span>' +
        '<strong>' + esc(bpLabel) + '</strong>' +
      '</div>' +
      '<div class="ops-gate-item ' + authCls + '">' +
        '<span class="ops-gate-label">3. 开赛资格与授权</span>' +
        '<strong>' + esc(authLabel) + '</strong>' +
      '</div>' +
      '<div class="ops-gate-item ' + (allRuns.length ? 'is-ok' : 'is-neutral') + '">' +
        '<span class="ops-gate-label">4. 实际开局记录</span>' +
        '<strong>' + esc(runsText) + '</strong>' +
      '</div>';
  }

  /* ==================== Tab 1: 开赛授权、阵容与局次 ==================== */
  function renderAuthCard() {
    var ov = bundle.overview;
    var match = bundle.context.match;
    var badge = document.getElementById('opsAuthBadge');
    if (ov.ready_for_start) {
      badge.className = 'badge badge-accent';
      badge.textContent = '已授权可开赛';
    } else if (ov.eligible && !ov.authorized) {
      badge.className = 'badge badge-gold';
      badge.textContent = '等待授权';
    } else if (ov.authorized) {
      badge.className = 'badge';
      badge.textContent = '已授权';
    } else {
      badge.className = 'badge badge-danger';
      badge.textContent = '未就绪';
    }

    var authInfo = match.authorized_at
      ? ('已于 <span data-i18n-ignore>' + esc(match.authorized_at) + '</span> 由 <strong data-i18n-ignore>' + esc(match.authorized_by_name || '-') + '</strong> 授权开赛。授权后赛前竞猜自动关闭，导播端和管理员均可登记实际开局。')
      : (ov.eligible
        ? '本场名单已冻结且 BP 排图完整，已具备开赛资格。请确认赛前准备就绪后显式授权开赛；授权后赛前竞猜将关闭。'
        : '当前尚不满足开赛条件：<strong>' + esc(ov.reason || '请先冻结本场阵容并完成 BP') + '</strong>');

    var btnHtml = '';
    if (!ov.authorized) {
      btnHtml = '<button type="button" class="btn btn-primary" id="opsAuthorizeBtn"' +
        (ov.eligible ? '' : ' disabled') + '>授权本场开赛</button>';
    }

    document.getElementById('opsAuthBody').innerHTML =
      '<div class="ops-auth-row">' +
        '<div>' +
          '<p class="ops-auth-desc">' + authInfo + '</p>' +
          '<div class="ops-flag-list">' +
            '<span class="ops-flag ' + (ov.eligible ? 'is-true' : 'is-false') + '">开赛资格：' + (ov.eligible ? '满足' : '不满足') + '</span>' +
            '<span class="ops-flag ' + (ov.authorized ? 'is-true' : 'is-false') + '">管理员授权：' + (ov.authorized ? '已授权' : '未授权') + '</span>' +
            '<span class="ops-flag ' + (ov.ready_for_start ? 'is-true' : 'is-false') + '">当前可登记开局：' + (ov.ready_for_start ? '是' : '否') + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="ops-auth-actions">' + btnHtml + '</div>' +
      '</div>';

    var authBtn = document.getElementById('opsAuthorizeBtn');
    if (authBtn) {
      authBtn.addEventListener('click', handleAuthorize);
    }
  }

  async function handleAuthorize() {
    var ok = await window.showConfirm(tr('确定授权本场比赛开赛吗？授权后赛前预测将关闭，且不能再修改 BP 排图。'), tr('授权开赛'));
    if (!ok) return;
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/authorize', { method: 'POST', json: {} });
    if (!r.ok) {
      showFeedback(r.data.error || '授权开赛失败', 'error');
      return;
    }
    showFeedback('已授权本场比赛开赛，现在可为排定赛图登记实际开局。', 'success');
    await refreshBundle(true);
  }

  function renderFrozenRoster() {
    var parts = bundle.context.participants || [];
    if (!parts.length) {
      document.getElementById('opsFrozenRosterBody').innerHTML = '<p class="empty-state">尚未绑定参赛双方。</p>';
      return;
    }
    var html = '<div class="ops-two-col">';
    parts.forEach(function (side) {
      var initialSet = new Set(side.initial_player_ids || []);
      html += '<div class="ops-subcard">' +
        '<div class="ops-subcard-head">' +
          '<strong data-i18n-ignore>' + esc(side.name) + '</strong>' +
          '<span class="badge ' + (side.frozen ? 'badge-accent' : 'badge-gold') + '">' +
            (side.frozen ? '已冻结' : '未冻结') +
          '</span>' +
        '</div>' +
        '<ol class="ops-mini-roster">';
      (side.players || []).forEach(function (p) {
        var isInit = initialSet.has(p.id);
        html += '<li>' +
          '<span class="ops-slot">' + esc(p.slot) + '</span>' +
          '<span class="ops-pname" data-i18n-ignore>' + esc(p.nickname) + '</span>' +
          '<span class="ops-steam" data-i18n-ignore>' + esc(p.steam_id || '-') + '</span>' +
          '<span class="badge">' + (isInit ? '初始五人' : '赛前替补') + '</span>' +
        '</li>';
      });
      html += '</ol>';
      var reserves = side.assigned_reserves || [];
      html += '<div class="ops-reserves-line"><span>本队可用候补席：</span>';
      if (reserves.length) {
        reserves.forEach(function (res) {
          html += '<span class="badge" data-i18n-ignore>' + esc(res.nickname) + '</span> ';
        });
      } else {
        html += '<span class="muted">无</span>';
      }
      html += '</div></div>';
    });
    html += '</div>';
    document.getElementById('opsFrozenRosterBody').innerHTML = html;
  }

  function renderMapsAndRuns() {
    var maps = bundle.overview.maps || [];
    var resultsByMap = {};
    ((bundle.overview.results || {}).maps || []).forEach(function (rm) {
      resultsByMap[rm.scheduled_map_id] = rm;
    });

    if (!maps.length) {
      document.getElementById('opsMapsContainer').innerHTML =
        '<p class="empty-state">尚未生成排定赛图（Scheduled Maps）。请先在赛前配置或 BP 房间完成地图排定。</p>';
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
        ? '<span class="badge badge-accent">正式赛果 ' + esc(resInfo.score1) + ' : ' + esc(resInfo.score2) + '（Rev ' + esc(resInfo.revision) + '）</span>'
        : '<span class="badge">尚无正式赛果</span>';

      // Build Effective Roster summary grouped by side
      var effHome = (m.effective_roster || []).filter(function (r) { return r.side_key === 'home'; });
      var effAway = (m.effective_roster || []).filter(function (r) { return r.side_key === 'away'; });

      html += '<article class="ops-map-card" data-scheduled-map-id="' + m.scheduled_map_id + '">' +
        '<div class="ops-map-head">' +
          '<div class="ops-map-title-group">' +
            '<span class="ops-map-order">图 ' + esc(m.map_order) + '</span>' +
            '<h3 data-i18n-ignore>' + esc(mapDisplay(m.map_name)) + '</h3>' +
            '<span class="muted" data-i18n-ignore>ScheduledMap #' + esc(m.scheduled_map_id) + '</span>' +
            officialBadge +
          '</div>' +
          '<div class="ops-map-actions">';

      if (canStartFirst) {
        html += '<button type="button" class="btn btn-sm btn-primary" data-action="open-start-run" data-map-id="' + m.scheduled_map_id + '">登记实际开局</button>';
      } else if (canStartReplay) {
        html += '<button type="button" class="btn btn-sm btn-primary" data-action="open-start-run" data-map-id="' + m.scheduled_map_id + '" data-prev-run-id="' + latestRun.map_run_id + '">开启重赛新局（承接 #' + latestRun.map_run_id + '）</button>';
      } else if (!activeOrClosed.length && !bundle.overview.ready_for_start) {
        html += '<span class="muted">需先满足开赛条件并完成授权</span>';
      }

      html += '</div></div>';

      // Effective roster strip
      html += '<div class="ops-effective-strip">' +
        '<div class="ops-effective-label">本图当前有效阵容（Effective Roster）：</div>' +
        '<div class="ops-effective-sides">';
      [[homeName(), effHome], [awayName(), effAway]].forEach(function (pair) {
        html += '<div class="ops-eff-side"><strong data-i18n-ignore>' + esc(pair[0]) + '</strong>：';
        if (pair[1].length) {
          pair[1].forEach(function (ep) {
            var isTechSub = !frozenIds.has(ep.player_id);
            html += '<span class="ops-eff-chip' + (isTechSub ? ' is-sub' : '') + '">' +
              '<span data-i18n-ignore>' + esc(playerLabel(ep.player_id)) + '</span>' +
              (isTechSub ? ' <em>技术替补</em>' : '') +
              '</span>';
          });
        } else {
          html += '<span class="muted">待冻结阵容</span>';
        }
        html += '</div>';
      });
      html += '</div></div>';

      if (needsReplayStart) {
        html += '<div class="ops-callout-warn">上一局（#' + esc(latestRun.map_run_id) + '）已因技术重赛作废。请点击右上角“开启重赛新局”登记重赛开局，系统会自动关联作废局并沿用最新有效阵容。</div>';
      }

      // Runs list
      if (!runs.length) {
        html += '<p class="ops-empty-inline">这张排定赛图尚未登记实际开局。</p>';
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
                '<span class="badge">第 ' + esc(run.attempt_no) + ' 次开局</span>' +
                runStatusBadge(run.status) +
                (run.previous_map_run_id
                  ? '<span class="badge badge-gold">重赛承接 #' + esc(run.previous_map_run_id) + '</span>'
                  : '') +
              '</div>' +
              '<div class="ops-run-actions">' +
                '<button type="button" class="btn btn-sm" data-action="view-receipts" data-run-id="' + run.map_run_id + '">导播回执</button>';
          var writable = !isVoid && !bundle.context.match.event_archived && bundle.context.match.status !== 'cancelled';
          var unrecordedCount = (run.lineup || []).filter(function (lp) { return !partByPlayer[lp.player_id]; }).length;
          if (writable) {
            if (run.status === 'active') html += '<button type="button" class="btn btn-sm" data-action="bind-director" data-run-id="' + run.map_run_id + '" data-map-id="' + m.scheduled_map_id + '">绑定导播会话</button>';
            html += '<button type="button" class="btn btn-sm" data-action="open-participation" data-run-id="' + run.map_run_id + '">登记出场</button>';
            if (unrecordedCount > 1) {
              html += '<button type="button" class="btn btn-sm" data-action="open-batch-participation" data-run-id="' + run.map_run_id + '">批量登记出场</button>';
            }
            if (!maps.some(function (later) { return later.map_order > m.map_order && later.runs.length; })) {
              html += '<button type="button" class="btn btn-sm btn-danger" data-action="open-tech-replay" data-run-id="' + run.map_run_id + '" data-map-id="' + m.scheduled_map_id + '">批准技术重赛</button>';
            }
          }
          html += '</div></div>';

          html += '<div class="ops-run-meta">' +
            '<span>来源：<strong data-i18n-ignore>' + esc(run.source || '-') + '</strong></span>' +
            '<span>开局时间：<span data-i18n-ignore>' + esc(run.started_at || '-') + '</span></span>' +
            '<span>现场依据：<span data-i18n-ignore>' + esc(run.start_evidence || '-') + '</span></span>' +
          '</div>';

          if (sessions.length) {
            html += '<div class="ops-director-bar"><span>已绑定导播会话：</span>';
            sessions.forEach(function (ds) {
              html += '<span class="ops-session-chip" title="' + esc(ds.reason || '') + '">' +
                '<code data-i18n-ignore>' + esc(ds.session_id) + '</code>' +
                ' <small data-i18n-ignore>(' + esc(ds.bound_at || '') + ')</small></span>';
            });
            html += '</div>';
          }

          if (run.replay) {
            html += '<div class="ops-replay-callout">' +
              '<strong>技术重赛作废记录：</strong>' +
              '<span data-i18n-ignore>' + esc(run.replay.reason || '-') + '</span>' +
              ' · 操作人：<span data-i18n-ignore>' + esc(adminLabel(run.replay.admin_id)) + '</span>';
            if (run.replay.outgoing_player_id && run.replay.incoming_player_id) {
              html += '<br><strong>技术替补：</strong><span data-i18n-ignore>' +
                esc(playerLabel(run.replay.outgoing_player_id)) + ' → ' +
                esc(playerLabel(run.replay.incoming_player_id)) +
                '</span>（重赛新局与本场后续地图自动沿用该替补）';
            }
            html += '</div>';
          }

          // Lineup vs actual participations table
          html += '<details class="ops-lineup-details"' + (isVoid ? '' : ' open') + '>' +
            '<summary>本局批准名单与实际出场（已确认 ' +
              (run.participations || []).filter(function (rp) { return rp.is_current; }).length +
              ' / ' + (run.lineup || []).length + ' 人）</summary>' +
            '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
              '<th>阵营 / 参赛队</th><th>选手</th><th>Steam ID</th><th>出场状态</th><th>来源 / 版本 / 依据</th><th class="num">操作</th>' +
            '</tr></thead><tbody>';

          (run.lineup || []).forEach(function (lp) {
            var party = participantById(lp.match_participant_id);
            var rp = partByPlayer[lp.player_id] || null;
            var statusHtml = !rp
              ? '<span class="badge">未登记出场</span>'
              : (rp.is_current
                ? '<span class="badge badge-accent">已确认出场</span>'
                : '<span class="badge badge-danger">已撤回出场</span>');
            var detailText = rp
              ? ('<span data-i18n-ignore>' + esc(rp.source) + ' · Rev ' + esc(rp.revision) + '</span>' +
                 (rp.reason ? ' · <span data-i18n-ignore>' + esc(rp.reason) + '</span>' : ''))
              : '<span class="muted">仅在批准名单，尚未确认上场</span>';

            var rowActions = '';
            if (writable) {
              if (!rp) {
                rowActions = '<button type="button" class="btn btn-sm" data-action="quick-participation" data-run-id="' + run.map_run_id + '" data-player-id="' + lp.player_id + '" data-party-id="' + lp.match_participant_id + '">登记出场</button>';
              } else if (rp.is_current) {
                rowActions =
                  '<button type="button" class="btn btn-sm" data-action="jump-stats" data-run-id="' + run.map_run_id + '" data-player-id="' + lp.player_id + '">修订统计</button> ' +
                  '<button type="button" class="btn btn-sm btn-warning" data-action="review-participation" data-part-id="' + rp.participation_id + '" data-present="0" data-rev="' + rp.revision + '" data-player-name="' + esc(playerLabel(lp.player_id)) + '">撤回</button>';
              } else {
                rowActions = '<button type="button" class="btn btn-sm" data-action="review-participation" data-part-id="' + rp.participation_id + '" data-present="1" data-rev="' + rp.revision + '" data-player-name="' + esc(playerLabel(lp.player_id)) + '">恢复出场</button>';
              }
            } else {
              rowActions = '<span class="muted">只读</span>';
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
    document.getElementById('opsMapsContainer').innerHTML = html;
  }

  /* ==================== Tab 2: Demo 上传、解析与选择性采纳 ==================== */
  function populateDemoUploadSelectors() {
    var mapSel = document.getElementById('demoUploadMapSelect');
    var runSel = document.getElementById('demoUploadRunSelect');
    var maps = bundle.overview.maps || [];
    var prevMap = mapSel.value;
    mapSel.innerHTML = '';
    if (!maps.length) {
      mapSel.innerHTML = '<option value="">暂无排定赛图</option>';
      runSel.innerHTML = '<option value="">暂无实际开局</option>';
      document.getElementById('demoUploadSubmitBtn').disabled = true;
      return;
    }
    maps.forEach(function (m) {
      var opt = document.createElement('option');
      opt.value = String(m.scheduled_map_id);
      opt.textContent = '图 ' + m.map_order + ' · ' + mapDisplay(m.map_name) + ' (#' + m.scheduled_map_id + ')';
      mapSel.appendChild(opt);
    });
    if (prevMap && maps.some(function (m) { return String(m.scheduled_map_id) === prevMap; })) {
      mapSel.value = prevMap;
    }
    updateDemoUploadRuns();
  }

  function updateDemoUploadRuns() {
    var mapId = Number(document.getElementById('demoUploadMapSelect').value);
    var runSel = document.getElementById('demoUploadRunSelect');
    var btn = document.getElementById('demoUploadSubmitBtn');
    var mapObj = (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === mapId; });
    var runs = (mapObj && mapObj.runs) || [];
    runSel.innerHTML = '';
    if (!runs.length) {
      runSel.innerHTML = '<option value="">该图尚无实际开局，请先登记开局</option>';
      btn.disabled = true;
      return;
    }
    btn.disabled = false;
    runs.forEach(function (r) {
      var opt = document.createElement('option');
      opt.value = String(r.map_run_id);
      var suffix = r.status === 'void' ? tr(' [已作废 · 仅留档]') : ' [' + r.status + ']';
      opt.textContent = 'Run #' + r.map_run_id + ' · ' + tr('第 ' + r.attempt_no + ' 次开局') + suffix;
      runSel.appendChild(opt);
    });
    var preferred = runs.find(function (r) { return r.status !== 'void'; }) || runs[runs.length - 1];
    if (preferred) runSel.value = String(preferred.map_run_id);
  }

  function renderDemosList() {
    var originals = bundle.originals || [];
    var box = document.getElementById('opsDemosList');
    if (!originals.length) {
      box.innerHTML = '<p class="empty-state">本场比赛尚未上传原始 Demo。</p>';
      return;
    }
    var html = '<div class="table-wrap"><table class="table"><thead><tr>' +
      '<th>Demo #</th><th>排定赛图 / 局次</th><th>局次状态</th><th>大小</th><th>上传信息</th><th class="num">操作</th>' +
    '</tr></thead><tbody>';

    originals.forEach(function (orig) {
      var cached = state.demoAnalysesCache[orig.demo_id] || null;
      var isVoid = orig.run_status === 'void';
      html += '<tr>' +
        '<td data-i18n-ignore>#' + esc(orig.demo_id) + '</td>' +
        '<td><span>' + esc(tr('图 ' + orig.map_order)) + '</span> · <span data-i18n-ignore>' + esc(mapDisplay(orig.map_name)) + ' · Run #' + esc(orig.map_run_id) + '</span>' +
          (orig.download_default ? ' <span class="badge badge-accent">已指定前台下载</span>' : '') + '</td>' +
        '<td>' + runStatusBadge(orig.run_status) + (isVoid ? '<div class="cell-sub">作废局原档仅支持审计下载，不可采纳为正式统计</div>' : '') + '</td>' +
        '<td class="mono">' + esc(fmtBytes(orig.byte_count)) + '</td>' +
        '<td><span data-i18n-ignore>' + esc(adminLabel(orig.uploaded_by)) + '</span><div class="cell-sub" data-i18n-ignore>' + esc(orig.uploaded_at || '-') + '</div></td>' +
        '<td class="num ops-row-btns">' +
          '<a class="btn btn-sm" href="/admin/matches/' + MATCH_ID + '/api/demos/' + orig.demo_id + '/file">下载原档</a> ' +
          '<button type="button" class="btn btn-sm" data-action="parse-demo" data-demo-id="' + orig.demo_id + '">' + (cached && cached.length ? '重新解析' : '发起解析') + '</button> ' +
          '<button type="button" class="btn btn-sm" data-action="toggle-analyses" data-demo-id="' + orig.demo_id + '">解析历史</button>' +
        '</td>' +
      '</tr>';

      if (cached) {
        html += '<tr class="ops-analyses-subrow"><td colspan="6">';
        if (!cached.length) {
          html += '<span class="muted">尚无解析任务，请点击“发起解析”。</span>';
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
                  ? '<button type="button" class="btn btn-sm btn-primary" data-action="preview-analysis" data-analysis-id="' + job.analysis_id + '">预览并选择采纳</button>'
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
    var fileInput = document.getElementById('demoUploadFile');
    if (!fileInput.files || !fileInput.files.length) {
      showError('demoUploadError', '请选择一个 .dem 录像文件');
      return;
    }
    var fd = new FormData();
    fd.append('scheduled_map_id', document.getElementById('demoUploadMapSelect').value);
    fd.append('map_run_id', document.getElementById('demoUploadRunSelect').value);
    fd.append('demo', fileInput.files[0]);

    var btn = document.getElementById('demoUploadSubmitBtn');
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
        showError('demoUploadError', data.error || ('上传失败（HTTP ' + res.status + '）'));
        return;
      }
      fileInput.value = '';
      showFeedback(
        data.duplicate
          ? '该原始 Demo 已存在（Demo #' + data.original.demo_id + '），保留原档未重复写入。'
          : '原始 Demo 上传成功（Demo #' + data.original.demo_id + '）。',
        'success'
      );
      await refreshBundle(true);
    } catch (_err) {
      showError('demoUploadError', '网络请求失败，请稍后重试');
    } finally {
      btn.disabled = false;
    }
  }

  async function loadDemoAnalyses(demoId) {
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/api/demos/' + demoId, { method: 'GET' });
    if (!r.ok) {
      showFeedback(r.data.error || '读取解析记录失败', 'error');
      return;
    }
    state.demoAnalysesCache[demoId] = (r.data.original && r.data.original.analyses) || [];
    renderDemosList();
  }

  async function triggerDemoParse(demoId) {
    showFeedback('正在解析 Demo #' + demoId + '，请稍候…', 'info');
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/api/demos/' + demoId + '/parse', { method: 'POST', json: {} });
    await loadDemoAnalyses(demoId);
    if (!r.ok) {
      showFeedback(r.data.error || 'Demo 解析未成功，请在解析历史中查看详细错误', 'error');
      return;
    }
    showFeedback('Demo #' + demoId + ' 解析完成（Analysis #' + r.data.analysis_id + '）', 'success');
    if (r.data.status === 'ready' && r.data.analysis_id) {
      await openAnalysisPreview(r.data.analysis_id);
    }
  }

  async function openAnalysisPreview(analysisId, keepChoices) {
    var body = document.getElementById('opsDemoPreviewBody');
    var checked = keepChoices ? new Set(Array.from(body.querySelectorAll('input[data-review]:checked'), cb => cb.dataset.review)) : null;
    var reason = keepChoices ? document.getElementById('demoAdoptReason').value : '';
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/api/demos/analyses/' + analysisId, { method: 'GET' });
    if (!r.ok) {
      showFeedback(r.data.error || '读取解析预览失败', 'error');
      return;
    }
    state.activeAnalysis = r.data.analysis;
    renderAnalysisPreview();
    if (keepChoices) {
      body.querySelectorAll('input[data-review]:not(:disabled)').forEach(cb => { cb.checked = checked.has(cb.dataset.review); });
      document.getElementById('demoAdoptReason').value = reason;
      showFeedback('已刷新差异。只保留依据未变的勾选项，请重新核对。', 'info');
    }
    var panel = document.getElementById('opsDemoPreviewPanel');
    panel.hidden = false;
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderAnalysisPreview() {
    var a = state.activeAnalysis;
    var panel = document.getElementById('opsDemoPreviewPanel');
    if (!a) {
      panel.hidden = true;
      return;
    }
    document.getElementById('opsDemoPreviewTitle').textContent =
      tr('Demo 解析预览与选择性采纳') + ' · Analysis #' + a.analysis_id + ' (Demo #' + a.original.demo_id + ')';

    var html = '';
    if (a.blocks && a.blocks.length) {
      html += '<div class="ops-callout-danger"><strong>存在硬性阻断，当前不能采纳：</strong><ul>';
      a.blocks.forEach(function (b) { html += '<li>' + esc(b) + '</li>'; });
      html += '</ul></div>';
    }
    if (a.stats_block) {
      html += '<div class="ops-callout-warn"><strong>统计字段与默认下载暂不可采纳：</strong>' + esc(a.stats_block) + '</div>';
    }

    var cand = a.candidate_score || {};
    var off = a.official_result || null;
    var scoreMismatch = off && cand.score1 != null && cand.score2 != null &&
      (Number(cand.score1) !== Number(off.score1) || Number(cand.score2) !== Number(off.score2));

    var mapA = a.mapping && a.mapping.A ? participantById(a.mapping.A) : null;
    var mapB = a.mapping && a.mapping.B ? participantById(a.mapping.B) : null;

    html += '<div class="ops-preview-meta-grid">' +
      '<div class="ops-subcard">' +
        '<div class="ops-subcard-head"><strong>地图与双方映射</strong></div>' +
        '<p>解析地图：<strong data-i18n-ignore>' + esc(mapDisplay(a.map_name)) + '</strong> · 关联 <span data-i18n-ignore>Run #' + esc(a.original.map_run_id) + '</span></p>' +
        '<p>录像 A 队 → <strong data-i18n-ignore>' + esc(mapA ? mapA.name : tr('未映射')) + '</strong></p>' +
        '<p>录像 B 队 → <strong data-i18n-ignore>' + esc(mapB ? mapB.name : tr('未映射')) + '</strong></p>' +
      '</div>' +
      '<div class="ops-subcard">' +
        '<div class="ops-subcard-head"><strong>比分核对（Demo 候选 vs 正式赛果）</strong></div>' +
        '<p>Demo 候选比分：<strong>' + esc(fmtVal(cand.score1)) + ' : ' + esc(fmtVal(cand.score2)) + '</strong></p>' +
        '<p>当前正式赛果：' + (off
          ? '<strong>' + esc(off.score1) + ' : ' + esc(off.score2) + '</strong>（Rev ' + esc(off.revision) + '）'
          : '<span class="muted">尚未确认单图正式赛果</span>') + '</p>' +
        (scoreMismatch ? '<p class="ops-err-text">候选比分与当前正式赛果不一致，请先在“赛果、结算与竞猜”核对正式赛果。</p>' : '') +
      '</div>' +
    '</div>';

    // Bulk selection buttons
    var blocked = Boolean(a.blocks && a.blocks.length);
    var statsBlocked = Boolean(a.stats_block);
    html += '<div class="ops-adopt-toolbar">' +
      '<button type="button" class="btn btn-sm" id="demoSelectSafeBtn"' + (blocked ? ' disabled' : '') + '>全选无冲突新值</button>' +
      '<button type="button" class="btn btn-sm" id="demoSelectAllBtn"' + (blocked ? ' disabled' : '') + '>全选含冲突覆盖</button>' +
      '<button type="button" class="btn btn-sm" id="demoClearSelectBtn">清空勾选</button>' +
    '</div>';

    // Players diffs table
    var playersObj = a.players || {};
    var steamIds = Object.keys(playersObj);
    html += '<div class="ops-adopt-players">';
    steamIds.forEach(function (steamId) {
      var p = playersObj[steamId];
      var matched = p.lineup;
      var pname = matched ? playerLabel(matched.player_id) : tr('未匹配到本局批准名单');
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
            '<span class="muted">观测到 ' + esc((p.rounds || []).length) + ' 个回合</span>' +
            (p.withdrawn ? ' <span class="badge badge-danger">出场已人工撤回</span>' : '') +
            (p.round_side_conflict ? ' <span class="badge badge-danger">回合阵营冲突</span>' : '') +
          '</div>' +
          '<label class="ops-checkbox-inline">' +
            '<input type="checkbox" class="demo-record-cb" data-review="' + esc(JSON.stringify(evidence)) + '" data-steam-id="' + esc(steamId) + '"' + (canRecord ? '' : ' disabled') + '>' +
            '<span>登记实际出场' + (p.participation_revision != null ? '（已记录 Rev ' + p.participation_revision + '）' : '') + '</span>' +
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
            '<div class="ops-adopt-scope-title">' + esc(sc.toUpperCase()) + ' 字段差异（' + entries.length + ' 项）</div>' +
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
              (isConflict ? ' <em>冲突覆盖</em>' : '') + '</span>' +
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
        '<span>同时设为前台本图默认下载 Demo</span>' +
      '</label>' +
      '<label class="field">' +
        '<span class="field-label">采纳理由（必填，最多 500 字）</span>' +
        '<input type="text" id="demoAdoptReason" maxlength="500" placeholder="例如：核对 CSDA 解析比分与选手数据一致，采纳本局数据">' +
      '</label>' +
      '<div id="demoAdoptError" class="roster-inline-error" role="alert" hidden></div>' +
      '<div class="ops-adopt-submit-row">' +
        '<button type="button" class="btn" id="demoReviewLatest">重新核对差异</button>' +
        '<button type="button" class="btn btn-primary" id="demoAdoptSubmitBtn"' + (blocked ? ' disabled' : '') + '>确认采纳所选内容</button>' +
      '</div>' +
    '</div>';

    if (a.adoptions && a.adoptions.length) {
      html += '<details class="ops-lineup-details"><summary>本解析历史采纳记录（' + a.adoptions.length + ' 次）</summary><ul class="ops-simple-list">';
      a.adoptions.forEach(function (ad) {
        html += '<li><span data-i18n-ignore>#' + esc(ad.adoption_id) + '</span> · 操作人 <span data-i18n-ignore>' + esc(adminLabel(ad.actor)) + '</span> · <span data-i18n-ignore>' + esc(ad.adopted_at || '') + '</span> · 理由：<span data-i18n-ignore>' + esc(ad.reason || '') + '</span></li>';
      });
      html += '</ul></details>';
    }

    document.getElementById('opsDemoPreviewBody').innerHTML = html;
    bindAnalysisPreviewEvents();
  }

  function bindAnalysisPreviewEvents() {
    var body = document.getElementById('opsDemoPreviewBody');
    var a = state.activeAnalysis;
    if (!body || !a) return;

    var safeBtn = document.getElementById('demoSelectSafeBtn');
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
    var allBtn = document.getElementById('demoSelectAllBtn');
    if (allBtn) {
      allBtn.addEventListener('click', function () {
        body.querySelectorAll('.demo-record-cb:not(:disabled), .demo-field-cb:not(:disabled)').forEach(function (c) {
          c.checked = true;
        });
      });
    }
    var clearBtn = document.getElementById('demoClearSelectBtn');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        body.querySelectorAll('.demo-record-cb, .demo-field-cb').forEach(function (c) { c.checked = false; });
        var dl = document.getElementById('demoDownloadDefaultCb');
        if (dl) dl.checked = false;
      });
    }
    var submitBtn = document.getElementById('demoAdoptSubmitBtn');
    document.getElementById('demoReviewLatest').addEventListener('click', function () { openAnalysisPreview(a.analysis_id, true); });
    if (submitBtn) {
      submitBtn.addEventListener('click', submitDemoAdoption);
    }
  }

  async function submitDemoAdoption() {
    clearError('demoAdoptError');
    var a = state.activeAnalysis;
    if (!a) return;
    var reason = (document.getElementById('demoAdoptReason').value || '').trim();
    if (!reason) {
      showError('demoAdoptError', '请填写采纳理由');
      return;
    }
    var body = document.getElementById('opsDemoPreviewBody');
    var downloadDefault = Boolean((document.getElementById('demoDownloadDefaultCb') || {}).checked);
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
      showError('demoAdoptError', '请至少勾选一名选手的出场/字段，或勾选设为默认下载 Demo');
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

    document.getElementById('demoAdoptSubmitBtn').disabled = true;
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/api/demos/adopt', {
      method: 'POST',
      json: { approvals: [approval] }
    });
    if (!r.ok) {
      document.getElementById('demoAdoptSubmitBtn').disabled = false;
      showError('demoAdoptError', r.data.error || ('采纳失败（HTTP ' + r.status + '）'));
      return;
    }
    showFeedback('已采纳所选内容。', 'success');
    await refreshBundle(true);
    await openAnalysisPreview(a.analysis_id);
  }

  /* ==================== Tab 3: 赛果、结算、竞猜与历史 ==================== */
  async function loadLiveReference() {
    var box = document.querySelector('[data-live-run]');
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
      ? (/^stale_/.test(frame.source) ? tr('断流前最后观测') + ' · ' + frame.source.slice(6).toUpperCase() : frame.source.toUpperCase())
      : tr(frame.reason === 'map_run_void' ? '原局已作废，等待新局' : '无当前图实时快照');
  }

  function renderResultsTab() {
    var ov = bundle.overview;
    var res = ov.results || {};
    var mapsById = {};
    (ov.maps || []).forEach(function (m) { mapsById[m.scheduled_map_id] = m; });

    // 1. Official map results
    var mapHtml = '';
    var mapResults = res.maps || [];
    if (!mapResults.length) {
      mapHtml = '<p class="empty-state">尚无排定赛图。</p>';
    } else {
      mapHtml = '<div class="ops-results-grid">';
      mapResults.forEach(function (rm) {
        var mapObj = mapsById[rm.scheduled_map_id] || { runs: [] };
        var validRuns = (mapObj.runs || []).filter(function (r) { return r.status !== 'void'; });
        var hasOfficial = rm.official_map_result_id != null;

        mapHtml += '<div class="ops-result-card">' +
          '<div class="ops-subcard-head">' +
            '<div><span class="ops-map-order">图 ' + esc(rm.map_order) + '</span> <strong data-i18n-ignore>' + esc(mapDisplay(rm.map_name)) + '</strong></div>' +
            '<span class="badge ' + (hasOfficial ? 'badge-accent' : '') + '">' + (hasOfficial ? 'Rev ' + rm.revision : '未确认') + '</span>' +
          '</div>' +
          '<div class="ops-score-compare">' +
            '<div class="ops-score-box">' +
              '<span class="ops-score-box-label">正式赛果</span>' +
              '<strong>' + (hasOfficial ? (esc(rm.score1) + ' : ' + esc(rm.score2)) : '待确认') + '</strong>' +
              (hasOfficial
                ? '<small data-i18n-ignore>Run #' + esc(rm.map_run_id) + ' · ' + esc(rm.source) + (rm.terminal_receipt ? ' · 回执 ' + esc(rm.terminal_receipt) : '') + '</small>'
                : '<small>须绑定已开启的有效局</small>') +
            '</div>' +
            '<div class="ops-score-box is-ref"' + (rm.run_status === 'active' ? ' data-live-run="' + rm.map_run_id + '"' : '') + '>' +
              '<span class="ops-score-box-label">直播实时参考</span>' +
              '<strong>-</strong><small>无当前图实时快照</small>' +
              (rm.run_status === 'active' ? '<a href="' + esc(bundle.context.match.public_url) + '#data-live" target="_blank" rel="noopener">查看现场</a>' : '') +
            '</div>' +
          '</div>' +
          (hasOfficial && rm.reason ? '<p class="ops-mini-note">裁定说明：<span data-i18n-ignore>' + esc(rm.reason) + '</span></p>' : '') +
          '<div class="ops-card-foot">' +
            '<button type="button" class="btn btn-sm ' + (hasOfficial ? '' : 'btn-primary') + '" data-action="open-confirm-map" data-map-id="' + rm.scheduled_map_id + '"' + (validRuns.length ? '' : ' disabled') + '>' +
              (hasOfficial ? '修改正式赛果' : '确认单图赛果') +
            '</button>' +
            (!validRuns.length ? '<span class="muted">请先在“开赛与局次”登记有效实际开局</span>' : '') +
          '</div>' +
        '</div>';
      });
      mapHtml += '</div>';
    }
    document.getElementById('opsMapResultsContainer').innerHTML = mapHtml;

    // 2. Series settlement & downstream links
    var settled = Boolean(res.series && res.series.state === 'settled');
    var bo = (res.bo_format || 'BO3').toUpperCase();
    var winsNeeded = { BO1: 1, BO3: 2, BO5: 3 }[bo] || 2;
    var reachedWin = bundle.context.series_decided;

    var revBadge = document.getElementById('opsSeriesRevBadge');
    revBadge.className = 'badge ' + (settled ? 'badge-done' : 'badge-gold');
    revBadge.textContent = (settled ? '已正式完赛' : '未完赛') + ' · Rev ' + (res.revision || 0);

    var seriesHtml =
      '<div class="ops-series-box">' +
        '<div class="ops-series-main">' +
          '<div class="ops-series-score-line">' +
            '<span data-i18n-ignore>' + esc(homeName()) + '</span> ' +
            '<strong>' + esc(fmtVal(res.score1)) + ' : ' + esc(fmtVal(res.score2)) + '</strong> ' +
            '<span data-i18n-ignore>' + esc(awayName()) + '</span>' +
          '</div>' +
          '<p class="muted">' + esc(bo) + ' 需先赢 ' + winsNeeded + ' 图。达到胜场目标<strong>不会自动完赛</strong>，必须由管理员显式点击“正式完赛”才会结算晋级签位与竞猜积分。</p>' +
          (res.series
            ? '<p class="ops-mini-note">最近系列赛决定：<strong>' + (res.series.state === 'settled' ? '正式完赛' : '撤销完赛') + '</strong> · 操作人 <span data-i18n-ignore>' + esc(adminLabel(res.series.actor)) + '</span> · <span data-i18n-ignore>' + esc(res.series.recorded_at || '') + '</span>' + (res.series.reason ? ' · 原因：<span data-i18n-ignore>' + esc(res.series.reason) + '</span>' : '') + '</p>'
            : '') +
        '</div>' +
        '<div class="ops-series-actions">' +
          (!settled
            ? '<button type="button" class="btn btn-primary" data-action="open-series-settle"' + (reachedWin ? '' : ' disabled title="当前正式图胜场尚未达到赛制获胜条件"') + '>正式完赛（结算本场）</button>'
            : '<button type="button" class="btn btn-danger" data-action="open-series-reopen">撤销完赛（重新开启）</button>') +
        '</div>' +
      '</div>';

    // Outgoing downstream links
    var links = bundle.context.downstream_links || [];
    seriesHtml += '<div class="ops-downstream-block">' +
      '<div class="ops-subcard-head">' +
        '<strong>本场关联的下游晋级签位</strong>' +
        '<a class="btn btn-sm" href="' + esc(bundle.context.match.event_bracket_url) + '">管理赛事晋级图</a>' +
      '</div>';
    if (!links.length) {
      seriesHtml += '<p class="muted">本场尚未配置胜者 / 败者下游晋级签位。</p>';
    } else {
      seriesHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        '<th>出口</th><th>下游比赛</th><th>目标侧</th><th>当前已填入参赛队</th><th>保护状态</th>' +
      '</tr></thead><tbody>';
      links.forEach(function (lk) {
        seriesHtml += '<tr>' +
          '<td>' + (lk.outcome === 'winner' ? '胜者' : '败者') + '</td>' +
          '<td><a href="/admin/matches/' + lk.target_match_id + '/operate" data-i18n-ignore>' + esc(lk.target_label) + '</a></td>' +
          '<td>' + (lk.target_side === 'home' ? '主队侧 (home)' : '客队侧 (away)') + '</td>' +
          '<td data-i18n-ignore>' + esc(lk.current_entrant_name || 'TBD') + '</td>' +
          '<td>' +
            (lk.detached ? '<span class="badge badge-gold">已保留脱离（结算 #' + esc(lk.detached_settlement_id) + '）</span>'
              : lk.protected ? '<span class="badge badge-danger">' + esc(tr(lk.protection_reason)) + '</span>'
              : '<span class="badge badge-accent">可随结算更新</span>') +
          '</td>' +
        '</tr>';
      });
      seriesHtml += '</tbody></table></div>';
    }
    seriesHtml += '</div>';
    document.getElementById('opsSeriesContainer').innerHTML = seriesHtml;

    // 3. Predictions status
    var pred = bundle.context.predictions || {};
    var predBadge = document.getElementById('opsPredStateBadge');
    predBadge.className = 'badge ' + (pred.vote_open ? 'badge-accent' : 'badge-done');
    predBadge.textContent = pred.vote_open ? '竞猜开放中' : '竞猜已截止';

    var predHtml =
      '<div class="ops-pred-stats">' +
        '<div class="ops-pred-stat"><span>总投票</span><strong>' + esc(pred.total_votes || 0) + '</strong></div>' +
        '<div class="ops-pred-stat"><span data-i18n-ignore>' + esc(homeName()) + '</span><strong>' + esc(pred.t1_votes || 0) + ' 票</strong></div>' +
        '<div class="ops-pred-stat"><span data-i18n-ignore>' + esc(awayName()) + '</span><strong>' + esc(pred.t2_votes || 0) + ' 票</strong></div>' +
        '<div class="ops-pred-stat"><span>已结算</span><strong>' + esc(pred.settled_count || 0) + ' / ' + esc(pred.total_votes || 0) + '</strong></div>' +
      '</div>';

    var votes = pred.votes || [];
    if (votes.length) {
      predHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        '<th>用户</th><th>预测胜方</th><th>预测比分</th><th>结算状态</th><th class="num">获得积分</th>' +
      '</tr></thead><tbody>';
      votes.forEach(function (v) {
        var pickName = v.voted_for === 't1' ? homeName() : (v.voted_for === 't2' ? awayName() : v.voted_for);
        var scoreGuess = (v.score1_guess != null && v.score2_guess != null) ? (v.score1_guess + ' : ' + v.score2_guess) : '-';
        predHtml += '<tr>' +
          '<td data-i18n-ignore>' + esc(v.username || ('User #' + v.user_id)) + '</td>' +
          '<td data-i18n-ignore>' + esc(pickName) + '</td>' +
          '<td>' + esc(scoreGuess) + '</td>' +
          '<td>' + (v.scored ? '<span class="badge badge-accent">已结算</span>' : '<span class="badge">未结算</span>') + '</td>' +
          '<td class="num"><strong>' + (v.scored ? esc(v.points_earned) + ' 分' : '-') + '</strong></td>' +
        '</tr>';
      });
      predHtml += '</tbody></table></div>';
    } else {
      predHtml += '<p class="ops-empty-inline">本场比赛暂无用户竞猜记录。</p>';
    }

    var predChanges = (bundle.history && bundle.history.predictions) || [];
    if (predChanges.length) {
      predHtml += '<details class="ops-lineup-details"><summary>竞猜结算与重算变更记录（' + predChanges.length + ' 条）</summary>' +
        '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
          '<th>结算 #</th><th>投票 #</th><th>用户</th><th>原积分 → 新积分</th>' +
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
    document.getElementById('opsPredictionsContainer').innerHTML = predHtml;

    // 4. Full audit history
    var hist = bundle.history || {};
    var hHtml = '';

    hHtml += '<details class="ops-lineup-details"><summary>单图正式赛果历史（' + (hist.maps || []).length + ' 条）</summary>';
    if ((hist.maps || []).length) {
      hHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        '<th>图序</th><th>Rev</th><th>局次</th><th>比分</th><th>来源 / 操作人</th><th>说明</th><th>时间</th>' +
      '</tr></thead><tbody>';
      hist.maps.forEach(function (hm) {
        hHtml += '<tr>' +
          '<td>图 ' + esc(hm.map_order) + '</td>' +
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
      hHtml += '<p class="ops-empty-inline">暂无单图裁定记录。</p>';
    }
    hHtml += '</details>';

    hHtml += '<details class="ops-lineup-details"><summary>系列赛结算 / 重开历史（' + (hist.series || []).length + ' 条）</summary>';
    if ((hist.series || []).length) {
      hHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        '<th>Rev</th><th>状态</th><th>大比分</th><th>操作人</th><th>原因</th><th>时间</th>' +
      '</tr></thead><tbody>';
      hist.series.forEach(function (hs) {
        hHtml += '<tr>' +
          '<td>Rev ' + esc(hs.revision) + '</td>' +
          '<td>' + (hs.state === 'settled' ? '<span class="badge badge-done">正式完赛</span>' : '<span class="badge badge-gold">撤销重开</span>') + '</td>' +
          '<td><strong>' + esc(hs.score1) + ' : ' + esc(hs.score2) + '</strong></td>' +
          '<td data-i18n-ignore>' + esc(adminLabel(hs.actor)) + '</td>' +
          '<td data-i18n-ignore>' + esc(hs.reason || '-') + '</td>' +
          '<td data-i18n-ignore>' + esc(hs.recorded_at || '-') + '</td>' +
        '</tr>';
      });
      hHtml += '</tbody></table></div>';
    } else {
      hHtml += '<p class="ops-empty-inline">暂无系列赛结算记录。</p>';
    }
    hHtml += '</details>';

    hHtml += '<details class="ops-lineup-details"><summary>下游晋级变动与保留裁定（变动 ' + (hist.bracket || []).length + ' / 保留 ' + (hist.retained || []).length + '）</summary>';
    if ((hist.bracket || []).length) {
      hHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        '<th>结算 #</th><th>下游比赛</th><th>侧别</th><th>原参赛队 → 新参赛队</th>' +
      '</tr></thead><tbody>';
      hist.bracket.forEach(function (hb) {
        hHtml += '<tr>' +
          '<td data-i18n-ignore>#' + esc(hb.settlement_id) + '</td>' +
          '<td data-i18n-ignore>Match #' + esc(hb.target_match_id) + '</td>' +
          '<td>' + (hb.target_side === 'home' ? '主队侧' : '客队侧') + '</td>' +
          '<td data-i18n-ignore>' + esc(entrantLabel(hb.previous_entrant_id)) + ' → ' + esc(entrantLabel(hb.new_entrant_id)) + '</td>' +
        '</tr>';
      });
      hHtml += '</tbody></table></div>';
    }
    if ((hist.retained || []).length) {
      hHtml += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        '<th>Rev</th><th>下游比赛 / 侧别</th><th>保留参赛队</th><th>拟变更为</th><th>操作人 / 原因</th>' +
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
      hHtml += '<p class="ops-empty-inline">暂无下游晋级变动或保留裁定。</p>';
    }
    hHtml += '</details>';

    document.getElementById('opsHistoryContainer').innerHTML = hHtml;
  }

  /* ==================== Tab 4: 统计修订工作台 ==================== */
  function populateStatsSelectors() {
    var runSel = document.getElementById('statsRunSelect');
    var playerSel = document.getElementById('statsPlayerSelect');
    var runs = [];
    (bundle.overview.maps || []).forEach(function (m) {
      (m.runs || []).forEach(function (r) {
        runs.push({ map: m, run: r });
      });
    });

    runSel.innerHTML = '';
    if (!runs.length) {
      runSel.innerHTML = '<option value="">尚无实际开局</option>';
      playerSel.innerHTML = '<option value="">无可选选手</option>';
      document.getElementById('statsEditorArea').innerHTML = '<p class="empty-state">请先登记实际开局并确认选手出场后，再进行统计修订。</p>';
      document.getElementById('statsHistoryArea').innerHTML = '';
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

  function findRunById(runId) {
    var found = null;
    (bundle.overview.maps || []).forEach(function (m) {
      (m.runs || []).forEach(function (r) {
        if (Number(r.map_run_id) === Number(runId)) found = { map: m, run: r };
      });
    });
    return found;
  }

  function populateStatsPlayers() {
    var runId = Number(document.getElementById('statsRunSelect').value);
    state.statsTarget.runId = runId || null;
    var playerSel = document.getElementById('statsPlayerSelect');
    playerSel.innerHTML = '';
    var info = findRunById(runId);
    var parts = (info && info.run.participations) || [];
    if (!parts.length) {
      playerSel.innerHTML = '<option value="">本局尚未登记出场选手</option>';
      state.statsTarget.playerId = null;
      state.statsLoaded = null;
      state.statsPreview = null;
      renderStatsEditor();
      document.getElementById('statsRevBadge').textContent = '未加载';
      document.getElementById('statsEditorArea').innerHTML = '<p class="empty-state">本局尚无已登记的出场选手。请先在“开赛与局次”或通过 Demo 采纳登记实际出场。</p>';
      document.getElementById('statsHistoryArea').innerHTML = '';
      return;
    }
    parts.forEach(function (rp) {
      var party = participantById(rp.match_participant_id);
      var opt = document.createElement('option');
      opt.value = String(rp.player_id);
      opt.setAttribute('data-i18n-ignore', '');
      opt.textContent = playerLabel(rp.player_id) +
        (party ? ' (' + party.name + ')' : '') +
        (rp.is_current ? '' : tr(' [已撤回 · 只读]'));
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

  async function loadStatsTarget(preserveDraft) {
    clearError('statsInlineError');
    var runId = Number(document.getElementById('statsRunSelect').value);
    var playerId = Number(document.getElementById('statsPlayerSelect').value);
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
    document.getElementById('statsRevBadge').textContent = tr('加载中');

    state.statsTarget.runId = runId;
    state.statsTarget.playerId = playerId;

    var url = '/admin/matches/' + MATCH_ID + '/operations/runs/' + runId +
      '/players/' + playerId + '/stats?scope=' + encodeURIComponent(scope) + '&history=1';
    var r = await apiJson(url, { method: 'GET' });
    if (requestId !== state.statsRequest) return;
    if (!r.ok) {
      document.getElementById('statsRevBadge').textContent = tr('未加载');
      showError('statsInlineError', r.data.error || '读取统计字段失败');
      return;
    }
    state.statsLoaded = r.data;
    renderStatsEditor();
  }

  function renderStatsEditor() {
    var data = state.statsLoaded;
    var badge = document.getElementById('statsRevBadge');
    var statusBanner = document.getElementById('statsStatusBanner');
    var editor = document.getElementById('statsEditorArea');
    var previewArea = document.getElementById('statsPreviewArea');
    var historyArea = document.getElementById('statsHistoryArea');

    if (!data) {
      badge.textContent = '未加载';
      statusBanner.hidden = true;
      editor.innerHTML = '';
      previewArea.hidden = true;
      historyArea.innerHTML = '';
      return;
    }

    badge.className = 'badge ' + (data.editable ? 'badge-accent' : 'badge-danger');
    badge.textContent = '整局版本 Rev ' + data.revision + (data.editable ? ' · 可修订' : ' · 只读');

    if (!data.editable) {
      statusBanner.hidden = false;
      statusBanner.className = 'ops-status-banner is-warn';
      statusBanner.textContent = tr(
        '当前目标为只读状态（局次状态：' + data.run_status + '，出场有效：' + (data.participation_current ? '是' : '否') + '），仅可查看已采纳字段与历史记录。'
      );
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
          '<th>指标</th><th>当前采纳值</th><th>当前来源</th><th>修订值（留空为未知 -）</th><th class="num">快捷</th>' +
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
        var srcTitle = src ? [tr(srcLabel), adminLabel(src.actor), src.source_ref, src.method, src.reason].filter(Boolean).join(' · ') : '';
        var srcHtml = src
          ? '<span class="badge" title="' + esc(srcTitle) + '">' + esc(srcLabel) + '</span> <small class="muted" data-i18n-ignore>Rev ' + esc(src.revision) + '</small>'
          : '<span class="muted">-</span>';

        html += '<tr class="' + (touched ? 'is-dirty-row' : '') + '" data-stat-row="' + esc(key) + '">' +
          '<td><strong>' + esc(label) + '</strong> <code class="ops-field-code" data-i18n-ignore>' + esc(key) + '</code></td>' +
          '<td class="mono"><span class="ops-mobile-stat-label" aria-hidden="true">当前采纳值</span><strong>' + esc(fmtVal(currentVal)) + '</strong></td>' +
          '<td><span class="ops-mobile-stat-label" aria-hidden="true">当前来源</span>' + srcHtml + '</td>' +
          '<td><span class="ops-mobile-stat-label" aria-hidden="true">修订值</span>' +
            '<input type="number" class="ops-stat-input" aria-label="' + esc(tr(label)) + '" data-stat-field="' + esc(key) + '" data-stat-int="' + (isInt ? '1' : '0') + '" ' +
              'step="' + (isInt ? '1' : 'any') + '" placeholder="-" value="' + esc(inputVal) + '"' + (data.editable ? '' : ' disabled') + '>' +
          '</td>' +
          '<td class="num ops-row-btns">' +
            (data.editable
              ? '<button type="button" class="btn btn-sm" data-stat-clear="' + esc(key) + '" title="设为未知 (-)">设为未知</button>' +
                ' <button type="button" class="btn btn-sm" data-stat-reset="' + esc(key) + '"' + (touched ? '' : ' hidden') + '>还原</button>'
              : '<span class="muted">只读</span>') +
          '</td>' +
        '</tr>';
      });
      html += '</tbody></table></div></div>';
    });
    html += '</div>';

    if (data.editable) {
      var touchedKeys = Object.keys(state.statsDraft);
      html += '<div class="ops-stats-commit-bar">' +
        '<div class="ops-stats-dirty-summary">已改动字段：<strong id="statsDirtyCount">' + touchedKeys.length + '</strong> 项（保存时仅提交已改动字段）</div>' +
        '<label class="field">' +
          '<span class="field-label">修订原因（保存时必填）</span>' +
          '<input type="text" id="statsReasonInput" maxlength="2000" value="' + esc(state.statsReason) + '" placeholder="例如：依据服务器记分板与 Demo 回放核对补录/修正">' +
        '</label>' +
        '<div class="ops-stats-commit-btns">' +
          '<button type="button" class="btn" id="statsPreviewBtn">预览变更</button>' +
          '<button type="button" class="btn btn-primary" id="statsApplyBtn" disabled>确认保存修订</button>' +
          '<button type="button" class="btn" id="statsResetAllBtn">撤销全部未保存修改</button>' +
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
      var input = document.querySelector('.ops-stat-input[data-stat-field="' + key + '"]');
      if (input && !input.validity.valid) {
        throw new Error(tr(FIELD_LABELS[key] || key) + ': ' + input.validationMessage);
      }
      if (val === null || val === '') {
        payload[key] = null;
      } else {
        var num = Number(val);
        if (!Number.isFinite(num)) {
          throw new Error('字段 ' + (FIELD_LABELS[key] || key) + ' 不是有效数字');
        }
        if (countSet.has(key) && !Number.isInteger(num)) {
          throw new Error('字段 ' + (FIELD_LABELS[key] || key) + ' 必须是整数');
        }
        payload[key] = num;
      }
    }
    return payload;
  }

  function bindStatsEditorEvents() {
    var editor = document.getElementById('statsEditorArea');
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
      var cnt = document.getElementById('statsDirtyCount');
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

    var previewBtn = document.getElementById('statsPreviewBtn');
    var reasonInput = document.getElementById('statsReasonInput');
    if (reasonInput) reasonInput.addEventListener('input', function () { state.statsReason = reasonInput.value; });
    if (previewBtn) previewBtn.addEventListener('click', handleStatsPreview);
    var applyBtn = document.getElementById('statsApplyBtn');
    if (applyBtn) applyBtn.addEventListener('click', handleStatsApply);
    var resetAllBtn = document.getElementById('statsResetAllBtn');
    if (resetAllBtn) {
      resetAllBtn.addEventListener('click', function () {
        state.statsDraft = {};
        state.statsPreview = null;
        renderStatsEditor();
      });
    }
  }

  function renderStatsPreview() {
    var box = document.getElementById('statsPreviewArea');
    var p = state.statsPreview;
    var save = document.getElementById('statsApplyBtn');
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
      '<div class="ops-subcard-head"><strong>变更预览（整局版本 Rev ' + esc(p.revision) + '）</strong>' +
      (p.status === 'stale' ? '<span class="badge badge-danger">版本已过期</span>' : '<span class="badge badge-accent">' + keys.length + ' 项改动</span>') +
      '</div>';

    if (!keys.length) {
      html += '<p class="muted">所填数值与当前已采纳数据一致，没有实际改动。</p>';
    } else {
      html += '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        '<th>字段</th><th>原值</th><th>新值</th><th>说明</th>' +
      '</tr></thead><tbody>';
      keys.forEach(function (k) {
        var ch = changes[k];
        var isConf = Object.prototype.hasOwnProperty.call(conflicts, k) || ch.before != null;
        html += '<tr class="' + (isConf ? 'is-conflict-row' : '') + '">' +
          '<td><strong>' + esc(FIELD_LABELS[k] || k) + '</strong> <code data-i18n-ignore>' + esc(k) + '</code></td>' +
          '<td class="mono">' + esc(fmtVal(ch.before)) + '</td>' +
          '<td class="mono"><strong>' + esc(fmtVal(ch.after)) + '</strong></td>' +
          '<td>' + (isConf ? '<span class="badge badge-gold">覆盖已有非空值</span>' : '<span class="badge badge-accent">补充空值 / 常规更新</span>') + '</td>' +
        '</tr>';
      });
      html += '</tbody></table></div>';
    }
    html += '</div>';
    box.innerHTML = html;
  }

  function renderStatsHistory(history) {
    var area = document.getElementById('statsHistoryArea');
    if (!history.length) {
      area.innerHTML = '<details class="ops-lineup-details"><summary>字段修订历史（0 条）</summary><p class="ops-empty-inline">该选手在此阵营下暂无统计修订记录。</p></details>';
      return;
    }
    var html = '<details class="ops-lineup-details"><summary>字段修订历史（' + history.length + ' 条）</summary>' +
      '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
        '<th>Rev</th><th>来源 / 操作人</th><th>改动字段</th><th>原因</th><th>时间</th>' +
      '</tr></thead><tbody>';
    history.forEach(function (h) {
      var parts = [];
      Object.keys(h.changes || {}).forEach(function (k) {
        var c = h.changes[k];
        parts.push(tr(FIELD_LABELS[k] || k) + ': ' + fmtVal(c.before) + ' → ' + fmtVal(c.after));
      });
      html += '<tr>' +
        '<td>Rev ' + esc(h.revision) + '</td>' +
        '<td>' + esc(tr(sourceKindLabel(h.source))) + ' / <span data-i18n-ignore>' + esc(adminLabel(h.actor)) + '</span></td>' +
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
      showError('statsInlineError', '请先修改至少一个字段再预览');
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
        reason: ((document.getElementById('statsReasonInput') || {}).value || '').trim()
      }
    });
    if (target !== state.statsLoaded || draft !== JSON.stringify(state.statsDraft)) return;
    if (!r.ok) {
      if (r.status === 409 && r.data && r.data.status === 'stale') {
        await loadStatsTarget(true);
        showError('statsInlineError', '统计版本已更新。已保留输入和原因，请重新预览后确认。');
        return;
      }
      showError('statsInlineError', r.data.error || '预览变更失败');
      return;
    }
    state.statsPreview = r.data;
    renderStatsPreview();
  }

  async function handleStatsApply() {
    clearError('statsInlineError');
    if (!state.statsLoaded || !state.statsPreview) return;
    var target = state.statsLoaded;
    var reason = ((document.getElementById('statsReasonInput') || {}).value || '').trim();
    if (!reason) {
      showError('statsInlineError', '请填写统计修订原因');
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
      showError('statsInlineError', '没有待提交的字段改动');
      return;
    }
    document.getElementById('statsApplyBtn').disabled = true;
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
        showError('statsInlineError', '统计版本已更新。已保留输入和原因，请重新预览后确认。');
        return;
      }
      renderStatsPreview();
      showError('statsInlineError', r.data.error || '保存修订失败');
      return;
    }
    showFeedback('统计修订已保存（整局版本更新至 Rev ' + r.data.revision + '）。', 'success');
    await loadStatsTarget(false);
  }

  /* ==================== 下游保护槽位保留裁定 UI 构建 ==================== */
  function buildRetentionUI(containerId, proposedByOutcome) {
    var box = document.getElementById(containerId);
    if (!box) return;
    var previous = new Set(Array.from(box.querySelectorAll(':checked'), cb => cb.value));
    box.replaceChildren();
    if (proposedByOutcome && proposedByOutcome.error) {
      box.textContent = tr(proposedByOutcome.error);
      box.hidden = false;
      return;
    }
    var links = (bundle.context.downstream_links || []).filter(function (lk) {
      return proposedByOutcome && !lk.detached && proposedByOutcome[lk.outcome] !== lk.event_entrant_id;
    });
    if (!links.length) {
      box.hidden = true;
      box.innerHTML = '';
      return;
    }
    var html = '<strong>受影响的下游席位</strong><div class="ops-retention-list">';

    links.forEach(function (lk) {
      var proposedId = proposedByOutcome[lk.outcome];
      var selectable = lk.protected && lk.can_retain && lk.event_entrant_id != null;
      var key = [lk.target_match_id, lk.target_side, lk.event_entrant_id, proposedId].join(':');
      var tag = selectable ? 'label' : 'div';
      html += '<' + tag + ' class="ops-retention-item">' +
        (selectable ? '<input type="checkbox" class="ops-retain-cb" required value="' + esc(key) + '" ' +
          'data-target-match-id="' + lk.target_match_id + '" ' +
          'data-target-side="' + esc(lk.target_side) + '" ' +
          'data-retained-entrant-id="' + lk.event_entrant_id + '" ' +
          'data-proposed-entrant-id="' + (proposedId == null ? '' : proposedId) + '"' + (previous.has(key) ? ' checked' : '') + '>' : '') +
        '<div>' +
          '<div><strong>' + (lk.outcome === 'winner' ? '胜者' : '败者') + ' → <span data-i18n-ignore>' + esc(lk.target_label) + '</span>（' + (lk.target_side === 'home' ? '主队侧' : '客队侧') + '）</strong></div>' +
          '<span data-i18n-ignore>' + esc(entrantLabel(lk.event_entrant_id)) + ' → ' + esc(entrantLabel(proposedId)) + '</span>' +
          (lk.protection_reason ? '<div class="muted">' + esc(lk.protection_reason) + '</div>' : '') +
          '<div>' + (selectable ? '保留当前参赛队，此席不再跟随上游赛果' : (lk.protected ? '此席不能自动调整或保留' : '此席随正式结算更新')) + '</div>' +
        '</div>' +
      '</' + tag + '>';
    });
    html += '</div>';
    box.innerHTML = html;
    box.hidden = false;
  }

  function readRetentionDecisions(containerId) {
    var box = document.getElementById(containerId);
    if (!box || box.hidden) return null;
    var checked = Array.from(box.querySelectorAll('.ops-retain-cb:checked'));
    if (!checked.length) return null;
    return checked.map(function (cb) {
      var propRaw = cb.dataset.proposedEntrantId;
      return {
        target_match_id: Number(cb.dataset.targetMatchId),
        target_side: cb.dataset.targetSide,
        retained_entrant_id: Number(cb.dataset.retainedEntrantId),
        proposed_entrant_id: propRaw === '' ? null : Number(propRaw)
      };
    });
  }

  /* ==================== 弹窗打开与提交 ==================== */
  function openStartRunModal(mapId, prevRunId) {
    clearError('startRunError');
    var mapObj = (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === mapId; });
    if (!mapObj) return;
    state.dialogPayload.startRun = { scheduled_map_id: mapId, previous_map_run_id: prevRunId || null };
    document.getElementById('startRunDialogTitle').textContent =
      tr(prevRunId ? '开启技术重赛新局' : '登记实际开局');
    document.getElementById('startRunContext').textContent =
      '图 ' + mapObj.map_order + ' · ' + mapDisplay(mapObj.map_name) + ' (ScheduledMap #' + mapId + ')';
    var note = document.getElementById('startRunReplayNote');
    if (prevRunId) {
      note.hidden = false;
      note.textContent = tr('将承接已作废的 Run #' + prevRunId + ' 开启新局（previous_map_run_id = ' + prevRunId + '），并自动使用最新有效阵容。');
    } else {
      note.hidden = true;
    }
    document.getElementById('startRunEvidence').value = '';
    openDialog('startRunDialog');
  }

  function openBindDirectorModal(runId, mapId) {
    clearError('bindDirectorError');
    state.dialogPayload.bindDirector = { map_run_id: runId, scheduled_map_id: mapId };
    document.getElementById('bindDirectorContext').textContent = 'Run #' + runId + ' (ScheduledMap #' + mapId + ')';
    document.getElementById('bindDirectorSessionId').value = '';
    document.getElementById('bindDirectorReason').value = '';
    openDialog('bindDirectorDialog');
  }

  async function openDirectorReceiptsModal(runId) {
    var body = document.getElementById('directorReceiptsBody');
    body.innerHTML = '<p class="muted">正在读取导播回执…</p>';
    openDialog('directorReceiptsDialog');
    var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/runs/' + runId + '/director-receipts', { method: 'GET' });
    if (!r.ok) {
      body.innerHTML = '<p class="ops-err-text">' + esc(r.data.error || '读取导播回执失败') + '</p>';
      return;
    }
    var receipts = r.data.receipts || [];
    if (!receipts.length) {
      body.innerHTML = '<p class="empty-state">Run #' + esc(runId) + ' 尚无导播终图回执记录。</p>';
      return;
    }
    var html = '<div class="table-wrap"><table class="table ops-compact-table"><thead><tr>' +
      '<th>回执 ID</th><th>导播会话</th><th>帧序号</th><th>接收时间</th><th>候选选手数</th>' +
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
        html += '<tr><td colspan="5"><details><summary>选手字段回执</summary><ul class="ops-simple-list">';
        rc.statistics.forEach(function (item) {
          var applied = item.applied_fields.map(key => tr(FIELD_LABELS[key] || key));
          html += '<li><strong data-i18n-ignore>' + esc(playerLabel(item.player_id)) + '</strong> · ' +
            '<span>已补入</span>：' + esc(applied.join(', ') || '-');
          Object.entries(item.conflicts).forEach(function (entry) {
            var diff = entry[1];
            html += ' · <span>' + esc(FIELD_LABELS[entry[0]] || entry[0]) + '</span>：' +
              '<span>保留原值</span> ' + esc(fmtVal(diff.current)) + ' / <span>导播上报</span> ' + esc(fmtVal(diff.reported));
          });
          if (item.status === 'participation_protected') html += ' · <span>出场已人工撤回</span>';
          if (item.status === 'participation_unproven') html += ' · <span>尚无实际出场依据</span>';
          html += '</li>';
        });
        html += '</ul></details></td></tr>';
      }
    });
    html += '</tbody></table></div>';
    body.innerHTML = html;
  }

  function openRecordParticipationModal(runId, prePlayerId, prePartyId) {
    clearError('recordPartError');
    var info = findRunById(runId);
    if (!info) return;
    state.dialogPayload.recordPart = { map_run_id: runId };
    document.getElementById('recordPartContext').textContent =
      '图 ' + info.map.map_order + ' ' + mapDisplay(info.map.map_name) + ' · Run #' + runId;
    var sel = document.getElementById('recordPartPlayerSelect');
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
    document.getElementById('recordPartRound').value = '';
    document.getElementById('recordPartSide').value = '';
    document.getElementById('recordPartReason').value = '';
    openDialog('recordPartDialog');
  }

  function openBatchParticipationModal(runId) {
    clearError('batchPartError');
    var info = findRunById(runId);
    if (!info) return;
    state.dialogPayload.batchPart = { map_run_id: runId };
    document.getElementById('batchPartContext').textContent =
      tr('图 ' + info.map.map_order) + ' ' + mapDisplay(info.map.map_name) + ' · ' + tr('实际开局') + ' #' + runId;
    var partByPlayer = {};
    (info.run.participations || []).forEach(function (rp) {
      partByPlayer[rp.player_id] = rp;
    });
    var listEl = document.getElementById('batchPartPlayerList');
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
    document.getElementById('batchPartReason').value = '';
    syncBatchSelection();
    openDialog('batchPartDialog');
  }

  function syncBatchSelection() {
    var choices = document.querySelectorAll('#batchPartPlayerList input');
    var count = Array.from(choices).filter(function (cb) { return cb.checked; }).length;
    var all = document.getElementById('batchPartAll');
    all.checked = count > 0 && count === choices.length;
    all.indeterminate = count > 0 && count < choices.length;
    document.getElementById('batchPartSubmitBtn').disabled = !count || !document.getElementById('batchPartReason').value.trim();
  }

  function openReviewParticipationModal(partId, present, rev, playerName) {
    clearError('reviewPartError');
    state.dialogPayload.reviewPart = { participation_id: partId, present: present, expected_revision: rev };
    document.getElementById('reviewPartDialogTitle').textContent = tr(present ? '恢复选手出场' : '撤回选手出场');
    document.getElementById('reviewPartContext').textContent =
      playerName + ' · 出场记录 #' + partId + ' (Rev ' + rev + ')';
    document.getElementById('reviewPartSubmitBtn').textContent = tr(present ? '确认恢复出场' : '确认撤回出场');
    document.getElementById('reviewPartReason').value = '';
    openDialog('reviewPartDialog');
  }

  function openTechReplayModal(runId, mapId) {
    clearError('techReplayError');
    document.getElementById('techReplayReload').hidden = true;
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

    document.getElementById('techReplayContext').textContent =
      '图 ' + info.map.map_order + ' ' + mapDisplay(info.map.map_name) + ' · Run #' + runId +
      ' (第 ' + info.run.attempt_no + ' 次开局)';
    document.getElementById('techReplayReason').value = '';
    var toggle = document.getElementById('techReplaySubToggle');
    toggle.checked = false;
    document.getElementById('techReplaySubFields').hidden = true;

    // Populate outgoing from effective_roster
    var outSel = document.getElementById('techReplayOutgoing');
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
      document.getElementById('techReplayRetentionBox').hidden = true;
    }
    openDialog('techReplayDialog');
  }

  function updateTechReplayIncomingOptions(mapObj, reviewedSelection) {
    var outSel = document.getElementById('techReplayOutgoing');
    var inSel = document.getElementById('techReplayIncoming');
    var checkBox = document.getElementById('techReplaySubCheck');
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
      inSel.innerHTML = '<option value="">该队暂无可用的已分配候补席选手</option>';
      checkBox.className = 'ops-sub-check is-warn';
      checkBox.textContent = tr('该参赛队当前没有满足条件的已分配候补（需先在赛事名单管理中为该队分配替补席）。');
      return;
    }
    reserves.forEach(function (r) {
      var o = document.createElement('option');
      o.value = String(r.player_id);
      o.setAttribute('data-i18n-ignore', '');
      o.textContent = r.nickname + (r.steam_id ? ' (' + r.steam_id + ')' : ' [缺 SteamID]');
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
    checkBox.textContent = tr('换人后该队将保留本届初始五人 ' + kept + ' / 5 名' + (kept >= 3 ? '（满足 ≥3 人规则）' : '（不足 3 人，将被后端拒绝）'));
  }

  function openConfirmMapModal(mapId) {
    clearError('confirmMapError');
    document.getElementById('confirmMapReload').hidden = true;
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

    document.getElementById('confirmMapDialogTitle').textContent =
      tr(rm.official_map_result_id ? '修改单图正式赛果' : '确认单图正式赛果');
    document.getElementById('confirmMapContext').textContent =
      '图 ' + rm.map_order + ' · ' + mapDisplay(rm.map_name) + ' · 当前正式版本 Rev ' + (rm.revision || 0);
    document.getElementById('confirmMapScore1Label').textContent = homeName() + ' 回合分';
    document.getElementById('confirmMapScore2Label').textContent = awayName() + ' 回合分';

    var runSel = document.getElementById('confirmMapRunSelect');
    runSel.innerHTML = '';
    validRuns.forEach(function (r) {
      var opt = document.createElement('option');
      opt.value = String(r.map_run_id);
      opt.textContent = 'Run #' + r.map_run_id + ' · 第 ' + r.attempt_no + ' 次开局 (' + r.status + ')';
      runSel.appendChild(opt);
    });
    if (rm.map_run_id && validRuns.some(function (r) { return r.map_run_id === rm.map_run_id; })) {
      runSel.value = String(rm.map_run_id);
    }

    document.getElementById('confirmMapScore1').value = rm.score1 != null ? String(rm.score1) : '';
    document.getElementById('confirmMapScore2').value = rm.score2 != null ? String(rm.score2) : '';
    document.getElementById('confirmMapReason').value = '';
    refreshConfirmMapRetentionBox();
    openDialog('confirmMapDialog');
  }

  function refreshConfirmMapRetentionBox() {
    var payload = state.dialogPayload.confirmMap;
    if (!payload || !payload.settled) {
      document.getElementById('confirmMapRetentionBox').hidden = true;
      return;
    }
    var s1 = document.getElementById('confirmMapScore1').valueAsNumber;
    var s2 = document.getElementById('confirmMapScore2').valueAsNumber;
    var options = bundle.context.map_change_options[payload.scheduled_map_id] || {};
    var proposed = (Number.isInteger(s1) && Number.isInteger(s2) && s1 !== s2)
      ? options[s1 > s2 ? 'home' : 'away'] : null;
    buildRetentionUI('confirmMapRetentionBox', proposed);
  }

  function openSeriesActionModal(mode) {
    clearError('seriesActionError');
    document.getElementById('seriesActionReload').hidden = true;
    buildRetentionUI('seriesRetentionBox', null);
    var res = bundle.overview.results || {};
    state.dialogPayload.seriesAction = { mode: mode, expected_revision: res.revision || 0 };
    var titleEl = document.getElementById('seriesActionDialogTitle');
    var warnEl = document.getElementById('seriesActionWarn');
    var submitBtn = document.getElementById('seriesActionSubmitBtn');
    var reasonLabel = document.getElementById('seriesActionReasonLabel');

    document.getElementById('seriesActionContext').textContent =
      homeName() + ' ' + fmtVal(res.score1) + ' : ' + fmtVal(res.score2) + ' ' + awayName() +
      ' · ' + (res.bo_format || 'BO3') + ' · 当前系列赛版本 Rev ' + (res.revision || 0);
    document.getElementById('seriesActionReason').value = '';

    if (mode === 'settle') {
      titleEl.textContent = tr('正式完赛（结算系列赛）');
      warnEl.className = 'ops-callout-note';
      warnEl.textContent = tr('确认正式完赛后，系统将写入最终系列赛结算记录、按配置的晋级规则填充下游比赛，并结算本场赛前竞猜积分（8 / 3 / 0 分）。');
      reasonLabel.textContent = tr('完赛说明（可选）');
      submitBtn.className = 'btn btn-primary';
      submitBtn.textContent = tr('确认正式完赛');
      document.getElementById('seriesRetentionBox').hidden = true;
    } else {
      titleEl.textContent = tr('撤销完赛（重新开启比赛）');
      warnEl.className = 'ops-callout-warn';
      warnEl.textContent = tr('撤销完赛将把本场恢复为进行中状态，撤销本场竞猜结算积分，并尝试回退尚未受保护的下游晋级签位。请务必填写重开原因。');
      reasonLabel.textContent = tr('撤销完赛原因（必填）');
      submitBtn.className = 'btn btn-danger';
      submitBtn.textContent = tr('确认撤销完赛');
      buildRetentionUI('seriesRetentionBox', { winner: null, loser: null });
    }
    openDialog('seriesActionDialog');
  }

  /* ==================== 全局事件委托 ==================== */
  function bindEvents() {
    window.setInterval(function () {
      if (state.tab === 'results' && !document.hidden) loadLiveReference();
    }, 5000);
    var tabs = Array.from(document.querySelectorAll('[data-ops-tab]'));
    tabs.forEach(function (btn, index) {
      btn.addEventListener('click', function () {
        setActiveTab(btn.dataset.opsTab, true);
      });
      btn.addEventListener('keydown', function (event) {
        var next = {ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length,
          Home: 0, End: tabs.length - 1}[event.key];
        if (next === undefined) return;
        event.preventDefault();
        tabs[next].focus();
        setActiveTab(tabs[next].dataset.opsTab, true);
      });
    });

    document.getElementById('opsRefreshBtn').addEventListener('click', function () {
      refreshBundle(false);
    });
    document.getElementById('demoRefreshBtn').addEventListener('click', function () {
      refreshBundle(false);
    });
    document.getElementById('opsDemoPreviewCloseBtn').addEventListener('click', function () {
      state.activeAnalysis = null;
      document.getElementById('opsDemoPreviewPanel').hidden = true;
    });

    document.getElementById('demoUploadMapSelect').addEventListener('change', updateDemoUploadRuns);
    document.getElementById('opsDemoUploadForm').addEventListener('submit', handleDemoUpload);

    // Stats toolbar events
    document.getElementById('statsRunSelect').addEventListener('change', function () {
      populateStatsPlayers();
      loadStatsTarget(false);
    });
    document.getElementById('statsPlayerSelect').addEventListener('change', function () {
      loadStatsTarget(false);
    });
    document.querySelectorAll('[data-stats-scope]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.statsTarget.scope = btn.dataset.statsScope;
        document.querySelectorAll('[data-stats-scope]').forEach(function (b) {
          var active = b.dataset.statsScope === state.statsTarget.scope;
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        loadStatsTarget(false);
      });
    });
    document.getElementById('statsReloadBtn').addEventListener('click', function () {
      loadStatsTarget(true);
    });

    // Dialog close buttons
    document.querySelectorAll('[data-close-dialog]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        closeDialog(btn.dataset.closeDialog);
      });
    });

    // Tech replay sub toggle & select change
    document.getElementById('techReplaySubToggle').addEventListener('change', function (e) {
      document.getElementById('techReplaySubFields').hidden = !e.target.checked;
    });
    document.getElementById('techReplayOutgoing').addEventListener('change', function () {
      var p = state.dialogPayload.techReplay;
      var mapObj = p && (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === p.scheduled_map_id; });
      if (mapObj) updateTechReplayIncomingOptions(mapObj);
    });
    document.getElementById('techReplayIncoming').addEventListener('change', function () {
      var p = state.dialogPayload.techReplay;
      var mapObj = p && (bundle.overview.maps || []).find(function (m) { return m.scheduled_map_id === p.scheduled_map_id; });
      if (mapObj) updateTechReplayIncomingOptions(mapObj);
    });
    document.getElementById('confirmMapScore1').addEventListener('input', refreshConfirmMapRetentionBox);
    document.getElementById('confirmMapScore2').addEventListener('input', refreshConfirmMapRetentionBox);
    document.getElementById('confirmMapReload').addEventListener('click', async function () {
      if (!await refreshBundle(true)) return;
      var p = state.dialogPayload.confirmMap;
      var res = bundle.overview.results;
      var map = res.maps.find(m => m.scheduled_map_id === p.scheduled_map_id);
      if (!map || map.map_run_id !== Number(document.getElementById('confirmMapRunSelect').value)) {
        showError('confirmMapError', '实际开局已改变，请返回选择当前局。');
        return;
      }
      p.expected_revision = map.revision;
      p.settled = Boolean(res.series && res.series.state === 'settled');
      p.expected_series_revision = res.revision;
      document.getElementById('confirmMapContext').textContent = tr('最新正式赛果') + ' ' + fmtVal(map.score1) + ' : ' + fmtVal(map.score2) + ' · Rev ' + map.revision;
      buildRetentionUI('confirmMapRetentionBox', null);
      refreshConfirmMapRetentionBox();
      clearError('confirmMapError');
      this.hidden = true;
    });

    document.getElementById('techReplayReload').addEventListener('click', async function () {
      if (!await refreshBundle(true)) return;
      var p = state.dialogPayload.techReplay;
      if (!document.querySelector('[data-action="open-tech-replay"][data-run-id="' + p.map_run_id + '"]')) {
        showError('techReplayError', '实际开局已改变，请返回选择当前局。');
        return;
      }
      var reason = document.getElementById('techReplayReason').value;
      var withSub = document.getElementById('techReplaySubToggle').checked;
      var out = document.getElementById('techReplayOutgoing').value;
      var incoming = document.getElementById('techReplayIncoming').value;
      openTechReplayModal(p.map_run_id, p.scheduled_map_id);
      document.getElementById('techReplayReason').value = reason;
      if (withSub) {
        document.getElementById('techReplaySubToggle').checked = true;
        document.getElementById('techReplaySubFields').hidden = false;
        document.getElementById('techReplayOutgoing').value = out;
        updateTechReplayIncomingOptions(findRunById(p.map_run_id).map, incoming);
      }
      var map = bundle.overview.results.maps.find(m => m.scheduled_map_id === p.scheduled_map_id);
      document.getElementById('techReplayContext').textContent += ' · ' + tr('最新正式赛果') + ' ' +
        fmtVal(map.score1) + ' : ' + fmtVal(map.score2) + ' · Rev ' + map.revision;
    });
    document.getElementById('seriesActionReload').addEventListener('click', async function () {
      if (!await refreshBundle(true)) return;
      var mode = state.dialogPayload.seriesAction.mode;
      if (!document.querySelector('[data-action="open-series-' + mode + '"]:not(:disabled)')) {
        showError('seriesActionError', '系列赛状态已改变，请返回查看最新赛果。');
        return;
      }
      var reason = document.getElementById('seriesActionReason').value;
      openSeriesActionModal(mode);
      document.getElementById('seriesActionReason').value = reason;
    });

    // Dynamic action buttons inside panes
    document.getElementById('adminMain').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-action]');
      if (!btn) return;
      var act = btn.dataset.action;
      if (act === 'open-start-run') {
        openStartRunModal(Number(btn.dataset.mapId), btn.dataset.prevRunId ? Number(btn.dataset.prevRunId) : null);
      } else if (act === 'bind-director') {
        openBindDirectorModal(Number(btn.dataset.runId), Number(btn.dataset.mapId));
      } else if (act === 'view-receipts') {
        openDirectorReceiptsModal(Number(btn.dataset.runId));
      } else if (act === 'open-participation') {
        openRecordParticipationModal(Number(btn.dataset.runId));
      } else if (act === 'open-batch-participation') {
        openBatchParticipationModal(Number(btn.dataset.runId));
      } else if (act === 'quick-participation') {
        openRecordParticipationModal(Number(btn.dataset.runId), Number(btn.dataset.playerId), Number(btn.dataset.partyId));
      } else if (act === 'review-participation') {
        openReviewParticipationModal(
          Number(btn.dataset.partId),
          btn.dataset.present === '1',
          Number(btn.dataset.rev),
          btn.dataset.playerName || ''
        );
      } else if (act === 'open-tech-replay') {
        openTechReplayModal(Number(btn.dataset.runId), Number(btn.dataset.mapId));
      } else if (act === 'jump-stats') {
        state.statsTarget.runId = Number(btn.dataset.runId);
        state.statsTarget.playerId = Number(btn.dataset.playerId);
        populateStatsSelectors();
        setActiveTab('stats', true);
        if (state.statsLoaded) loadStatsTarget(false);
      } else if (act === 'parse-demo') {
        btn.disabled = true;
        triggerDemoParse(Number(btn.dataset.demoId)).finally(function () { btn.disabled = false; });
      } else if (act === 'toggle-analyses') {
        loadDemoAnalyses(Number(btn.dataset.demoId));
      } else if (act === 'preview-analysis') {
        openAnalysisPreview(Number(btn.dataset.analysisId));
      } else if (act === 'open-confirm-map') {
        openConfirmMapModal(Number(btn.dataset.mapId));
      } else if (act === 'open-series-settle') {
        openSeriesActionModal('settle');
      } else if (act === 'open-series-reopen') {
        openSeriesActionModal('reopen');
      }
    });

    // Form submissions
    document.getElementById('startRunForm').addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError('startRunError');
      var p = state.dialogPayload.startRun || {};
      var evidence = (document.getElementById('startRunEvidence').value || '').trim();
      if (!evidence) {
        showError('startRunError', '请填写开局现场依据');
        return;
      }
      var body = { scheduled_map_id: p.scheduled_map_id, evidence: evidence };
      if (p.previous_map_run_id) body.previous_map_run_id = p.previous_map_run_id;
      var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/start', { method: 'POST', json: body });
      if (!r.ok) {
        showError('startRunError', r.data.error || '登记实际开局失败');
        return;
      }
      closeDialog('startRunDialog');
      showFeedback('已登记实际开局（Run #' + r.data.map_run_id + '）。', 'success');
      await refreshBundle(true);
    });

    document.getElementById('bindDirectorForm').addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError('bindDirectorError');
      var p = state.dialogPayload.bindDirector || {};
      var sessionId = (document.getElementById('bindDirectorSessionId').value || '').trim();
      var reason = (document.getElementById('bindDirectorReason').value || '').trim();
      if (!sessionId || !reason) {
        showError('bindDirectorError', '请填写导播会话编号与核对说明');
        return;
      }
      var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/bind-director-session', {
        method: 'POST',
        json: { map_run_id: p.map_run_id, session_id: sessionId, reason: reason }
      });
      if (!r.ok) {
        showError('bindDirectorError', r.data.error || '绑定导播会话失败');
        return;
      }
      closeDialog('bindDirectorDialog');
      showFeedback('已绑定导播会话 ' + sessionId + ' 到 Run #' + p.map_run_id + '。', 'success');
      await refreshBundle(true);
    });

    document.getElementById('recordPartForm').addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError('recordPartError');
      var p = state.dialogPayload.recordPart || {};
      var pair = (document.getElementById('recordPartPlayerSelect').value || '').split(':');
      var reason = (document.getElementById('recordPartReason').value || '').trim();
      var roundRaw = (document.getElementById('recordPartRound').value || '').trim();
      var sideVal = document.getElementById('recordPartSide').value;
      if (pair.length !== 2 || !reason) {
        showError('recordPartError', '请选择选手并填写登记依据');
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
        showError('recordPartError', r.data.error || '登记出场失败');
        return;
      }
      closeDialog('recordPartDialog');
      showFeedback('已登记选手出场（#' + r.data.participation_id + '）。', 'success');
      await refreshBundle(true);
    });

    var batchPartForm = document.getElementById('batchPartForm');
    if (batchPartForm) {
      var batchFields = document.getElementById('batchPartFields');
      var batchClose = batchPartForm.querySelectorAll('[data-close-dialog]');
      document.getElementById('batchPartDialog').addEventListener('cancel', function (e) {
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
        var reason = (document.getElementById('batchPartReason').value || '').trim();
        var checked = Array.from(document.querySelectorAll('#batchPartPlayerList .batch-part-cb:checked'));
        if (!checked.length || !reason) {
          return;
        }
        var submitBtn = document.getElementById('batchPartSubmitBtn');
        submitBtn.disabled = true;
        submitBtn.textContent = tr('提交中……');
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
              var message = tr(r.data.error || '批量登记出场失败');
              if (i) message = tr('已登记 ' + i + ' 名选手。') + ' ' + message;
              showError('batchPartError', message);
              await refreshBundle(true);
              return;
            }
            var team = checked[i].closest('fieldset');
            checked[i].closest('label').remove();
            if (!team.querySelector('input')) team.remove();
          }
          closeDialog('batchPartDialog');
          showFeedback('已登记 ' + checked.length + ' 名选手。', 'success');
          await refreshBundle(true);
        } finally {
          batchFields.disabled = false;
          submitBtn.textContent = tr('确认登记出场');
          batchClose.forEach(function (btn) { btn.disabled = false; });
          syncBatchSelection();
        }
      });
    }

    document.getElementById('reviewPartForm').addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError('reviewPartError');
      var p = state.dialogPayload.reviewPart || {};
      var reason = (document.getElementById('reviewPartReason').value || '').trim();
      if (!reason) {
        showError('reviewPartError', '请填写核准原因');
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
        showError('reviewPartError', r.data.error || '核准出场失败');
        return;
      }
      closeDialog('reviewPartDialog');
      showFeedback(p.present ? '已恢复该选手出场记录。' : '已撤回该选手出场记录。', 'success');
      await refreshBundle(true);
    });

    document.getElementById('techReplayForm').addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError('techReplayError');
      var p = state.dialogPayload.techReplay || {};
      var reason = (document.getElementById('techReplayReason').value || '').trim();
      if (!reason) {
        showError('techReplayError', '请填写故障原因');
        return;
      }
      var body = { map_run_id: p.map_run_id, reason: reason };
      if (p.expected_revision != null) body.expected_revision = p.expected_revision;
      if (p.expected_series_revision != null) body.expected_series_revision = p.expected_series_revision;

      if (document.getElementById('techReplaySubToggle').checked) {
        var outId = Number(document.getElementById('techReplayOutgoing').value);
        var inId = Number(document.getElementById('techReplayIncoming').value);
        if (!outId || !inId) {
          showError('techReplayError', '请选择有效的换出选手与该队可用候补');
          return;
        }
        body.outgoing_player_id = outId;
        body.incoming_player_id = inId;
      }
      var retained = readRetentionDecisions('techReplayRetentionBox');
      if (retained) body.retain_downstream = retained;

      var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/technical-replay', { method: 'POST', json: body });
      if (!r.ok) {
        if (r.status === 409) document.getElementById('techReplayReload').hidden = false;
        showError('techReplayError', r.data.error || '批准技术重赛失败');
        return;
      }
      closeDialog('techReplayDialog');
      showFeedback('已批准技术重赛，Run #' + r.data.void_map_run_id + ' 已作废，请开启重赛新局。', 'success');
      await refreshBundle(true);
    });

    document.getElementById('confirmMapForm').addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError('confirmMapError');
      var p = state.dialogPayload.confirmMap || {};
      var runId = Number(document.getElementById('confirmMapRunSelect').value);
      var s1 = Number(document.getElementById('confirmMapScore1').value);
      var s2 = Number(document.getElementById('confirmMapScore2').value);
      var reason = (document.getElementById('confirmMapReason').value || '').trim();
      if (!Number.isInteger(s1) || !Number.isInteger(s2) || s1 === s2) {
        showError('confirmMapError', '回合分必须为整数且不能平局');
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

      var r = await apiJson('/admin/matches/' + MATCH_ID + '/operations/confirm-map', { method: 'POST', json: body });
      if (!r.ok) {
        if (r.status === 409) document.getElementById('confirmMapReload').hidden = false;
        showError('confirmMapError', r.data.error || '保存单图正式赛果失败');
        return;
      }
      closeDialog('confirmMapDialog');
      showFeedback('单图正式赛果已确认（' + s1 + ' : ' + s2 + '）。', 'success');
      await refreshBundle(true);
    });

    document.getElementById('seriesActionForm').addEventListener('submit', async function (e) {
      e.preventDefault();
      clearError('seriesActionError');
      var p = state.dialogPayload.seriesAction || {};
      var reason = (document.getElementById('seriesActionReason').value || '').trim();
      if (p.mode === 'reopen' && !reason) {
        showError('seriesActionError', '撤销完赛必须填写原因');
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
        if (r.status === 409) document.getElementById('seriesActionReload').hidden = false;
        showError('seriesActionError', r.data.error || '系列赛操作失败');
        return;
      }
      closeDialog('seriesActionDialog');
      showFeedback(p.mode === 'settle' ? '比赛已正式完赛，晋级签位与竞猜积分已按正式赛果结算。' : '已撤销本次完赛结算，比赛恢复为进行中。', 'success');
      await refreshBundle(true);
    });
  }

  function renderAll() {
    renderSummary();
    renderAuthCard();
    renderFrozenRoster();
    renderMapsAndRuns();
    populateDemoUploadSelectors();
    renderDemosList();
    renderResultsTab();
    if (state.tab === 'results') loadLiveReference();
    populateStatsSelectors();
    if (state.tab === 'stats' && state.statsTarget.runId && state.statsTarget.playerId) {
      loadStatsTarget(true);
    }
  }

  bindEvents();
  renderAll();

  var initialHash = (window.location.hash || '').replace(/^#/, '');
  setActiveTab(initialHash || 'runs', false);
})();
