// 快捷赛期：按自然日计算，开始当天算第 1 天，最后一天 20:00 结束
function setEventDuration(days) {
  var startInput = document.getElementById('startDateInput');
  var endInput = document.getElementById('endDateInput');
  var startDate = startInput.value ? new Date(startInput.value) : new Date();
  if (isNaN(startDate.getTime())) startDate = new Date();
  function formatDT(d) {
    var pad = function (n) { return n < 10 ? '0' + n : n; };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  if (!startInput.value) {
    startDate.setHours(10, 0, 0, 0);
    startInput.value = formatDT(startDate);
    startInput.dispatchEvent(new Event('change', { bubbles: true }));
  }
  var endDate = new Date(startDate.getTime());
  endDate.setDate(endDate.getDate() + days - 1);
  endDate.setHours(20, 0, 0, 0);
  // 开始时间已经晚于最后一天 20:00（如单日赛 21:00 开赛），就改为当天 23:59 结束
  if (endDate.getTime() <= startDate.getTime()) endDate.setHours(23, 59, 0, 0);
  endInput.value = formatDT(endDate);
  endInput.dispatchEvent(new Event('change', { bubbles: true }));
}
document.querySelectorAll('[data-event-days]').forEach(function (chip) {
  chip.addEventListener('click', function () { setEventDuration(Number(chip.getAttribute('data-event-days'))); });
});
