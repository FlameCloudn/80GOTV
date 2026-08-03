(function () {
  'use strict';

  var form = document.getElementById('bingoPickForm');
  if (!form) return;

  var cells = Array.prototype.slice.call(document.querySelectorAll('.bingo-cell-pick'));
  var rowInput = document.getElementById('bingoRowIndex');
  var columnInput = document.getElementById('bingoColumnIndex');
  var playerInput = document.getElementById('bingoPlayerId');
  var query = document.getElementById('bingoPlayerQuery');
  var submit = document.getElementById('bingoSubmit');
  var label = document.getElementById('bingoSelectionLabel');
  var error = document.getElementById('bingoFormError');
  var options = Array.prototype.slice.call(document.querySelectorAll('#bingoPlayerOptions option'));

  function resolvePlayer() {
    var value = (query.value || '').trim().toLocaleLowerCase();
    var match = options.find(function (option) {
      return option.value.trim().toLocaleLowerCase() === value;
    });
    playerInput.value = match ? match.dataset.playerId : '';
    return Boolean(match);
  }

  function selectCell(button) {
    cells.forEach(function (cell) { cell.classList.remove('is-selected'); });
    button.classList.add('is-selected');
    rowInput.value = button.dataset.row;
    columnInput.value = button.dataset.column;
    label.textContent = button.dataset.rowLabel + ' × ' + button.dataset.columnLabel;
    query.disabled = false;
    submit.disabled = false;
    query.value = '';
    playerInput.value = '';
    error.textContent = '';
    query.focus();
  }

  cells.forEach(function (button) {
    button.addEventListener('click', function () { selectCell(button); });
  });

  query.addEventListener('input', function () {
    error.textContent = '';
    resolvePlayer();
  });

  form.addEventListener('submit', function (event) {
    if (rowInput.value === '' || columnInput.value === '') {
      event.preventDefault();
      error.textContent = '请先选择一个空格';
      return;
    }
    if (!resolvePlayer()) {
      event.preventDefault();
      error.textContent = '请从候选列表中选择一名选手';
      query.focus();
    }
  });

  if (cells.length) selectCell(cells[0]);
})();
