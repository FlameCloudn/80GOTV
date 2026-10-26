// 80GOTV 后台表单保护（接线部分）：提交前校验、未保存离开提醒、草稿提示条、服务器拒绝后的处理。
// 依赖 admin_forms.js、admin_form_guard.js、site_dialogs.js；要在 admin.js 之前引入。
// 错误和注意事项一律用右上角浮动提示（showToast）；表单里只留“要不要恢复草稿”这一条可选操作。
(function () {
  'use strict';

  var F = window.adminForms;
  var G = window.adminFormGuard;
  if (!F || !G) return;
  var t = F.t;
  var guarded = [];

  function confirmBox(text) {
    return window.adminConfirm ? window.adminConfirm(text) : Promise.resolve(window.confirm(t(text)));
  }

  function timeLabel(ms) {
    var d = new Date(ms);
    var pad = function (n) { return n < 10 ? '0' + n : String(n); };
    return F.isEnglish() ? (d.getMonth() + 1) + '/' + d.getDate() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes())
      : (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  // 表单顶部“有一份未保存的草稿”：带恢复 / 放弃按钮，选完就消失
  function draftNotice(form, text, actions) {
    var bar = document.createElement('div');
    bar.className = 'form-notice form-notice-draft';
    bar.setAttribute('role', 'status');
    bar.innerHTML = G.icon('draft') + '<span class="form-notice-text"></span>';
    bar.querySelector('.form-notice-text').textContent = text;
    actions.forEach(function (action) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-sm' + (action.primary ? ' btn-primary' : '');
      button.textContent = action.label;
      button.addEventListener('click', function () { action.run(); bar.remove(); });
      bar.appendChild(button);
    });
    form.insertBefore(bar, form.firstElementChild ? form.firstElementChild.nextSibling : null);
    return bar;
  }

  // 恢复后还要用户自己补的：文件要重新选、密码要重新填（草稿不存这两样）
  function leftToRedo(form, files) {
    var notes = [];
    if (files && files.length) {
      var names = files.map(function (name) { return t(name); }).join(F.isEnglish() ? ', ' : '、');
      notes.push(F.isEnglish() ? 'Files are not kept. Please choose again: ' + names : '文件不会保留，请重新选择：' + names);
    }
    var password = Array.prototype.some.call(form.querySelectorAll('input[type="password"]'), function (el) {
      return !el.disabled && !el.closest('[hidden]');
    });
    if (password) notes.push(t('密码不会存进草稿，需要重新填写。'));
    return notes;
  }

  // 右上角黄色提示（不会自动消失）：说明表单现在的状态，并列出要补的文件、密码
  function restoredToast(form, state, lead, files) {
    var lines = (lead ? [lead] : []).concat(leftToRedo(form, files));
    if (lines.length) window.showToast(lines.join('\n'), 'warning', { key: 'form-restored:' + state.key });
  }

  function restore(form, state, draft, reason) {
    F.apply(form, draft.fields || {});
    state.check();
    G.updateGroups(form);
    restoredToast(form, state, reason, draft.files);
  }

  // 打开页面时：有这条记录的草稿、而且和当前内容不同，就问要不要恢复（不自动填、不自动提交）
  function offerDraft(form, state) {
    var draft = F.readDraft(state.key);
    if (!draft || !F.draftDiffers(form, draft)) return;
    var text = F.isEnglish() ? 'Unsaved draft from ' + timeLabel(draft.savedAt) + '.'
      : '有一份 ' + timeLabel(draft.savedAt) + ' 未保存的草稿。';
    draftNotice(form, text, [
      { label: t('恢复草稿'), primary: true, run: function () { restore(form, state, draft); } },
      { label: t('放弃草稿'), run: function () { F.removeDraft(state.key); } },
    ]);
  }

  function setup(form) {
    // 浏览器自带的校验气泡找不到折叠组、隐藏标签页里的字段；改由本脚本校验并定位
    form.noValidate = true;
    var state = { key: F.draftKey(form), dirty: false, submitting: false, serverRejected: form.hasAttribute('data-server-rejected'), timer: null };
    var initial = JSON.stringify(F.collect(form, true)) + '|' + F.chosenFiles(form).join(',');
    // 打开时表单已经是草稿的内容、又不同于服务器原始值：是浏览器“返回”时填回的未保存内容，按“有改动”算
    var saved = F.readDraft(state.key);
    state.restored = !!saved && !F.draftDiffers(form, saved) && F.differsFromServer(form);
    state.check = function () {
      state.dirty = state.serverRejected || state.restored || JSON.stringify(F.collect(form, true)) + '|' + F.chosenFiles(form).join(',') !== initial;
      form.classList.toggle('is-dirty', state.dirty);
      return state.dirty;
    };
    // 分组状态（还差几项必填 / 几处需修改）和“有改动”标记每次输入立即刷新；只有写草稿稍等一下再存
    function changed(event) {
      var target = event && event.target;
      // 选完文件只查这个文件的大小和格式（不连带把别的空字段标红）；已标红的其他字段边改边复查
      if (target && target.type === 'file') {
        if (event.type === 'change') G.checkField(target);
      } else if (target && target.getAttribute && target.getAttribute('aria-invalid') === 'true') G.validate(form);
      state.check();
      G.updateGroups(form);
      if (!form.hasAttribute('data-draft')) return;
      clearTimeout(state.timer);
      state.timer = setTimeout(function () {
        if (state.check()) F.writeDraft(state.key, form); else F.removeDraft(state.key);
      }, 400);
    }
    form.addEventListener('input', changed);
    form.addEventListener('change', changed);
    form.addEventListener('click', function () { setTimeout(changed, 0); });
    form._adminState = state;
    guarded.push(form);
    state.check();
    G.updateGroups(form);
    return state;
  }

  // 提交：先校验（出错就定位、右上角说明，不提交），通过后记下“刚提交过”，下一页据此清除或放回草稿
  function bindSubmit() {
    document.addEventListener('submit', function (event) {
      var form = event.target;
      if (!form._adminState) return;
      // 带 formnovalidate 的按钮（如“清空该年”）不做填写检查，和浏览器原来的规则一样
      if (event.submitter && event.submitter.formNoValidate) return;
      var bad = G.validate(form, true);
      if (bad.length) {
        event.preventDefault();
        event.stopImmediatePropagation();
        G.focusField(bad[0]);
      }
    }, true);
    document.addEventListener('submit', function (event) {
      var form = event.target;
      var state = form._adminState;
      if (!state || event.defaultPrevented) return;
      state.submitting = true;
      if (form.hasAttribute('data-draft')) F.writeDraft(state.key, form);
      if (F.session) {
        F.session.setItem(F.PENDING_KEY, JSON.stringify({
          key: state.key, path: location.pathname, files: F.chosenFiles(form), at: Date.now(),
        }));
      }
    });
  }

  function bindLeaveGuard() {
    window.addEventListener('beforeunload', function (event) {
      var dirty = guarded.some(function (form) { var s = form._adminState; return s.check() && !s.submitting; });
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = '';
    });
    document.addEventListener('click', function (event) {
      var link = event.target.closest('[data-discard]');
      var form = link && link.closest('form');
      var state = form && form._adminState;
      if (!state || !state.check()) return;
      event.preventDefault();
      confirmBox('放弃未保存的修改吗？').then(function (yes) {
        if (!yes) return;
        F.removeDraft(state.key);
        state.submitting = true;
        location.href = link.href;
      });
    });
  }

  // 读出“上一页刚提交过”的记录（读完就删）；超过 30 分钟的不算
  function takePending() {
    if (!F.session) return null;
    var pending = null;
    try { pending = JSON.parse(F.session.getItem(F.PENDING_KEY) || 'null'); } catch (e) { pending = null; }
    F.session.removeItem(F.PENDING_KEY);
    return pending && Date.now() - pending.at <= 30 * 60 * 1000 ? pending : null;
  }

  // 服务器这次的结果：后台提示区（.admin-flashes）里第一条提示的类型
  function flashKind() {
    var alert = document.querySelector('.admin-flashes .alert');
    return alert ? (alert.className.match(/alert-(success|error|info)/) || [])[1] : '';
  }

  // 上一页刚提交、服务器没保存又回到同一页：把刚才填的放回来（不提交）。
  // 服务器给的原因在它自己的红色提示里；这里再用一条黄色提示说明表单状态
  function handleRejected(pending) {
    var form = guarded.filter(function (f) { return f._adminState.key === pending.key; })[0];
    if (!form) return;
    var state = form._adminState;
    var draft = F.readDraft(pending.key);
    state.serverRejected = true;
    if (draft && F.draftDiffers(form, draft)) {
      restore(form, state, draft, t('服务器没有保存，已把刚才填写的内容放回表单（尚未提交）。'));
    } else {
      restoredToast(form, state, t('服务器没有保存，当前修改尚未提交。'), pending.files);
      state.check();
    }
  }

  // 提交和离开的监听在脚本加载时就注册：要排在 admin.js 的“操作前确认”之前
  bindSubmit();
  bindLeaveGuard();

  window.addEventListener('pageshow', function () {
    setTimeout(function () {
      guarded.forEach(function (form) {
        var state = form._adminState;
        if (!state) return;
        state.submitting = false;
        state.check();
        G.updateGroups(form);
      });
    }, 0);
  });

  // 先处理“刚保存成功”（清掉草稿），再登记表单，免得把刚保存的内容当成未保存
  function init() {
    F.purgeExpired();
    var pending = takePending();
    var kind = flashKind();
    if (pending && kind === 'success') F.removeDraft(pending.key);
    document.querySelectorAll('form[data-guard], form[data-draft]').forEach(setup);
    if (pending && kind === 'error' && location.pathname === pending.path) handleRejected(pending);
    if (!pending) guarded.forEach(function (form) { if (form.hasAttribute('data-draft')) offerDraft(form, form._adminState); });
  }

  // 页面自己的脚本先把初始状态摆好（比如按单选显示对应字段），再记录“打开时的样子”
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 0); });
  else setTimeout(init, 0);
})();
