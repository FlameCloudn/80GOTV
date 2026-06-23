# Bug 日志

记录每个修过的 bug，方便以后回顾。

## [2026-06-01] 数据库创建 demo_file 列时 crash
- 现象: 启动 app.py 时报错 `no such column: matches.demo_file`
- 原因: init_tables 里没有定义 demo_file 列，但代码里用到了
- 修复: 在 matches 表的 CREATE TABLE 里加上 demo_file TEXT 列
- 文件: models.py
