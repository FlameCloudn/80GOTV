# 网站源码导航

这是一个 Flask 网站，不是多个后端服务。开发启动是 [app.py](../app.py)，它装入页面路由并注册后台；[web_app.py](../web_app.py) 建立 Flask 应用、模板环境和公共请求行为。线上 [wsgi.py](../wsgi.py) 只提供网页，周期任务由 [live_worker.py](../live_worker.py) 另起进程。不要在网页进程再启动一份轮询。

## 按业务找代码

| 用户在做什么 | 请求交给谁 | 谁负责这份数据 | 页面、交互或回归入口 |
|---|---|---|---|
| 建赛事、报名、分队、换人 | [公开赛事](../routes/events.py)、[后台赛事](../blueprints/admin_events.py) | [本届参赛身份与名单](../site_core/events/)；长期俱乐部和选手不是本届阵容 | [名单工作台](../templates/admin/event_roster.html) → [交互](../static/js/admin_event_roster.js)；[赛前整链](../tests/test_host_prematch_chain.py) |
| 建比赛、确认双方、冻结阵容、选图 | [后台比赛](../blueprints/admin_matches.py)、[BP 房间](../routes/bp.py) | [本场双方](../site_core/matches/participants.py)、[排图](../site_core/matches/maps.py)，旧选图行为在 [bp_manager](../utils/bp_manager.py) | [比赛表单](../templates/admin/matches_form.html)、[BP 页](../templates/bp_room.html)；[BP 测试](../tests/test_host_bp_maps.py) |
| 开局、技术重赛、审定结果、晋级 | [赛务操作](../blueprints/match_operations.py)，沿用后台 Blueprint | [实际局次与出场](../site_core/matches/operations.py)、[正式结果](../site_core/matches/results.py)、[竞猜积分](../site_core/predictions.py) | [运营页](../templates/admin/match_operations.html) → [运营脚本](../static/js/admin_match_operations.js)；[运营整链](../tests/test_host_operations_chain.py) |
| 上传、解析、采纳 Demo | [托管赛 Demo API](../blueprints/match_operation_demos.py)、[历史附件](../routes/match_assets.py) | 托管赛的[私有原件](../site_core/matches/demo_storage.py)、[解析](../site_core/matches/demo_analysis.py)、[采纳](../site_core/matches/demo_adoption.py)分开；[旧赛事导入](../services/demo_service.py)仍兼容 | 同一运营页；[托管 Demo 测试](../tests/test_host_operations_demo.py) |
| 导播取数、推送现场、观众看直播 | [导播读取](../routes/broadcast.py)、[接收现场](../routes/live_ingest.py)、[直播页面](../routes/live.py) | [现场来源](../site_core/matches/live_sources.py)、[现场状态](../site_core/matches/live.py)；直播画面不等于正式赛果 | [数据直播模板](../templates/match_data_live.html)、[工具接入表](../integrations/README.md)、[导播兼容用例](../tests/test_host_director_consumer.py) |
| 查比赛、选手、排名、冠军 | [比赛](../routes/matches.py)、[选手](../routes/players.py)、[统计](../routes/stats.py) | [托管统计](../site_core/matches/statistics.py)、[历史统计存取](../utils/stats_storage.py)、[表现汇总](../services/performance_service.py)、[冠军](../site_core/awards/championship.py) | [比赛详情](../templates/match_detail.html) → [统计切换](../static/js/match_stats_views.js)；[选手详情](../templates/player_detail.html) |
| 登录、审核、论坛、通知 | [账号](../routes/auth.py)、[论坛](../routes/forum.py)、[通知](../routes/notifications.py) | [账号与认领](../site_core/accounts.py)、[互动写入](../site_core/community.py)，私人备注另属[备注服务](../services/player_remark_service.py) | [登录](../templates/login.html)、[论坛模板](../templates/forum/)、[权限回归](../tests/test_account_authorization.py) |
| 查新闻、玩小游戏、首页或公开 JSON | [新闻](../routes/news.py)、[游戏](../routes/games.py)、[前台 API](../routes/front_api.py) | [公开查询](../services/public_data_service.py)、[站内搜索](../services/search_service.py)、[游戏规则](../site_core/games.py)与各游戏服务 | [首页](../templates/index.html)、[前台请求脚本](../static/js/front_api.js)、[公开流程测试](../tests/test_public_backend_workflow.py) |

## 各层边界

- **地址和权限：** `routes/` 不只放公开页面，也有机器接口；`blueprints/` 负责后台和受保护的 Demo 入口。现有代码同时用两种 Flask 注册方式，迁移没有改变网址或函数导入契约。查新地址：`python -m flask --app app routes`。
- **业务和数据库：** [models.py](../models.py) 是旧表、升级和兼容入口，不是所有业务的归宿。[site_core/database.py](../site_core/database.py) 管连接，[site_core/host.py](../site_core/host.py) 管托管写操作；各业务目录的 SQL 与消费它的代码放一起。[迁移记录](../MIGRATIONS.md)记录数据结构变化。`services/` 中有明确归属的业务继续留在原处；跨页面通用的计算和旧格式转换主要在 `utils/`。
- **页面和资源：** 一张页面先从路由中的 `render_template` 找模板，再找模板引用的 JS。[公共页面骨架](../templates/base.html)、[样式入口](../static/css/app.css)、[页面样式](../static/css/pages/)、[英文词表](localization/ENGLISH_GLOSSARY.md)。网站前端不是 Node 单页应用；`resources/` 是地图、雷达等源素材，`static/` 有正式发布资源，也有不进 Git 的本地上传目录。
- **命令和外接程序：** [scripts/](../scripts/) 是网站维护、图片生成、备份与恢复；[integrations/](../integrations/) 是需要网站代码的采集端入口。不要把独立桌面客户端依赖加进网站。`entrant_slice/` 是可单独运行的 Slice 1 演练，不是线上写入入口。
- **测试：** [tests/](../tests/) 是 Python 回归，[tests/e2e/](../tests/e2e/) 是普通浏览器流程，[tests/acceptance/](../tests/acceptance/) 是各轮专用验收驱动，[tests/fixtures/](../tests/fixtures/) 是刻意保留的测试输入。不要把浏览器用户目录、数据库或截图当成测试源码。
- **配置与发布：** [config.py](../config.py)、[示例环境变量](../.env.example)、[Python 依赖](../requirements.txt)、[测试依赖](../requirements-test.txt)、[Node 锁文件](../package-lock.json)、[CI](../.github/workflows/ci.yml)、[Linux 部署](../deploy/README.md)。不更改服务器路径；不向服务器复制外层工作区。

涉及跨业务写入时，看[全站业务地图](maintenance/MODULE_INVENTORY.md)与[数据归属和兼容约定](maintenance/TARGET_ARCHITECTURE.md)。这两份资料里标记的历史交付及截图链接需要配套工作区；启动、构建和标准测试不需要它。
