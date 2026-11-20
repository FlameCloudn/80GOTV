import { updateMatchStatsSide } from './stat-values.mjs';

const view = document.querySelector('.match-detail-layout');

// 地图数据切换：“全部地图”和每张地图各一个面板
function switchDetailTab(idx) {
  view.querySelectorAll('button.detail-tab').forEach(function(btn, i) {
    btn.classList.toggle('active', i === idx);
    btn.setAttribute('aria-selected', i === idx ? 'true' : 'false');
  });
  view.querySelectorAll('.detail-panel').forEach(function(p, i) {
    p.classList.toggle('active', i === idx);
  });
  view.querySelectorAll('.match-stat-map-card').forEach(function(card, i) {
    card.classList.toggle('active', i === idx - 1);
  });
}

function switchMatchStatsTab(name) {
  view.querySelectorAll('.match-stats-tab').forEach(function(btn) {
    var active = btn.getAttribute('data-match-stat') === name;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  view.querySelectorAll('.match-stats-content').forEach(function(panel) {
    panel.classList.toggle('active', panel.id === 'match-stat-' + name);
  });
  applyRatingColors();
}

// 双方 / T / CT：切换显示的列，并按当前视图的 RATING 重新排序
function switchSideView(mode) {
  updateMatchStatsSide(view, mode);
  view.querySelectorAll('.side-toggle-btn').forEach(function(btn) {
    var match = btn.getAttribute('data-side') === mode;
    btn.classList.toggle('active', match);
    btn.setAttribute('aria-selected', match ? 'true' : 'false');
  });
  view.querySelectorAll('.stats-table').forEach(function(table) {
    table.classList.toggle('side-overall', mode === 'overall');
    table.classList.toggle('side-t', mode === 't');
    table.classList.toggle('side-ct', mode === 'ct');
    table.querySelectorAll('tbody').forEach(function(tbody) {
      var rows = Array.from(tbody.querySelectorAll('tr'));
      var colClass = mode === 't' ? '.col-t' : (mode === 'ct' ? '.col-ct' : '.col-overall');
      rows.sort(function(a, b) {
        var aVal = parseFloat((a.querySelector(colClass + '.rt-cell') || {}).textContent) || 0;
        var bVal = parseFloat((b.querySelector(colClass + '.rt-cell') || {}).textContent) || 0;
        return bVal - aVal;
      });
      rows.forEach(function(row) { tbody.appendChild(row); });
    });
    table.querySelectorAll('th.sort-asc, th.sort-desc').forEach(function(th) {
      th.classList.remove('sort-asc', 'sort-desc');
      th.setAttribute('aria-sort', 'none');
    });
    var rtTh = table.querySelector('th[data-sort="rating"]');
    if (rtTh) {
      rtTh.classList.add('sort-desc');
      rtTh.setAttribute('aria-sort', 'descending');
    }
  });
}

// 表格列排序
function sortStatsTable(th) {
  var table = th.closest('table');
  var tbody = table.querySelector('tbody');
  if (!tbody) return;
  var colIdx = Array.from(th.parentNode.children).indexOf(th);
  var descending = !th.classList.contains('sort-desc');
  table.querySelectorAll('th.sort-asc, th.sort-desc').forEach(function(h) {
    h.classList.remove('sort-asc', 'sort-desc');
    h.setAttribute('aria-sort', 'none');
  });
  th.classList.add(descending ? 'sort-desc' : 'sort-asc');
  th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
  var rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort(function(a, b) {
    var aTd = a.children[colIdx];
    var bTd = b.children[colIdx];
    var aVal = parseFloat(aTd ? (aTd.getAttribute('data-val') || aTd.textContent) : '') || 0;
    var bVal = parseFloat(bTd ? (bTd.getAttribute('data-val') || bTd.textContent) : '') || 0;
    return descending ? (bVal - aVal) : (aVal - bVal);
  });
  rows.forEach(function(row) { tbody.appendChild(row); });
  applyRatingColors();
}

function applyRatingColors() {
  view.querySelectorAll('.rt-cell').forEach(function(cell) {
    var val = parseFloat(cell.textContent.trim());
    if (isNaN(val) || val === 0) return;
    cell.classList.remove('rt-1','rt-2','rt-3','rt-4','rt-5');
    if (val >= 1.05)      cell.classList.add('rt-4');
    else if (val >= 0.95) cell.classList.add('rt-3');
    else                  cell.classList.add('rt-1');
  });
}
applyRatingColors();

view.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (button?.hasAttribute('data-detail-index')) switchDetailTab(Number(button.dataset.detailIndex));
  if (button?.matches('.match-stats-tab[data-match-stat]')) switchMatchStatsTab(button.dataset.matchStat);
  if (button?.matches('.side-toggle-btn[data-side]')) switchSideView(button.dataset.side);
  const header = event.target.closest('th.sortable');
  if (header) sortStatsTable(header);
});
