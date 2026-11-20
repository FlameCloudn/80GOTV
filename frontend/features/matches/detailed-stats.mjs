import { updateMatchStatsSide } from './stat-values.mjs';

const view = document.querySelector('.match-detailed-layout');

function switchDetailedStatsTab(name) {
  var root = view.querySelector('.match-detailed-page');
  if (root) root.setAttribute('data-current-tab', name);
  view.querySelectorAll('[data-detailed-tab]').forEach(function(btn) {
    var active = btn.getAttribute('data-detailed-tab') === name;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  view.querySelectorAll('.match-detailed-content').forEach(function(panel) {
    panel.classList.toggle('active', panel.id === 'detailed-tab-' + name);
  });
  syncDetailedMapLinks(name);
}

// 切换标签后，地图卡片的链接带上当前标签，换地图时停在同一个标签
function syncDetailedMapLinks(name) {
  view.querySelectorAll('.match-detailed-map-card[data-map-href]').forEach(function(link) {
    link.setAttribute('href', link.getAttribute('data-map-href') + '&tab=' + encodeURIComponent(name));
  });
}

// 双方 / T / CT：切换显示的列，并按当前视图的 Rating 重新排序
function switchDetailedSide(side) {
  var root = view.querySelector('.match-detailed-page');
  if (!root) return;
  updateMatchStatsSide(root, side);
  root.classList.toggle('match-detailed-side-t', side === 't');
  root.classList.toggle('match-detailed-side-ct', side === 'ct');
  view.querySelectorAll('.match-detailed-side-tabs button').forEach(function(btn) {
    var active = btn.getAttribute('data-side') === side;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  var ratingKey = side === 't' ? 't-rating' : (side === 'ct' ? 'ct-rating' : 'rating');
  view.querySelectorAll('.match-detailed-team-table table').forEach(function(table) {
    var ratingHeader = table.querySelector('th[data-sort="' + ratingKey + '"]');
    if (ratingHeader) sortDetailedTable(ratingHeader, true);
  });
}

function sortDetailedTable(th, forceDescending) {
  var table = th.closest('table');
  var tbody = table ? table.querySelector('tbody') : null;
  if (!tbody) return;
  var columnIndex = Array.from(th.parentNode.children).indexOf(th);
  var descending = forceDescending || !th.classList.contains('sort-desc');
  table.querySelectorAll('th.sort-asc, th.sort-desc').forEach(function(header) {
    header.classList.remove('sort-asc', 'sort-desc');
    header.setAttribute('aria-sort', 'none');
  });
  th.classList.add(descending ? 'sort-desc' : 'sort-asc');
  th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
  Array.from(tbody.querySelectorAll('tr')).sort(function(a, b) {
    var aCell = a.children[columnIndex];
    var bCell = b.children[columnIndex];
    var aValue = parseFloat(aCell ? (aCell.getAttribute('data-val') || aCell.textContent) : '') || 0;
    var bValue = parseFloat(bCell ? (bCell.getAttribute('data-val') || bCell.textContent) : '') || 0;
    return descending ? (bValue - aValue) : (aValue - bValue);
  }).forEach(function(row) {
    tbody.appendChild(row);
  });
}

function switchKillMatrixMode(mode) {
  var root = view.querySelector('.match-detailed-kill-matrix');
  if (!root) return;
  root.querySelectorAll('[data-matrix-tab]').forEach(function(btn) {
    var active = btn.getAttribute('data-matrix-tab') === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  root.querySelectorAll('[data-matrix-mode]').forEach(function(body) {
    body.hidden = body.getAttribute('data-matrix-mode') !== mode;
  });
}

// Rating 上色：≥1.05 绿、0.95~1.05 常规、<0.95 红（和全站一致）
function applyDetailedRatingColors() {
  view.querySelectorAll('.match-detailed-page .rt-cell').forEach(function(cell) {
    var val = parseFloat(cell.textContent.trim());
    if (isNaN(val) || val === 0) return;
    cell.classList.remove('rt-1','rt-2','rt-3','rt-4','rt-5');
    if (val >= 1.05) cell.classList.add('rt-4');
    else if (val >= 0.95) cell.classList.add('rt-3');
    else cell.classList.add('rt-1');
  });
}
applyDetailedRatingColors();
view.addEventListener('click', function(event) {
  var header = event.target.closest('.match-detailed-table-wrap th.sortable');
  if (header) sortDetailedTable(header, false);
});
view.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (button?.hasAttribute('data-detailed-tab')) switchDetailedStatsTab(button.dataset.detailedTab);
  if (button?.matches('.match-detailed-side-tabs [data-side]')) switchDetailedSide(button.dataset.side);
  if (button?.hasAttribute('data-matrix-tab')) switchKillMatrixMode(button.dataset.matrixTab);
});
