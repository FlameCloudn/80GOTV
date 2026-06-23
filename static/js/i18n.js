(function () {
  var saved = localStorage.getItem('siteLang');
  var mode = saved || 'auto';
  var systemLanguage = (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en';
  var language = mode === 'auto' ? systemLanguage : mode;
  var translations = {
    '跟随系统': 'Auto', '中文': 'Chinese', '语言': 'Language',
    '新闻': 'News', '比赛': 'Matches', '赛果': 'Results', '赛果列表': 'Results', '赛事': 'Events',
    '全部赛事': 'All events', '进行中': 'Ongoing', '历史赛事': 'Archive', '日历': 'Calendar',
    '选手': 'Players', '全部选手': 'All players', 'MVP 选手': 'MVP players',
    'EVP 选手': 'EVP players', '数据': 'Stats', '总览': 'Overview',
    '选手排行': 'Top players', '地图': 'Maps', '荣誉堂': 'Awards',
    '预测': 'Predictions', '数据看板': 'Dashboard', '论坛': 'Forum',
    '预测排行': 'Predictions', '预测积分榜': 'Prediction standings',
    '赛季积分 TOP 10': 'Season points TOP 10',
    '站内公告、赛事消息和更新记录': 'Site announcements, match news, and update notes',
    '查看赛事状态、时间、赛制和比赛数量': 'Event status, dates, format, and match count',
    '按队伍筛选选手，查看基础比赛数据': 'Filter players by team and view basic match stats',
    '已结束比赛的比分和赛事归属': 'Completed match scores and event information',
    '选手、地图、荣誉和全局统计': 'Players, maps, awards, and overall stats',
    '图表化查看 RATING、荣誉和赛事数据': 'Chart view for RATING, awards, and event data',
    '预测积分排行和热门预测比赛': 'Prediction standings and popular prediction matches',
    '讨论赛事、约战和网站内容': 'Discuss events, scrims, and site content',
    '当前标签：': 'Current tag: ', '标签：': 'Tag: ', '搜索：': 'Search: ',
    '清除标签': 'Clear tag', '清除搜索': 'Clear search', '发新帖': 'New thread',
    '历史': 'Archive', '快捷入口': 'Quick links', '赛事状态': 'Event status',
    '登录': 'Log in', '退出': 'Log out', '注册': 'Register', '搜索...': 'Search...',
    '今日新闻': 'Today news', '今日比赛': 'Today matches', '近期赛果': 'Recent results',
    '排行': 'Ranking', '焦点新闻': 'Featured news', '近期动态': 'Recent activity',
    '本周最佳选手': 'Player of the week', '新闻列表': 'News', '热门标签': 'Popular tags', '清除筛选': 'Clear filter',
    '暂无标签': 'No tags', '上一页': 'Previous', '下一页': 'Next',
    '比赛列表': 'Matches', '赛事列表': 'Events', '选手列表': 'Players',
    '赛事筛选': 'Event filter', '状态筛选': 'Status filter', '日期筛选': 'Date filter',
    '全部状态': 'All statuses', '全部日期': 'All dates',
    '未开始': 'Upcoming', '已结束': 'Completed', '直播中': 'Live',
    '全部队伍': 'All teams', '队伍筛选': 'Team filter', '筛选': 'Filter',
    '暂无比赛': 'No matches', '暂无赛果': 'No results', '暂无数据': 'No data', '此图暂无数据': 'No data for this map',
    '未分组赛事': 'Ungrouped event', '上一月': 'Previous month', '下一月': 'Next month',
    '赛事信息': 'Event information', '赛制：': 'Format: ', '队伍数：': 'Teams: ',
    '比赛数：': 'Matches: ', '参赛队伍': 'Teams', '比赛列表': 'Matches',
    '对阵图': 'Bracket', '赛事数据 →': 'Event stats →', '赛事图池': 'Map pool',
    '← 返回赛事列表': '← Back to events', '即将开始': 'Upcoming',
    '观赛平台': 'Watch platforms', '下载赛果海报': 'Download result poster',
    '2D回放': '2D replay', '2D Demo 回放': '2D Demo replay', 'Demo 下载': 'Demo download', '下载地图': 'Download map',
    '历史交锋': 'Head-to-head', '比赛数据直播': 'Live match data',
    '报名开放中': 'Registration open', '创建队伍报名': 'Create team registration',
    '报名需要先绑定 Steam': 'Bind Steam before registering', '去绑定': 'Bind now',
    '管理员账号不能报名，请使用选手账号登录': 'Admin accounts cannot register; use a player account',
    '退出管理员': 'Log out admin', '登录后报名': 'Log in to register',
    '加入此位置': 'Join this slot', '绑定 Steam': 'Bind Steam',
    '选手账号加入': 'Player account required', '登录加入': 'Log in to join',
    '报名 —': 'Registration -', '创建队伍并选择你的位置（可预填队友信息）': 'Create a team and choose your slot. Teammate info can be prefilled.',
    '队伍名称': 'Team name', '选择你的位置：': 'Choose your slot:',
    '队友信息（至少填自己的位置，其他可选填）：': 'Teammate info. Fill your slot; others are optional.',
    '提交报名': 'Submit registration',
    '等待观战账号连接': 'Waiting for observer account', '等待回合数据': 'Waiting for round data',
    '尚未收到数据': 'No data received', '炸弹状态：-': 'Bomb status: -',
    '比赛日志': 'Game log', '等待数据': 'Waiting for data',
    '手枪': 'Pistol', '主武器': 'Primary', '血量': 'HP', '护甲': 'Armor', '金钱': 'Money',
    '数据统计': 'Stats', '概览': 'Overview', '地图数据': 'Map stats',
    '选手总数': 'Players', '队伍总数': 'Teams', '赛事总数': 'Events',
    '已完成比赛': 'Completed matches', '统计数据条数': 'Stat records',
    '全员平均 RATING': 'Average RATING', '全员平均 ADR': 'Average ADR',
    '最近比赛': 'Recent matches', 'RATING': 'RATING', 'RATING 趋势': 'RATING trend',
    '平均 RATING': 'Average RATING', '影响力': 'Impact', '场次': 'Maps',
    '数据仪表盘': 'Dashboard', 'MVP 数量': 'MVP count', 'EVP 数量': 'EVP count',
    '选手生涯 RATING 分布': 'Player RATING distribution',
    'MVP 数量排行 TOP 5': 'MVP count TOP 5',
    'EVP 数量排行 TOP 5': 'EVP count TOP 5',
    '赛事比赛数量': 'Matches per event',
    '人数': 'Players', '比赛数': 'Matches',
    '登录 / 注册 — 80GOTV': 'Log in / Register — 80GOTV',
    '用户名': 'Username', '密码': 'Password', '验证码': 'Captcha',
    '忘记密码？': 'Forgot password?', '返回首页': 'Back to home',
    '确认密码 *': 'Confirm password *', '头像': 'Avatar', '注册类型 *': 'Account type *',
    '我是选手': 'I am a player', '我是游客': 'I am a visitor',
    'Steam 身份验证 *': 'Steam verification *', '使用 Steam 验证身份': 'Verify with Steam',
    '后台管理': 'Admin', '首页': 'Home', '队伍': 'Teams', '管理功能': 'Management',
    '队伍管理': 'Manage teams', '选手管理': 'Manage players', '赛事管理': 'Manage events',
    '比赛管理': 'Manage matches', '新闻管理': 'Manage news', '直播状态': 'Live status',
    '保存比赛日志': 'Save game log', '添加': 'Add', '编辑': 'Edit', '删除': 'Delete',
    '保存': 'Save', '取消': 'Cancel', '返回': 'Back', '待定': 'TBD',
    '返回比赛': 'Back to match', '回看': 'Rewatch', '暂无回看资源': 'No rewatch resources',
    '暂无 BP 记录': 'No BP record', '暂无已完成地图': 'No completed maps',
    '选图': 'PICK', '线上': 'Online',
    '比赛结束': 'Match over', '点击播放直播': 'Click to play live stream', '直播不会自动加载': 'The stream will not load automatically',
    '队伍 RATING 2.0': 'Team RATING 2.0', '地图记录': 'Map record',
    '表现 - RATING 2.0': 'Performance - RATING 2.0', '详细数据': 'Detailed stats',
    '最高 RATING': 'Best RATING', '最高 ADR': 'Best ADR', '最多击杀': 'Most kills',
    '最多助攻': 'Most assists', '最多闪白': 'Most flashed',
    '经济': 'Economy', '测试': 'Beta', '热力图': 'Heatmaps',
    '赛前预测': 'Pre-match prediction', '你已投票给': 'You voted for',
    '比分(可选)': 'Score (optional)', '后即可参与投票预测': 'to join the prediction',
    '写下你的评论...': 'Write a comment...', '发表评论': 'Post comment', '后即可发表评论': 'to comment',
    '评论': 'Comments', '暂无评论': 'No comments', '返回赛事': 'Back to event',
    '一月': 'January', '二月': 'February', '三月': 'March', '四月': 'April',
    '五月': 'May', '六月': 'June', '七月': 'July', '八月': 'August',
    '九月': 'September', '十月': 'October', '十一月': 'November', '十二月': 'December',
    '周一': 'Mon', '周二': 'Tue', '周三': 'Wed', '周四': 'Thu',
    '周五': 'Fri', '周六': 'Sat', '周日': 'Sun',
    '直播': 'Live', '比赛筛选': 'Match filters', '已结束比赛': 'Completed matches',
    '暂无新闻': 'No news', '暂无赛事': 'No events', '暂无选手': 'No players',
    '数据概览': 'Stats overview', '地图数据': 'Map stats',
    '返回数据概览': 'Back to stats overview', '返回选手资料': 'Back to player profile',
    '选手信息': 'Player information', '当前队伍': 'Current team', '地图数': 'Maps',
    '无队伍': 'No team', '无': 'None', '昵称': 'Nickname', '真名': 'Real name',
    '历史昵称': 'Previous nicknames', '查看': 'View', '的完整数据': 'complete stats',
    '日期': 'Date', '对阵': 'Matchup', '冠军': 'Champion',
    '暂无荣誉': 'No awards', '暂无冠军记录': 'No trophies',
    '时间筛选': 'Time filter', '地图筛选': 'Map filter', '全部': 'All',
    '最近 3 个月': 'Last 3 months', '最近 6 个月': 'Last 6 months', '最近 12 个月': 'Last 12 months',
    '双方': 'Both sides', '恐怖分子': 'Terrorist', '反恐精英': 'Counter-Terrorist', 'T 方': 'T side', 'CT 方': 'CT side',
    '全部地图': 'All maps', '比赛数据': 'Match stats',
    '炙热沙城Ⅱ': 'Dust2', '荒漠迷城': 'Mirage', '炼狱小镇': 'Inferno',
    '核子危机': 'Nuke', '死亡游乐园': 'Overpass', '远古遗迹': 'Ancient', '阿努比斯': 'Anubis',
    '死城之谜': 'Cache', '列车停放站': 'Train', '殒命大厦': 'Vertigo',
    '快速导航': 'Quick navigation', '最佳选手': 'Best players', '最佳队伍': 'Top teams',
    '热门赛事': 'Top events', '手枪局': 'Pistol rounds', '闪光弹': 'Flashes', '常用武器': 'Top weapons',
    '资料': 'Info', '荣誉': 'Achievements', '近期比赛': 'Recent matches', '个人数据': 'Individual',
    '趋势': 'Career', '武器': 'Weapons', '残局': 'Clutches', '多杀': 'Multi-kills', '对手': 'Opponents',
    '选手数据导航': 'Player stats navigation', '统计单位：': 'Stats per: ', '阵营：': 'Side: ',
    '回合': 'Round', '24 回合': '24 rounds', '地图': 'Maps',
    '统计总览': 'Statistics', 'RATING 趋势': 'RATING timeline', '数据统计': 'Statistics', '对': 'vs',
    '火力': 'Firepower', '协作': 'Trading', '突破': 'Entrying', '补枪': 'Trading', '开局': 'Opening', '残局': 'Clutches', '狙击': 'Sniping', '道具': 'Utility',
    '每回合击杀': 'Kills per round', '每回合伤害': 'Damage per round', 'K-D 差': 'K-D difference',
    '影响力 RATING': 'Impact RATING', '多杀回合占比': 'Multi-kill rounds %', '爆头率': 'Headshot percentage', '每回合首杀': 'Opening kills per round',
    '每回合首死': 'Opening deaths per round', '开局对枪参与率': 'Opening attempts',
    '开局成功率': 'Opening success', '首杀后回合胜率': 'Win% after opening kill',
    '被补率': 'Trade death rate', '每回合补枪': 'Trade kills / r', '每回合被补': 'Traded deaths / r',
    '每回合补枪击杀': 'Trade kills per round', '每回合被补枪死亡': 'Trade deaths per round',
    '补枪击杀/回合': 'Trade kills / round', '被补枪死亡/回合': 'Trade deaths / round',
    '补枪击杀占比': 'Trade kills percentage', '被补枪死亡占比': 'Traded deaths percentage', '被补枪占比': 'Traded deaths %',
    '每回合助攻': 'Assists per round', '每回合开局对枪': 'Attacks per round',
    '每回合残局得分': 'Clutch points per round', '残局获胜数': 'Clutches won', '残局得分/回合': 'Clutch pts / round',
    '下包数': 'Bomb plants', '拆包数': 'Bomb defuses', '回合存活率估算': 'Rounds survived proxy',
    '首杀/首死比': 'Opening K-D ratio',
    '每回合狙击击杀': 'Sniper kills per round', '狙击击杀占比': 'Sniper kills percentage',
    '有狙击击杀回合占比': 'Rounds with sniper kills percentage', '有狙击击杀回合': 'Sniper kill rounds',
    '狙击多杀回合': 'Sniper multi-kill rounds', '每回合狙击首杀': 'Sniper opening kills per round', '狙击首杀': 'Sniper opening kills',
    '每回合道具伤害': 'Utility damage per round', '总道具伤害': 'Total utility damage',
    '每回合闪光投掷': 'Flashes thrown per round', '每回合致盲敌人': 'Enemies flashed per round',
    '闪光成功率': 'Flash success', '总击杀': 'Total kills', '总回合': 'Rounds played',
    '总死亡': 'Total deaths', '每回合死亡': 'Deaths per round',
    '每回合被队友补枪': 'Saved by teammate per round', '每回合补枪队友': 'Saved teammates per round',
    '击杀': 'Kills', '首杀': 'First kills', '首死': 'First deaths', '投掷': 'Thrown',
    '致盲': 'Blinded', '敌方被闪': 'Opp flashed', '差值': 'Diff', '成功率': 'Success',
    '暂无武器数据': 'No weapon data', '暂无荣誉记录': 'No award records',
    '出场': 'Played', '出场率': 'Pick rate', 'T 胜率': 'T win rate', 'CT 胜率': 'CT win rate',
    '概览': 'Overview', 'FA': 'FA', '被闪': 'Blinded',
    '胜 - 负': 'Won - Lost', '手枪局胜率': 'Pistol win %',
    '第二局转换': 'Round 2 conv', '第二局破局': 'Round 2 break',
    '直播与回放': 'Stream & VODs', '地图记录': 'Map record', '残局获胜': 'Clutches won',
    '队伍 Rating': 'Team Rating', '1vX 残局': '1vX clutches',
    '表现总览': 'Performance overview', '表现 - Rating': 'Performance - Rating',
    '对位击杀': 'Kill matrix', '对位击杀类型': 'Kill matrix type',
    '来自 Demo': 'From demo', '暂无可匹配击杀': 'No matched kills',
    '首杀-首死': 'Opening K-D', '击杀(爆头)': 'Kills (HS)', '助攻(闪白)': 'Assists (flash)',
    '死亡(被补)': 'Deaths (traded)', 'AWP 击杀': 'AWP kills',
    '选手表现总览': 'Player performance overview', '暂无队伍 1 选手数据': 'No team 1 player stats',
    '暂无队伍 2 选手数据': 'No team 2 player stats', '偏低': 'Bad', '优秀': 'Good', '平均': 'Average',
    '首杀': 'First kills', '暂无比赛数据': 'No match data', '暂无直播或回放资源': 'No streams or VODs',
    '返回比赛': 'Back to match', '下载赛果海报': 'Download result poster',
    '2D Demo 回放': '2D Demo replay', '表现': 'Performance', '经济': 'Economy',
    '热力图': 'Heatmaps', '测试': 'Beta', '赛前预测': 'Pre-match prediction',
    '返回赛事': 'Back to event', '← 返回赛事': '← Back to event', '🎯 2D Demo 回放': '🎯 2D Demo replay',
    '即将': 'Upcoming', '即将开始': 'Upcoming', '比赛结束': 'Match over'
  };
  var extraTranslations = {
    '英文': 'English',
    '打开菜单': 'Open menu',
    '主导航': 'Main navigation',
    '站内搜索': 'Site search',
    '搜索': 'Search',
    '通知': 'Notifications',
    '加载中...': 'Loading...',
    '查看全部': 'View all',
    '全部已读': 'Mark all read',
    '请先登录': 'Please log in first',
    '暂无通知': 'No notifications',
    '切换主题': 'Toggle theme',
    '切换深色/浅色模式': 'Toggle dark/light mode',
    '八十中 80GO CS交流群 · 仅供学习交流使用 · QQ群号：668460739': 'Bashizhong 80GO CS group · For learning only · QQ group: 668460739',
    '© 八十中 80GO CS交流群 · 仅供学习交流使用 · QQ群号：668460739': '© Bashizhong 80GO CS group · For learning only · QQ group: 668460739',
    '暂无动态': 'No activity',
    '未命名新闻': 'Untitled news',
    '无匹配结果': 'No matching results',
    '删除': 'Delete',
    '回复': 'Reply',
    '刚刚': 'Just now',
    '提交中...': 'Submitting...',
    '网络错误，请重试': 'Network error, please try again',
    '确认删除此评论？如有回复也会一并删除': 'Delete this comment? Replies will also be deleted.',
    '确定': 'OK',
    '查看比赛详情': 'View match details',
    '查看完整比赛 →': 'View full match →',
    '该场比赛未被记录': 'This match is not recorded',
    '暂无地图比分': 'No map scores',
    '返回比赛详情': 'Back to match details',
    '这场比赛还没有录入选手数据': 'No player stats have been entered for this match yet',
    '暂无表现数据': 'No performance data',
    '最高 Rating': 'Best Rating',
    '最多首杀': 'Most opening kills',
    '最多残局': 'Most clutches',
    '这个地图暂时没有可用于矩阵的 Demo 击杀数据': 'No demo kill data is available for this map matrix yet',
    '暂无选手表现数据': 'No player performance data',
    '地图选择': 'Map selection',
    '阵营切换': 'Side switch',
    '死亡': 'Deaths',
    '助攻': 'Assists',
    '良好': 'Good',
    '正常': 'Normal',
    '较差': 'Poor',
    '差': 'Bad',
    '条记录': 'records',
    '自由选手': 'Free agent',
    '选手对比': 'Player comparison',
    '选择选手 A...': 'Select player A...',
    '选择选手 B...': 'Select player B...',
    '对比': 'Compare',
    '请选择两名选手进行对比': 'Please select two players to compare',
    '后台首页': 'Admin home',
    'CS2 后台管理': 'CS2 Admin',
    '管理后台': 'Admin panel',
    '添加新闻': 'Add news',
    '编辑新闻': 'Edit news',
    '标题': 'Title',
    '作者': 'Author',
    '发布时间': 'Published at',
    '评论数': 'Comments',
    '操作': 'Actions',
    '添加选手': 'Add player',
    '编辑选手': 'Edit player',
    '游戏昵称': 'Game nickname',
    '真实姓名（可选）': 'Real name (optional)',
    '支持 jpg/png/gif，留空则不修改': 'Supports jpg/png/gif. Leave blank to keep unchanged.',
    '保存修改': 'Save changes',
    '添加比赛': 'Add match',
    '编辑比赛': 'Edit match',
    '选择赛事': 'Select event',
    '比赛时间': 'Match time',
    '比赛阶段': 'Match stage',
    '队伍1': 'Team 1',
    '队伍2': 'Team 2',
    '选择队伍': 'Select team',
    '选择五名选手': 'Select five players',
    '参赛队伍（创建后不可修改）': 'Teams (cannot be changed after creation)',
    '比赛设置': 'Match settings',
    '地图模式': 'Map mode',
    '手动选图': 'Manual map picks',
    '在线 BP': 'Online BP',
    '图一': 'Map 1',
    '图二': 'Map 2',
    '图三': 'Map 3',
    '图四': 'Map 4',
    '图五': 'Map 5',
    '大比分': 'Series score',
    '队伍1 大比分': 'Team 1 series score',
    '队伍2 大比分': 'Team 2 series score',
    '未打的图（如 2:0 则勾选图三）': 'Unplayed maps (for 2:0, tick map 3)',
    '无图三': 'No map 3',
    '无图四': 'No map 4',
    '无图五': 'No map 5',
    '留空则保持原密码': 'Leave blank to keep the current password',
    '留空则不启用在线 BP': 'Leave blank to disable online BP',
    '清除现有 BP 密码': 'Clear current BP password',
    '每行一步，例如：': 'One step per line, for example:',
    '可选：直播、观赛平台与比赛服务器': 'Optional: live stream, watch platforms, and match server',
    'B站直播间链接': 'Bilibili live room link',
    '观赛平台链接': 'Watch platform links',
    '平台名+URL，前台显示为可点击按钮': 'Platform name + URL, shown as a clickable button on the site',
    '+ 添加平台': '+ Add platform',
    '比赛服务器地址': 'Match server address',
    '可直接粘贴 TGPro 连接串': 'You can paste a TGPro connection string directly',
    '状态': 'Status',
    '保存此图数据': 'Save this map data',
    '录入比赛数据': 'Enter match stats',
    '从 Demo 导入数据': 'Import data from Demo',
    '已保存 Demo：': 'Saved Demo:',
    '编辑比分': 'Edit score',
    '移除队伍': 'Remove team',
    '从对阵图中移除': 'Remove from bracket',
    '未知赛制': 'Unknown format',
    '选择赛制后将显示对阵图编辑区域': 'Select a format to show the bracket editor',
    '拖入队伍': 'Drag team here',
    '编辑比赛 —': 'Edit match -',
    '确认删除此比赛及其数据？': 'Delete this match and its data?',
    '删除确认': 'Delete confirmation',
    '保存中...': 'Saving...',
    '对阵图保存成功！': 'Bracket saved successfully!',
    '保存失败：': 'Save failed: ',
    '未知错误': 'Unknown error',
    '确认重置对阵图？所有未保存的修改将丢失。': 'Reset the bracket? Unsaved changes will be lost.',
    '重置确认': 'Reset confirmation',
    '请选择赛制': 'Please select a format',
    '自定义': 'Custom',
    '昵称管理 - 80GOTV': 'Nickname management - 80GOTV',
    '选手昵称管理': 'Player nickname management',
    '正式昵称用于网站显示，Steam 和 Demo 中见过的旧昵称仍会保留。': 'The official nickname is shown on the site. Old nicknames seen in Steam and Demo are still kept.',
    '返回后台': 'Back to admin',
    '合并重复选手': 'Merge duplicate players',
    '把错误生成的重复档案合并到要保留的档案。历史比赛会一起搬过去。': 'Merge the incorrectly created duplicate profile into the profile you want to keep. Historical matches will move with it.',
    '要移除的重复档案': 'Duplicate profile to remove',
    '合并到': 'Merge into',
    '要保留的正式档案': 'Official profile to keep',
    '合并档案': 'Merge profiles',
    '正式昵称': 'Official nickname',
    '确定合并这两个选手档案吗？重复档案会被移除。': 'Merge these two player profiles? The duplicate profile will be removed.',
    '未设置': 'Not set',
    '选择地图': 'Select map',
    '平台名（如 Bilibili）': 'Platform name (e.g. Bilibili)'
    ,'暂无更多新闻': 'No more news',
    '直播中与即将开始': 'Live and upcoming',
    '最新赛果': 'Latest results',
    '赛事统计': 'Event stats',
    '冠军赛事': 'Champion events',
    '用户': 'User',
    '预测场次': 'Predictions',
    '正确': 'Correct',
    '准确率': 'Accuracy',
    '总积分': 'Total points',
    '热门预测比赛': 'Popular prediction matches',
    '暂无预测数据，去比赛详情页参与预测吧！': 'No prediction data yet. Join predictions on match detail pages.',
    '近期热门': 'Recent hot tags',
    '全部热门': 'All hot tags',
    '登录发帖': 'Log in to post',
    '浏览': 'views',
    '搜索标题和内容...': 'Search titles and content...',
    '清除': 'Clear',
    '多标签模式:': 'Multi-tag mode:',
    '包含任一': 'Any tag',
    '包含全部': 'All tags',
    '切换为': 'Switch to ',
    '暂无帖子，快来发第一个吧': 'No posts yet. Be the first to post.',
    '没有找到包含「': 'No posts containing "',
    '没有找到标签为「': 'No posts with tag "',
    '」的帖子': '" found',
    '评分': 'Rating',
    '依报名队伍决定': 'Depends on registered teams',
    '单场BO3': 'Single BO3',
    '双败淘汰': 'Double elimination',
    '轮空': 'bye',
    '新闻 - 80GOTV': 'News - 80GOTV',
    '比赛 - 80GOTV': 'Matches - 80GOTV',
    '赛果 - 80GOTV': 'Results - 80GOTV',
    '赛事列表 - 80GOTV': 'Events - 80GOTV',
    '选手列表 - 80GOTV': 'Players - 80GOTV',
    '数据统计 - 80GOTV': 'Stats - 80GOTV',
    '预测排行 - 80GOTV': 'Predictions - 80GOTV',
    '社区论坛': 'Forum',
    '进行中赛事': 'Ongoing events',
    '即将开始 - 80GOTV': 'Upcoming - 80GOTV',
    '历史赛事 - 80GOTV': 'Archived events - 80GOTV'
  };
  Object.keys(extraTranslations).forEach(function (key) {
    translations[key] = extraTranslations[key];
  });
  var partialTranslations = [
    ['赛果 - ', 'Results - '], ['评论 ', 'Comments '], [' 场比赛', ' matches'],
    [' 支队伍', ' teams'], ['共 ', 'Total '], [' 个赛事', ' events'],
    ['第 ', 'Page '], [' 页', ''], [' 对 ', ' vs '], [' 条', ' items'], [' 场', ' matches'],
    [' 地图', ' maps'], [' 回合', ' rounds'], [' 数据 - ', ' stats - '],
    [' 选图', ' pick'],
    ['（线上）', ' (Online)'], ['线上', 'Online']
  ];
  var extraPartialTranslations = [
    ['回复 @', 'Reply @'],
    ['确定删除新闻【', 'Delete news "'],
    ['确定删除选手【', 'Delete player "'],
    ['】吗？', '"?'],
    [' 图', ' map'],
    ['选手 ', 'Player '],
    ['下载 ', 'Download '],
    ['比赛结束', 'Match over'],
    ['即将开始', 'Upcoming'],
    ['直播中', 'Live'],
    ['进行中', 'Ongoing'],
    ['已结束', 'Completed'],
    ['人预测', 'predictions'],
    ['浏览', 'views'],
    ['依报名队伍决定', 'Depends on registered teams'],
    ['单场BO3', 'Single BO3'],
    ['双败淘汰', 'Double elimination'],
    ['轮空', 'bye']
  ];
  var englishToChinese = {};
  Object.keys(translations).forEach(function (key) {
    if (!englishToChinese[translations[key]]) englishToChinese[translations[key]] = key;
  });
  var extraEnglishToChinese = {
    'Auto': '跟随系统',
    'Chinese': '中文',
    'English': '英文',
    'Home': '首页',
    'News': '新闻',
    'Matches': '比赛',
    'Results': '赛果',
    'Events': '赛事',
    'Players': '选手',
    'Teams': '队伍',
    'Stats': '数据',
    'Dashboard': '数据看板',
    'Forum': '论坛',
    'Predictions': '预测',
    'Search': '搜索',
    'Admin': '后台管理',
    'Management': '管理功能',
    'Live': '直播',
    'Upcoming': '未开始',
    'Completed': '已结束',
    'Ongoing': '进行中',
    'Archive': '历史',
    'All': '全部',
    'All maps': '全部地图',
    'All events': '全部赛事',
    'All teams': '全部队伍',
    'All statuses': '全部状态',
    'No data': '暂无数据',
    'No matches': '暂无比赛',
    'No results': '暂无赛果',
    'No events': '暂无赛事',
    'No players': '暂无选手',
    'No comments': '暂无评论',
    'No notifications': '暂无通知',
    'Loading...': '加载中...',
    'Log in': '登录',
    'Log out': '退出',
    'Register': '注册',
    'Save': '保存',
    'Cancel': '取消',
    'Back': '返回',
    'Add': '添加',
    'Edit': '编辑',
    'Delete': '删除',
    'Reply': '回复',
    'OK': '确定',
    'Language': '语言',
    'Online': '线上',
    'Player comparison': '选手对比',
    'Compare': '对比',
    'Free agent': '自由选手',
    'Map 1': '图一',
    'Map 2': '图二',
    'Map 3': '图三',
    'Map 4': '图四',
    'Map 5': '图五',
    'records': '条记录',
    'normal': '正常',
    'news': '新闻',
    'match': '比赛',
    'event': '赛事',
    'player': '选手',
    'team': '队伍'
  };
  Object.keys(extraEnglishToChinese).forEach(function (key) {
    englishToChinese[key] = extraEnglishToChinese[key];
  });
  var reversePartialTranslations = partialTranslations.concat(extraPartialTranslations).map(function (pair) {
    return [pair[1], pair[0]];
  }).concat([
    ['Reply @', '回复 @'],
    ['Delete news "', '确定删除新闻【'],
    ['Delete player "', '确定删除选手【'],
    ['"?', '】吗？'],
    [' map', ' 图'],
    ['Player ', '选手 '],
    ['Download ', '下载 ']
  ]);
  var ignored = [
    '.news-title', '.news-summary', '.news-detail', '.comment-content', '.comment-body',
    '.comment-author', '.comment-avatar-fb', '.username',
    '.team', '.team-name', '.player-name', '.player-link', '.sidebar-event-name',
    '.bp-player-name', '.sd-label', '.sd-sub', '.overview-mini-tag', '.overview-team-mark',
    '.overview-rank-name', '.award-event-name', '.award-champ-team', '.award-medal-player',
    '.award-medal-team', '.overview-avatar-fallback', '.profile-trophy span', '.profile-achievement-list span',
    '.profile-match-row small', '[data-i18n-ignore]'
  ].join(',');
  var monthNames = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];

  function formatDatesForLanguage(value) {
    if (!value) return value;
    var result = value.replace(/(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s+(\d{1,2}:\d{2}))?/g, function (_, year, month, day, time) {
      if (language === 'en') {
        return monthNames[Number(month) - 1] + ' ' + Number(day) + ', ' + year + (time ? ' ' + time : '');
      }
      return year + '年' + Number(month) + '月' + Number(day) + '日' + (time ? ' ' + time : '');
    });
    if (language === 'zh') {
      monthNames.forEach(function (month, index) {
        var monthPattern = new RegExp(month + ' (\\d{1,2}), (\\d{4})(?:\\s+(\\d{1,2}:\\d{2}))?', 'g');
        result = result.replace(monthPattern, function (_, day, year, time) {
          return year + '年' + (index + 1) + '月' + Number(day) + '日' + (time ? ' ' + time : '');
        });
      });
    }
    return result;
  }

  function replaceAllText(value, from, to) {
    return value.split(from).join(to);
  }

  function applyPhrasePairs(value, pairs) {
    var result = value;
    pairs.forEach(function (pair) {
      if (pair[0]) result = replaceAllText(result, pair[0], pair[1]);
    });
    return result;
  }

  function translateZhToEn(value) {
    var trimmed = value.trim();
    if (translations[trimmed]) return formatDatesForLanguage(value.replace(trimmed, translations[trimmed]));
    var result = value;
    result = applyPhrasePairs(result, partialTranslations.concat(extraPartialTranslations));
    result = result.replace(/Demo 下载（地图\s*(\d+)）/g, 'Demo download (Map $1)');
    result = result.replace(/地图\s*(\d+)/g, 'Map $1');
    result = result.replace(/(^|[\s（(])图\s*(\d+)/g, '$1Map $2');
    result = result.replace(/(\d+)\s*票/g, '$1 votes');
    result = result.replace(/BO([135])（Online）/g, 'BO$1 (Online)');
    result = result.replace(/BO([135])（线上）/g, 'BO$1 (Online)');
    return formatDatesForLanguage(result);
  }

  function translateEnToZh(value) {
    var trimmed = value.trim();
    if (englishToChinese[trimmed]) return formatDatesForLanguage(value.replace(trimmed, englishToChinese[trimmed]));
    var result = value;
    result = applyPhrasePairs(result, reversePartialTranslations);
    result = result.replace(/(\d+)\s*votes/g, '$1 票');
    result = result.replace(/BO([135])\s*\(Online\)/g, 'BO$1（线上）');
    return formatDatesForLanguage(result);
  }

  function translateText(value) {
    if (!value || !value.trim()) return value;
    return language === 'en' ? translateZhToEn(value) : translateEnToZh(value);
  }

  var observer = null;
  var translateTimer = null;
  function startObserver() {
    if (!observer || !document.body) return;
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['placeholder', 'title', 'aria-label']
    });
  }

  function scheduleTranslate() {
    clearTimeout(translateTimer);
    translateTimer = setTimeout(translatePage, 40);
  }

  function translatePage() {
    document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
    if (observer) observer.disconnect();
    document.title = translateText(document.title);
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var parent = node.parentElement;
      if (!parent || /^(SCRIPT|STYLE|TEXTAREA)$/.test(parent.tagName) || parent.closest(ignored)) return;
      node.nodeValue = translateText(node.nodeValue);
    });
    document.querySelectorAll('[placeholder],[title],[aria-label]').forEach(function (element) {
      ['placeholder', 'title', 'aria-label'].forEach(function (attribute) {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, translateText(element.getAttribute(attribute)));
        }
      });
    });
    bindToggle();
    startObserver();
  }

  function bindToggle() {
    var select = document.getElementById('languageSelect');
    if (!select) {
      select = document.createElement('select');
      select.id = 'languageSelect';
      select.className = 'language-floating';
      select.setAttribute('aria-label', language === 'zh' ? '语言' : 'Language');
      select.style.cssText = 'position:fixed;right:14px;top:14px;z-index:9999;padding:6px 9px;border:1px solid #ccd4dc;border-radius:0;background:#fff;color:#3b516b;font:600 12px sans-serif;cursor:pointer';
      document.body.appendChild(select);
    }
    select.setAttribute('aria-label', language === 'zh' ? '语言' : 'Language');
    select.innerHTML = language === 'zh'
      ? '<option value="auto">跟随系统</option><option value="zh">中文</option><option value="en">英文</option>'
      : '<option value="auto">Auto</option><option value="zh">Chinese</option><option value="en">English</option>';
    select.value = mode;
    if (select.getAttribute('data-i18n-bound') !== '1') {
      select.setAttribute('data-i18n-bound', '1');
      select.addEventListener('change', function () {
      if (select.value === 'auto') localStorage.removeItem('siteLang');
      else localStorage.setItem('siteLang', select.value);
      location.reload();
      });
    }
  }

  function init() {
    // 翻译完成前隐藏页面，避免文字切换闪烁
    document.documentElement.style.visibility = 'hidden';
    observer = new MutationObserver(scheduleTranslate);
    translatePage();
    // 翻译完成后显示页面
    requestAnimationFrame(function () {
      document.documentElement.style.visibility = '';
    });
  }
  window.applySiteI18n = translatePage;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
