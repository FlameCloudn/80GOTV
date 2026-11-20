// 先检查队标再发送报名或变更队标的请求。
(function() {
  var SELECTOR = 'input[type="file"][data-max-bytes]';

  function report(input) {
    var problem = window.checkUploadFile ? window.checkUploadFile(input) : '';
    var key = 'upload:' + (input.id || input.name);
    if (problem) {
      input.setAttribute('aria-invalid', 'true');
      window.showToast(problem, 'error', { key: key });
    } else {
      input.removeAttribute('aria-invalid');
      window.dismissToast(key);
    }
    return problem;
  }

  document.addEventListener('change', function(event) {
    if (event.target.matches && event.target.matches(SELECTOR)) report(event.target);
  });

  // 排在页面自己的提交处理（如队长操作的页面内提交）前面
  document.addEventListener('submit', function(event) {
    var bad = Array.prototype.filter.call(event.target.querySelectorAll(SELECTOR), report)[0];
    if (!bad) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    bad.focus();
  }, true);
})();
