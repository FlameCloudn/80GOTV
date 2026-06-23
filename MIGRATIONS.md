# 数据库迁移日志

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

## 补充迁移（在 migrations 列表外执行）

| # | SQL 语句 | 状态 |
|---|----------|------|
| 29 | 旧赛事无简称时补 `EVENT_` + id | 已完成 |
| 30 | `event_registrations` 添加 `creator_user_id` 列，从 `captain_user_id` 同步数据 | 已完成 |
| 31 | 旧版 Demo 自动创建的账号（密码为 `123456`）标记为待接管 | 已完成 |

## 说明

- 所有迁移在 `init_tables()` 函数中执行，应用每次启动都会尝试运行
- 已存在的列会被跳过（检测 "duplicate column" 和 "already exists" 错误）
- 后续新增迁移请在 `migrations` 列表末尾追加，然后更新本文件
