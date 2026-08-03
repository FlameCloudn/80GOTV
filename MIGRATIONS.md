# 数据库升级日志

数据库现在使用 `schema_migrations` 表记录已经完成的版本。版本 1 包含下方列出的历史升级；完成后不会在每次启动时重新执行改列、重算选手表现或清理旧直播密钥。

运行升级：

```bash
python scripts/migrate_database.py
```

只检查服务器是否已经升级：

```bash
python scripts/migrate_database.py --check
```

以后增加数据库字段时必须新增版本，不能修改已经发布的旧版本。关键步骤失败会停止启动，不再只记录警告后继续。

> 从 `models.py` 的 migrations 列表提取，按代码中出现的先后顺序排列。

| # | SQL 语句 | 状态 |
|---|----------|------|
| 1 | `ALTER TABLE match_stats ADD COLUMN multi1k INTEGER DEFAULT 0` | 已完成 |
| 2 | `ALTER TABLE match_stats ADD COLUMN multi2k INTEGER DEFAULT 0` | 已完成 |
| 3 | `ALTER TABLE match_stats ADD COLUMN multi3k INTEGER DEFAULT 0` | 已完成 |
| 4 | `ALTER TABLE match_stats ADD COLUMN multi4k INTEGER DEFAULT 0` | 已完成 |
| 5 | `ALTER TABLE match_stats ADD COLUMN multi5k INTEGER DEFAULT 0` | 已完成 |
| 6 | `ALTER TABLE match_stats ADD COLUMN first_kills INTEGER DEFAULT 0` | 已完成 |
| 7 | `ALTER TABLE match_stats ADD COLUMN first_deaths INTEGER DEFAULT 0` | 已完成 |
| 8 | `ALTER TABLE match_stats ADD COLUMN mvp_count INTEGER DEFAULT 0` | 已完成 |
| 9 | `ALTER TABLE match_stats ADD COLUMN utility_damage REAL DEFAULT 0` | 已完成 |
| 10 | `ALTER TABLE match_stats ADD COLUMN enemies_flashed INTEGER DEFAULT 0` | 已完成 |
| 11 | `ALTER TABLE match_stats ADD COLUMN flash_count INTEGER DEFAULT 0` | 已完成 |
| 12 | `ALTER TABLE match_stats ADD COLUMN he_count INTEGER DEFAULT 0` | 已完成 |
| 13 | `ALTER TABLE match_stats ADD COLUMN smoke_count INTEGER DEFAULT 0` | 已完成 |
| 14 | `ALTER TABLE match_stats ADD COLUMN molotov_count INTEGER DEFAULT 0` | 已完成 |
| 15 | `ALTER TABLE match_stats ADD COLUMN trade_kills INTEGER DEFAULT 0` | 已完成 |
| 16 | `ALTER TABLE match_stats ADD COLUMN trade_deaths INTEGER DEFAULT 0` | 已完成 |
| 17 | `ALTER TABLE match_stats ADD COLUMN bomb_plants INTEGER DEFAULT 0` | 已完成 |
| 18 | `ALTER TABLE match_stats ADD COLUMN bomb_defuses INTEGER DEFAULT 0` | 已完成 |
| 19 | `ALTER TABLE match_stats ADD COLUMN utility_damage_per_round REAL DEFAULT 0` | 已完成 |
| 20 | `ALTER TABLE match_stats ADD COLUMN rounds_played INTEGER DEFAULT 0` | 已完成 |
| 21 | `ALTER TABLE match_stats ADD COLUMN damage_delta_per_round REAL DEFAULT 0` | 已完成 |
| 22 | `ALTER TABLE match_stats ADD COLUMN rws_basic REAL DEFAULT 0` | 已完成 |
| 23 | `ALTER TABLE matches ADD COLUMN stage TEXT` | 已完成 |
| 24 | `ALTER TABLE matches ADD COLUMN slug TEXT` | 已完成 |
| 25 | 自动生成 matches.slug（现有比赛的 URL 友好标识） | 已完成 |
| 26 | `ALTER TABLE events ADD COLUMN short_name TEXT` | 已完成 |
| 27 | `ALTER TABLE events ADD COLUMN registration_open INTEGER DEFAULT 0` | 已完成 |
| 28 | `ALTER TABLE users ADD COLUMN is_placeholder INTEGER DEFAULT 0` | 已完成 |
| 29 | `ALTER TABLE users ADD COLUMN is_cheater INTEGER DEFAULT 0` | 已完成 |

## 补充迁移（在 migrations 列表外执行）

| # | SQL 语句 | 状态 |
|---|----------|------|
| 30 | 旧赛事无简称时补 `EVENT_` + id | 已完成 |
| 31 | `event_registrations` 添加 `creator_user_id` 列，从 `captain_user_id` 同步数据 | 已完成 |
| 32 | 旧版 Demo 自动创建的账号（密码为 `123456`）标记为待接管 | 已完成 |
| 33 | `match_stats` 添加残局、闪光时长和闪光助攻字段 | 已完成 |
| 34 | 新建 `player_performance_summary`，持久保存选手全时段表现汇总 | 已完成 |
| 35 | 新建 `match_kill_events`，保存武器、击杀关系和回合信息 | 已完成 |
| 36 | 为比赛、统计、评论、报名和选手汇总补充组合索引 | 已完成 |

## 选手表现数据重建

部署本次迁移后运行一次：

```bash
/srv/80gotv/venv/bin/python /srv/80gotv/app/scripts/rebuild_performance_database.py
```

脚本会逐个读取现有 CSDA 缓存，把页面需要的残局、闪光、武器和击杀数据写入数据库。以后网页只查询数据库，不会在访客打开页面时临时解析大文件。脚本可以重复运行，不会重复插入击杀记录。

## 说明

- `init_tables()` 会先读取 `schema_migrations`；版本 1 已记录时只做轻量检查，不再重跑历史升级
- 第一次升级会在一个事务中完成；任何关键步骤失败都会回滚，且不会写入版本号
- 数据库版本高于当前代码时会拒绝启动，避免旧代码误用新结构
- `player_performance_summary` 会从 `match_stats` 自动更新；Demo 导入、GOTV 更新、手工修改和删除比赛后也会同步刷新
- 后续新增迁移必须提高版本号并追加新步骤，不能修改已经发布的版本
