import { csrfToken } from '../../shared/site-http.mjs';

const config = JSON.parse(document.getElementById('bracketEditorData').textContent);

// ==================== 对阵图编辑器 ====================

// 赛制定义
var FORMATS = {
  '4de': {
    name: window.siteMessage('client.bracket_editor.4_team_double_elimination'),
    type: 'double_elim',
    total_teams: 4,
    sections: [
      { label: window.siteMessage('client.bracket_editor.upper_bracket'), rounds: [
        { name: window.siteMessage('client.bracket_editor.ub_round_1'), matches: [
          { id: 'UB_R1_M1', slots: 2 },
          { id: 'UB_R1_M2', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.ub_round_2'), matches: [
          { id: 'UB_R2_M1', slots: 2 }
        ]}
      ]},
      { label: window.siteMessage('client.bracket_editor.lower_bracket'), rounds: [
        { name: window.siteMessage('client.bracket_editor.lb_round_1'), matches: [
          { id: 'LB_R1_M1', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.lower_bracket_final'), matches: [
          { id: 'LB_R2_M1', slots: 2 }
        ]}
      ]},
      { label: window.siteMessage('client.bracket_editor.grand_final'), rounds: [
        { name: window.siteMessage('client.bracket_editor.grand_final'), matches: [
          { id: 'GF_R1_M1', slots: 2 }
        ]}
      ]}
    ]
  },
  '8de': {
    name: window.siteMessage('client.bracket_editor.8_team_double_elimination'),
    type: 'double_elim',
    total_teams: 8,
    sections: [
      { label: window.siteMessage('client.bracket_editor.upper_bracket'), rounds: [
        { name: window.siteMessage('client.bracket_editor.ub_round_1'), matches: [
          { id: 'UB_R1_M1', slots: 2 }, { id: 'UB_R1_M2', slots: 2 },
          { id: 'UB_R1_M3', slots: 2 }, { id: 'UB_R1_M4', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.ub_round_2'), matches: [
          { id: 'UB_R2_M1', slots: 2 }, { id: 'UB_R2_M2', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.ub_final'), matches: [
          { id: 'UB_F_M1', slots: 2 }
        ]}
      ]},
      { label: window.siteMessage('client.bracket_editor.lower_bracket'), rounds: [
        { name: window.siteMessage('client.bracket_editor.lb_round_1'), matches: [
          { id: 'LB_R1_M1', slots: 2 }, { id: 'LB_R1_M2', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.lb_round_2'), matches: [
          { id: 'LB_R2_M1', slots: 2 }, { id: 'LB_R2_M2', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.lb_round_3'), matches: [
          { id: 'LB_R3_M1', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.lb_final'), matches: [
          { id: 'LB_F_M1', slots: 2 }
        ]}
      ]},
      { label: window.siteMessage('client.bracket_editor.grand_final'), rounds: [
        { name: window.siteMessage('client.bracket_editor.grand_final'), matches: [
          { id: 'GF_R1_M1', slots: 2 }
        ]}
      ]}
    ]
  },
  '4se': {
    name: window.siteMessage('client.bracket_editor.4_team_single_elimination'),
    type: 'single_elim',
    total_teams: 4,
    sections: [
      { label: window.siteMessage('client.bracket_editor.playoffs'), rounds: [
        { name: window.siteMessage('client.bracket_editor.semifinal'), matches: [
          { id: 'SF_M1', slots: 2 }, { id: 'SF_M2', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.final'), matches: [
          { id: 'F_M1', slots: 2 }
        ]}
      ]}
    ]
  },
  '8se': {
    name: window.siteMessage('client.bracket_editor.8_team_single_elimination'),
    type: 'single_elim',
    total_teams: 8,
    sections: [
      { label: window.siteMessage('client.bracket_editor.playoffs'), rounds: [
        { name: window.siteMessage('client.bracket_editor.quarterfinal'), matches: [
          { id: 'QF_M1', slots: 2 }, { id: 'QF_M2', slots: 2 },
          { id: 'QF_M3', slots: 2 }, { id: 'QF_M4', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.semifinal'), matches: [
          { id: 'SF_M1', slots: 2 }, { id: 'SF_M2', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.final'), matches: [
          { id: 'F_M1', slots: 2 }
        ]}
      ]}
    ]
  },
  'swiss': {
    name: window.siteMessage('client.bracket_editor.swiss_system'),
    type: 'swiss',
    total_teams: 8,
    sections: [
      { label: window.siteMessage('client.bracket_editor.round_1_0_0_pool'), rounds: [
        { name: '0-0', matches: [
          { id: 'SW_R1_M1', slots: 2 }, { id: 'SW_R1_M2', slots: 2 },
          { id: 'SW_R1_M3', slots: 2 }, { id: 'SW_R1_M4', slots: 2 }
        ]}
      ]},
      { label: window.siteMessage('client.bracket_editor.round_2'), rounds: [
        { name: window.siteMessage('client.bracket_editor.1_0_pool'), matches: [
          { id: 'SW_R2_10_M1', slots: 2 }, { id: 'SW_R2_10_M2', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.0_1_pool'), matches: [
          { id: 'SW_R2_01_M1', slots: 2 }, { id: 'SW_R2_01_M2', slots: 2 }
        ]}
      ]},
      { label: window.siteMessage('client.bracket_editor.round_3'), rounds: [
        { name: window.siteMessage('client.bracket_editor.2_0_pool'), matches: [
          { id: 'SW_R3_20_M1', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.1_1_pool'), matches: [
          { id: 'SW_R3_11_M1', slots: 2 }, { id: 'SW_R3_11_M2', slots: 2 }
        ]},
        { name: window.siteMessage('client.bracket_editor.0_2_pool'), matches: [
          { id: 'SW_R3_02_M1', slots: 2 }
        ]}
      ]}
    ]
  }
};

// 内部状态
var _state = {
  format: '4de',
  tournamentName: '',
  // matchId -> { team1, team2, score1, score2, match_id, match_time, bo_format, maps }
  matches: {},
  // teamKey -> { key, db_id, name, short_name }
  teams: {},
  // 从 DB 获取的队伍列表
  dbTeams: [],
  eventTeams: []
};

// ==================== 初始化 ====================
function init() {
  loadTeams().then(function() {
    if (config.bracket) {
      loadBracketData(config.bracket);
    }
    applyFormat();
  });
}

function loadTeams() {
  return fetch('/admin/events/' + config.eventId + '/bracket/api/teams', {
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    _state.dbTeams = data.all_teams || [];
    _state.eventTeams = data.event_teams || [];
    renderTeamPool();
  })
  .catch(function(err) {
    console.error('Failed to load teams:', err);
  });
}

// 数据库里存的是 JSON 文本，模板原样传过来时是字符串，这里统一转成对象
function parseBracketData(data) {
  if (typeof data !== 'string') return data;
  try {
    return JSON.parse(data);
  } catch (err) {
    console.error(window.siteMessage('client.bracket_editor.could_not_read_bracket_data'), err);
    return null;
  }
}

function loadBracketData(data) {
  data = parseBracketData(data);
  if (!data || typeof data !== 'object') return;
  var tour = data.tournament || data;
  if (!tour) return;

  _state.tournamentName = tour.name || config.eventName || '';

  // 检测格式
  var tt = tour.total_teams || 8;
  if (tour.format_key && FORMATS[tour.format_key]) {
    _state.format = tour.format_key;
  } else if (tour.type && tour.type.indexOf('single') !== -1) {
    _state.format = tt <= 4 ? '4se' : '8se';
  } else if (tour.type && tour.type.indexOf('swiss') !== -1) {
    _state.format = 'swiss';
  } else {
    // double_elim / double_elimination / double
    _state.format = tt <= 4 ? '4de' : '8de';
  }
  document.getElementById('formatSelect').value = _state.format;
  var boSelect = document.getElementById('bracketBoFormat');
  if (boSelect && tour.bo_format) boSelect.value = tour.bo_format;

  // 加载队伍映射
  if (tour.teams) {
    tour.teams.forEach(function(t) {
      _state.teams[t.id] = {
        key: t.id,
        db_id: t.db_id || null,
        name: t.name,
        short_name: t.short_name || t.name
      };
    });
  }

  // 加载比赛数据（优先sections，兼容旧rounds格式）
  _state.matches = {};
  var allRounds = [];
  if (tour.sections && tour.sections.length > 0) {
    tour.sections.forEach(function(sec) {
      if (sec.rounds) sec.rounds.forEach(function(r) { allRounds.push(r); });
    });
  } else if (tour.rounds) {
    allRounds = tour.rounds;
  }

  // 旧轮次名 → 新格式 match ID 的映射前缀
  var roundToPrefix = {
    '胜者组第一轮': 'UB_R1_M',
    '胜者组第二轮': 'UB_R2_M',
    '胜者组决赛':   'UB_F_M',
    '败者组第一轮': 'LB_R1_M',
    '败者组第二轮': 'LB_R2_M',
    '败者组第三轮': 'LB_R3_M',
    '败者组决赛':   'LB_R2_M',  // 4de 用 LB_R2_M1；8de 用 LB_F_M1，但旧名『败者组决赛』在 4de 中即为 LB_R2
    '总决赛':       'GF_R1_M',
    '决赛':         'F_M',
    '四分之一决赛':  'QF_M',
    '半决赛':       'SF_M',
    'Upper Bracket R1': 'UB_R1_M',
    'Upper Bracket R2': 'UB_R2_M',
    'Upper Bracket Final': 'UB_F_M',
    'Lower Bracket R1': 'LB_R1_M',
    'Lower Bracket R2': 'LB_R2_M',
    'Lower Bracket R3': 'LB_R3_M',
    'Lower Bracket Final': 'LB_F_M',
    'Grand Final': 'GF_R1_M',
    'Quarter Final': 'QF_M',
    'Semi Final': 'SF_M',
    'Final': 'F_M'
  };

  allRounds.forEach(function(round) {
    if (round.matches) {
      var prefix = roundToPrefix[round.name] || null;
      round.matches.forEach(function(m, idx) {
        // 优先使用 m.id，其次 m.match_id，再尝试旧名映射，最后用回退 ID
        var id;
        if (m.id && m.id !== 'M1' && m.id !== 'M2' && m.id.indexOf('_') !== -1) {
          id = m.id;  // 已是新格式 ID (如 UB_R1_M1)
        } else if (prefix) {
          id = prefix + (idx + 1);  // 用旧轮次名映射 + 序号
        } else {
          id = m.id || m.match_id || (round.name + '_' + (m.team1 || '') + '_' + (m.team2 || ''));
        }
        var eventMatch = findEventMatch(m.match_id);
        var matchData = {
          team1: m.team1 || null,
          team2: m.team2 || null,
          score1: m.score1 != null ? m.score1 : '',
          score2: m.score2 != null ? m.score2 : '',
          match_id: m.match_id || '',
          match_time: m.match_time || (eventMatch ? eventMatch.match_time : '') || '',
          bo_format: m.bo_format || (eventMatch ? eventMatch.bo_format : '') || tour.bo_format || 'BO3',
          maps: m.maps || []
        };
        _state.matches[id] = matchData;
      });
    }
  });
}

function findEventMatch(matchId) {
  if (!matchId || !Array.isArray(config.eventMatches)) return null;
  for (var i = 0; i < config.eventMatches.length; i++) {
    if (String(config.eventMatches[i].id) === String(matchId)) return config.eventMatches[i];
  }
  return null;
}

// ==================== 队伍池渲染 ====================
function renderTeamPool() {
  var pool = document.getElementById('teamPool');
  var searchTerm = (document.getElementById('teamSearch').value || '').toLowerCase();

  // 收集实际分配到槽位的队伍 key
  var usedTeamKeys = {};
  Object.keys(_state.matches).forEach(function(mid) {
    var m = _state.matches[mid];
    if (m.team1) usedTeamKeys[m.team1] = true;
    if (m.team2) usedTeamKeys[m.team2] = true;
  });

  var html = '';

  // 自定义队伍添加
  html += '<div class="custom-team-row">';
  html += ("<input type=\"text\" id=\"customTeamInput\" class=\"custom-team-input\" placeholder=\"" + window.siteMessage('client.bracket_editor.enter_a_temporary_team_name') + "\" onkeydown=\"if(event.key==='Enter')addCustomTeam()\">");
  html += '<button type="button" class="btn btn-xs btn-primary" data-add-custom-team style="flex-shrink:0">+</button>';
  html += '</div>';

  var teamsToShow = _state.eventTeams.length > 0 ? _state.eventTeams : _state.dbTeams;

  teamsToShow.forEach(function(t) {
    if (searchTerm && t.name.toLowerCase().indexOf(searchTerm) === -1) return;
    var teamKey = findTeamKeyByDbId(t.id);
    var inUse = teamKey && usedTeamKeys[teamKey];
    html += '<div class="team-chip' + (inUse ? ' in-use' : '') + '" draggable="true" data-team-id="' + t.id + '" data-team-name="' + escAttr(t.name) + '" data-team-short="' + escAttr(t.short_name || t.name) + '">';
    html += '<span class="chip-avatar">' + (t.short_name || t.name)[0] + '</span>';
    html += '<span class="chip-name">' + escHtml(t.name) + '</span>';
    if (inUse) {
      html += '<button type="button" class="chip-remove" data-remove-bracket-team="' + escAttr(teamKey) + '" title="' + escAttr(window.siteMessage('client.bracket_editor.remove_from_bracket')) + '">&times;</button>';
    }
    html += '</div>';
  });

  // 也显示自定义队伍（不在 DB 中，但在对阵图中）
  Object.keys(_state.teams).forEach(function(k) {
    var tm = _state.teams[k];
    if (!tm.db_id) {
      var inUse = usedTeamKeys[k];
      html += '<div class="team-chip' + (inUse ? ' in-use' : '') + '" draggable="true" data-team-id="" data-team-name="' + escAttr(tm.name) + '" data-team-short="' + escAttr(tm.short_name || tm.name) + '" data-team-key="' + escAttr(k) + '">';
      html += '<span class="chip-avatar">' + (tm.name || '?')[0] + '</span>';
      html += '<span class="chip-name">' + escHtml(tm.name) + (window.siteMessage('client.bracket_editor.custom') + "</span>");
      if (inUse) {
        html += '<button type="button" class="chip-remove" data-remove-bracket-team="' + escAttr(k) + '">&times;</button>';
      }
      html += '</div>';
    }
  });

  if (!html) {
    html = ("<div style=\"color:#aaa;font-size:12px;text-align:center;padding:20px\">" + window.siteMessage('client.bracket_editor.no_teams') + "</div>");
  }

  pool.innerHTML = html;
}

function addCustomTeam() {
  var input = document.getElementById('customTeamInput');
  var name = (input ? input.value : '').trim();
  if (!name) return;
  var key = 'custom_' + Date.now();
  _state.teams[key] = { key: key, db_id: null, name: name, short_name: name };
  if (input) input.value = '';
  renderAll();
}

function findTeamKeyByDbId(dbId) {
  for (var k in _state.teams) {
    if (_state.teams[k].db_id == dbId) return k;
  }
  return null;
}

function filterTeams() {
  renderTeamPool();
}

// ==================== 拖拽 ====================
// 团队池中的拖拽启动
function onTeamDragStart(e) {
  var chip = e.target.closest('.team-chip');
  if (!chip) {
    e.preventDefault();
    return;
  }
  // 点到了移除按钮则不触发拖拽
  if (e.target.closest('.chip-remove')) {
    e.preventDefault();
    return;
  }
  chip.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', JSON.stringify({
    db_id: chip.dataset.teamId,
    name: chip.dataset.teamName,
    short_name: chip.dataset.teamShort,
    team_key: chip.dataset.teamKey || ''
  }));
}

function onTeamDragEnd(e) {
  var chip = e.target.closest('.team-chip');
  if (chip) chip.classList.remove('dragging');
}

// 事件委托：在 bracketEditor 容器上统一处理拖放
var _bracketDragDelegateSetup = false;
function setupDragDelegate() {
  if (_bracketDragDelegateSetup) return;
  _bracketDragDelegateSetup = true;
  var editor = document.getElementById('bracketEditor');
  if (!editor) return;

  editor.addEventListener('dragover', function(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    // 清除之前的视觉反馈
    var prevHighlights = editor.querySelectorAll('.drag-over,.drop-target');
    for (var i = 0; i < prevHighlights.length; i++) {
      prevHighlights[i].classList.remove('drag-over', 'drop-target');
    }

    // 优先高亮 slot-team，其次 bracket-slot
    var slotTeam = e.target.closest('.slot-team');
    if (slotTeam && isInitialMatch(slotTeam.dataset.matchId)) {
      slotTeam.classList.add('drop-target');
    } else {
      var bracketSlot = e.target.closest('.bracket-slot');
      if (bracketSlot && isInitialMatch(bracketSlot.dataset.matchId)) bracketSlot.classList.add('drag-over');
    }
  });

  editor.addEventListener('drop', function(e) {
    e.preventDefault();

    // 清除所有视觉反馈
    var highlights = editor.querySelectorAll('.drag-over,.drop-target');
    for (var i = 0; i < highlights.length; i++) {
      highlights[i].classList.remove('drag-over', 'drop-target');
    }

    var rawData = e.dataTransfer.getData('text/plain');
    if (!rawData) return;
    var teamData;
    try { teamData = JSON.parse(rawData); } catch(err) { return; }

    // 优先处理 slot-team 上的投放
    var slotTeam = e.target.closest('.slot-team');
    if (slotTeam && isInitialMatch(slotTeam.dataset.matchId)) {
      assignTeamToSlot(slotTeam.dataset.matchId, parseInt(slotTeam.dataset.slotIndex), teamData);
      return;
    }

    // 回退到 bracket-slot
    var bracketSlot = e.target.closest('.bracket-slot');
    if (bracketSlot) {
      var matchId = bracketSlot.dataset.matchId;
      if (!isInitialMatch(matchId)) return;
      var m = _state.matches[matchId] || { team1: null, team2: null };
      var idx = m.team1 ? (m.team2 ? 0 : 1) : 0;
      assignTeamToSlot(matchId, idx, teamData);
    }
  });

  // 拖离编辑器时清除视觉反馈
  editor.addEventListener('dragleave', function(e) {
    if (!editor.contains(e.relatedTarget)) {
      var highlights = editor.querySelectorAll('.drag-over,.drop-target');
      for (var i = 0; i < highlights.length; i++) {
        highlights[i].classList.remove('drag-over', 'drop-target');
      }
    }
  });
}

function assignTeamToSlot(matchId, slotIndex, teamData) {
  if (!isInitialMatch(matchId)) return;
  if (!_state.matches[matchId]) {
    _state.matches[matchId] = { team1: null, team2: null, score1: '', score2: '', match_id: '', match_time: '', bo_format: '', maps: [] };
  }
  var match = _state.matches[matchId];

  // 分配 team key：优先使用拖拽数据中的 team_key，其次按 db_id 匹配
  var teamKey;
  if (teamData.team_key && _state.teams[teamData.team_key]) {
    teamKey = teamData.team_key;
  } else {
    var existingKeys = [];
    Object.keys(_state.teams).forEach(function(k) {
      if (teamData.db_id && _state.teams[k].db_id == teamData.db_id) existingKeys.push(k);
    });
    if (existingKeys.length > 0) {
      teamKey = existingKeys[0];
    } else {
      teamKey = 't' + (Object.keys(_state.teams).length + 1);
    }
  }

  var newField = slotIndex === 0 ? 'team1' : 'team2';
  var oppositeField = slotIndex === 0 ? 'team2' : 'team1';

  // 检查这个 team 是否已经在这个 match 的另一个位置
  if (match[oppositeField] === teamKey) {
    match[oppositeField] = match[newField];
  }

  match[newField] = teamKey;

  // 保存到 teams 映射
  if (!_state.teams[teamKey]) {
    _state.teams[teamKey] = {
      key: teamKey,
      db_id: parseInt(teamData.db_id) || null,
      name: teamData.name,
      short_name: teamData.short_name || teamData.name
    };
  } else {
    _state.teams[teamKey].db_id = parseInt(teamData.db_id) || _state.teams[teamKey].db_id;
    _state.teams[teamKey].name = teamData.name;
    _state.teams[teamKey].short_name = teamData.short_name || teamData.name;
  }

  setTimeout(renderAll, 10);
}

function removeTeamFromSlot(matchId, slotIndex) {
  var field = slotIndex === 0 ? 'team1' : 'team2';
  if (_state.matches[matchId]) {
    _state.matches[matchId][field] = null;
  }
  setTimeout(renderAll, 10);
}

function removeTeamFromBracket(teamKey) {
  Object.keys(_state.matches).forEach(function(mid) {
    var m = _state.matches[mid];
    if (m.team1 === teamKey) m.team1 = null;
    if (m.team2 === teamKey) m.team2 = null;
  });
  delete _state.teams[teamKey];
  setTimeout(renderAll, 10);
}

// ==================== 对阵图渲染 ====================
function applyFormat() {
  _state.format = document.getElementById('formatSelect').value;
  renderAll();
}

function isInitialMatch(matchId) {
  if (_state.format === '4se') return matchId.indexOf('SF_') === 0;
  if (_state.format === '8se') return matchId.indexOf('QF_') === 0;
  if (_state.format === '4de' || _state.format === '8de') return matchId.indexOf('UB_R1_') === 0;
  return matchId.indexOf('SW_R1_') === 0;
}

function renderAll() {
  renderTeamPool();
  renderBracket();
}

function renderBracket() {
  var container = document.getElementById('bracketEditor');
  var fmt = FORMATS[_state.format];
  if (!fmt) { container.innerHTML = ("<div class=\"empty-bracket-hint\">" + window.siteMessage('client.bracket_editor.unknown_format') + "</div>"); return; }

  var isSwiss = _state.format === 'swiss';
  var html = '';

  fmt.sections.forEach(function(section) {
    // 瑞士制 section 用特殊样式
    if (isSwiss) {
      html += '<div class="bracket-section-label swiss-section-label">' + escHtml(section.label) + '</div>';
    } else {
      html += '<div class="bracket-section-label">' + escHtml(section.label) + '</div>';
    }

    // 瑞士制：每个 record-group 内横排
    if (isSwiss) {
      section.rounds.forEach(function(round) {
        html += '<div class="swiss-record-group">';
        html += '<div class="swiss-record-title">' + escHtml(round.name) + '</div>';
        html += '<div class="swiss-record-matches">';
        round.matches.forEach(function(matchDef) {
          html += renderBracketSlot(matchDef);
        });
        html += '</div></div>';
      });
    } else {
      // 淘汰赛：每个 round 一列
      html += '<div class="section-rounds-row">';
      section.rounds.forEach(function(round) {
        html += '<div class="round-col">';
        html += '<div class="round-title">' + escHtml(round.name) + '</div>';
        round.matches.forEach(function(matchDef) {
          html += renderBracketSlot(matchDef);
        });
        html += '</div>';
      });
      html += '</div>'; // .section-rounds-row
    }
  });

  container.innerHTML = html || ("<div class=\"empty-bracket-hint\">" + window.siteMessage('client.bracket_editor.select_a_format_to_show_the') + "</div>");
  setupDragDelegate();
}

// 一个对阵卡片：标题行（编号 + 操作）、双方队伍、比赛设置，三块上下排列
function renderBracketSlot(matchDef) {
  var m = _state.matches[matchDef.id] || { team1: null, team2: null, score1: '', score2: '', match_id: '', match_time: '', bo_format: '', maps: [] };
  var filled = (m.team1 || m.team2);
  var html = '<div class="bracket-slot' + (filled ? ' filled' : '') + '" data-match-id="' + matchDef.id + '">';
  html += '<div class="slot-header"><span class="slot-label">' + escHtml(matchDef.id) + '</span>';
  html += '<div class="slot-actions">' + renderMatchAction(m) + '</div>';
  html += '</div>';
  html += '<div class="slot-teams">';
  html += renderTeamSlot(matchDef.id, 0, m.team1, m.score1, m.team2, m.score2);
  html += '<div class="slot-vs">VS</div>';
  html += renderTeamSlot(matchDef.id, 1, m.team2, m.score2, m.team1, m.score1);
  html += '</div>';
  html += renderMatchSettings(matchDef.id, m.match_time, m.bo_format, m.match_id);
  html += '</div>';
  return html;
}

function renderMatchAction(match) {
  if (match && match.match_id) {
    return '<a class="btn btn-xs btn-primary" href="/admin/matches/edit/' + encodeURIComponent(match.match_id) + ("\">" + window.siteMessage('client.bracket_editor.match_settings') + "</a>");
  }
  return ("<span class=\"slot-auto-label\">" + window.siteMessage('client.bracket_editor.created_on_save') + "</span>");
}

function renderMatchSettings(matchId, value, boFormat, currentMatchId) {
  var selectedBo = boFormat || ((document.getElementById('bracketBoFormat') || {}).value) || 'BO3';
  var boOptions = ['BO1', 'BO3', 'BO5'].map(function(bo) {
    return '<option value="' + bo + '"' + (bo === selectedBo ? ' selected' : '') + '>' + bo + '</option>';
  }).join('');
  var matchOptions = ("<option value=\"\">" + window.siteMessage('client.bracket_editor.auto_match_or_create_on_save') + "</option>");
  (config.eventMatches || []).forEach(function(eventMatch) {
    var selected = String(eventMatch.id) === String(currentMatchId || '');
    var usedElsewhere = false;
    Object.keys(_state.matches).forEach(function(otherId) {
      if (otherId !== matchId && String(_state.matches[otherId].match_id || '') === String(eventMatch.id)) {
        usedElsewhere = true;
      }
    });
    if (usedElsewhere && !selected) return;
    var team1 = eventMatch.t1_name || eventMatch.team1_name || 'TBD';
    var team2 = eventMatch.t2_name || eventMatch.team2_name || 'TBD';
    var stage = eventMatch.stage ? ' · ' + eventMatch.stage : '';
    matchOptions += '<option value="' + escAttr(eventMatch.id) + '"' + (selected ? ' selected' : '') + '>' +
      escHtml('#' + eventMatch.id + ' ' + team1 + ' vs ' + team2 + stage) + '</option>';
  });
  return '<div class="slot-match-settings">' +
    '<label class="slot-binding-row"><span>' + window.siteMessage('client.bracket_editor.linked_match') + '</span><select data-bind-match="' + escAttr(matchId) + '">' +
    matchOptions + '</select></label>' +
    ("<label class=\"slot-time-row\"><span>" + window.siteMessage('client.bracket_editor.match_time') + "</span>") +
    '<input type="datetime-local" value="' + escAttr(value || '') + '" ' +
    'data-slot-time="' + escAttr(matchId) + '"></label>' +
    '<label class="slot-bo-row"><span>' + window.siteMessage('client.bracket_editor.format') + '</span><select data-slot-format="' + escAttr(matchId) + '">' +
    boOptions + '</select></label></div>';
}

function ensureBracketTeam(dbId, name, shortName) {
  if (!dbId) return null;
  var existing = findTeamKeyByDbId(dbId);
  if (existing) return existing;
  var key = 'db_' + dbId;
  _state.teams[key] = {
    key: key,
    db_id: parseInt(dbId),
    name: name || shortName || 'TBD',
    short_name: shortName || name || 'TBD'
  };
  return key;
}

function setMatchBinding(matchId, value) {
  if (!_state.matches[matchId]) {
    _state.matches[matchId] = { team1: null, team2: null, score1: '', score2: '', match_id: '', match_time: '', bo_format: '', maps: [] };
  }
  var selectedId = value ? parseInt(value, 10) : null;
  if (selectedId) {
    for (var otherId in _state.matches) {
      if (otherId !== matchId && parseInt(_state.matches[otherId].match_id, 10) === selectedId) {
        showToast(window.siteMessage('client.bracket_editor.this_match_is_already_linked_to'), 'error');
        renderAll();
        return;
      }
    }
  }
  var match = _state.matches[matchId];
  match.match_id = selectedId || '';
  var eventMatch = selectedId ? findEventMatch(selectedId) : null;
  if (eventMatch) {
    match.match_time = eventMatch.match_time || match.match_time || '';
    match.bo_format = eventMatch.bo_format || match.bo_format || 'BO3';
    if (eventMatch.team1_id) {
      match.team1 = ensureBracketTeam(
        eventMatch.team1_id,
        eventMatch.t1_name || eventMatch.team1_name,
        eventMatch.t1_short_name
      );
    }
    if (eventMatch.team2_id) {
      match.team2 = ensureBracketTeam(
        eventMatch.team2_id,
        eventMatch.t2_name || eventMatch.team2_name,
        eventMatch.t2_short_name
      );
    }
  }
  renderAll();
}

function setMatchTime(matchId, value) {
  if (!_state.matches[matchId]) {
    _state.matches[matchId] = { team1: null, team2: null, score1: '', score2: '', match_id: '', match_time: '', bo_format: '', maps: [] };
  }
  _state.matches[matchId].match_time = value || '';
}

function setMatchBo(matchId, value) {
  if (!_state.matches[matchId]) {
    _state.matches[matchId] = { team1: null, team2: null, score1: '', score2: '', match_id: '', match_time: '', bo_format: '', maps: [] };
  }
  _state.matches[matchId].bo_format = ['BO1', 'BO3', 'BO5'].indexOf(value) !== -1 ? value : 'BO3';
}

function renderTeamSlot(matchId, slotIndex, teamKey, score, oppositeKey, oppositeScore) {
  var tm = teamKey ? _state.teams[teamKey] : null;
  var initial = isInitialMatch(matchId);
  var nameHtml = tm ? escHtml(tm.short_name || tm.name) : '<span class="team-name-text placeholder">' + (initial ? window.siteMessage('client.bracket_editor.drag_team_here') : window.siteMessage('client.bracket_editor.tbd_decided_by_results')) + '</span>';
  var nameClass = tm ? 'team-name-text' : 'team-name-text placeholder';
  var scoreVal = (score !== '' && score != null) ? score : '';

  var html = '<div class="slot-team' + (initial ? ' drop-target' : ' auto-slot') + '" data-match-id="' + matchId + '" data-slot-index="' + slotIndex + '">';
  html += '<span class="seed-badge">' + (slotIndex + 1) + '</span>';
  html += '<span class="' + nameClass + '">' + nameHtml + '</span>';
  if (tm && initial) {
    html += '<button type="button" class="remove-team-btn" data-remove-slot-team title="' + escAttr(window.siteMessage('client.bracket_editor.remove_team')) + '">&times;</button>';
  }
  html += ("<span class=\"team-score readonly-score\" title=\"" + window.siteMessage('client.bracket_editor.the_score_is_updated_by_live') + "\">") + (scoreVal === '' ? '-' : scoreVal) + '</span>';
  html += '</div>';
  return html;
}

// ==================== 保存 ====================
function saveBracket() {
  var fmt = FORMATS[_state.format];
  if (!fmt) { showToast(window.siteMessage('client.bracket_editor.please_select_a_format'), 'error'); return; }

  var teamsList = [];
  Object.keys(_state.teams).forEach(function(k) {
    var t = _state.teams[k];
    teamsList.push({ id: k, db_id: t.db_id, name: t.name, short_name: t.short_name });
  });

  // 构建 sections（新格式，前端渲染用）
  var sections = [];
  // 构建 rounds（旧格式，向后兼容）
  var rounds = [];

  fmt.sections.forEach(function(section) {
    var secData = { label: section.label, rounds: [] };
    section.rounds.forEach(function(round) {
      var roundData = { name: round.name, matches: [] };
      var compatRoundData = { name: round.name, matches: [] };
      round.matches.forEach(function(matchDef) {
        var m = _state.matches[matchDef.id] || { team1: null, team2: null, score1: '', score2: '', match_id: '', match_time: '', bo_format: '', maps: [] };
        var matchObj = {
          id: matchDef.id,
          team1: m.team1 || null,
          team2: m.team2 || null,
          score1: m.score1 !== '' ? parseInt(m.score1) : null,
          score2: m.score2 !== '' ? parseInt(m.score2) : null,
          match_id: m.match_id || null,
          match_time: m.match_time || null,
          bo_format: m.bo_format || (document.getElementById('bracketBoFormat') || {}).value || 'BO3',
          maps: m.maps || []
        };
        roundData.matches.push(matchObj);
        compatRoundData.matches.push(matchObj);
      });
      secData.rounds.push(roundData);
      rounds.push(compatRoundData);
    });
    sections.push(secData);
  });

  var data = {
    tournament: {
      name: config.eventName || fmt.name,
      format_key: _state.format,
      type: fmt.type,
      total_teams: fmt.total_teams,
      bo_format: (document.getElementById('bracketBoFormat') || {}).value || 'BO3',
      teams: teamsList,
      sections: sections,
      rounds: rounds
    }
  };

  var btn = document.getElementById('saveBracketBtn');
  // 只换按钮里的文字（.btn-label），图标保留
  var label = btn.querySelector('.btn-label') || btn;
  var origText = label.textContent;
  btn.disabled = true;
  label.textContent = window.siteMessage('client.bracket_editor.saving');

  fetch('/admin/events/' + config.eventId + '/bracket/api/save', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      'X-CSRF-Token': csrfToken()
    },
    body: JSON.stringify(data)
  })
  .then(readSaveResponse)
  .then(function(result) {
    btn.disabled = false;
    label.textContent = origText;
    handleSaveResult(result);
  }, function(err) {
    // 只有请求根本没发出去或没收到回复才算网络错误
    btn.disabled = false;
    label.textContent = origText;
    showToast(window.siteMessage('client.bracket_editor.network_error_no_reply_from_the'), 'error');
    console.error(err);
  });
}

// 把服务器回复读成 { status, body }；回复不是 JSON（例如登录过期跳到登录页）时 body 为 null
function readSaveResponse(response) {
  return response.text().then(function(text) {
    var body = null;
    try { body = JSON.parse(text); } catch (err) { body = null; }
    return { status: response.status, body: body };
  });
}

function handleSaveResult(result) {
  var res = result.body;
  if (!res) {
    console.warn(window.siteMessage('client.bracket_editor.bracket_save_returned_a_non_json'), result.status);
    showToast(window.siteMessage('client.bracket_editor.save_failed_unrecognized_server_reply_your'), 'error');
    return;
  }
  if (!res.success) {
    showToast(window.siteMessage('client.bracket_editor.save_failed_value1', {value1: (res.error || window.siteMessage('client.bracket_editor.unknown_error'))}), 'error');
    return;
  }
  if (res.bracket) {
    loadBracketData(res.bracket);
    renderAll();
  }
  showToast(res.message || window.siteMessage('client.bracket_editor.bracket_and_all_matches_created'), 'success');
}

function resetBracket() {
  showConfirm(window.siteMessage('client.bracket_editor.reset_the_bracket_unsaved_changes_will'), window.siteMessage('client.bracket_editor.reset_confirmation')).then(function(yes) {
    if (!yes) return;
    _state.matches = {};
    _state.teams = {};
    renderAll();
  });
}

// ==================== 工具函数 ====================
function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escAttr(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ==================== 启动 ====================
document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('formatSelect').addEventListener('change', applyFormat);
  document.getElementById('saveBracketBtn').addEventListener('click', saveBracket);
  document.getElementById('teamSearch').addEventListener('input', filterTeams);
  const root = document.getElementById('adminMain');
  root.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.hasAttribute('data-reset-bracket')) resetBracket();
    if (button.hasAttribute('data-add-custom-team')) addCustomTeam();
    if (button.hasAttribute('data-remove-bracket-team')) {
      event.stopPropagation();
      removeTeamFromBracket(button.dataset.removeBracketTeam);
    }
    if (button.hasAttribute('data-remove-slot-team')) {
      event.stopPropagation();
      const slot = button.closest('.slot-team');
      removeTeamFromSlot(slot.dataset.matchId, Number(slot.dataset.slotIndex));
    }
  });
  root.addEventListener('input', (event) => {
    if (event.target.hasAttribute('data-slot-time')) setMatchTime(event.target.dataset.slotTime, event.target.value);
  });
  root.addEventListener('change', (event) => {
    const input = event.target;
    if (input.hasAttribute('data-bind-match')) setMatchBinding(input.dataset.bindMatch, input.value);
    if (input.hasAttribute('data-slot-format')) setMatchBo(input.dataset.slotFormat, input.value);
  });
  root.addEventListener('dragstart', (event) => {
    if (event.target.closest('.team-chip')) onTeamDragStart(event);
  });
  root.addEventListener('dragend', onTeamDragEnd);
  init();
});
