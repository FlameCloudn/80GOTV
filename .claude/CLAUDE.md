在终端中的一切输出用中文

我是一个高一学生，不是专业程序员。别假设我懂任何概念。你做我跑，用我能看懂的步骤告诉我怎么操作。

\# 我需要你做的事
\- 别用术语，必须用时先解释
\- 别讲原理，我问你再讲

\# 用户偏好
\- 界面风格: 简洁、电竞风、暗色系
\- 代码风格: 中文注释、函数不超过50行、变量名有意义
\- 沟通风格: 不讲术语、不解释原理、步骤化操作

\# 项目信息
Flask + SQLite/Turso CS2电竞赛事网站 80GOTV
- 启动: `python app.py` (端口5000)
- 管理后台: /admin/login (admin/test123456)
- Python: `python` 不是 `python3`, `pip` 不是 `pip3`
- 不开梯子

\# 代码风格
- 路由: routes/ (前台) blueprints/ (后台)
- 数据库: `from models import query_db, execute_db` 或 `with db() as conn:`
- 模板: Jinja2, 继承 base.html, 过滤器 |cn_time |rating_class
- 服务层: services/
- Edit 易失败 → 用 Write 整篇重写

\# 核心脚本 (.claude/scripts/)
| 命令 | 用途 |
|------|------|
| doctor.py | 一键体检19项(服务/DB/页面/登录/日志/备份/余额) |
| run_tests.py | 自动化测试39项 |
| browser.py --flow full | 浏览器自动操控全流程 |
| live_preview.py | 改代码浏览器自动刷新 |
| visual_check.py [url] | 截图发给Kimi看效果 |
| visual_compare.py --reference 图 | Kimi分析参考图 |
| db_query.py "SQL" | 直接查数据库 |
| backup.py | 一键备份 |
| verify_changes.py | 10页验证 |
| check_balance.py | Kimi余额 |
| release_checklist.py | 发布前检查 |
| check_deps.py | 依赖更新检查 |
| secret_scan.py | 密钥泄露检查 |
| env_check.py | 环境变量检查 |


\# 安全工具
- ruff (格式化+lint) + pyright (类型检查) + bandit (安全) + vulture (死代码) + pip-audit (漏洞)

\# 提交前自动检查
ruff format → ruff check → pyright → 提醒跑doctor

\# 环境变量 (.env)
KIMI_API_KEY / ADMIN_USERNAME / ADMIN_PASSWORD / SECRET_KEY / GOTV_SECRET / TURSO_URL

\# 参考文档 (.claude/)
PATTERNS.md (代码模式) / COMMON_ERRORS.md (常见错误) / NAMING.md (命名) / COMMENT_GUIDE.md (注释) / API_CONTRACT.md (接口) / DECISIONS.md (决策) / CHEATSHEET.md (命令速查) / SESSION_START.md (开局读)
