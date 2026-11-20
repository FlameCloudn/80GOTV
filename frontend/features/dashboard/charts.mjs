const charts = JSON.parse(document.getElementById('dashboardChartData').textContent);

(function(){
  // 图表颜色直接读全站设计变量，换主题时颜色自动跟着变
  var rootStyle = getComputedStyle(document.documentElement);
  function token(name, fallback) { return rootStyle.getPropertyValue(name).trim() || fallback; }
  var textColor = token('--text-secondary', '#c5ced7');
  var gridColor = token('--border-color', '#3a4652');
  var accentColor = token('--accent', '#5e96be');
  var goldColor = token('--color-gold', '#d4a72c');
  Chart.defaults.font.family = token('--site-font-family', 'sans-serif');
  Chart.defaults.font.size = 12;
  Chart.defaults.devicePixelRatio = window.devicePixelRatio || 1;
  var commonOptions = { responsive: true, maintainAspectRatio: false };

  // 1. RATING 分布 — 柱状图
  var buckets = charts.ratingBuckets;
  new Chart(document.getElementById('chartRating'), {
    type: 'bar',
    data: {
      labels: buckets.map(function(b){ return b.bucket; }),
      datasets: [{
        label: window.siteMessage('client.inline_dashboard.players'), data: buckets.map(function(b){ return b.cnt; }),
        backgroundColor: accentColor, borderRadius: 4
      }]
    },
    options: {
      ...commonOptions,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: textColor }, grid: { color: gridColor } },
        y: { beginAtZero: true, ticks: { color: textColor }, grid: { color: gridColor } }
      }
    }
  });

  function drawMedalChart(canvasId, rows, valueKey, label, color) {
    new Chart(document.getElementById(canvasId), {
      type: 'bar',
      data: {
        labels: rows.map(function(t){ return t.nickname; }),
        datasets: [{
          label: label,
          data: rows.map(function(t){ return t[valueKey] || 0; }),
          backgroundColor: color,
          borderRadius: 4
        }]
      },
      options: {
        indexAxis: 'y',
        ...commonOptions,
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, ticks: { stepSize: 1, color: textColor }, grid: { color: gridColor } },
          y: { ticks: { color: textColor }, grid: { color: gridColor } }
        }
      }
    });
  }

  // 2. MVP 排行 — 独立横向柱状图
  drawMedalChart('chartMvpMedals', charts.topMvps, 'mvp_count', 'MVP', goldColor);

  // 3. EVP 排行 — 独立横向柱状图
  drawMedalChart('chartEvpMedals', charts.topEvps, 'evp_count', 'EVP', accentColor);

  // 4. 赛事比赛数量 — 饼图
  var events = charts.eventMatches;
  var pieColors = [accentColor, goldColor, token('--color-t', '#e0a23c'), token('--color-green', '#22c55e'), token('--color-ct', '#5b9bd5'), token('--color-red', '#ef4444'), token('--text-muted', '#96a4b1'), token('--border-strong', '#526171')];
  new Chart(document.getElementById('chartEvents'), {
    type: 'doughnut',
    data: {
      labels: events.map(function(e){ return e.event; }),
      datasets: [{
        data: events.map(function(e){ return e.cnt; }),
        backgroundColor: pieColors, borderWidth: 0
      }]
    },
    options: {
      ...commonOptions,
      plugins: { legend: { position: 'right', labels: { color: textColor, usePointStyle: true, pointStyle: 'rectRounded' } } }
    }
  });

})();
