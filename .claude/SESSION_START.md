# 每次打开项目的起点

## 当前状态
- 项目: 80GOTV CS2电竞赛事网站，Flask+SQLite+Jinja2
- 启动: `python app.py` → http://127.0.0.1:5000
- 管理员: admin / test123456
- Kimi API: 已配置，余额 58.94 元
- 测试: 39/39 全部通过
- 数据库: 25 表，数据完整

## 环境注意
- `python` 不是 `python3`
- `pip` 不是 `pip3`
- 不开梯子
- Edit 工具易失败 → 用 Write 整篇重写
- Kimi API: api.moonshot.cn（国内）

## 快速命令
- 体检: `python .claude/scripts/doctor.py`
- 测试: `python .claude/scripts/run_tests.py`
- 备份: `python .claude/scripts/backup.py`
- 浏览器预览: `python .claude/scripts/live_preview.py`
- 查数据库: `python .claude/scripts/db_query.py "SQL"`
- 提交前检查: `python .claude/scripts/release_checklist.py`

## 脚本全在 .claude/scripts/ 下，命令速查 .claude/CHEATSHEET.md
