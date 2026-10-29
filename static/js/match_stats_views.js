(function () {
  'use strict';

  window.updateMatchStatsSide = function (root, side) {
    root.querySelectorAll('tr[data-side-values]').forEach(function (row) {
      var values = JSON.parse(row.getAttribute('data-side-values'))[side] || {};
      row.querySelectorAll('[data-stat]').forEach(function (node) {
        var value = values[node.getAttribute('data-stat')];
        var known = value !== null && value !== undefined && Number.isFinite(Number(value));
        node.textContent = known
          ? Number(value).toFixed(Number(node.getAttribute('data-digits')) || 0) + (node.getAttribute('data-suffix') || '')
          : '-';
      });
      row.querySelectorAll('[data-stat-sort]').forEach(function (cell) {
        var value = values[cell.getAttribute('data-stat-sort')];
        cell.setAttribute('data-val', value === null || value === undefined ? '' : String(value));
      });
    });
  };
})();
