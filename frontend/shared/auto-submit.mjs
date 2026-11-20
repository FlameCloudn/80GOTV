// 没有脚本时仍用表单的提交按钮。
  document.querySelectorAll('select[data-auto-submit]').forEach(function (select) {
    select.addEventListener('change', function () { select.form.submit(); });
  });
  document.querySelectorAll('[data-js-hidden]').forEach(function (el) { el.hidden = true; });
