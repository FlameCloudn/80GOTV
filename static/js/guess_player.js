(function () {
  'use strict';

  function initPlayerSearch() {
    var form = document.getElementById('guessPlayerForm');
    if (!form) return;

    var query = document.getElementById('guessPlayerQuery');
    var playerId = document.getElementById('guessPlayerId');
    var error = document.getElementById('guessFormError');
    var options = Array.prototype.slice.call(
      document.querySelectorAll('#guessPlayerOptions option')
    );

    function resolveSelection() {
      var value = (query.value || '').trim().toLocaleLowerCase();
      var match = options.find(function (option) {
        return option.value.trim().toLocaleLowerCase() === value;
      });
      playerId.value = match ? match.dataset.playerId : '';
      return Boolean(match);
    }

    query.addEventListener('input', function () {
      error.textContent = '';
      resolveSelection();
    });

    form.addEventListener('submit', function (event) {
      if (!resolveSelection()) {
        event.preventDefault();
        error.textContent = '请从候选列表中选择一名选手';
        query.focus();
      }
    });
  }

  function formatCountdown(milliseconds) {
    var seconds = Math.max(0, Math.floor(milliseconds / 1000));
    var hours = String(Math.floor(seconds / 3600)).padStart(2, '0');
    var minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
    var remainder = String(seconds % 60).padStart(2, '0');
    return hours + ':' + minutes + ':' + remainder;
  }

  function initCountdown() {
    var countdown = document.getElementById('guessCountdown');
    if (!countdown) return;

    function update() {
      var next = new Date();
      next.setHours(24, 0, 0, 0);
      countdown.textContent = formatCountdown(next.getTime() - Date.now());
    }

    update();
    window.setInterval(update, 1000);
  }

  function resultEmoji(cell) {
    if (cell.classList.contains('clue-correct')) return '\uD83D\uDFE9';
    if (cell.classList.contains('clue-close')) return '\uD83D\uDFE8';
    if (cell.classList.contains('clue-neutral')) return '\u2B1C';
    return '\u2B1B';
  }

  function buildShareText(result) {
    var rows = Array.prototype.slice.call(
      document.querySelectorAll('.guess-results-table tbody tr')
    );
    var score = result.dataset.won === '1' ? result.dataset.attempts : 'X';
    var lines = rows.map(function (row) {
      return Array.prototype.slice.call(row.querySelectorAll('td'))
        .map(resultEmoji)
        .join('');
    });
    return [
      '80GO 猜选手 #' + result.dataset.challenge + ' ' + score + '/8',
      '',
      lines.join('\n'),
      '',
      window.location.origin + '/guess-player'
    ].join('\n');
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    textarea.remove();
    return Promise.resolve();
  }

  function initShare() {
    var result = document.getElementById('guessResult');
    var button = document.getElementById('guessShareScore');
    if (!result || !button) return;

    button.addEventListener('click', function () {
      var text = buildShareText(result);
      var action = navigator.share
        ? navigator.share({ title: '80GO 猜选手', text: text })
        : copyText(text);
      action.then(function () {
        var original = button.textContent;
        button.textContent = navigator.share ? '已打开分享' : '结果已复制';
        window.setTimeout(function () { button.textContent = original; }, 1800);
      }).catch(function () {});
    });
  }

  initPlayerSearch();
  initCountdown();
  initShare();
})();
