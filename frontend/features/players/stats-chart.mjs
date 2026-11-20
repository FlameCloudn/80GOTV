(function() {
  var chartData = JSON.parse(document.getElementById('playerChartData').textContent);
  var canvas = document.getElementById('ratingChart');
  if (!canvas || !chartData.labels.length) return;
  var chart = null;
  // 颜色从全站变量里取，深浅主题都跟着变
  function token(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function drawChart() {
    if (chart) { chart.resize(); return; }
    var accent = token('--accent'), soft = token('--accent-soft'), muted = token('--text-muted'), line = token('--border-color');
    chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: chartData.labels,
        datasets: [{
          label: 'RATING',
          data: chartData.rating,
          borderColor: accent,
          backgroundColor: soft,
          fill: true,
          tension: .25,
          pointRadius: 2,
          pointHitRadius: 10,   // 鼠标离点 12px 以内就显示数值（默认只有 3px，很难对准）
          pointBackgroundColor: accent
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: muted, maxTicksLimit: 8, font: { size: 11 } }, grid: { color: line } },
          y: { ticks: { color: muted, font: { size: 11 } }, grid: { color: line }, min: 0, suggestedMax: 2 }
        }
      }
    });
  }
  document.addEventListener('site:tab-activated', function(event) {
    if (event.detail && event.detail.group === 'player-stats' && event.detail.tab === 'career') drawChart();
  });
})();
