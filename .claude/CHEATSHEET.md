# 命令速查表

> 自动生成于 2026-06-15 21:38 | 运行 `python gen_cheatsheet.py` 刷新

共 42 个工具脚本

## 🔍 检查与诊断

| 脚本文件 | 用途 | 运行命令 |
|----------|------|----------|
| `check_balance.py` | 查询 Kimi API 余额 | `python check_balance.py` |
| `check_deps.py` | 依赖检查工具 | `python check_deps.py` |
| `check_template_vars.py` | 检查模板中可能的变量问题 | `python check_template_vars.py` |
| `check_uncommitted.py` | 未提交提醒工具 | `python check_uncommitted.py` |
| `doctor.py` | 一键体检：检查网站各项指标，出具健康报告 | `python doctor.py` |
| `env_check.py` | 环境检查工具 | `python env_check.py` |
| `find_dead_css.py` | 扫描未使用的CSS class | `python find_dead_css.py` |
| `find_dead_links.py` | 检查模板中内部链接的有效性 | `python find_dead_links.py` |
| `find_duplicates.py` | 重复代码检测工具 | `python find_duplicates.py` |
| `find_todos.py` | TODO 扫描工具 | `python find_todos.py` |
| `release_checklist.py` | 发布检查清单 — 依次运行所有检查脚本，综合判断是否可以发布 | `python release_checklist.py` |
| `secret_scan.py` | 敏感信息检查 — 扫描项目中疑似 API Key、密码、token 的泄露 | `python secret_scan.py` |
| `sql_audit.py` | SQL 注入风险扫描器 — 检查 routes/ 和 blueprints/ 下所有 .py 文件， | `python sql_audit.py` |
| `type_check.py` | 类型检查：跑 pyright 检查项目 Python 代码 | `python type_check.py` |
| `verify_changes.py` | 改完代码后快速验证页面是否正常 | `python verify_changes.py` |
| `visual_check.py` | 调用 Kimi K2.6 视觉能力分析网页截图。前置：pip install playwright openai | `python visual_check.py` |

## 🛠️  开发工具

| 脚本文件 | 用途 | 运行命令 |
|----------|------|----------|
| `add_lazy_loading.py` | 给 templates/ 下所有 HTML 文件的 <img> 标签添加 loading="lazy" 属性 | `python add_lazy_loading.py` |
| `browser.py` | 浏览器操控工具。自动填表、点击、截图、走流程 | `python browser.py` |
| `cache_utils.py` | 内存缓存工具 — 用字典实现的简单缓存，不依赖第三方库 | `python cache_utils.py` |
| `gen_cheatsheet.py` | 命令速查表 — 扫描 .claude/scripts/ 下所有 .py 脚本，提取说明，生成 Markdown 表格 | `python gen_cheatsheet.py` |
| `gen_route_docs.py` | 自动生成路由文档 | `python gen_route_docs.py` |
| `gen_scaffold.py` | 代码片段生成器 | `python gen_scaffold.py` |
| `live_preview.py` | 自动刷新浏览器。改代码 → 浏览器自动刷，不用按 F5 | `python live_preview.py` |
| `toggle_hooks.py` | Git Hooks 开关工具 | `python toggle_hooks.py` |

## 📊 分析与报告

| 脚本文件 | 用途 | 运行命令 |
|----------|------|----------|
| `file_heatmap.py` | 文件热度分析工具 | `python file_heatmap.py` |
| `project_stats.py` | 项目指标看板 —— 统计代码、数据库、测试概况 | `python project_stats.py` |

| `weekly_report.py` | 周报工具 | `python weekly_report.py` |

## 💾 备份与恢复

| 脚本文件 | 用途 | 运行命令 |
|----------|------|----------|
| `auto_backup.py` | 每日自动备份 — 检查今天是否已备份，没有则自动备份，保留最近7天。适合放计划任务 | `python auto_backup.py` |
| `backup.py` | 一键备份：数据库 + 头像 + 配置文件 | `python backup.py` |
| `db_query.py` | 数据库查询工具 | `python db_query.py` |
| `rollback.py` | 改前备份工具 | `python rollback.py` |

## 🧪 测试与验证

| 脚本文件 | 用途 | 运行命令 |
|----------|------|----------|
| `api_bench.py` | API 性能测试工具 | `python api_bench.py` |
| `run_tests.py` | 自动化测试 | `python run_tests.py` |
| `visual_compare.py` | 视觉对比 + 参考图分析 | `python visual_compare.py` |

## 📋 其他

| 脚本文件 | 用途 | 运行命令 |
|----------|------|----------|
| `asset_sizes.py` | 静态资源体积 — 列出 static/ 下所有资源文件大小，按大小降序，标注大文件 | `python asset_sizes.py` |
| `clean_imports.py` | 未使用import清理 — 扫描 routes/ blueprints/ 下 .py 文件，找出 import 了但未使... | `python clean_imports.py` |
| `dev_reset.py` | 一键重置开发环境 — 备份数据库 → 重建 → 重启Flask → 验证 | `python dev_reset.py` |
| `dev_summary.py` | 变更摘要工具 | `python dev_summary.py` |
| `log_analyzer.py` | 日志分析器 — 分析 flask.log 中的错误趋势和重复错误 | `python log_analyzer.py` |
| `route_conflicts.py` | 路由冲突检测 — 检查 Flask 应用中是否有两个路由指向同一路径和方法 | `python route_conflicts.py` |
| `template_tree.py` | 模板继承图 — 分析 templates/ 下所有 .html 的 extends/include 关系，输出树状结构 | `python template_tree.py` |
