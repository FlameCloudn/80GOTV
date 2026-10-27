(function () {
  function text(value, fallback) {
    if (value === null || value === undefined || value === '') return fallback || '';
    return String(value);
  }

  function make(tag, className, content) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (content !== undefined) el.textContent = content;
    return el;
  }

  function makeLink(href, className) {
    var a = make('a', className);
    a.href = href || '#';
    return a;
  }

  function setIgnoreI18n(el) {
    el.setAttribute('data-i18n-ignore', '');
    return el;
  }

  function emptyNode(message) {
    return make('div', 'h-empty', message);
  }

  function fetchJson(url) {
    return fetch(url, {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    });
  }

  function shortName(match, side) {
    return text(match['team' + side + '_short'], '') || text(match['team' + side], 'TBD');
  }

  function matchOpponents(match) {
    if (Array.isArray(match.opponents) && match.opponents.length === 2) return match.opponents;
    return [1, 2].map(function (side) {
      return {
        side: 't' + side,
        name: text(match['team' + side + '_full'] || match['team' + side], 'TBD'),
        short: shortName(match, side),
        logo: match['team' + side + '_logo'],
        score: match['score' + side]
      };
    }).sort(function (a, b) {
      if ((a.name === 'TBD') !== (b.name === 'TBD')) return a.name === 'TBD' ? 1 : -1;
      var aKey = a.short.toLowerCase(), bKey = b.short.toLowerCase();
      return aKey < bKey ? -1 : (aKey > bKey ? 1 : 0);
    });
  }

  function teamLogo(url) {
    var logo = document.createElement('img');
    logo.className = 'team-logo sm';
    logo.src = url;
    logo.alt = '';
    logo.loading = 'lazy';
    return logo;
  }

  // 下面三个函数输出的结构要和 templates/index.html 里服务器直接渲染的一致
  function renderHomeMatches(target, matches) {
    target.replaceChildren();
    if (!matches || !matches.length) {
      target.appendChild(emptyNode('暂无比赛'));
      return;
    }
    matches.forEach(function (match) {
      var opponents = matchOpponents(match);
      var row = makeLink(match.url, 'list-row h-match-mini');
      row.title = opponents[0].name + ' vs ' + opponents[1].name;
      var status = make('span', 'h-mini-status' + (match.status === 'live' ? ' live' : ''));
      status.textContent = match.status === 'live' ? '直播' : text(match.time, 'TBD');

      var teams = make('span', 'h-mini-teams');
      opponents.forEach(function (opponent) {
        var label = setIgnoreI18n(make('b', '', opponent.short));
        label.setAttribute('data-match-side', opponent.side);
        teams.appendChild(label);
      });

      row.appendChild(status);
      row.appendChild(teams);
      row.appendChild(make('span', 'h-mini-bo', text(match.bo, 'BO1')));
      target.appendChild(row);
    });
  }

  function renderHomeActivity(target, threads) {
    target.replaceChildren();
    if (!threads || !threads.length) {
      var empty = makeLink('/forum', 'h-empty');
      empty.textContent = '暂无论坛动态';
      target.appendChild(empty);
      return;
    }
    threads.slice(0, 8).forEach(function (item) {
      var row = makeLink(item.url, 'list-row h-activity-row');
      row.appendChild(setIgnoreI18n(make('span', 'grow title', text(item.title, '未命名帖子'))));
      row.appendChild(make('small', 'h-activity-count', text(item.replies, '0')));
      target.appendChild(row);
    });
  }

  function resultTeam(opponent, other, right) {
    var scored = opponent.score != null && other.score != null;
    var state = scored && opponent.score > other.score ? ' win' : (scored && other.score > opponent.score ? ' lose' : '');
    var team = make('span', 'h-result-team' + (right ? ' right' : '') + state);
    var logoUrl = opponent.logo;
    var name = setIgnoreI18n(make('span', 'truncate', opponent.short));
    team.setAttribute('data-match-side', opponent.side);
    if (!right && logoUrl) team.appendChild(teamLogo(logoUrl));
    team.appendChild(name);
    if (right && logoUrl) team.appendChild(teamLogo(logoUrl));
    return team;
  }

  function renderHomeRecent(target, results) {
    target.replaceChildren();
    if (!results || !results.length) {
      target.appendChild(emptyNode('暂无赛果'));
      return;
    }
    results.forEach(function (match) {
      var opponents = matchOpponents(match), left = opponents[0], right = opponents[1];
      var row = makeLink(match.url, 'list-row h-result-mini');
      row.title = left.name + ' ' + text(left.score, '-') + ' : ' + text(right.score, '-') + ' ' + right.name;
      setIgnoreI18n(row);
      row.appendChild(resultTeam(left, right, false));
      row.appendChild(make('b', 'h-result-score', text(left.score, '-') + ' : ' + text(right.score, '-')));
      row.appendChild(resultTeam(right, left, true));
      target.appendChild(row);
    });
  }

  function hydrateHome() {
    var root = document.querySelector('[data-front-home]');
    if (!root) return;
    fetchJson('/api/front/home')
      .then(function (data) {
        if (!data || !data.ok) return;
        var matches = root.querySelector('[data-front-home-target="matches"]');
        var activity = root.querySelector('[data-front-home-target="activity"]');
        var recent = root.querySelector('[data-front-home-target="recent"]');
        if (matches) renderHomeMatches(matches, data.matches);
        if (activity) renderHomeActivity(activity, data.forum_activity);
        if (recent) renderHomeRecent(recent, data.recent_results);
        root.setAttribute('data-api-ready', '1');
      })
      .catch(function (err) {
        console.debug('front home api fallback:', err.message);
      });
  }

  function renderMatchList(root, target, matches) {
    var empty = root.querySelector('[data-front-empty]');
    target.replaceChildren();
    if (!matches || !matches.length) {
      if (empty) {
        empty.style.display = '';
      } else {
        target.appendChild(emptyNode('暂无比赛'));
      }
      return;
    }
    if (empty) empty.style.display = 'none';
    matches.forEach(function (match) {
      var row = makeLink(match.url, 'match-schedule-row');

      var time = make('div', 'match-schedule-time');
      if (match.status === 'live') {
        time.appendChild(make('span', 'match-live-label', '直播中'));
      } else {
        time.appendChild(make('span', 'match-time-text', text(match.time, 'TBD')));
      }
      time.appendChild(make('span', 'match-bo', text(match.bo, 'BO1')));

      var teams = make('div', 'match-schedule-teams');
      matchOpponents(match).forEach(function (opponent) {
        var team = make('div', 'match-schedule-team');
        team.setAttribute('data-match-side', opponent.side);
        appendMatchTeam(team, opponent.logo, opponent.short === 'TBD' ? '?' : opponent.short.slice(0, 3), opponent.name);
        teams.appendChild(team);
      });

      var meta = make('div', 'match-schedule-meta');
      var eventText = text(match.event, '未分组赛事');
      var eventNode = make('span', '', eventText);
      if (match.event) setIgnoreI18n(eventNode);
      meta.appendChild(eventNode);
      if (match.date) meta.appendChild(make('span', '', match.date));

      row.appendChild(time);
      row.appendChild(teams);
      row.appendChild(meta);
      target.appendChild(row);
    });
  }

  function appendMatchTeam(container, logoUrl, fallback, teamName) {
    if (logoUrl) {
      var logo = document.createElement('img');
      logo.className = 'match-team-logo';
      logo.src = logoUrl;
      logo.alt = '';
      logo.loading = 'lazy';
      container.appendChild(logo);
    } else {
      container.appendChild(setIgnoreI18n(make('span', 'match-team-mark', fallback)));
    }
    container.appendChild(setIgnoreI18n(make('span', 'team-name', text(teamName, 'TBD'))));
  }

  function hydrateMatches() {
    var root = document.querySelector('[data-front-matches]');
    if (!root) return;
    var target = root.querySelector('[data-front-matches-target]');
    if (!target) return;

    var params = new URLSearchParams(window.location.search);
    var date = params.get('date') || root.getAttribute('data-date-filter') || '';
    var event = params.get('event') || root.getAttribute('data-event-filter') || '';
    var apiParams = new URLSearchParams({ status: 'active' });
    if (date) apiParams.set('date', date);
    if (event) apiParams.set('event', event);

    fetchJson('/api/front/matches?' + apiParams.toString())
      .then(function (data) {
        if (!data || !data.ok) return;
        renderMatchList(root, target, data.matches);
        root.setAttribute('data-api-ready', '1');
      })
      .catch(function (err) {
        console.debug('front matches api fallback:', err.message);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      hydrateHome();
      hydrateMatches();
    });
  } else {
    hydrateHome();
    hydrateMatches();
  }
})();
