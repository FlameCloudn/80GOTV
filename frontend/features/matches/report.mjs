const report = JSON.parse(document.getElementById('matchReportData').textContent);


// 生成 Markdown / BBcode 两种格式的战报文字
function buildText(kind) {
  var bold = kind === 'markdown' ? ['**', '**'] : ['[b]', '[/b]'];
  var bullet = kind === 'markdown' ? '- ' : '[*] ';
  var lines = [bold[0] + report.headline + bold[1] + report.event];
  report.maps.forEach(function (line) { lines.push(bullet + line); });
  if (report.mvp) {
    var mvpLine = 'MVP: ' + report.mvp;
    lines.push((kind === 'bbcode' ? bold[0] + mvpLine + bold[1] : mvpLine) + report.mvpNote);
  }
  return lines.join('\n') + '\n';
}

var toast = document.getElementById('copyToast');
document.querySelectorAll('[data-copy]').forEach(function (button) {
  button.addEventListener('click', function () {
    navigator.clipboard.writeText(buildText(button.dataset.copy)).then(function () {
      toast.hidden = false;
      setTimeout(function () { toast.hidden = true; }, 2000);
    });
  });
});
