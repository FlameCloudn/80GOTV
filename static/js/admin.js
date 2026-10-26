// 80GOTV 后台公共脚本：深浅色切换、操作前确认、复制进服指令、撤销 BP。
// 确认框、提示条用站内同一套（site_dialogs.js 的 showConfirm / showToast），要在本文件之前引入。
(function () {
  'use strict';

  var t = function (text) { return window.siteTranslate ? window.siteTranslate(text) : text; };

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  // ---------- 深浅色 ----------
  function bindThemeToggle() {
    var button = document.getElementById('themeToggle');
    if (!button) return;
    var root = document.documentElement;
    function sync() {
      var dark = root.getAttribute('data-theme') === 'dark';
      button.setAttribute('aria-label', t(dark ? '切换到浅色模式' : '切换到深色模式'));
    }
    button.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) { /* 浏览器禁止存储时只在本页生效 */ }
      sync();
    });
    sync();
  }

  // ---------- 操作前确认 ----------
  // 用法：<form data-confirm="确定删除……？"> 或提交按钮上写 data-confirm（同一表单不同按钮、不同提示）。
  // 文字先转义再放进确认框，队名、标题里有特殊符号也只会当文字显示。
  // 键盘：焦点只在“取消 / 确定”之间切换，Esc 等于取消，关闭后焦点回到原来的按钮；
  // 危险操作（删除、清空、合并、结束等红色按钮）默认停在“取消”上，误按回车不会执行。
  function trapKeys(overlay, ok, cancel) {
    overlay.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && cancel) { event.preventDefault(); cancel.click(); return; }
      if (event.key !== 'Tab') return;
      var items = [cancel, ok].filter(Boolean);
      var index = items.indexOf(document.activeElement);
      event.preventDefault();
      var next = event.shiftKey ? (index <= 0 ? items.length - 1 : index - 1) : (index + 1) % items.length;
      items[next].focus();
    });
  }

  function askConfirm(message, options) {
    var danger = !!(options && options.danger);
    var opener = document.activeElement;
    var pending = window.showConfirm(escapeHtml(t(message)));
    var overlays = document.querySelectorAll('.site-modal-overlay');
    var overlay = overlays[overlays.length - 1];
    if (overlay) {
      var ok = overlay.querySelector('.site-modal-ok');
      var cancel = overlay.querySelector('.site-modal-cancel');
      var body = overlay.querySelector('.site-modal-body');
      overlay.setAttribute('role', 'alertdialog');
      overlay.setAttribute('aria-modal', 'true');
      if (body) { body.id = 'adminConfirmText'; overlay.setAttribute('aria-describedby', body.id); }
      if (ok && danger) ok.classList.add('is-danger');
      (danger && cancel ? cancel : ok || cancel).focus();
      trapKeys(overlay, ok, cancel);
    }
    return pending.then(function (yes) {
      if (!yes && opener && opener.focus && document.contains(opener)) opener.focus();
      return yes;
    });
  }

  function isDanger(form, submitter) {
    var button = submitter || form.querySelector('button[type="submit"]');
    return form.hasAttribute('data-confirm-danger') || !!(button && button.classList.contains('btn-danger'));
  }

  function bindConfirmations() {
    document.addEventListener('submit', function (event) {
      var form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      var submitter = event.submitter;
      var message = (submitter && submitter.getAttribute('data-confirm')) || form.getAttribute('data-confirm');
      if (!message) return;
      if (form.dataset.confirmed === '1') { form.dataset.confirmed = ''; return; }
      event.preventDefault();
      event.stopImmediatePropagation();
      askConfirm(message, { danger: isDanger(form, submitter) }).then(function (yes) {
        if (!yes) return;
        form.dataset.confirmed = '1';
        if (submitter && form.requestSubmit) form.requestSubmit(submitter);
        else if (form.requestSubmit) form.requestSubmit();
        else form.submit();
      });
    }, true);
  }

  // ---------- 复制进服指令 ----------
  function bindCopyButtons() {
    document.addEventListener('click', function (event) {
      var button = event.target.closest('.copy-connect-btn');
      if (!button) return;
      var command = button.getAttribute('data-connect');
      if (!command) return;
      // 只换按钮里的文字部分，图标保留
      var textNode = button.querySelector('.btn-label') || button;
      var label = textNode.textContent;
      var done = function () {
        textNode.textContent = t('已复制');
        button.classList.add('copied');
        if (window.showToast) window.showToast(t('进服指令已复制'), 'success');
        setTimeout(function () { textNode.textContent = label; button.classList.remove('copied'); }, 1600);
      };
      if (navigator.clipboard && window.isSecureContext !== false) {
        navigator.clipboard.writeText(command).then(done).catch(function () {
          window.prompt(t('请按 Ctrl+C 复制进服指令：'), command);
        });
      } else {
        window.prompt(t('请按 Ctrl+C 复制进服指令：'), command);
      }
    });
  }

  // ---------- 撤销上一步 BP ----------
  function bindBpUndo() {
    document.addEventListener('click', function (event) {
      var button = event.target.closest('[data-bp-undo]');
      if (!button) return;
      askConfirm(button.getAttribute('data-bp-confirm') || '确定撤销上一步 BP 吗？', { danger: true }).then(function (yes) {
        if (!yes) return;
        button.disabled = true;
        fetch('/api/bp/' + encodeURIComponent(button.getAttribute('data-bp-undo')) + '/undo', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRF-Token': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (response) { return response.json(); }).then(function (data) {
          if (data.ok) {
            window.showToast(t('已撤销上一步 BP'), 'success');
            setTimeout(function () { window.location.reload(); }, 900);
          } else {
            button.disabled = false;
            window.showToast(data.msg || t('撤销失败'), 'error');
          }
        }).catch(function () {
          button.disabled = false;
          window.showToast(t('网络错误，撤销失败'), 'error');
        });
      });
    });
  }

  // ---------- 提交中：防止重复点击 ----------
  // 用法：<form data-busy-text="保存中……">，提交后按钮变灰并换成这段文字；返回页面时恢复。
  function bindBusyForms() {
    document.addEventListener('submit', function (event) {
      var form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.hasAttribute('data-busy-text')) return;
      if (event.defaultPrevented) return;
      if (form.dataset.submitting === '1') { event.preventDefault(); return; }
      form.dataset.submitting = '1';
      var button = event.submitter || form.querySelector('button[type="submit"]');
      var status = form.querySelector('.save-status');
      // 等浏览器把表单内容（含按钮自己的 name/value）收好之后再把按钮变灰，免得按钮的值被漏掉
      setTimeout(function () {
        if (button) {
          button._adminBusyIdleNodes = Array.prototype.map.call(button.childNodes, function (node) {
            return node.cloneNode(true);
          });
          button.dataset.idleText = button.textContent;
          button.disabled = true;
          button.textContent = t(form.getAttribute('data-busy-text'));
        }
        if (status) status.hidden = false;
      }, 0);
    });
    window.addEventListener('pageshow', function () {
      document.querySelectorAll('form[data-busy-text]').forEach(function (form) {
        form.dataset.submitting = '';
        form.querySelectorAll('button[type="submit"]').forEach(function (button) {
          button.disabled = false;
          if (button._adminBusyIdleNodes) {
            while (button.firstChild) button.removeChild(button.firstChild);
            button._adminBusyIdleNodes.forEach(function (node) {
              button.appendChild(node.cloneNode(true));
            });
            delete button._adminBusyIdleNodes;
          } else if (button.dataset.idleText) {
            button.textContent = button.dataset.idleText;
          }
          delete button.dataset.idleText;
        });
        var status = form.querySelector('.save-status');
        if (status) status.hidden = true;
      });
    });
  }

  // ---------- 列表即时筛选（只在本页过滤显示，不改数据） ----------
  // <input data-list-search="#表格">：按行的 data-search（没有就用整行文字）找；
  // <select data-list-filter="#表格" data-filter-key="team">：按行上的 data-team 精确匹配；
  // <span data-list-count="#表格">：显示“显示几 / 共几”。搜索框里按 Esc 清空。
  function filterRows(table, controls, counter) {
    var shown = 0;
    var rows = table.querySelectorAll('tbody tr:not(.filter-empty):not(.empty-row)');
    rows.forEach(function (row) {
      var ok = controls.every(function (control) {
        var value = control.value.trim().toLowerCase();
        if (!value) return true;
        if (control.hasAttribute('data-list-search')) {
          return (row.getAttribute('data-search') || row.textContent).toLowerCase().indexOf(value) !== -1;
        }
        return (row.getAttribute('data-' + control.getAttribute('data-filter-key')) || '').toLowerCase() === value;
      });
      row.hidden = !ok;
      if (ok) shown += 1;
    });
    var empty = table.querySelector('tbody tr.filter-empty');
    if (!empty) {
      empty = document.createElement('tr');
      empty.className = 'filter-empty empty-row';
      empty.innerHTML = '<td colspan="' + (table.tHead ? table.tHead.rows[0].cells.length : 1) + '"></td>';
      table.tBodies[0].appendChild(empty);
    }
    empty.firstChild.textContent = t('没有符合条件的记录');
    empty.hidden = shown !== 0 || rows.length === 0;
    if (counter) counter.textContent = shown === rows.length ? String(rows.length) : shown + ' / ' + rows.length;
  }

  function bindListFilters() {
    var groups = {};
    document.querySelectorAll('[data-list-search], [data-list-filter]').forEach(function (control) {
      var target = control.getAttribute('data-list-search') || control.getAttribute('data-list-filter');
      (groups[target] = groups[target] || []).push(control);
    });
    Object.keys(groups).forEach(function (target) {
      var table = document.querySelector(target);
      if (!table || !table.tBodies.length) return;
      var controls = groups[target];
      var counter = document.querySelector('[data-list-count="' + target + '"]');
      var run = function () { filterRows(table, controls, counter); };
      // 从别的页面带着条件进来（如 ?team=队名、?q=关键词），先填好筛选
      var params = new URLSearchParams(window.location.search);
      controls.forEach(function (control) {
        var value = params.get(control.getAttribute('data-filter-key') || 'q');
        if (value === null) return;
        var known = control.tagName !== 'SELECT' || Array.prototype.some.call(control.options, function (o) { return o.value === value; });
        if (known) control.value = value;
      });
      controls.forEach(function (control) {
        control.addEventListener('input', run);
        control.addEventListener('change', run);
        if (control.hasAttribute('data-list-search')) {
          control.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && control.value) { control.value = ''; run(); }
          });
        }
      });
      run();
    });
  }

  window.adminConfirm = askConfirm;
  bindThemeToggle();
  bindConfirmations();
  bindCopyButtons();
  bindBpUndo();
  bindBusyForms();
  bindListFilters();
})();
