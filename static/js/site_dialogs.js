// 全站通用的提示条和确认框（前台 main.js 与后台独立页面共用）。
// 只在还没有定义时注册，重复引入也不会覆盖。
// ==================== 自定义 Toast / 模态框（替代浏览器 alert/confirm） ====================
(function() {
  if (window.showToast && window.showConfirm) return;
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
    var icon = document.createElement('span');
    icon.className = 'site-toast-icon';
    icon.textContent = iconMap[type] || 'ℹ';
    var message = document.createElement('span');
    message.className = 'site-toast-msg';
    message.textContent = String(msg || '');
    el.appendChild(icon);
    el.appendChild(message);
    ensureContainer().appendChild(el);
    setTimeout(function() {
      el.classList.add('toast-out');
      el.addEventListener('animationend', function() { if (el.parentNode) el.remove(); });
    }, type === 'error' ? 5500 : 3500);
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
