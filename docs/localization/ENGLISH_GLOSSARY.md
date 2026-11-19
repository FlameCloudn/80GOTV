# 80GOTV 英文术语表与本地化规范（English Glossary）

本文档为 80GOTV 全站中英双语界面的项目级英文用词标准。后续新增前台页面、后台管理、赛程运营与统计文案时，均以本表为准。

---

## 一、核心赛事与报名生命周期术语

| 中文概念 | 标准英文 | 使用场景与区分说明 |
|---|---|---|
| 赛事 | Event | 锦标赛/杯赛统称；导航与列表用 `Events` / `Event` |
| 新报名管理 | Managed registration | 新流程的赛事报名与分队体系 |
| 参赛队 / 参赛身份 | Event Entrant (下拉/简写可用 `Entrant`) | 某支队伍在**某一届赛事**中的独立参赛身份（含临时队与俱乐部队），不等同于长期俱乐部 `Club` |
| 长期俱乐部 | Club | 长期存在于战队档案表中的俱乐部；关联时标为 `Club: <name>` |
| 临时队 | Temp team | 无长期俱乐部身份的本届参赛队；标签与徽标统一用 `Temp team` |
| 报名队伍 / 预备组 | Registration group | 报名截止前队长创建的报名组 |
| 个人报名 | Individual registration / Solo signup | 按钮与状态用 `Individual registration` 或 `Solo signup` |
| 分队 / 正式分队 | Team formation | 报名截止后按 Steam 时长自动编队，按钮用 `Form teams` |
| 分队前检查 | Pre-formation check | 分队前的人数、预留核实与缺员检查 |
| 调整分队 | Adjust formation | 确认初始五人前的成员微调 |
| 预留席位 | Reserved slot | 队长报名占位但尚未对应真人账号的位置 |
| 核实预留（认领 / 释放） | Review reservation (`Claim` / `Release`) | 截止后由管理员按原预留 Steam 认领绑定或释放为空位 |
| 初始五人（本届初始五人） | Initial Roster | 某届最终确认的最初 5 名主力，确认后只读、作资格基准（`Confirmed` / `Pending confirmation`） |
| 确认初始五人 | Confirm Initial Roster | 将分队结果固定为本届初始五人 |
| 当前阵容（本届当前阵容） | Current Roster | 参赛队当前的 5 人合法阵容，需至少保留 3 名 `Initial Roster` 成员 |
| 候补 | Reserve (`Reserve pool` / `Unassigned reserve`) | 候补池或替补资格本身；独立候补标为 `Independent reserve` |
| 替补 | Substitute (`Sub`) | 某队实际分配的替补席位（`Substitute slot`）或换入上场的替补选手（`Substituted in` / `Subbed out`） |
| 赛前换人 | Pre-match roster change | 比赛开始前在 `Current Roster` 内用已获本队替补席的选手替换原队员 |
| 归档队伍 | Archive team (`Archived`) | 终止该参赛队在本届继续参赛/建场 |
| 名单版本（冲突校验） | Roster revision (`Revision N`) | 工作台防多人并发覆盖的版本标记 |
| 本场阵容 | Match Roster | 单场比赛独立记录的双方五人出场名单 |
| 本场阵容冻结 / 确认冻结 | Lock Match Roster (`Roster locked` / `Unlocked`) | 锁定本场双方十人快照以便进入 Map Veto；界面须明确注记“仅记录参赛名单，不代表选手已到场或比赛已开打” |

---

## 二、CS2 比赛、BP 与运营术语

| 中文概念 | 标准英文 | 使用场景与说明 |
|---|---|---|
| 比赛 | Match | 列表/标题用 `Matches` / `Match` |
| 对阵 | Matchup | 赛前对阵双方与交锋展示 |
| 赛果 | Results | 已完成比赛的结果列表与详情 |
| 赛制（BO 格式） | Format (`BO1` / `BO3` / `BO5`) | 标签用 `BO1 (Best of 1)` / `BO3 (Best of 3)` / `BO5 (Best of 5)` |
| 地图 BP / 在线 BP | Map Veto / Online Veto | 全站统一用 **Veto / Map Veto** 替代中式英语 `BP`（兼容旧测试断言的保留项见第六节） |
| BP 房间 | Veto Room | 在线选图房间 |
| BP 共享口令 | Shared veto passcode | 队长或参赛队员验证进入操作席的口令 |
| 选图 / 禁图 / 决胜图 | Pick / Ban / Decider | 地图卡片与 Veto 步骤标签 |
| 选边 | Side selection | 选择 `CT side` 或 `T side` 起始阵营 |
| 先手 / 后手 | First / Second | Roll 胜方选择先或后 Ban/Pick |
| 拼刀局 | Knife round | 决定起始阵营 |
| 直播中 / 未开始 / 已结束 / 已取消 | Live / Upcoming / Completed / Cancelled | 全站比赛状态统一使用此 4 个标准状态（拼写统一 `Cancelled`） |
| 历史赛事 / 已归档赛事 | Archive / Archived events | 导航筛选简写可用 `Archived`；标题与空状态用 `Archived events` |
| 正式赛果 | Official Result | 经管理员或导播确认的正式结算赛果 |
| 弃权 / 直接判负 | Forfeit / Walkover | 赛中退赛或判负结果 |
| 技术暂停 / 战术暂停 | Technical timeout / Tactical timeout | 赛事直播与时间线事件 |
| 技术重赛 | Technical rematch | 因服务器或技术故障取消原开局并重新开打 |
| 实际开局 | Map run / Match live run | 对应单张赛图的实际开启场次（`active` / `closed` / `void`） |
| 赛前授权开打 | Start authorization | 管理员授权本场/本图开赛 |
| 数据直播 / 比分播报 | Scorebot | 前台比赛实时记分板面板 |
| 导播 / 观战账号 | Director / Observer | 现场数据推送与观战采集来源 |
| 比赛录像 | Demo (`.dem`) | 统一大写 `Demo`（文件名后缀 `.dem`，小写复数可用 `demos`） |
| 对阵图 / 签表 | Bracket (`Upper bracket` / `Lower bracket`) | 淘汰赛/双败/瑞士制签表（Swiss pools: `0-0 pool` 等） |
| 赛前预测 / 竞猜 | Pre-match prediction (`Predictions`) | 公开预测榜单、赛前投票与排行榜 |
| 测试模式 / 测试比赛 | Test mode (`Test`) | 后台测试用空场标记，与实验性功能徽标 `Beta` 明确区分 |

---

## 三、CS2 数据统计与荣誉术语

全站沿用 HLTV / CS2 社区标准大写与缩写，**在中文与英文模式下均保持缩写原文**：

| 指标 / 荣誉 | 标准英文写法 | 中文界面保留说明 |
|---|---|---|
| Rating / Rating 2.0 | `Rating` / `Rating 2.0` | 表格列头可用 `RATING` / `Rating`（保留原页面大写节奏） |
| 影响力 | `Impact` | 卡片简写允许 `IMP` |
| 每回合伤害 | `ADR` (`Damage / round`) | — |
| KAST | `KAST` / `KAST%` | — |
| 击杀-死亡 / 击杀死亡比 / 净胜 | `K-D` / `K/D` / `K-D Diff` | — |
| 爆头率 | `HS%` (`Headshot %`) | — |
| 胜负贡献值 | `RWS` | — |
| 首杀 / 首死 / 开局对枪 | `Opening kills` / `Opening deaths` / `Opening attempts` | 表头简写 `FK`；`Opening success` 为开局胜率 |
| 补枪 / 被补枪 | `Trade kills / round` / `Traded deaths / round` / `Traded deaths %` | — |
| 最多闪白（致盲敌人） | `Most enemies flashed` / `Enemies flashed / round` / `Opp. flashed` | **禁止**写成 `Most flashed`（易误解为自己被白最多） |
| 闪光命中率 / 闪光助攻 | `Flash success` / `Flash assists` | — |
| 残局 / 残局获胜 | `Clutches` (`1vX`) / `Clutches won` / `Clutch pts / round` | — |
| 回合存活率估算 | `Est. survived rounds` | 不用 `proxy` 等生硬学术词 |
| 赛事荣誉 | `MVP` / `EVP` / `Champion` / `Top 10` | 全站荣誉榜统一用 `Awards` |

---

## 四、同词不同境区分速查表

1. **「候补」vs「替补」**：`候补`（资格、待分配名单）一律译作 **Reserve**；`替补`（已授予某队的替补席或换入阵容的队员）一律译作 **Substitute**。
2. **「初始五人 / 首五已确认」vs「本场阵容已冻结」**：后台后端字段里都有“锁定/冻结”概念，界面严格区分——赛事名单侧译作 **Initial Roster confirmed / pending**，单场比赛侧译作 **Match roster locked / unlocked**（不混用两个 `Frozen` / `Locked`）。
3. **「测试」徽标 vs「测试」功能**：比赛列表里的 `<span class="test-badge">测试</span>` 译作 **Test**（测试场次）；比赛统计「经济」标签页上的 `测试` 译作 **Beta**（测试版功能）。
4. **「数据看板」vs「工作台」**：前台全站数据分析中心 `/dashboard` 用 **Dashboard**；后台管理首页 `/admin/` 用 **Overview**（避免与前台 Dashboard 混淆；内部区块保留兼容现有测试的 `Workspace` 仅按实际引用处理）。
5. **「个人主页」vs「账号资料」vs「群昵称」**：统一用 **Profile**（个人主页）、**Account details**（账号资料）、**Group nickname**（不再混用 `Group username` 与 `Group nickname`）。
6. **「绑定 Steam」vs「已关联账号」**：面向用户操作优先使用 **Link Steam** / **Linked Steam account**（仅在必须保留既有技术语境时保留 `Bind` 说明）。
7. **美式英语拼写与大小写**：正文与提示统一美式拼写（`centered`、`unrecognized`、`customizable`，不使用 `centred`、`unrecognised`）；界面标签、按钮、状态采用 **Sentence case**（首词首字母大写，专有名词与 CS2 缩写例外），按钮短促有力，不使用冗余完整句。

---

## 五、不予翻译的动态与专有内容

凡以下内容均必须在模板或前端脚本中加 `data-i18n-ignore`（或置于忽略选择器内），在英文模式下**保持用户输入原文**：

- 选手昵称、群内昵称、Steam 用户名与历史昵称
- 战队名称、俱乐部名称、临时队名与队标字母缩写
- CS2 官方地图英文原名（`Mirage`、`Dust2`、`Inferno`、`Nuke`、`Ancient`、`Anubis`、`Overpass`、`Vertigo`、`Train`、`Cache` —— 且中文模式下不得将普通英文误回译为中文地图名）
- 管理员与用户填写的赛事名称、新闻标题/摘要/正文、帖子/评论内容、处理/拒绝/调整/归档理由
- URL 路径、Steam64 ID、连接指令、数据库与 JSON 字段名

---

## 六、与既有自动化测试约定的兼容性说明

为保护仓库现有单元测试与 E2E 回归（见 `tests/e2e/admin-i18n.spec.js`、`dot-followup.spec.js`、`frontend-smoke.spec.js`、`frontend-polish.spec.js`、`tests/test_stats_ui_regressions.py`），下列既有译文继续锁定保留，不作破坏性更名：

- `'出场阵容'` → `'Lineups'`
- `'赛事运营'` → `'Tournament operations'`
- `'进行中与即将开始'` → `'Live and upcoming'`
- `'开始时间'` → `'Start date and time'`
- `'当前设定：未设置'` / 带原因的 `Match completed; N new Game Log entries saved`、`Stats save failed: ...`、`Match save failed: ...`、`Delete event "..."?` 等精确回归锚点字符串。
