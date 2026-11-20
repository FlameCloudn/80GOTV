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
  rows.forEach(function(row, i) {
    var rankCell = row.querySelector('.rank-cell');
    if (rankCell) rankCell.textContent = i + 1;
    tbody.appendChild(row);
  });
  applyRatingColors();
}
function applyRatingColors() {
  document.querySelectorAll('.rt-cell').forEach(function(cell) {
    var val = parseFloat(cell.textContent.trim());
    if (isNaN(val) || val === 0) return;
    cell.classList.remove('rt-1','rt-2','rt-3','rt-4','rt-5');
    if (val >= 1.05)      cell.classList.add('rt-4');
    else if (val >= 0.95) cell.classList.add('rt-3');
    else                  cell.classList.add('rt-1');
  });
}
document.addEventListener('click', function(e) {
  var th = e.target.closest('th.sortable');
  if (th) sortStatsTable(th);
});
applyRatingColors();
