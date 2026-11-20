// 80GOTV 后台表单保护（界面部分），依赖 admin_forms.js（草稿存取）和 site_dialogs.js（右上角提示）；
// 要在 admin.js 之前引入，这样提交校验先于“操作前确认”和“保存中”按钮状态。
(function () {
  'use strict';

  var F = window.adminForms;
  if (!F) return;

  function icon(name) {
    var paths = {
      alert: '<path d="M12 4l9 15.5H3z"/><path d="M12 10v4M12 17h.01"/>',
      draft: '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4M9 12h6M9 15.5h6"/>',
    };
    return '<svg class="admin-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + paths[name] + '</svg>';
  }

  // ---------- 错误文字（和后端同样的说法） ----------
  function message(el) {
    var form = el.form;
    var label = F.fieldLabel(el);
    var en = F.isEnglish();
    var same = el.getAttribute('data-same-as');
    if (same && el.value && form.elements[same] && el.value !== form.elements[same].value) {
      return el.getAttribute('data-msg-same') || window.siteMessage('client.admin_form_guard.the_two_entries_don_t_match');
    }
    var after = el.getAttribute('data-not-before');
    var start = after && form.elements[after];
    if (start && el.value && start.value && el.value < start.value) return el.getAttribute('data-msg-not-before') || window.siteMessage('client.admin_form_guard.the_end_time_cannot_be_earlier');
    // 上传文件：大小和格式（站内统一检查，见 site_dialogs.js 的 checkUploadFile）
    var fileProblem = el.type === 'file' && window.checkUploadFile ? window.checkUploadFile(el) : '';
    if (fileProblem) return fileProblem;
    var maxBytes = Number(el.getAttribute('data-max-utf8-bytes'));
    if (maxBytes > 0 && new Blob([el.value]).size > maxBytes) {
      return el.getAttribute('data-msg-max-bytes');
    }
    var v = el.validity;
    if (v.valid) return '';
    var choose = el.tagName === 'SELECT' || el.type === 'radio' || el.type === 'checkbox';
    if (v.valueMissing) return en ? label + ' is required' : (choose ? window.siteMessage('client.admin_form_guard.select') : window.siteMessage('client.admin_form_guard.enter')) + label;
    if (v.patternMismatch && el.getAttribute('data-msg-pattern')) return el.getAttribute('data-msg-pattern');
    if (v.tooShort) return en ? label + ' must be at least ' + el.minLength + ' characters' : window.siteMessage('client.admin_form_guard.label_must_be_at_least_minlength', {label: label, minlength: el.minLength});
    if (v.tooLong) return en ? label + ' cannot exceed ' + el.maxLength + ' characters' : window.siteMessage('client.admin_form_guard.label_cannot_exceed_maxlength_characters', {label: label, maxlength: el.maxLength});
    return en ? label + ' is invalid' : window.siteMessage('client.admin_form_guard.label_has_an_invalid_format', {label: label});
  }

  // ---------- 显示 / 清除字段错误 ----------
  function holder(el) { return el.closest('.field') || el.closest('.check-row') || el.parentNode; }

  function clearError(el) {
    var box = holder(el);
    var old = box && box.querySelector(':scope > .field-error[data-for="' + F.nameOf(el) + '"]');
    if (old) old.remove();
    el.removeAttribute('aria-invalid');
    if (box) box.classList.remove('has-error');
  }

  function showError(el, text) {
    clearError(el);
    var box = holder(el);
    var note = document.createElement('span');
    note.className = 'field-error';
    note.id = 'err-' + (el.id || F.nameOf(el)) + '-' + Math.random().toString(36).slice(2, 7);
    note.setAttribute('data-for', F.nameOf(el));
    note.setAttribute('data-i18n-ignore', '');
    note.innerHTML = icon('alert') + '<span></span>';
    note.lastChild.textContent = text;
    box.appendChild(note);
    box.classList.add('has-error');
    el.setAttribute('aria-invalid', 'true');
    el.setAttribute('aria-describedby', note.id);
  }

  // 让出错字段看得见：展开所在折叠组、切到所在标签页
  function reveal(el) {
    for (var d = el.closest('details'); d; d = d.parentElement && d.parentElement.closest('details')) d.open = true;
    var pane = el.closest('.tab-pane[id^="pane-"]');
    if (pane && (pane.hidden || !pane.classList.contains('active'))) {
      var tab = document.querySelector('[data-tab="' + pane.id.slice(5) + '"]');
      if (tab) tab.click();
    }
  }

  function focusField(el) {
    reveal(el);
    var target = el.getAttribute('data-error-target') ? document.querySelector(el.getAttribute('data-error-target')) : el;
    if (!target) target = el;
    target.scrollIntoView({ block: 'center' });
    try { target.focus({ preventScroll: true }); } catch (e) { target.focus(); }
  }

  // 校验整张表单；返回出错字段（同名单选只算一次）。announce=true（点了保存）时重新弹出右上角提示
  function validate(form, announce) {
    var bad = [];
    var seen = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      var name = F.nameOf(el);
      if (!name || el.disabled || !el.willValidate || seen[name]) return;
      var text = message(el);
      if (text) { seen[name] = true; bad.push(el); showError(el, text); } else clearError(el);
    });
    updateGroups(form);
    updateSummary(form, bad, announce);
    return bad;
  }

  // 只查一个字段（选完文件马上查大小和格式），结果并进这张表单的右上角提示
  function checkField(el) {
    var text = message(el);
    if (text) showError(el, text); else clearError(el);
    updateGroups(el.form);
    var seen = {};
    var bad = Array.prototype.filter.call(el.form.elements, function (field) {
      var name = F.nameOf(field);
      if (field.getAttribute('aria-invalid') !== 'true' || seen[name]) return false;
      seen[name] = true;
      return true;
    });
    updateSummary(el.form, bad, !!text);
  }

  // 右上角“几处需修改”：一处时直接写出问题，多处时逐条列出、点一下跳到那一项；全部改好后自动收起。
  // 改着改着（announce=false）只更新已有的那条，用户关掉了就不再弹
  function updateSummary(form, bad, announce) {
    if (!window.showToast) return;
    var key = 'form-errors:' + (form.id || form.getAttribute('action') || location.pathname);
    if (!bad.length) { window.dismissToast(key); return; }
    var text = bad.length === 1 ? message(bad[0])
      : (F.isEnglish() ? bad.length + ' fields need attention:' : window.siteMessage('client.admin_form_guard.length_fields_need_attention', {length: bad.length}));
    var actions = bad.length === 1 ? [] : bad.slice(0, 5).map(function (el) {
      return { label: message(el) || F.fieldLabel(el), run: function () { focusField(el); } };
    });
    if (announce) window.showToast(text, 'error', { key: key, actions: actions });
    else window.updateToast(key, text, actions);
  }

  // ---------- 分组状态：已填几项 / 还差几项必填 / 几处需修改 ----------
  function filled(el) {
    if (el.type === 'checkbox' || el.type === 'radio') return el.checked;
    if (el.type === 'file') return !!(el.files && el.files.length);
    return String(el.value || '').trim() !== '';
  }

  function groupCounts(group) {
    var names = {};
    var counts = { filled: 0, missing: 0, errors: group.querySelectorAll('.field-error').length };
    group.querySelectorAll('input, select, textarea').forEach(function (el) {
      var name = F.nameOf(el);
      // 被富文本编辑器替换而隐藏的正文框（带 data-error-target）照样算一项，不能漏掉
      var standIn = el.hasAttribute('data-error-target');
      if (!name || el.disabled || el.type === 'hidden' || (el.closest('[hidden]') && !standIn) || name === 'csrf_token') return;
      var entry = names[name] || (names[name] = { filled: false, required: false });
      entry.filled = entry.filled || filled(el);
      entry.required = entry.required || el.required;
    });
    Object.keys(names).forEach(function (name) {
      if (names[name].filled) counts.filled += 1;
      else if (names[name].required) counts.missing += 1;
    });
    return counts;
  }

  function groupText(group, c) {
    var en = F.isEnglish();
    if (c.errors) return { cls: 'is-error', text: en ? c.errors + ' to fix' : window.siteMessage('client.admin_form_guard.errors_fields_need_attention', {errors: c.errors}) };
    if (group.hasAttribute('data-required-group')) {
      return c.missing ? { cls: 'is-missing', text: en ? c.missing + ' required left' : window.siteMessage('client.admin_form_guard.missing_required_fields_remaining', {missing: c.missing}) }
        : { cls: 'is-done', text: en ? 'Complete' : window.siteMessage('client.admin_form_guard.required_fields_complete') };
    }
    return c.filled ? { cls: 'is-filled', text: en ? c.filled + ' filled' : window.siteMessage('client.admin_form_guard.filled_fields_filled', {filled: c.filled}) }
      : { cls: '', text: en ? 'Optional' : window.siteMessage('client.admin_form_guard.optional') };
  }

  function updateGroups(form) {
    form.querySelectorAll('.form-group').forEach(function (group) {
      var status = group.querySelector('[data-group-status]');
      if (!status) return;
      var info = groupText(group, groupCounts(group));
      status.className = 'group-status ' + info.cls;
      status.textContent = info.text;
    });
    form.querySelectorAll('.tab-pane[id^="pane-"]').forEach(function (pane) {
      var tab = document.querySelector('[data-tab="' + pane.id.slice(5) + '"]');
      if (!tab) return;
      var errors = pane.querySelectorAll('.field-error').length;
      tab.classList.toggle('has-error', errors > 0);
      if (errors) tab.setAttribute('data-error-count', String(errors)); else tab.removeAttribute('data-error-count');
    });
  }

  window.adminFormGuard = { validate: validate, checkField: checkField, updateGroups: updateGroups, focusField: focusField, icon: icon };
})();
