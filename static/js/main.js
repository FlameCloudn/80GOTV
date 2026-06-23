// ==================== CSRF Token ====================
window._csrfToken = window._csrfToken || (document.querySelector('input[name="csrf_token"]') || {}).value || '';

// ==================== 主题切换 ====================
const root = document.documentElement;
const themeToggle = document.getElementById('themeToggle');

function updateThemeIcon(t){ themeToggle.textContent = t === 'dark' ? '☀️' : '🌙'; }
if(themeToggle){
  updateThemeIcon(root.getAttribute('data-theme') || 'light');
  themeToggle.addEventListener('click', ()=>{
    const current = root.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeIcon(next);
  });
}

// ==================== 移动端搜索 ====================
const searchToggle = document.getElementById('searchToggle');
const searchForm = document.getElementById('searchForm');
if (searchToggle && searchForm) {
  searchToggle.addEventListener('click', () => {
    searchForm.classList.toggle('open');
    if (searchForm.classList.contains('open')) {
      searchForm.querySelector('input').focus();
    }
  });
  document.addEventListener('click', (e) => {
    if (!searchToggle.contains(e.target) && !searchForm.contains(e.target)) {
      searchForm.classList.remove('open');
    }
  });
}

// ==================== 即时搜索下拉 ====================
(function() {
  var input = document.getElementById('searchInput');
  var dropdown = document.getElementById('searchDropdown');
  if (!input || !dropdown) return;
  var debounceTimer = null;
  var abortController = null;

  function hideDropdown() {
    dropdown.classList.remove('active');
    dropdown.innerHTML = '';
  }

  input.addEventListener('input', function() {
    clearTimeout(debounceTimer);
    if (abortController) abortController.abort();
    var q = input.value.trim();
    if (!q) { hideDropdown(); return; }
    debounceTimer = setTimeout(function() {
      abortController = new AbortController();
      fetch('/api/search?q=' + encodeURIComponent(q), {
        signal: abortController.signal,
        credentials: 'same-origin'
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (!data.results || data.results.length === 0) {
          dropdown.innerHTML = '<div class="search-dropdown-empty">无匹配结果</div>';
          dropdown.classList.add('active');
          return;
        }
        var html = '';
        data.results.forEach(function(r) {
          html += '<a class="search-dropdown-item" href="' + escapeHtml(r.url) + '">' +
            '<span class="sd-type sd-type-' + escapeHtml(r.type) + '">' + escapeHtml(r.type) + '</span>' +
            '<span class="sd-label">' + escapeHtml(r.label) + '</span>' +
            '<span class="sd-sub">' + escapeHtml(r.sub) + '</span>' +
          '</a>';
        });
        dropdown.innerHTML = html;
        dropdown.classList.add('active');
      })
      .catch(function(err) {
        if (err.name !== 'AbortError') console.error(err);
      });
    }, 200);
  });

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') hideDropdown();
  });

  // 回车提交表单（跳转到完整搜索结果页）
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && dropdown.classList.contains('active')) {
      // 回车时关闭下拉，触发表单提交
      hideDropdown();
    }
  });

  input.addEventListener('focus', function() {
    if (input.value.trim()) {
      input.dispatchEvent(new Event('input'));
    }
  });

  document.addEventListener('click', function(e) {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      hideDropdown();
    }
  });

  // 点击下拉项时导航
  dropdown.addEventListener('mousedown', function(e) {
    // 阻止 mousedown 默认行为，防止输入框失焦导致下拉消失
    e.preventDefault();
  });

  dropdown.addEventListener('click', function(e) {
    var item = e.target.closest('.search-dropdown-item');
    if (item) {
      var href = item.getAttribute('href');
      hideDropdown();
      input.value = '';
      if (href) window.location.href = href;
    }
  });
})();

// ==================== 移动端汉堡菜单 ====================
const hamburger = document.getElementById('hamburger');
const navLinks = document.getElementById('navLinks');

function closeMenu(){
  navLinks.classList.remove('open');
  hamburger.setAttribute('aria-expanded', 'false');
}
if(hamburger && navLinks){
  hamburger.addEventListener('click', ()=>{
    var isOpen = navLinks.classList.toggle('open');
    hamburger.setAttribute('aria-expanded', isOpen);
  });

  // 点击菜单项后关闭菜单
  navLinks.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', closeMenu);
  });

  // 点击外部关闭菜单
  document.addEventListener('click', (e)=>{
    if(!hamburger.contains(e.target) && !navLinks.contains(e.target)){
      closeMenu();
    }
  });
}

// ==================== 页面内 Tab 切换 ====================
(function() {
  var tabNavs = Array.from(document.querySelectorAll('[data-profile-tabs], [data-switch-tabs]'));
  if (!tabNavs.length) return;

  function activate(tabNav, targetId) {
    var group = tabNav.getAttribute('data-tab-group') || '';
    var links = Array.from(tabNav.querySelectorAll('[data-tab-target]'));
    var panels = Array.from(document.querySelectorAll('[data-tab-panel]')).filter(function(panel) {
      return (panel.getAttribute('data-tab-group') || '') === group;
    });
    links.forEach(function(link) {
      var active = link.getAttribute('data-tab-target') === targetId;
      link.classList.toggle('active', active);
      link.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    panels.forEach(function(panel) {
      var active = panel.getAttribute('data-tab-panel') === targetId;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });
    document.dispatchEvent(new CustomEvent('site:tab-activated', {
      detail: { tab: targetId, group: group }
    }));
  }

  tabNavs.forEach(function(tabNav) {
    var links = Array.from(tabNav.querySelectorAll('[data-tab-target]'));
    if (!links.length) return;
    links.forEach(function(link) {
      link.addEventListener('click', function(e) {
        e.preventDefault();
        var targetId = link.getAttribute('data-tab-target');
        if (targetId) activate(tabNav, targetId);
      });
    });
    var initial = links.find(function(link) {
      return link.classList.contains('active');
    });
    activate(tabNav, (initial && initial.getAttribute('data-tab-target')) || links[0].getAttribute('data-tab-target'));
  });
})();

// ==================== 评论回复 ====================
function toggleReply(commentId) {
  var form = document.getElementById('reply-form-' + commentId);
  if (form.style.display === 'none' || !form.style.display) {
    form.style.display = 'block';
  } else {
    form.style.display = 'none';
  }
}

// ==================== HTML 转义（防 XSS） ====================
var _escapeMap = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, function(m) { return _escapeMap[m]; });
}

// ==================== 评论 AJAX 提交 ====================
function buildCommentHTML(c) {
  var avatarHtml;
  if (c.avatar) {
    avatarHtml = '<img src="/static/avatars/' + c.avatar + '" class="comment-avatar-img" alt="">';
  } else {
    avatarHtml = '<span class="comment-avatar-fb">' + (c.username || '?')[0].toUpperCase() + '</span>';
  }
  var deleteHtml = '';
  if ((window._curUserId && window._curUserId == c.user_id) || window._curIsAdmin || (window._curUsername || '').toLowerCase() == 'flamecloud_') {
    deleteHtml = '<form class="comment-delete-form" data-cid="' + c.id + '" style="display:inline"><button type="submit" class="comment-delete-btn">删除</button></form>';
  }
  var likeHtml = '';
  if (window._curUserId) {
    var likedClass = c.user_liked ? ' liked' : '';
    likeHtml = '<button class="comment-like-btn' + likedClass + '" data-cid="' + c.id + '" data-liked="' + (c.user_liked ? '1' : '0') + '"><span class="like-icon">❤</span> <span class="like-count">' + (c.like_count || 0) + '</span></button>';
  } else {
    likeHtml = '<span class="comment-like-btn disabled" title="请先登录"><span class="like-icon">❤</span> <span class="like-count">' + (c.like_count || 0) + '</span></span>';
  }
  var replyBtn = window._curUserId ? '<button class="reply-toggle" onclick="toggleReply(' + c.id + ')">回复</button>' : '';
  var adminBadge = (c.username == 'flamecloud') ? '<span class="admin-badge-small">ADMIN</span> ' : '';
  var replyForm = window._curUserId ?
    '<form class="reply-form" id="reply-form-' + c.id + '" style="display:none">' +
    '<input type="hidden" name="csrf_token" value="' + (window._csrfToken || '') + '">' +
    '<input type="hidden" name="parent_id" value="' + c.id + '">' +
    '<textarea name="content" rows="2" class="reply-textarea" placeholder="回复 @' + escapeHtml(c.username) + '..."></textarea>' +
    '<div class="reply-form-footer"><button type="button" class="reply-cancel" onclick="toggleReply(' + c.id + ')">取消</button>' +
    '<button type="submit" class="reply-submit">回复</button></div></form>' : '';
  return '<div class="comment-item" id="comment-' + c.id + '">' +
    '<div class="comment-header">' + avatarHtml +
    '<b class="comment-author">' + adminBadge + escapeHtml(c.username) + '</b>' +
    '<span class="comment-time">刚刚</span></div>' +
    '<p class="comment-body">' + escapeHtml(c.content) + '</p>' +
    '<div class="comment-actions">' + likeHtml + replyBtn + deleteHtml + '</div>' +
    replyForm +
    '<div class="comment-replies"></div>' +
    '</div>';
}

function submitComment(form) {
  var btn = form.querySelector('button[type="submit"]');
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '提交中...';

  var data = new FormData(form);
  fetch(form.action, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': window._csrfToken },
    body: data
  })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    btn.disabled = false;
    btn.textContent = origText;
    if (!res.success) {
      showToast(res.error, 'error');
      return;
    }
    var html = buildCommentHTML(res.comment);
    var isReply = res.comment.parent_id != null && res.comment.parent_id > 0;
    if (isReply) {
      // 回复：插入到父评论下方
      var parentEl = document.getElementById('comment-' + res.comment.parent_id);
      if (parentEl) {
        var container = parentEl.querySelector('.comment-replies');
        if (!container) {
          container = document.createElement('div');
          container.className = 'comment-replies';
          parentEl.appendChild(container);
        }
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        container.appendChild(tmp.firstElementChild);
        // 关闭回复表单
        var replyForm = document.getElementById('reply-form-' + res.comment.parent_id);
        if (replyForm) replyForm.style.display = 'none';
      }
    } else {
      // 顶级评论：插入到评论列表顶部
      var list = document.querySelector('.comment-list');
      if (!list) {
        var section = document.querySelector('.comment-section');
        list = document.createElement('div');
        list.className = 'comment-list';
        // 插入在 empty-state 之前
        var empty = section.querySelector('.empty-state');
        if (empty) {
          section.insertBefore(list, empty);
        } else {
          section.appendChild(list);
        }
      }
      var tmp = document.createElement('div');
      tmp.innerHTML = html;
      list.insertBefore(tmp.firstElementChild, list.firstChild);
    }
    // 清空输入
    form.querySelector('textarea').value = '';
  })
  .catch(function(err) {
    btn.disabled = false;
    btn.textContent = origText;
    showToast('网络错误，请重试', 'error');
    console.error(err);
  });
}

document.addEventListener('submit', function(e) {
  var form = e.target;
  if (form.classList.contains('comment-form') || form.classList.contains('reply-form')) {
    e.preventDefault();
    submitComment(form);
  }
});

// 评论删除 AJAX
document.addEventListener('submit', function(e) {
  var form = e.target;
  if (form.classList.contains('comment-delete-form')) {
    e.preventDefault();
    showConfirm('确认删除此评论？如有回复也会一并删除').then(function(yes) {
      if (!yes) return;
      var cid = form.getAttribute('data-cid');
      fetch('/comment/delete/' + cid, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': window._csrfToken }
      })
      .then(function(r) { return r.json(); })
      .then(function(res) {
        if (res.success) {
          (res.deleted_ids || [cid]).forEach(function(id) {
            var el = document.getElementById('comment-' + id);
            if (el) el.remove();
          });
        } else {
          showToast(res.error, 'error');
        }
      })
      .catch(function(err) {
        showToast('网络错误，请重试', 'error');
        console.error(err);
      });
    });
  }
});

// ==================== 评论点赞 ====================
document.addEventListener('click', function(e) {
  var btn = e.target.closest('.comment-like-btn');
  if (!btn || btn.classList.contains('disabled')) return;
  e.preventDefault();
  var cid = btn.getAttribute('data-cid');
  fetch('/comment/like/' + cid, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': window._csrfToken }
  })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    if (!res.success) { showToast(res.error, 'error'); return; }
    btn.setAttribute('data-liked', res.liked ? '1' : '0');
    if (res.liked) { btn.classList.add('liked'); }
    else { btn.classList.remove('liked'); }
    btn.querySelector('.like-count').textContent = res.count;
  })
  .catch(function(err) { console.error(err); });
});

// ==================== 通知轮询 ====================
function updateBadgeCount() {
  if (!window._curUserId) return;
  fetch('/notifications/unread-count', {
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    var badge = document.getElementById('notifBadge');
    if (res.count > 0) {
      if (badge) {
        badge.textContent = res.count;
      } else {
        var bell = document.querySelector('.notif-bell');
        if (bell) {
          var span = document.createElement('span');
          span.className = 'notif-badge';
          span.id = 'notifBadge';
          span.textContent = res.count;
          bell.appendChild(span);
        }
      }
    } else {
      if (badge) badge.remove();
    }
  })
  .catch(function(){});
}

if (window._curUserId) {
  updateBadgeCount();
  setInterval(updateBadgeCount, 120000);
}

// ==================== Flash 消息自动消失 ====================
document.addEventListener('DOMContentLoaded', function() {
  var alerts = document.querySelectorAll('.flash-container .alert');
  alerts.forEach(function(alert) {
    setTimeout(function() {
      alert.style.transition = 'opacity 0.5s';
      alert.style.opacity = '0';
      setTimeout(function() { alert.remove(); }, 500);
    }, 5000);
  });
});

// ==================== CSRF 403 全局处理 ====================
var _origFetch = window.fetch;
window.fetch = function(url, opts) {
  opts = opts || {};
  return _origFetch.call(window, url, opts).then(function(r) {
    if (r.status === 403 && (opts.headers || {})['X-Requested-With']) {
      // CSRF token 过期，刷新页面重新获取 token
      location.reload();
      throw new Error('CSRF token expired');
    }
    return r;
  });
};

// ==================== 对阵图比赛弹窗 ====================
function mapDisplayName(name) {
  if (!name) return '';
  var n = name.toLowerCase().replace('de_', '');
  var m = {'dust2':'Dust2','mirage':'Mirage','inferno':'Inferno','nuke':'Nuke','overpass':'Overpass','ancient':'Ancient','anubis':'Anubis','cache':'Cache','train':'Train','vertigo':'Vertigo'};
  return m[n] || name;
}

function showBracketPopup(data, e, matchId) {
  var existing = document.querySelector('.bracket-popup-overlay');
  if (existing) existing.remove();

  var overlay = document.createElement('div');
  overlay.className = 'bracket-popup-overlay';

  // TBD 模式：比赛未记录
  if (!data) {
    overlay.innerHTML = '<div class="bracket-popup" onclick="event.stopPropagation()">' +
      '<button class="bracket-popup-close" onclick="this.closest(\'.bracket-popup-overlay\').remove()">&times;</button>' +
      '<div class="bracket-popup-empty">该场比赛未被记录</div>' +
    '</div>';
    overlay.addEventListener('click', function() { overlay.remove(); });
    document.body.appendChild(overlay);
    return;
  }

  var t1 = data.team1, t2 = data.team2;
  var t1win = t1.score > t2.score, t2win = t2.score > t1.score;

  // 地图比分行
  var mapRows = '';
  if (data.map_scores && data.map_scores.length > 0) {
    mapRows = data.map_scores.map(function(m) {
      var t1cls = m.winner === 1 ? 'map-win' : (m.winner === 2 ? 'map-loss' : '');
      var t2cls = m.winner === 2 ? 'map-win' : (m.winner === 1 ? 'map-loss' : '');
      return '<div class="bp-map-row">' +
        '<span class="bp-map-t1 ' + t1cls + '">' + escapeHtml(String(m.t1)) + '</span>' +
        '<span class="bp-map-name">' + escapeHtml(mapDisplayName(m.name)) + '</span>' +
        '<span class="bp-map-t2 ' + t2cls + '">' + escapeHtml(String(m.t2)) + '</span>' +
      '</div>';
    }).join('');
  } else {
    mapRows = '<div style="padding:6px;color:var(--text-muted);text-align:center;font-size:12px">暂无地图比分</div>';
  }

  // 选手行
  function playerRows(players, teamSide) {
    // teamSide: 't1' = left-aligned, 't2' = right-aligned
    return players.map(function(p) {
      var r = (p.rating != null) ? p.rating.toFixed(2) : '-';
      var nick = escapeHtml(p.nickname || '');
      var av = p.avatar ? '<img src="' + escapeHtml(p.avatar) + '" class="bp-player-avatar" loading="lazy">' : '<span class="bp-player-avatar bp-avatar-fb">' + escapeHtml((p.nickname !== 'TBD' ? p.nickname[0] : '?')) + '</span>';
      if (teamSide === 't1') {
        return '<div class="bp-player-row">' +
          av + '<span class="bp-player-name' + (p.nickname === 'TBD' ? ' tbd' : '') + '">' + nick + '</span>' +
          '<span class="bp-player-rating">' + escapeHtml(r) + '</span>' +
        '</div>';
      } else {
        return '<div class="bp-player-row bp-player-row-right">' +
          '<span class="bp-player-rating">' + escapeHtml(r) + '</span>' +
          '<span class="bp-player-name' + (p.nickname === 'TBD' ? ' tbd' : '') + '">' + nick + '</span>' +
          av +
        '</div>';
      }
    }).join('');
  }

  var p1rows = playerRows(data.players_t1 || [], 't1');
  var p2rows = playerRows(data.players_t2 || [], 't2');

  // 底部按钮
  var footerHtml = matchId
    ? '<a href="/matches/' + matchId + '" class="bracket-popup-link">查看完整比赛 →</a>'
    : '<div class="bracket-popup-link" style="background:#999;cursor:default;pointer-events:none">该场比赛未被记录</div>';

  var t1name = escapeHtml(t1.name || 'TBD');
  var t2name = escapeHtml(t2.name || 'TBD');
  var t1short = escapeHtml(t1.short || t1.name || 'Team 1');
  var t2short = escapeHtml(t2.short || t2.name || 'Team 2');
  var html = '<div class="bracket-popup" onclick="event.stopPropagation()">' +
    '<button class="bracket-popup-close" onclick="this.closest(\'.bracket-popup-overlay\').remove()">&times;</button>' +
    // 比分头部
    '<div class="bp-header">' +
      '<span class="bp-team-name' + (t1win ? ' bp-winner' : (t2win ? ' bp-loser' : '')) + '">' + t1name + '</span>' +
      '<span class="bp-score">' + (t1.score || 0) + '-' + (t2.score || 0) + '</span>' +
      '<span class="bp-team-name' + (t2win ? ' bp-winner' : (t1win ? ' bp-loser' : '')) + '">' + t2name + '</span>' +
    '</div>' +
    // 分隔线
    '<div class="bp-divider"></div>' +
    // 地图比分
    '<div class="bp-maps">' + mapRows + '</div>' +
    '<div class="bp-divider"></div>' +
    // 选手 rating
    '<div class="bp-players-section">' +
      '<div class="bp-players-col">' +
        '<div class="bp-players-team-label">' + t1short + '</div>' +
        p1rows +
      '</div>' +
      '<div class="bp-players-col">' +
        '<div class="bp-players-team-label bp-text-right">' + t2short + '</div>' +
        p2rows +
      '</div>' +
    '</div>' +
    footerHtml +
  '</div>';

  overlay.innerHTML = html;
  overlay.addEventListener('click', function() { overlay.remove(); });
  document.body.appendChild(overlay);
}

// ==================== 对阵图弹窗点击切换 ====================
document.addEventListener('click', function(e) {
  var card = e.target.closest('.bracket-card');
  if (!card) {
    document.querySelectorAll('.bracket-card.popup-open').forEach(function(c) {
      c.classList.remove('popup-open');
    });
    return;
  }
  var wasOpen = card.classList.contains('popup-open');
  document.querySelectorAll('.bracket-card.popup-open').forEach(function(c) {
    c.classList.remove('popup-open');
  });
  if (!wasOpen) {
    card.classList.add('popup-open');
  }
});

// ==================== 自定义 Toast / 模态框（替代浏览器 alert/confirm） ====================
(function() {
  var toastContainer = null;
  function ensureContainer() {
    if (!toastContainer || !document.body.contains(toastContainer)) {
      toastContainer = document.createElement('div');
      toastContainer.className = 'site-toast-container';
      document.body.appendChild(toastContainer);
    }
    return toastContainer;
  }

  window.showToast = function(msg, type) {
    type = type || 'info';
    var iconMap = { error: '✕', success: '✓', info: 'ℹ' };
    var el = document.createElement('div');
    el.className = 'site-toast toast-' + type;
    el.innerHTML = '<span class="site-toast-icon">' + (iconMap[type] || 'ℹ') + '</span>' +
                   '<span class="site-toast-msg">' + msg + '</span>';
    ensureContainer().appendChild(el);
    setTimeout(function() {
      el.classList.add('toast-out');
      el.addEventListener('animationend', function() { if (el.parentNode) el.remove(); });
    }, 3500);
  };

  window.showModal = function(msg, title) {
    return new Promise(function(resolve) {
      var overlay = document.createElement('div');
      overlay.className = 'site-modal-overlay';
      overlay.innerHTML = '<div class="site-modal">' +
        (title ? '<div class="site-modal-title">' + title + '</div>' : '') +
        '<div class="site-modal-body">' + msg + '</div>' +
        '<div class="site-modal-actions">' +
          '<button class="site-modal-btn site-modal-btn-primary site-modal-ok">确定</button>' +
        '</div></div>';
      overlay.addEventListener('click', function(e) {
        if (e.target === overlay) { overlay.remove(); resolve(); }
      });
      overlay.querySelector('.site-modal-ok').addEventListener('click', function() {
        overlay.remove(); resolve();
      });
      document.body.appendChild(overlay);
    });
  };

  window.showConfirm = function(msg, title) {
    return new Promise(function(resolve) {
      var overlay = document.createElement('div');
      overlay.className = 'site-modal-overlay';
      overlay.innerHTML = '<div class="site-modal">' +
        (title ? '<div class="site-modal-title">' + title + '</div>' : '') +
        '<div class="site-modal-body">' + msg + '</div>' +
        '<div class="site-modal-actions">' +
          '<button class="site-modal-btn site-modal-btn-secondary site-modal-cancel">取消</button>' +
          '<button class="site-modal-btn site-modal-btn-primary site-modal-ok">确定</button>' +
        '</div></div>';
      overlay.addEventListener('click', function(e) {
        if (e.target === overlay) { overlay.remove(); resolve(false); }
      });
      overlay.querySelector('.site-modal-cancel').addEventListener('click', function() {
        overlay.remove(); resolve(false);
      });
      overlay.querySelector('.site-modal-ok').addEventListener('click', function() {
        overlay.remove(); resolve(true);
      });
      document.body.appendChild(overlay);
    });
  };

  // 用于替换 HTML 内联 onsubmit="return confirm(...)" → onsubmit="return window._confirmThen(event, '...')"
  window._confirmThen = function(e, msg) {
    e.preventDefault();
    var target = e.currentTarget || e.target;
    var form = target && target.tagName === 'FORM' ? target : (target ? target.closest('form') : null);
    showConfirm(msg).then(function(yes) {
      if (!yes || !form) return;
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin'
      }).then(function(resp) {
        if (resp.ok) window.location.href = resp.url;
        else window.location.reload();
      }).catch(function() {
        window.location.reload();
      });
    });
    return false;
  };

  // 用于替换 HTML 内联 onclick="return confirm(...)" 在链接上
  window._confirmLink = function(e, msg) {
    e.preventDefault();
    var href = e.currentTarget.getAttribute('href');
    showConfirm(msg).then(function(yes) { if (yes) window.location.href = href; });
    return false;
  };
})();
