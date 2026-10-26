(function () {
  'use strict';

  var root = document.querySelector('.guess-room');
  if (!root) return;

  var form = document.getElementById('guessRoomForm');
  var query = document.getElementById('guessPlayerQuery');
  var playerId = document.getElementById('guessPlayerId');
  var search = window.initGuessPlayerSearch();
  var pollTimer = null;
  var submitting = false;

  function text(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function clueCell(value, state) {
    var cell = document.createElement('td');
    cell.className = 'clue-' + (state || 'neutral');
    cell.textContent = value;
    return cell;
  }

  function numericCell(value, feedback) {
    var cell = clueCell(value, feedback.state);
    if (feedback.direction) {
      var arrow = document.createElement('span');
      arrow.className = 'guess-arrow is-' + feedback.direction;
      cell.appendChild(arrow);
    }
    return cell;
  }

  function roleLabel(role) {
    if (role === 'awper') return 'AWPer';
    if (role === 'hybrid') return 'Hybrid';
    if (role === 'rifler') return 'Rifler';
    return '未知';
  }

  function renderResults(results) {
    var body = document.getElementById('roomResults');
    body.replaceChildren();
    results.forEach(function (result) {
      var row = document.createElement('tr');
      row.appendChild(clueCell(result.nickname, result.name_state));
      row.appendChild(clueCell(result.affiliation || '未知', result.team_state));
      var country = clueCell(result.country_flag ? '' : '未知', result.country_state);
      if (result.country_flag) {
        var flag = document.createElement('span');
        flag.className = 'guess-country-flag';
        flag.textContent = result.country_flag;
        flag.setAttribute('aria-label', result.country_name || result.country_flag);
        country.title = result.country_name || '';
        country.appendChild(flag);
      }
      row.appendChild(country);
      row.appendChild(numericCell(result.age == null ? '未知' : String(result.age), result.age_feedback));
      row.appendChild(clueCell(roleLabel(result.role), result.role_state));
      row.appendChild(numericCell(
        result.major_appearances < 0 ? '未知' : String(result.major_appearances),
        result.major_feedback
      ));
      body.appendChild(row);
    });
    document.getElementById('roomResultsWrap').hidden = results.length === 0;
    document.getElementById('roomEmpty').hidden = results.length !== 0;
  }

  function renderState(state) {
    var waiting = state.status === 'waiting';
    var finished = state.status === 'finished';
    document.getElementById('roomWaiting').hidden = !waiting;
    document.getElementById('roomPlay').hidden = waiting;
    text('roomMeName', state.me.username);
    text('roomMeAttempts', state.me.attempts);
    // 对手没进来时是界面文字“等待对手”，要跟着翻译；进来后是用户名，不翻译
    document.getElementById('roomOpponentName').toggleAttribute('data-i18n-ignore', !!state.opponent.joined);
    text('roomOpponentName', state.opponent.username);
    text('roomOpponentAttempts', state.opponent.attempts);
    text('roomRemaining', state.remaining + ' 次机会');
    text('roomStatusText', finished ? '比赛结束' : (state.status === 'active' ? '比赛进行中' : '房间已失效'));
    document.querySelector('.guess-contender.is-me').classList.toggle('is-solved', state.me.solved);
    document.querySelector('.guess-contender.is-opponent').classList.toggle('is-solved', state.opponent.solved);
    form.hidden = !state.can_guess;
    renderResults(state.results || []);

    var outcome = document.getElementById('roomOutcome');
    outcome.hidden = !finished;
    outcome.classList.remove('is-win', 'is-loss', 'is-draw');
    if (finished && state.answer) {
      var labels = { win: '你赢了', loss: '对手先猜中了', draw: '本局平局' };
      outcome.classList.add(state.outcome === 'win' ? 'is-win' : (state.outcome === 'loss' ? 'is-loss' : 'is-draw'));
      text('roomOutcomeLabel', labels[state.outcome] || '比赛结束');
      text('roomAnswerName', state.answer.nickname);
      text('roomAnswerDetail', state.answer.full_name + (state.answer.affiliation ? ' · ' + state.answer.affiliation : ''));
    }
    if (finished && pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function schedulePoll() {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(fetchState, document.hidden ? 4000 : 1400);
  }

  function fetchState() {
    fetch(root.dataset.stateUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      cache: 'no-store'
    }).then(function (response) { return response.json(); })
      .then(function (payload) {
        if (payload.success) renderState(payload.state);
      })
      .catch(function () {})
      .finally(function () {
        if (!document.getElementById('roomOutcome').hidden) return;
        schedulePoll();
      });
  }

  // 出错用右上角提示；没从候选里选中时输入框标红，重新输入时去掉
  function showFormError(message, markInput) {
    if (markInput) query.setAttribute('aria-invalid', 'true');
    window.showToast(message, 'error', { key: 'guess-form' });
  }

  query.addEventListener('input', function () {
    query.removeAttribute('aria-invalid');
    window.dismissToast('guess-form');
    search.resolve();
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    if (!search.resolve()) {
      showFormError('请从候选列表中选择一名选手', true);
      query.focus();
      return;
    }
    var resolvedId = playerId.value;
    if (submitting) return;
    submitting = true;
    window.dismissToast('guess-form');
    fetch(root.dataset.guessUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': window._csrfToken || '',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ player_id: Number(resolvedId) })
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok || !payload.success) throw new Error(payload.error || '提交失败');
        return payload;
      });
    }).then(function (payload) {
      query.value = '';
      playerId.value = '';
      search.reset();
      renderState(payload.state);
    }).catch(function (requestError) {
      showFormError(requestError.message || '提交失败', false);
    }).finally(function () {
      submitting = false;
    });
  });

  document.getElementById('copyRoomCode').addEventListener('click', function () {
    var button = this;
    navigator.clipboard.writeText(root.dataset.roomCode).then(function () {
      button.textContent = '已复制';
      window.setTimeout(function () { button.textContent = '复制房间码'; }, 1200);
    }).catch(function () {
      button.textContent = root.dataset.roomCode;
    });
  });

  renderState(window.guessRoomInitialState);
  if (window.guessRoomInitialState.status !== 'finished') schedulePoll();
})();
