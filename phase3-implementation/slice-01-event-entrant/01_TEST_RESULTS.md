# 01 · 测试结果

**状态：本地隔离验证完成。** 以下数字分别记录，不把 HTTP 请求、旧合同组和新增测试重复相加。

## 改前基线

开始本切片前：分支 `main`，HEAD `c691791f86c32c04b1ca1a38da4f2fd2f7170a1a`；已有 37 个跟踪文件改动、19 项未跟踪归组（展开 132 个文件）、暂存 0。该记录是改前快照，不是当前 Git 状态。

已有网站选定基线 **305 项通过，0 失败、0 错误、0 跳过，218.560 秒**。测试使用隔离副本；它不是全站所有测试的数量，也不是新功能已通过的证明。

基线复跑入口，在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -B phase3-preparation/checks/run_legacy_baseline.py
```

## 本切片检查

| 范围 | 已有过程记录 | 最终结果 |
|---|---|---|
| 新增五个测试模块 | **28/28 通过，48.184 秒**：领域 14、事务 11、兼容 1、HTTP 全流程 1、命令行和数据库生命周期 1。0 失败、0 错误、0 跳过。 | 包含独立连接竞争和回滚。用例不按请求数或数据库操作数拆算。 |
| 旧页面和导播读取 | [兼容用例](../../tests/test_entrant_slice_compatibility.py) **1/1 通过**：使用真实旧 Flask 页面/JSON、导播原 TypeScript 读取代码及 Node SQLite。 | 已计入上述 28 项，不重复相加；不是装机导播。详见 [02](02_API_COMPATIBILITY_RESULTS.md)。 |
| 报名到确认的 HTTP 全流程 | [端到端用例](../../tests/test_entrant_slice_http.py) **1/1 通过**；Flask 测试客户端与独立时钟进程覆盖管理员登录、旧表单报名、无人访问时到期分队、确认/重复确认、旧页面和导播读取、拒绝路径及外键检查 0 项。 | 已计入上述 28 项；不是浏览器或装机导播实测。 |
| 真实本机服务冒烟 | 在全新隔离目录实际启动 `serve`，首个 HTTP 请求到来前自动分出两队；访问原 `/events/entrant-practice` 返回 200，页面包含正式队名。正常中断后预览和截止子进程均退出。 | 这是另一次本机操作检查，不计入上述 28 项，也不是公网联调。 |
| 数据库命令与重建 | [命令行用例](../../tests/test_entrant_slice_cli.py) **1/1 通过**，覆盖空库、重复迁移、真实写锁超时后的自动恢复、分队不重复、清理和重建。 | 已计入上述 28 项；`status` 读的是新模型，旧页面读取另由兼容和 HTTP 用例验证。见 [03](03_DATABASE_MIGRATION_RESULTS.md)。 |
| 305 项旧网站测试 | 改前 305/305，218.560 秒。 | 最终两处 Jinja 调整后，同一组 25 个模块 **305/305**，0 失败、0 错误、0 跳过，234.320 秒；旧断言未改。 |
| 旧网站及导播合同回放 | Flask **20/20 组、133 次测试客户端请求**；桌面原函数 **21/21 组**，其中 4 组使用 Flask 的真实回执。包含预期 500 的整笔回滚检查。 | 使用合成数据与本机测试环境，不等于装机导播或公网联调。 |
| 新旧测试混跑 | 定向混跑 **26/26**，由 1 项旧测试和 25 项新测试组成；pytest 同样 **26/26**。 | 不与 28 项或 305 项相加。 |
| 干净暂存代码复建 | 从基准提交和本次暂存内容导出到全新临时目录，使用项目 Python 环境和已有 TypeScript 依赖运行，**28/28 通过**；按仓库格式化后再次复建，最终为 **47.425 秒**，0 失败、0 错误、0 跳过。 | 未带入未暂存业务文件，也未读 `.env` 或历史数据；本次临时目录已删除。 |
| Ruff、Pyright 和 JavaScript 语法 | 对下面列出的切片代码、测试及检查脚本运行 Ruff、Pyright，均通过；Pyright 0 错误、0 警告。两个 `.cjs` 检查文件的语法检查通过。 | 范围不是旧站全库；完整命令见下方。 |
| 页面实际操作与截图 | 最终代码用真实浏览器分别检查桌面 **1440×900** 和手机 **360×780**，共 11 张截图；检查了原报名弹窗的键盘焦点和 Esc、首次独立候补报名成功、两队冻结后的展示及归档历史。没有横向溢出、控制台/页面错误、失败请求或外部请求。 | 截图位于 [本轮截图目录](../../output/ui-audit/entrant-slice-01/)；不等同于装机导播或线上操作。 |

截图：

- 报名页面：[桌面](../../output/ui-audit/entrant-slice-01/01-open-desktop.png)、[手机](../../output/ui-audit/entrant-slice-01/01-open-mobile.png)。
- 原报名弹窗：[桌面](../../output/ui-audit/entrant-slice-01/02-registration-dialog-desktop.png)、[手机](../../output/ui-audit/entrant-slice-01/02-registration-dialog-mobile.png)。
- [首次候补报名，手机](../../output/ui-audit/entrant-slice-01/03-first-reserve-mobile.png)。
- 截止后：[桌面](../../output/ui-audit/entrant-slice-01/04-cutoff-desktop.png)、[手机](../../output/ui-audit/entrant-slice-01/04-cutoff-mobile.png)。
- 两队确认后：[桌面](../../output/ui-audit/entrant-slice-01/05-confirmed-teams-desktop.png)、[手机](../../output/ui-audit/entrant-slice-01/05-confirmed-teams-mobile.png)。
- 归档历史：[桌面](../../output/ui-audit/entrant-slice-01/06-archived-roster-desktop.png)、[手机](../../output/ui-audit/entrant-slice-01/06-archived-roster-mobile.png)。

在项目根目录运行当前领域和事务用例：

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_entrant_slice_domain tests.test_entrant_slice_transactions -v
```

运行旧页面与导播组合兼容用例：

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_entrant_slice_compatibility -v
```

该用例会调用导播源码回放，不把每个请求分别算成一项测试。测试以隔离数据运行，不使用或替换生产数据库。

最终新增检查为 **14 个领域用例 + 11 个事务用例 + 1 个兼容组合用例 + 1 个 HTTP 全流程用例 + 1 个命令行用例**，共 28 项。旧合同回放属于另一组检查，不与这 28 项混加。

完整复跑 28 项：

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_entrant_slice_domain tests.test_entrant_slice_transactions tests.test_entrant_slice_compatibility tests.test_entrant_slice_http tests.test_entrant_slice_cli -v
```

运行独立 HTTP 全流程：

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_entrant_slice_http -v
```

最终静态和语法检查，均在项目根目录运行。本站虚拟环境用于运行网站和测试；本机的 Ruff 和 Pyright 安装在系统 Python，所以下面两条直接用 `python`：

```powershell
python -B -m ruff check --no-cache entrant_slice tests/entrant_slice_fixtures.py tests/test_entrant_slice_cli.py tests/test_entrant_slice_compatibility.py tests/test_entrant_slice_domain.py tests/test_entrant_slice_http.py tests/test_entrant_slice_transactions.py phase3-implementation/slice-01-event-entrant/checks
python -B -m pyright entrant_slice tests/entrant_slice_fixtures.py tests/test_entrant_slice_cli.py tests/test_entrant_slice_compatibility.py tests/test_entrant_slice_domain.py tests/test_entrant_slice_http.py tests/test_entrant_slice_transactions.py phase3-implementation/slice-01-event-entrant/checks/browser_smoke.py
node --check phase3-implementation/slice-01-event-entrant/checks/browser_smoke.cjs
node --check phase3-implementation/slice-01-event-entrant/checks/legacy_director_replay.cjs
```
