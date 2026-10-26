(function () {
  'use strict';

  window.initGuessPlayerSearch = function () {
    var query = document.getElementById('guessPlayerQuery');
    var playerId = document.getElementById('guessPlayerId');
    var source = document.getElementById('guessPlayerOptions');
    var players = Array.from(source.options).map(function (option) {
      return { id: option.dataset.playerId, nickname: option.value, name: option.textContent.trim() };
    });
    var list = document.createElement('ul');
    list.id = 'guessPlayerSuggestions';
    list.className = 'guess-suggestions';
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    query.parentNode.appendChild(list);
    query.removeAttribute('list');
    query.setAttribute('role', 'combobox');
    query.setAttribute('aria-autocomplete', 'list');
    query.setAttribute('aria-controls', list.id);
    query.setAttribute('aria-expanded', 'false');
    var matches = [];
    var activeIndex = -1;

    function normalized(value) { return value.trim().toLocaleLowerCase(); }

    function hide() {
      list.hidden = true;
      query.setAttribute('aria-expanded', 'false');
      query.removeAttribute('aria-activedescendant');
      activeIndex = -1;
    }

    function resolve() {
      var raw = query.value.trim();
      var value = normalized(raw);
      var exact = players.find(function (player) { return player.nickname === raw; });
      if (!exact) exact = players.find(function (player) { return normalized(player.nickname) === value; });
      if (!exact && value) {
        var realNames = players.filter(function (player) { return normalized(player.name) === value; });
        if (realNames.length === 1) exact = realNames[0];
      }
      playerId.value = exact ? exact.id : '';
      return Boolean(exact);
    }

    function rank(player, value) {
      var nickname = normalized(player.nickname);
      var name = normalized(player.name);
      if (nickname === value) return 0;
      if (nickname.startsWith(value)) return 1;
      if (nickname.includes(value)) return 2;
      if (name.startsWith(value)) return 3;
      if (name.includes(value)) return 4;
      return 5;
    }

    function activate(index) {
      activeIndex = index;
      Array.from(list.children).forEach(function (item, i) {
        item.setAttribute('aria-selected', i === index ? 'true' : 'false');
      });
      var item = list.children[index];
      if (item) {
        query.setAttribute('aria-activedescendant', item.id);
        item.scrollIntoView({ block: 'nearest' });
      }
    }

    function choose(index) {
      if (!matches[index]) return;
      query.value = matches[index].nickname;
      playerId.value = matches[index].id;
      query.removeAttribute('aria-invalid');
      hide();
      query.focus();
    }

    function render() {
      resolve();
      var value = normalized(query.value);
      if (!value) { hide(); return; }
      matches = players.filter(function (player) { return rank(player, value) < 5; });
      matches.sort(function (left, right) {
        return rank(left, value) - rank(right, value) || left.nickname.localeCompare(right.nickname);
      });
      matches = matches.slice(0, 12);
      list.replaceChildren();
      matches.forEach(function (player, index) {
        var item = document.createElement('li');
        item.id = 'guessPlayerSuggestion-' + index;
        item.setAttribute('role', 'option');
        item.setAttribute('data-i18n-ignore', '');
        var nickname = document.createElement('strong');
        nickname.textContent = player.nickname;
        var name = document.createElement('small');
        name.textContent = player.name;
        item.append(nickname, name);
        item.addEventListener('mousedown', function (event) { event.preventDefault(); });
        item.addEventListener('click', function () { choose(index); });
        list.appendChild(item);
      });
      list.hidden = matches.length === 0;
      query.setAttribute('aria-expanded', matches.length ? 'true' : 'false');
      activeIndex = -1;
      query.removeAttribute('aria-activedescendant');
    }

    query.addEventListener('input', render);
    query.addEventListener('focus', render);
    query.addEventListener('blur', hide);
    query.addEventListener('keydown', function (event) {
      if (event.isComposing) return;
      if (event.key === 'Escape') { hide(); return; }
      if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && matches.length) {
        event.preventDefault();
        if (list.hidden) render();
        var direction = event.key === 'ArrowDown' ? 1 : -1;
        activate(activeIndex < 0 ? (direction > 0 ? 0 : matches.length - 1) : (activeIndex + direction + matches.length) % matches.length);
      } else if (event.key === 'Enter' && !list.hidden && activeIndex >= 0) {
        event.preventDefault();
        choose(activeIndex);
      }
    });
    return { resolve: resolve, reset: hide };
  };
})();
