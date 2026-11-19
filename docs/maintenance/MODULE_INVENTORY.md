# 全站模块地图

范围是原 Flask 网站、后台、工作进程以及导播/HUD/中继与网站的交界。归档、演练源码和安装包不是第二套线上系统。入口由 [app.py](../../app.py)、[后台注册](../../blueprints/admin.py) 和 [web_app.py](../../web_app.py) 确认。下表的“负责”指谁决定事实，不是建议把页面按表拆开。

| 业务 | 实际入口 / 数据与下游 | 所有权与拆分判断 |
|---|---|---|
| 账号、审核、权限 | `routes/auth.py`、`blueprints/admin_core.py`、`utils/web_helpers.py`；账号、管理员、校验挑战、会话 | 账号不等于选手；Steam 登录、邮箱验证和审核不能互代。公开访问与个人/管理员/机器写入分开。 |
| 选手、长期队、私人备注 | `admin_catalog.py`、`routes/players.py`、`player_service.py`、`player_remark_service.py`；当前队籍、曾用名、档案和按阅读者生效的备注 | 后台和个人资料会改同一身份；并档牵涉出场、积分以外的个人记录和荣誉，不能当普通改名。转队不改历史出场。搜索、比赛、排名均消费身份。 |
| 赛事、报名、候补 | `routes/events.py`、`admin_events.py`、`site_core/events/`、`steam_playtime_service.py`；赛事、报名组、本届参赛方、初始阵容和换人 | 新管理按届启用，旧届保留旧入口。`entrant_slice/` 是独立演练，不是网站里的另一名写入者。截止由同一个业务命令办理，不能等用户打开网页。 |
| 比赛、签表、阵容、选图 | `admin_matches.py`、`bracket_service.py`、`routes/bp.py`、`utils/bp_manager.py`、`site_core/matches/{participants,maps,bracket_display}.py` | 本届参赛方不必有长期队号。本场双方、确认名单和排图供导播/现场使用；BP 选边不交换赛程双方。晋级须和系列赛结算一起提交。 |
| 开局、现场、机器接入 | `routes/{live,live_ingest,broadcast}.py`、`utils/live_poller.py`、`site_core/matches/{operations,live,live_sources,live_results}.py` | 分开最新画面、实际出场和正式图分。普通 GSI、指定场导播、GOTV、中断重连不是四个能任意改赛果的入口。旧届仍有独立兼容写法。 |
| Demo、人工统计、改判 | `match_operation_demos.py`、`demo_{storage,analysis,adoption}.py`、`demo_service.py`、`manual_stats_service.py`、`site_core/matches/results.py` | 分开原件、解析、采纳、正式选局；同一赛图可有多次开局。旧版 Demo 可联动比分，托管路径不重用该写法。 |
| 统计、队榜、对比、看板 | `matches/statistics.py`、`utils/{stats_storage,side_stats}.py`、`performance_service.py`、`routes/{stats,players,matches,events}.py`、`public_data_service.py` | 个人正式图数、按边分母和当前修订应由统计负责。公开查询拼接新旧有效来源；不能在海报/页面重新用全图回合填补分边缺项。 |
| 竞猜与积分 | 比赛详情投票、`routes/stats.py` 的预测页、`routes/front_api.py`、旧后台与托管系列结算 | 写票、逐票积分及排行榜共用规则。旧赛有效完赛查询与托管赛正式结算依据不同；不能把两份积分再加一次。 |
| 已授荣誉 | 原赛事编辑、托管赛事的冠军与个人奖接口、后台年度 Top 10、`champion_service.py`、`player_awards_service.py`、`award_service.py`、荣誉页和海报 | MVP/EVP 是已授记录，年度名次不是实时 Rating。冠军成员有单独证据；不能按当前俱乐部成员倒推历史。接口和请求字段见[目标架构](TARGET_ARCHITECTURE.md)。 |
| 新闻和站内引用 | `admin_news.py`、`routes/news.py`、`news_references.py`、`match_assets.py` | 文章、跳转、站内引用和比赛战报；保留文章旧 ID、链接与阅读权限。引用比赛不获得修改比赛的权力。 |
| 社区、通知与反馈 | `routes/{comments,forum,notifications,feedback}.py`、后台反馈、文章/比赛删除 | 新闻/比赛评论与论坛回复共用存储但可见性、计数和链接不同；写回复与发通知应同成同败。已读和私人备注都按当前用户隔离。 |
| 游戏 | `routes/{games,guess_player,map_quiz,player_bingo}.py`，对应的三个 `services/*_service.py` | 每日、练习、多人房间各有作答和权限规则；游戏职业选手题库不是本站账号，游戏连胜不是比赛竞猜积分。可独立于赛务更改。 |
| 站内发现、首页和公开 JSON | `routes/{search,home,front_api,sitemap}.py`、`home_service.py`、`public_data_service.py`、SEO 和历史 slug | 搜索页与即时提示曾重复查五类实体；站内发现应只读。特殊赛事的可见性不能由搜索、新闻链接或缓存扩张。公开展示顺序不改固定双方。 |
| 网站界面、后台与外部客户端 | `templates/`、`static/{js,css}/`、`docs/localization/`；`jts-hud-manager/`、`broadcast_hud/`、`gotv_relay/` | Jinja 首屏和局部 JSON 并存。后台是业务入口而不是规则所有者。前端实现由站主另行处理；本轮保护原输出及中英文术语，不修改客户端。 |
| 数据库、后台和文件 | `models.py` 安装/升级表，`live_worker.py`、`utils/live_poller.py` 定时作业；`services/backup_service.py`、`scripts/restore_site.py`、上传与私有 Demo 存储 | 区分业务连接、只读备份快照、缓存及原件；文件不随 SQL 回滚。Web 请求不新起生产 worker；快照和恢复只在目标临时目录演练。 |

**不能分开切的三处：** 确认本届参赛方与初始五人；正式选局与统计有效性；系列结算、签表晋级与竞猜重算。**可独立交付：** 社区互动、已授个人奖、公开搜索查询、游戏作答、连接和任务生命周期。实际接入及验收范围以[本地进度](PROGRESS.md)为准，不以目录是否存在判断。

## 具体维护入口

| 要改的事实 | 应找的实际源码 | 容易碰错的另一处 |
|---|---|---|
| 谁拥有这个 Steam 身份、哪些昵称能公开 | [账号写入与认领](../../site_core/accounts.py)、[公开选手身份](../../site_core/player_directory.py)、[搜索](../../services/search_service.py) | 占位账号不能取代正式账号；私人备注不写回公共档案 |
| 队员是否处于本场当前一侧 | [导播名单投影](../../services/broadcast_roster_service.py)、[开局身份及 GSI 归队](../../services/live_roster_service.py) | 当前长期队籍、画面当前 CT/T、冻结五人和开局实际出场不是同一张名单 |
| 准备投票或给投票结分 | [竞猜](../../site_core/predictions.py)，由[结果结算](../../site_core/matches/results.py)传入同一连接 | 一票在 `match_votes` 中，托管赛还有结算依据；页面排序和最终得分不能由展示层写回 |
| 发布奖项或查询榜单 | [赛事个人奖与年度榜](../../services/player_awards_service.py)、[托管冠军](../../site_core/awards/championship.py)、[新旧冠军共读](../../services/champion_service.py) | `yearly_top_players` 是人工年榜，`player_medals` 要区分单场/赛事；`teams.id` 不是临时队编号 |
| 手枪局、武器、分边排行榜 | [旧赛证据读取](../../services/public_stat_evidence.py)、[托管统计](../../site_core/matches/statistics.py)、[有效统计来源](../../utils/stats_storage.py) | `match_kill_events` 和磁盘旧缓存没有托管开局身份，不能补进作废局或冒充正式证据 |
| 评论与通知、游戏记录 | [社区](../../site_core/community.py)、[每日游戏日与连胜](../../site_core/games.py) | 新闻与论坛都写 `comments`，但论坛是平铺回帖；三种小游戏分别决定胜负，积分不进入比赛竞猜 |
| 连接、截止任务、备份 | [连接与事务](../../site_core/database.py)、[工作进程](../../live_worker.py)、[备份](../../services/backup_service.py)、[恢复](../../scripts/restore_site.py) | 读取静态文件不等于允许下载 Demo；只恢复数据库不能冒充恢复了整站原件 |

**有意保留的旧实现。** 赛事报名、阵容和选图已经有真实宿主测试，不把 `entrant_slice` 的练习实现复制回站点；非托管历史届仍由旧赛务写。新闻编辑、引用和 SEO 各有实际消费者，保留现有链接，不改编辑器。地图题库、多人房间、CSDA 解析器和 Steam 对接继续使用现有实现；本轮整合它们输出数据的地方，而不重新实现外部协议。
