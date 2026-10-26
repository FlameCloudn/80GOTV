// 80GOTV 后台表单保护：提交前校验并定位到出错字段、未保存离开提醒、草稿保存与恢复。
//
// 用法（写在 <form> 上）：
//   data-guard   有未保存改动时离开页面要提醒；“取消”按钮写 data-discard，点了先问是否放弃
//   data-draft   普通编辑内容自动存草稿（浏览器本地），刷新或误离开后可以选择恢复
// 分组：<details class="form-group"> / <section class="form-group">，标题里放 <span data-group-status></span>，
//       必填分组再加 data-required-group。标签页：面板 class="tab-pane" id="pane-名字"，按钮 data-tab="名字"。
// 额外规则（和后端同样的文字）：data-same-as="另一字段名"、data-not-before="另一字段名"、data-msg-pattern="……"
//
// 草稿按“管理员账号 + 页面地址（含记录编号）+ 表单”分开存，3 天后过期；保存成功或点“放弃”后清除；
// 只填回表单，绝不自动提交。密码、口令、令牌、验证码、CSRF、隐藏字段、文件都不存（文件只记“选过”，提示重新选择）。
(function () {
  'use strict';

  var DRAFT_PREFIX = '80gotv:admin-draft:v1|';
  var PENDING_KEY = '80gotv:admin-pending-submit';
  var DRAFT_TTL_MS = 3 * 24 * 3600 * 1000;
  var SENSITIVE_NAME = /pass|secret|token|csrf|captcha|cookie|key|session|server_address|connect/i;
  var t = function (text) { return window.siteTranslate ? window.siteTranslate(text) : text; };
  var isEnglish = function () { return (document.documentElement.lang || '').indexOf('en') === 0; };

  function storage(kind) {
    try { var s = window[kind]; s.setItem('__t', '1'); s.removeItem('__t'); return s; } catch (e) { return null; }
  }
  var local = storage('localStorage');
  var session = storage('sessionStorage');

  // ---------- 字段 ----------
  function fieldLabel(el) {
    var field = el.closest('.field, fieldset');
    var label = field && field.querySelector('.field-label, legend');
    var native = el.labels && el.labels.length && !el.labels[0].contains(el) ? el.labels[0] : null;
    var text = label ? label.textContent : native ? native.textContent : (el.getAttribute('aria-label') || el.name || '');
    return text.replace(/[*＊]/g, '').replace(/（[^）]*）|\([^)]*\)/g, '').trim();
  }

  // 没有 name 的界面输入（比如拆开的日期、时间框）用 data-draft-name 参与草稿和校验
  function nameOf(el) { return el.name || el.getAttribute('data-draft-name') || ''; }

  function isDraftable(el) {
    if (!nameOf(el) || el.disabled) return false;
    var type = (el.type || '').toLowerCase();
    if (['password', 'file', 'hidden', 'submit', 'button', 'reset'].indexOf(type) !== -1) return false;
    return !SENSITIVE_NAME.test(nameOf(el)) && !el.closest('[data-draft-skip]');
  }

  function readValue(el) {
    var type = (el.type || '').toLowerCase();
    if (type === 'checkbox' || type === 'radio') return el.checked ? el.value : null;
    if (el.tagName === 'SELECT' && el.multiple) {
      return Array.prototype.filter.call(el.options, function (o) { return o.selected; }).map(function (o) { return o.value; });
    }
    return el.value;
  }

  // 服务器发来的原始值（HTML 里写的那份），不受浏览器“返回”时自动填回的影响
  function readDefault(el) {
    var type = (el.type || '').toLowerCase();
    if (type === 'checkbox' || type === 'radio') return el.defaultChecked ? el.value : null;
    if (el.tagName === 'SELECT') {
      var picked = Array.prototype.filter.call(el.options, function (o) { return o.defaultSelected; });
      if (el.multiple) return picked.map(function (o) { return o.value; });
      if (picked.length) return picked[picked.length - 1].value;
      return el.options.length ? el.options[0].value : '';
    }
    return el.defaultValue;
  }

  // 收集字段；sensitive=true 只在内存里判断“有没有改动”时用，绝不写进存储；
  // useDefaults=true 读服务器发来的原始值
  function collect(form, sensitive, useDefaults) {
    var data = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      var name = nameOf(el);
      if (!name || el.disabled) return;
      if (sensitive ? /^(hidden|submit|button|reset|file)$/.test(el.type) || name === 'csrf_token' : !isDraftable(el)) return;
      var type = (el.type || '').toLowerCase();
      var value = useDefaults ? readDefault(el) : readValue(el);
      if (type === 'checkbox') {
        data[name] = data[name] || [];
        if (value !== null) data[name].push(value);
      } else if (type === 'radio') {
        if (value !== null || !(name in data)) data[name] = value;
      } else {
        data[name] = value;
      }
    });
    return data;
  }

  function chosenFiles(form) {
    return Array.prototype.filter.call(form.querySelectorAll('input[type="file"]'), function (el) {
      return el.files && el.files.length;
    }).map(fieldLabel);
  }

  function fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); }

  // 把草稿填回表单（不提交）。页面自己的联动脚本靠 input/change 事件跟着更新
  function apply(form, data) {
    form.dispatchEvent(new CustomEvent('admin-draft:before-restore', { detail: data }));
    Object.keys(data).forEach(function (name) {
      var value = data[name];
      Array.prototype.forEach.call(form.elements, function (el) {
        if (nameOf(el) !== name || !isDraftable(el)) return;
        var type = (el.type || '').toLowerCase();
        var before = readValue(el);
        if (type === 'checkbox') el.checked = Array.isArray(value) && value.indexOf(el.value) !== -1;
        else if (type === 'radio') el.checked = value === el.value;
        else if (el.tagName === 'SELECT' && el.multiple) {
          Array.prototype.forEach.call(el.options, function (o) { o.selected = Array.isArray(value) && value.indexOf(o.value) !== -1; });
        } else if (value != null) el.value = value;
        if (JSON.stringify(before) !== JSON.stringify(readValue(el))) { fire(el, 'input'); fire(el, 'change'); }
      });
    });
    form.dispatchEvent(new CustomEvent('admin-draft:restored', { detail: data }));
  }

  // ---------- 草稿存取 ----------
  function draftKey(form) {
    var forms = Array.prototype.slice.call(document.querySelectorAll('form[data-draft]'));
    var owner = document.body.getAttribute('data-admin-key') || '';
    var context = form.getAttribute('data-draft-context');
    var identity = context ? 'context:' + encodeURIComponent(context) : (form.id || 'form' + forms.indexOf(form));
    return DRAFT_PREFIX + owner + '|' + location.pathname + '|' + identity;
  }

  function readDraft(key) {
    if (!local) return null;
    try {
      var draft = JSON.parse(local.getItem(key) || 'null');
      if (!draft || !draft.savedAt || Date.now() - draft.savedAt > DRAFT_TTL_MS) { local.removeItem(key); return null; }
      return draft;
    } catch (e) { local.removeItem(key); return null; }
  }

  function writeDraft(key, form) {
    if (!local) return;
    try {
      local.setItem(key, JSON.stringify({ savedAt: Date.now(), fields: collect(form, false), files: chosenFiles(form) }));
    } catch (e) { /* 存满或被禁止时不影响填写 */ }
  }

  function removeDraft(key) { if (local) local.removeItem(key); }

  // 清掉所有已过期的草稿（只看保存时间）
  function purgeExpired() {
    if (!local) return;
    for (var i = local.length - 1; i >= 0; i -= 1) {
      var key = local.key(i);
      if (key && key.indexOf(DRAFT_PREFIX) === 0) readDraft(key);
    }
  }

  function draftDiffers(form, draft) {
    var now = collect(form, false);
    return Object.keys(draft.fields || {}).some(function (name) {
      return name in now && JSON.stringify(now[name]) !== JSON.stringify(draft.fields[name]);
    });
  }

  // 现在表单里的内容和服务器发来的原始值不一样（比如浏览器“返回”时把上次输入填回来了）
  function differsFromServer(form) {
    return JSON.stringify(collect(form, false)) !== JSON.stringify(collect(form, false, true));
  }

  window.adminForms = {
    collect: collect, isDraftable: isDraftable, nameOf: nameOf, apply: apply, draftKey: draftKey,
    readDraft: readDraft, writeDraft: writeDraft, removeDraft: removeDraft, purgeExpired: purgeExpired,
    draftDiffers: draftDiffers, differsFromServer: differsFromServer, chosenFiles: chosenFiles, fieldLabel: fieldLabel, fire: fire,
    PENDING_KEY: PENDING_KEY, session: session, t: t, isEnglish: isEnglish,
  };
})();
