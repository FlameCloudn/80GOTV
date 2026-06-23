// ==================== 对阵图编辑器 ====================

// 赛制定义
var FORMATS = {
  '4de': {
    name: '4 队双败淘汰',
    type: 'double_elim',
    total_teams: 4,
    sections: [
      { label: '胜者组', rounds: [
        { name: 'UB 第一轮', matches: [
          { id: 'UB_R1_M1', slots: 2 },
          { id: 'UB_R1_M2', slots: 2 }
        ]},
        { name: 'UB 第二轮', matches: [
          { id: 'UB_R2_M1', slots: 2 }
        ]}
      ]},
      { label: '败者组', rounds: [
        { name: '败者组决赛', matches: [
          { id: 'LB_R2_M1', slots: 2 }
        ]}
      ]},
      { label: '总决赛', rounds: [
        { name: 'Grand Final', matches: [
          { id: 'GF_R1_M1', slots: 2 }
        ]}
      ]}
    ]
  },
  '8de': {
    name: '8 队双败淘汰',
    type: 'double_elim',
    total_teams: 8,
    sections: [
      { label: '胜者组', rounds: [
        { name: 'UB 第一轮', matches: [
          { id: 'UB_R1_M1', slots: 2 }, { id: 'UB_R1_M2', slots: 2 },
          { id: 'UB_R1_M3', slots: 2 }, { id: 'UB_R1_M4', slots: 2 }
        ]},
        { name: 'UB 第二轮', matches: [
          { id: 'UB_R2_M1', slots: 2 }, { id: 'UB_R2_M2', slots: 2 }
        ]},
        { name: 'UB 决赛', matches: [
          { id: 'UB_F_M1', slots: 2 }
        ]}
      ]},
      { label: '败者组', rounds: [
        { name: 'LB 第一轮', matches: [
          { id: 'LB_R1_M1', slots: 2 }, { id: 'LB_R1_M2', slots: 2 }
        ]},
        { name: 'LB 第二轮', matches: [
          { id: 'LB_R2_M1', slots: 2 }, { id: 'LB_R2_M2', slots: 2 }
        ]},
        { name: 'LB 第三轮', matches: [
          { id: 'LB_R3_M1', slots: 2 }
        ]},
        { name: 'LB 决赛', matches: [
          { id: 'LB_F_M1', slots: 2 }
        ]}
      ]},
      { label: '总决赛', rounds: [
        { name: 'Grand Final', matches: [
          { id: 'GF_R1_M1', slots: 2 }
        ]}
      ]}
    ]
  },
  '4se': {
    name: '4 队单败淘汰',
    type: 'single_elim',
    total_teams: 4,
    sections: [
      { label: '淘汰赛', rounds: [
        { name: '半决赛', matches: [
          { id: 'SF_M1', slots: 2 }, { id: 'SF_M2', slots: 2 }
        ]},
        { name: '决赛', matches: [
          { id: 'F_M1', slots: 2 }
        ]}
      ]}
    ]
  },
  '8se': {
    name: '8 队单败淘汰',
    type: 'single_elim',
    total_teams: 8,
    sections: [
      { label: '淘汰赛', rounds: [
        { name: '四分之一决赛', matches: [
          { id: 'QF_M1', slots: 2 }, { id: 'QF_M2', slots: 2 },
          { id: 'QF_M3', slots: 2 }, { id: 'QF_M4', slots: 2 }
        ]},
        { name: '半决赛', matches: [
          { id: 'SF_M1', slots: 2 }, { id: 'SF_M2', slots: 2 }
        ]},
        { name: '决赛', matches: [
          { id: 'F_M1', slots: 2 }
        ]}
      ]}
    ]
  },
  'swiss': {
    name: '瑞士制',
    type: 'swiss',
    total_teams: 8,
    sections: [
      { label: '第 1 轮 — 0-0 组', rounds: [
        { name: '0-0', matches: [
          { id: 'SW_R1_M1', slots: 2 }, { id: 'SW_R1_M2', slots: 2 },
          { id: 'SW_R1_M3', slots: 2 }, { id: 'SW_R1_M4', slots: 2 }
        ]}
      ]},
      { label: '第 2 轮', rounds: [
        { name: '1-0 组', matches: [
          { id: 'SW_R2_10_M1', slots: 2 }, { id: 'SW_R2_10_M2', slots: 2 }
        ]},
        { name: '0-1 组', matches: [
          { id: 'SW_R2_01_M1', slots: 2 }, { id: 'SW_R2_01_M2', slots: 2 }
        ]}
      ]},
      { label: '第 3 轮', rounds: [
        { name: '2-0 组', matches: [
          { id: 'SW_R3_20_M1', slots: 2 }
        ]},
        { name: '1-1 组', matches: [
          { id: 'SW_R3_11_M1', slots: 2 }, { id: 'SW_R3_11_M2', slots: 2 }
        ]},
        { name: '0-2 组', matches: [
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
  // matchId -> { team1: teamKey|null, team2: teamKey|null, score1: '', score2: '', match_id: '', maps: [] }
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
    if (window._bracketData) {
      loadBracketData(window._bracketData);
    }
    applyFormat();
  });
}

function loadTeams() {
  return fetch('/admin/events/' + window._eventId + '/bracket/api/teams', {
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    _state.dbTeams = data.all_teams || [];
    _state.eventTeams = data.event_teams || [];
    renderTeamPool();
    populateMatchSelect();
  })
  .catch(function(err) {
    console.error('Failed to load teams:', err);
  });
}

function loadBracketData(data) {
  var tour = data.tournament || data;
  if (!tour) return;

  _state.tournamentName = tour.name || '';

  // 检测格式
  var tt = tour.total_teams || 8;
  if (tour.type && tour.type.indexOf('single') !== -1) {
    _state.format = tt <= 4 ? '4se' : '8se';
  } else if (tour.type && tour.type.indexOf('swiss') !== -1) {
    _state.format = 'swiss';
  } else {
    // double_elim / double_elimination / double
    _state.format = tt <= 4 ? '4de' : '8de';
  }
  document.getElementById('formatSelect').value = _state.format;
  document.getElementById('tournamentName').value = _state.tournamentName;

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
        var matchData = {
          team1: m.team1 || null,
          team2: m.team2 || null,
          score1: m.score1 != null ? m.score1 : '',
          score2: m.score2 != null ? m.score2 : '',
          match_id: m.match_id || '',
          maps: m.maps || []
        };
        _state.matches[id] = matchData;
      });
    }
  });
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
  html += '<input type="text" id="customTeamInput" class="custom-team-input" placeholder="输入临时队伍名..." onkeydown="if(event.key===\'Enter\')addCustomTeam()">';
  html += '<button class="btn btn-xs btn-primary" onclick="addCustomTeam()" style="flex-shrink:0">+</button>';
  html += '</div>';

  var teamsToShow = _state.eventTeams.length > 0 ? _state.eventTeams : _state.dbTeams;

  teamsToShow.forEach(function(t) {
    if (searchTerm && t.name.toLowerCase().indexOf(searchTerm) === -1) return;
    var teamKey = findTeamKeyByDbId(t.id);
    var inUse = teamKey && usedTeamKeys[teamKey];
    html += '<div class="team-chip' + (inUse ? ' in-use' : '') + '" draggable="true" data-team-id="' + t.id + '" data-team-name="' + escAttr(t.name) + '" data-team-short="' + escAttr(t.short_name || t.name) + '" ondragstart="onTeamDragStart(event)" ondragend="onTeamDragEnd(event)">';
    html += '<span class="chip-avatar">' + (t.short_name || t.name)[0] + '</span>';
    html += '<span class="chip-name">' + escHtml(t.name) + '</span>';
    if (inUse) {
      html += '<button class="chip-remove" onclick="event.stopPropagation();removeTeamFromBracket(\'' + teamKey + '\')" title="从对阵图中移除">&times;</button>';
    }
    html += '</div>';
  });

  // 也显示自定义队伍（不在 DB 中，但在对阵图中）
  Object.keys(_state.teams).forEach(function(k) {
    var tm = _state.teams[k];
    if (!tm.db_id) {
      var inUse = usedTeamKeys[k];
      html += '<div class="team-chip' + (inUse ? ' in-use' : '') + '" draggable="true" data-team-id="" data-team-name="' + escAttr(tm.name) + '" data-team-short="' + escAttr(tm.short_name || tm.name) + '" data-team-key="' + k + '" ondragstart="onTeamDragStart(event)" ondragend="onTeamDragEnd(event)">';
      html += '<span class="chip-avatar">' + (tm.name || '?')[0] + '</span>';
      html += '<span class="chip-name">' + escHtml(tm.name) + ' (自定义)</span>';
      if (inUse) {
        html += '<button class="chip-remove" onclick="event.stopPropagation();removeTeamFromBracket(\'' + k + '\')">&times;</button>';
      }
      html += '</div>';
    }
  });

  if (!html) {
    html = '<div style="color:#aaa;font-size:12px;text-align:center;padding:20px">暂无队伍</div>';
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
    if (slotTeam) {
      slotTeam.classList.add('drop-target');
    } else {
      var bracketSlot = e.target.closest('.bracket-slot');
      if (bracketSlot) bracketSlot.classList.add('drag-over');
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
    if (slotTeam) {
      assignTeamToSlot(slotTeam.dataset.matchId, parseInt(slotTeam.dataset.slotIndex), teamData);
      return;
    }

    // 回退到 bracket-slot
    var bracketSlot = e.target.closest('.bracket-slot');
    if (bracketSlot) {
      var matchId = bracketSlot.dataset.matchId;
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
  if (!_state.matches[matchId]) {
    _state.matches[matchId] = { team1: null, team2: null, score1: '', score2: '', match_id: '', maps: [] };
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

function renderAll() {
  renderTeamPool();
  renderBracket();
  populateMatchSelect();
}

function renderBracket() {
  var container = document.getElementById('bracketEditor');
  var fmt = FORMATS[_state.format];
  if (!fmt) { container.innerHTML = '<div class="empty-bracket-hint">未知赛制</div>'; return; }

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
          var m = _state.matches[matchDef.id] || { team1: null, team2: null, score1: '', score2: '', match_id: '', maps: [] };
          var filled = (m.team1 || m.team2);
          html += '<div class="bracket-slot' + (filled ? ' filled' : '') + '" data-match-id="' + matchDef.id + '">';
          html += '<div class="slot-header"><span class="slot-label">' + escHtml(matchDef.id) + '</span>';
          html += '<div class="slot-actions">';
          html += '<button class="btn btn-xs btn-primary" onclick="openMatchModal(\'' + matchDef.id + '\')" title="编辑比分">编辑</button>';
          html += '</div></div>';
          html += '<div class="slot-teams">';
          html += renderTeamSlot(matchDef.id, 0, m.team1, m.score1, m.team2, m.score2);
          html += '<div class="slot-vs">VS</div>';
          html += renderTeamSlot(matchDef.id, 1, m.team2, m.score2, m.team1, m.score1);
          html += '</div></div>';
        });
        html += '</div></div>';
      });
    } else {
      // 淘汰赛：每个 round 一列
      html += '<div class="section-rounds-row">';
      section.rounds.forEach(function(round) {
        html += '<div class="round-col" style="flex:1">';
        html += '<div class="round-title">' + escHtml(round.name) + '</div>';
        round.matches.forEach(function(matchDef) {
          var m = _state.matches[matchDef.id] || { team1: null, team2: null, score1: '', score2: '', match_id: '', maps: [] };
          var filled = (m.team1 || m.team2);
          html += '<div class="bracket-slot' + (filled ? ' filled' : '') + '" data-match-id="' + matchDef.id + '">';
          html += '<div class="slot-header"><span class="slot-label">' + escHtml(matchDef.id) + '</span>';
          html += '<div class="slot-actions">';
          html += '<button class="btn btn-xs btn-primary" onclick="openMatchModal(\'' + matchDef.id + '\')" title="编辑比分">编辑</button>';
          html += '</div></div>';
          html += '<div class="slot-teams">';
          html += renderTeamSlot(matchDef.id, 0, m.team1, m.score1, m.team2, m.score2);
          html += '<div class="slot-vs">VS</div>';
          html += renderTeamSlot(matchDef.id, 1, m.team2, m.score2, m.team1, m.score1);
          html += '</div></div>';
        });
        html += '</div>';
      });
      html += '</div>'; // .section-rounds-row
    }
  });

  container.innerHTML = html || '<div class="empty-bracket-hint">选择赛制后将显示对阵图编辑区域</div>';
  setupDragDelegate();
}

function renderTeamSlot(matchId, slotIndex, teamKey, score, oppositeKey, oppositeScore) {
  var tm = teamKey ? _state.teams[teamKey] : null;
  var nameHtml = tm ? escHtml(tm.short_name || tm.name) : '<span class="team-name-text placeholder">拖入队伍</span>';
  var nameClass = tm ? 'team-name-text' : 'team-name-text placeholder';
  var scoreVal = (score !== '' && score != null) ? score : '';

  var html = '<div class="slot-team drop-target" data-match-id="' + matchId + '" data-slot-index="' + slotIndex + '">';
  html += '<span class="seed-badge">' + (slotIndex + 1) + '</span>';
  html += '<span class="' + nameClass + '">' + nameHtml + '</span>';
  if (tm) {
    html += '<button class="remove-team-btn" onclick="event.stopPropagation();removeTeamFromSlot(\'' + matchId + '\',' + slotIndex + ')" title="移除队伍">&times;</button>';
  }
  html += '<input type="number" class="team-score" min="0" max="3" value="' + scoreVal + '" placeholder="-" data-match-id="' + matchId + '" data-slot-index="' + slotIndex + '" onchange="onScoreChange(this)" onclick="event.stopPropagation()">';
  html += '</div>';
  return html;
}

function onScoreChange(input) {
  var matchId = input.dataset.matchId;
  var slotIndex = parseInt(input.dataset.slotIndex);
  var val = input.value;
  if (!_state.matches[matchId]) {
    _state.matches[matchId] = { team1: null, team2: null, score1: '', score2: '', match_id: '', maps: [] };
  }
  if (slotIndex === 0) _state.matches[matchId].score1 = val;
  else _state.matches[matchId].score2 = val;
}

// ==================== 比赛编辑弹窗 ====================
var _editingMatchId = null;

function openMatchModal(matchId) {
  _editingMatchId = matchId;
  var match = _state.matches[matchId] || { team1: null, team2: null, score1: '', score2: '', match_id: '', maps: [] };

  document.getElementById('modalTitle').textContent = '编辑比赛 — ' + matchId;

  document.getElementById('modalScore1').value = match.score1;
  document.getElementById('modalScore2').value = match.score2;
  document.getElementById('modalMatchId').value = match.match_id || '';

  renderMapRows(match.maps || []);

  document.getElementById('modalDeleteBtn').style.display = 'inline-block';
  document.getElementById('matchModal').style.display = 'flex';
}

function closeModal() {
  document.getElementById('matchModal').style.display = 'none';
  _editingMatchId = null;
}

function saveMatch() {
  if (!_editingMatchId) return;
  if (!_state.matches[_editingMatchId]) {
    _state.matches[_editingMatchId] = { team1: null, team2: null, score1: '', score2: '', match_id: '', maps: [] };
  }

  var m = _state.matches[_editingMatchId];
  m.score1 = document.getElementById('modalScore1').value;
  m.score2 = document.getElementById('modalScore2').value;
  m.match_id = document.getElementById('modalMatchId').value;

  var mapRows = document.querySelectorAll('#modalMapScores .map-scores-row');
  m.maps = [];
  mapRows.forEach(function(row) {
    var mapName = row.querySelector('.map-select').value;
    var s1 = row.querySelector('.map-s1').value;
    var s2 = row.querySelector('.map-s2').value;
    if (mapName || s1 || s2) {
      m.maps.push({ name: mapName, t1: parseInt(s1) || 0, t2: parseInt(s2) || 0 });
    }
  });

  closeModal();
  renderAll();
}

function deleteMatch() {
  if (!_editingMatchId) return;
  showConfirm('确认删除此比赛及其数据？', '删除确认').then(function(yes) {
    if (!yes) return;
    delete _state.matches[_editingMatchId];
    closeModal();
    renderAll();
  });
}

function renderMapRows(maps) {
  var container = document.getElementById('modalMapScores');
  var html = '';
  var mapOptions = ['de_inferno', 'de_mirage', 'de_nuke', 'de_overpass', 'de_dust2', 'de_vertigo', 'de_ancient', 'de_anubis', 'de_train'];
  var mapLabels = ['Inferno', 'Mirage', 'Nuke', 'Overpass', 'Dust2', 'Vertigo', 'Ancient', 'Anubis', 'Train'];
  var mapOptsHtml = mapOptions.map(function(n, i) {
    return '<option value="' + n + '">' + mapLabels[i] + '</option>';
  }).join('');

  (maps || []).forEach(function(m) {
    html += '<div class="map-scores-row">';
    html += '<select class="map-select" style="width:140px">' + mapOptsHtml.replace('value="' + m.name + '"', 'value="' + m.name + '" selected') + '</select>';
    html += '<input type="number" class="map-s1" min="0" max="99" value="' + (m.t1 || 0) + '" style="width:50px;text-align:center">';
    html += '<span>:</span>';
    html += '<input type="number" class="map-s2" min="0" max="99" value="' + (m.t2 || 0) + '" style="width:50px;text-align:center">';
    html += '<button class="btn btn-xs" style="color:#e74c3c" onclick="this.closest(\'.map-scores-row\').remove()">&times;</button>';
    html += '</div>';
  });
  container.innerHTML = html || '<div style="color:#999;font-size:12px">暂无地图比分</div>';
}

function addMapRow() {
  var container = document.getElementById('modalMapScores');
  var mapOptions = ['de_inferno', 'de_mirage', 'de_nuke', 'de_overpass', 'de_dust2', 'de_vertigo', 'de_ancient', 'de_anubis', 'de_train'];
  var mapLabels = ['Inferno', 'Mirage', 'Nuke', 'Overpass', 'Dust2', 'Vertigo', 'Ancient', 'Anubis', 'Train'];
  var mapOptsHtml = mapOptions.map(function(n, i) {
    return '<option value="' + n + '">' + mapLabels[i] + '</option>';
  }).join('');

  var row = document.createElement('div');
  row.className = 'map-scores-row';
  row.innerHTML = '<select class="map-select" style="width:140px">' + mapOptsHtml + '</select>' +
    '<input type="number" class="map-s1" min="0" max="99" value="0" style="width:50px;text-align:center">' +
    '<span>:</span>' +
    '<input type="number" class="map-s2" min="0" max="99" value="0" style="width:50px;text-align:center">' +
    '<button class="btn btn-xs" style="color:#e74c3c" onclick="this.closest(\'.map-scores-row\').remove()">&times;</button>';
  container.appendChild(row);
}

function populateMatchSelect() {
  var select = document.getElementById('modalMatchId');
  var currentVal = select.value;
  var matches = window._eventMatches || [];

  var html = '<option value="">-- 不关联 --</option>';
  matches.forEach(function(m) {
    var label = (m.match_time || '').substring(0, 16) + ' ' + (m.t1_name || '?') + ' vs ' + (m.t2_name || '?');
    var sel = currentVal == m.id ? ' selected' : '';
    html += '<option value="' + m.id + '"' + sel + '>' + escHtml(label) + '</option>';
  });
  select.innerHTML = html;
}

document.addEventListener('click', function(e) {
  if (e.target.id === 'matchModal') closeModal();
});

// ==================== 保存 ====================
function saveBracket() {
  var fmt = FORMATS[_state.format];
  if (!fmt) { showToast('请选择赛制', 'error'); return; }

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
        var m = _state.matches[matchDef.id] || { team1: null, team2: null, score1: '', score2: '', match_id: '', maps: [] };
        var matchObj = {
          id: matchDef.id,
          team1: m.team1 || null,
          team2: m.team2 || null,
          score1: m.score1 !== '' ? parseInt(m.score1) : null,
          score2: m.score2 !== '' ? parseInt(m.score2) : null,
          match_id: m.match_id || null,
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
      name: document.getElementById('tournamentName').value || fmt.name,
      type: fmt.type,
      total_teams: fmt.total_teams,
      teams: teamsList,
      sections: sections,
      rounds: rounds
    }
  };

  var btn = document.querySelector('.btn-primary');
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '保存中...';

  fetch('/admin/events/' + window._eventId + '/bracket/api/save', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      'X-CSRF-Token': window._csrfToken
    },
    body: JSON.stringify(data)
  })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    btn.disabled = false;
    btn.textContent = origText;
    if (res.success) {
      showToast('对阵图保存成功！', 'success');
    } else {
      showToast('保存失败：' + (res.error || '未知错误'), 'error');
    }
  })
  .catch(function(err) {
    btn.disabled = false;
    btn.textContent = origText;
    showToast('网络错误，请重试', 'error');
    console.error(err);
  });
}

function resetBracket() {
  showConfirm('确认重置对阵图？所有未保存的修改将丢失。', '重置确认').then(function(yes) {
    if (!yes) return;
    _state.matches = {};
    _state.teams = {};
    _state.tournamentName = '';
    document.getElementById('tournamentName').value = '';
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
  init();
});
