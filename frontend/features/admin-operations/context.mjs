import { message as siteMessage } from '../../shared/i18n.js';
import { csrfToken } from '../../shared/site-http.mjs';

const data = document.getElementById('matchOpsData');
export const urls = data.dataset;
export const MATCH_ID = Number(urls.matchId);
export const CSRF = csrfToken();
export let bundle = JSON.parse(data.textContent);

export const root = document.getElementById('adminMain');
export const byId = id => root.querySelector('#' + CSS.escape(id));
let onBundleChanged;
export function onRefresh(render) { onBundleChanged = render; }

export var state = {
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


export function esc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function fmtVal(value) {
  if (value === null || value === undefined || value === '') return '-';
  return String(value);
}

export function fmtBytes(n) {
  var num = Number(n || 0);
  if (!Number.isFinite(num) || num <= 0) return '0 B';
  if (num < 1024) return num + ' B';
  if (num < 1024 * 1024) return (num / 1024).toFixed(1) + ' KB';
  return (num / (1024 * 1024)).toFixed(2) + ' MB';
}

export function mapDisplay(name) {
  if (!name) return '-';
  return String(name).replace(/^(de_|cs_)/i, '').replace(/_/g, ' ').replace(/\b\w/g, function (c) {
    return c.toUpperCase();
  });
}

export function playerLabel(playerId) {
  var p = (bundle.context.players || {})[String(playerId)];
  return p ? p.nickname : '#' + playerId;
}

function playerSteam(playerId) {
  var p = (bundle.context.players || {})[String(playerId)];
  return p && p.steam_id ? p.steam_id : '';
}

export function adminLabel(actor) {
  if (actor === null || actor === undefined || actor === '') return '-';
  var name = (bundle.context.admins || {})[String(actor)];
  return name || '#' + actor;
}

export function entrantLabel(entrantId) {
  if (entrantId === null || entrantId === undefined || entrantId === '') return 'TBD';
  var e = (bundle.context.entrants || {})[String(entrantId)];
  return e ? e.name : '#' + entrantId;
}

export function participantById(pid) {
  return (bundle.context.participants || []).find(function (p) {
    return Number(p.match_participant_id) === Number(pid);
  }) || null;
}

function sideName(sideKey) {
  var list = bundle.context.participants || [];
  var found = list.find(function (p) { return p.side_key === sideKey; });
  return found ? found.name : (sideKey === 'home' ? siteMessage('client.ops_context.home') : siteMessage('client.ops_context.away'));
}

export function homeName() { return sideName('home'); }
export function awayName() { return sideName('away'); }

export function statusLabel(st) {
  return {
    upcoming: siteMessage('client.ops_context.upcoming'),
    live: siteMessage('client.ops_context.ongoing'),
    ongoing: siteMessage('client.ops_context.ongoing'),
    completed: siteMessage('client.ops_context.completed'),
    cancelled: siteMessage('client.ops_context.cancelled')
  }[st] || st || '-';
}

export function runStatusBadge(st) {
  if (st === 'active') return ("<span class=\"badge badge-live\">" + siteMessage('client.ops_context.active') + "</span>");
  if (st === 'closed') return ("<span class=\"badge badge-accent\">" + siteMessage('client.ops_context.closed') + "</span>");
  if (st === 'void') return ("<span class=\"badge badge-danger\">" + siteMessage('client.ops_context.void') + "</span>");
  return '<span class="badge">' + esc(st) + '</span>';
}

export function sourceKindLabel(kind) {
  return { demo: 'Demo', director: siteMessage('client.ops_context.director'), admin: siteMessage('client.ops_context.admin') }[kind] || kind || '-';
}

export function showFeedback(message, kind) {
  var el = byId('opsFeedback');
  if (!el) return;
  el.hidden = false;
  el.className = 'ops-feedback is-' + (kind || 'info');
  el.textContent = String(message);
  if (kind === 'success') {
    window.clearTimeout(showFeedback._timer);
    showFeedback._timer = window.setTimeout(function () {
      el.hidden = true;
    }, 6000);
  }
}

export function clearError(id) {
  var el = byId(id);
  if (el) {
    el.hidden = true;
    el.textContent = '';
  }
}

export function showError(id, msg) {
  var el = byId(id);
  if (el) {
    el.hidden = false;
    el.textContent = (msg || siteMessage('client.ops_context.operation_failed'));
  }
}

export function openDialog(id) {
  var dlg = byId(id);
  if (dlg && typeof dlg.showModal === 'function') {
    if (!dlg.open) dlg.showModal();
  }
}

export function closeDialog(id) {
  var dlg = byId(id);
  if (dlg && dlg.open) dlg.close();
}

export async function apiJson(url, options) {
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
      return { ok: false, status: res.status, data: { error: siteMessage('client.ops_context.no_valid_response_check_that_you') } };
    }
    var data = await res.json();
    return { status: res.status, ok: res.ok && data.ok !== false, data: data };
  } catch (error) {
    return { ok: false, status: 0, data: { error: siteMessage('client.ops_context.network_request_failed_please_try_again') } };
  }
}

export async function refreshBundle(quiet) {
  var r = await apiJson(urls.refreshUrl, { method: 'GET' });
  if (!r.ok) {
    showFeedback(r.data.error || siteMessage('client.ops_context.failed_to_refresh_match_status'), 'error');
    return false;
  }
  bundle = {
    context: r.data.context,
    overview: r.data.overview,
    history: r.data.history,
    originals: r.data.originals
  };
  onBundleChanged();
  if (!quiet) showFeedback(siteMessage('client.ops_context.match_status_refreshed'), 'info');
  return true;
}

export function findRunById(runId) {
  var found = null;
  (bundle.overview.maps || []).forEach(function (m) {
    (m.runs || []).forEach(function (r) {
      if (Number(r.map_run_id) === Number(runId)) found = { map: m, run: r };
    });
  });
  return found;
}

export function buildRetentionUI(containerId, proposedByOutcome) {
  var box = byId(containerId);
  if (!box) return;
  var previous = new Set(Array.from(box.querySelectorAll(':checked'), cb => cb.value));
  box.replaceChildren();
  if (proposedByOutcome && proposedByOutcome.error) {
    box.textContent = String(proposedByOutcome.error);
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
  var html = ("<strong>" + siteMessage('client.ops_context.affected_downstream_slots') + "</strong><div class=\"ops-retention-list\">");

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
        '<div><strong>' + (lk.outcome === 'winner' ? siteMessage('client.ops_context.winner') : siteMessage('client.ops_context.loser')) + ' → <span data-i18n-ignore>' + esc(lk.target_label) + '</span>（' + (lk.target_side === 'home' ? siteMessage('client.ops_context.home_side') : siteMessage('client.ops_context.away_side')) + '）</strong></div>' +
        '<span data-i18n-ignore>' + esc(entrantLabel(lk.event_entrant_id)) + ' → ' + esc(entrantLabel(proposedId)) + '</span>' +
        (lk.protection_reason ? '<div class="muted">' + esc(lk.protection_reason) + '</div>' : '') +
        '<div>' + (selectable ? siteMessage('client.ops_context.keep_the_current_entrant_and_detach') : (lk.protected ? siteMessage('client.ops_context.this_slot_cannot_be_updated_or') : siteMessage('client.ops_context.this_slot_will_follow_the_official'))) + '</div>' +
      '</div>' +
    '</' + tag + '>';
  });
  html += '</div>';
  box.innerHTML = html;
  box.hidden = false;
}

export function readRetentionDecisions(containerId) {
  var box = byId(containerId);
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
