function parseLocalDeadlineToEpoch(rawValue) {
  if (!rawValue) return null;
  var ms = new Date(rawValue).getTime();
  if (!Number.isFinite(ms)) return null;
  return Math.floor(ms / 1000);
}

// 新增赛事：三种报名方式切换 + 截止时间转成 UTC 秒
(function bindAddRegistrationMode() {
  var radios = document.querySelectorAll('input[name="registration_mode"]');
  if (!radios.length) return;
  var legacyOpen = document.getElementById('legacyRegOpenInput');
  var wrap = document.getElementById('managedAddDeadlineWrap');
  var localInput = document.getElementById('newRegDeadlineLocal');
  var epochInput = document.getElementById('newRegDeadlineEpoch');
  var eventForm = document.getElementById('eventForm');

  function syncDeadline() {
    if (!localInput || !epochInput) return;
    var active = !localInput.disabled;
    if (!active) {
      localInput.setCustomValidity('');
      epochInput.value = '';
      epochInput.disabled = true;
      return;
    }
    var epoch = parseLocalDeadlineToEpoch(localInput.value);
    if (epoch === null) {
      localInput.setCustomValidity('');
      epochInput.value = '';
      epochInput.disabled = false;
      return;
    }
    if (epoch <= Math.floor(Date.now() / 1000)) {
      localInput.setCustomValidity(window.siteMessage('client.inline_events_form.enter_a_future_registration_deadline'));
      epochInput.value = '';
      epochInput.disabled = false;
      return;
    }
    localInput.setCustomValidity('');
    epochInput.disabled = false;
    epochInput.value = String(epoch);
  }

  function syncMode() {
    var checked = document.querySelector('input[name="registration_mode"]:checked');
    var mode = checked ? checked.value : 'closed';
    if (legacyOpen) legacyOpen.disabled = mode !== 'legacy_open';
    var isManaged = mode === 'managed';
    if (wrap) wrap.hidden = !isManaged;
    if (localInput) {
      localInput.disabled = !isManaged;
      localInput.required = isManaged;
    }
    if (epochInput) epochInput.disabled = !isManaged;
    syncDeadline();
  }

  radios.forEach(function (radio) { radio.addEventListener('change', syncMode); });
  if (localInput) {
    localInput.addEventListener('input', syncDeadline);
    localInput.addEventListener('change', syncDeadline);
  }
  if (eventForm) {
    eventForm.addEventListener('admin-draft:restored', syncMode);
  }
  syncMode();
})();

// 编辑赛事：独立的启用 / 停用新报名管理请求
(function bindEditRegistrationControl() {
  var enableBtn = document.getElementById('enableManagedBtn');
  var disableBtn = document.getElementById('disableManagedBtn');
  var errBox = document.getElementById('managedControlError');
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.getAttribute('content') : '';

  function showErr(text) {
    if (errBox) {
      errBox.textContent = text;
      errBox.hidden = !text;
    }
    if (text && window.showToast) window.showToast(text, 'error');
  }

  async function postControl(btn, url, payload, pendingLabel, successMsg) {
    showErr('');
    var oldLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = pendingLabel;
    try {
      var resp = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(payload || {})
      });
      var data = await resp.json().catch(function () { return {}; });
      if (!resp.ok || data.success === false) {
        showErr(data.error || (window.siteMessage('client.inline_events_form.action_failed_http_status', {status: resp.status})));
        btn.disabled = false;
        btn.textContent = oldLabel;
        return;
      }
      if (window.showToast) window.showToast(successMsg, 'success');
      window.location.reload();
    } catch (e) {
      showErr(window.siteMessage('client.inline_events_form.network_error_please_try_again_later'));
      btn.disabled = false;
      btn.textContent = oldLabel;
    }
  }

  if (enableBtn) {
    enableBtn.addEventListener('click', function () {
      var input = document.getElementById('enableDeadlineLocal');
      var epoch = parseLocalDeadlineToEpoch(input ? input.value : '');
      if (epoch === null) {
        showErr(window.siteMessage('client.inline_events_form.enter_a_registration_deadline_first'));
        if (input) input.focus();
        return;
      }
      if (epoch <= Math.floor(Date.now() / 1000)) {
        showErr(window.siteMessage('client.inline_events_form.registration_deadline_must_be_in_the'));
        if (input) input.focus();
        return;
      }
      var msg = window.siteMessage('client.inline_events_form.enable_managed_registration_the_deadline_will');
      var confirmFn = window.adminConfirm || window.showConfirm;
      confirmFn(msg).then(function (yes) {
        if (!yes) return;
        postControl(enableBtn, enableBtn.getAttribute('data-action-url'), { registration_deadline: epoch }, window.siteMessage('client.inline_events_form.enabling'), window.siteMessage('client.inline_events_form.managed_registration_enabled'));
      });
    });
  }

  if (disableBtn) {
    disableBtn.addEventListener('click', function () {
      var msg = window.siteMessage('client.inline_events_form.disable_managed_registration_and_revert_to');
      var confirmFn = window.adminConfirm || window.showConfirm;
      confirmFn(msg, { danger: true }).then(function (yes) {
        if (!yes) return;
        postControl(disableBtn, disableBtn.getAttribute('data-action-url'), {}, window.siteMessage('client.inline_events_form.disabling'), window.siteMessage('client.inline_events_form.managed_registration_disabled'));
      });
    });
  }
})();
