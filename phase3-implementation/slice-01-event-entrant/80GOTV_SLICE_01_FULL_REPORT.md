# 80GOTV Slice 1 完整报告

本文件按 00–04 顺序一次性合并原文；原分章后续修改不会自动同步。

## 目录

- [00 · Slice 1 实现报告](#slice01-chapter-00)
- [01 · 测试结果](#slice01-chapter-01)
- [02 · 接口与兼容结果](#slice01-chapter-02)
- [03 · 隔离数据库结果](#slice01-chapter-03)
- [04 · 未完成与后续事项](#slice01-chapter-04)

---

<a id="slice01-chapter-00"></a>

# 00 · Slice 1 实现报告

**状态：隔离实现及本地验证完成，已通过独立架构审查。** 本切片仅供本地隔离开发与预览，生产站点尚未启用；生产迁移、发布和正式使用均不在本次范围。

## 实现范围

本次围绕一届赛事的报名、截止分队、本届参赛身份和初始五人，验证旧赛事页面与旧导播读取方式。保留现有 Steam 时长平衡函数；分队与最终确认初始五人是两步。正式站点的数据不作为隔离测试输入。

不在本次实现比赛、正式赛果、统计、Swiss、奖项或 Demo 系统的整体重构，也不重做前端。原有工作区改动保留；不部署、不推送。完成条件以最终测试和审查为准。

## 文件和模型

当前隔离代码位于 [entrant_slice](../../entrant_slice/)：

| 文件 | 当前职责 |
|---|---|
| [registration.py / registration.sql](../../entrant_slice/registration.py) | 赛事、队伍和个人报名、候补及预留位；隔离报名表定义见 [registration.sql](../../entrant_slice/registration.sql)。 |
| [formation.py / formation.sql](../../entrant_slice/formation.py) | 截止分队、本届参赛方、初始名单确认及赛前调整；表和约束见 [formation.sql](../../entrant_slice/formation.sql)。 |
| [storage.py](../../entrant_slice/storage.py) | 隔离写入事务与管理员检查。 |
| [legacy.py / legacy_projection.sql](../../entrant_slice/legacy.py) | 在隔离实例中把新记录投影给旧读取入口；投影定义见 [legacy_projection.sql](../../entrant_slice/legacy_projection.sql)。 |
| [legacy_match_guard.py](../../entrant_slice/legacy_match_guard.py) | 只读旧比赛信息，阻止在已有开赛证据等受保护情形下修改相关名单。 |
| [web.py](../../entrant_slice/web.py) | 隔离实例的写入入口及旧报名表单接入。 |
| [sandbox.py](../../entrant_slice/sandbox.py) | 创建、打开和移除有专用标记的隔离数据库，装配本地预览。 |
| [__main__.py](../../entrant_slice/__main__.py)、[worker.py](../../entrant_slice/worker.py)、[sample.py](../../entrant_slice/sample.py) | 本机操作命令、截止办理进程与虚构演示数据；预览仅监听 `127.0.0.1`，默认端口 5091。 |

表定义区分 `event_entrant`、当前成员 `entrant_member`、已确认名单 `initial_roster` 和 `initial_roster_member`；保留确认人和时间。

新增测试为[领域](../../tests/test_entrant_slice_domain.py)、[事务](../../tests/test_entrant_slice_transactions.py)、[兼容](../../tests/test_entrant_slice_compatibility.py)、[HTTP 全流程](../../tests/test_entrant_slice_http.py)、[命令行](../../tests/test_entrant_slice_cli.py)，共用[测试数据](../../tests/entrant_slice_fixtures.py)。本交付目录另含[旧导播回放](checks/legacy_director_replay.cjs)、浏览器检查脚本 [Python](checks/browser_smoke.py) / [Node](checks/browser_smoke.cjs) 和用于排除本地沙盒的 [.gitignore](.gitignore)。测试结果见 [01](#slice01-chapter-01)。

前端仅对原有 [赛事详情模板](../../templates/event_detail.html)和[报名列表模板](../../templates/_event_registration_list.html)作与本切片直接相关的局部判断：在隔离赛事中区分普通报名截止、独立候补入口及受保护操作。没有重做布局、组件体系，也没有为本切片修改网站 CSS、页面 JavaScript 或导播 APP。

## 接口与兼容

隔离实例中新增的管理入口、旧页面和旧导播读取边界见 [02 接口兼容](#slice01-chapter-02)。这些入口不代表公网新增接口。本机 `serve` 同时启动独立的到期办理进程，不需要访问页面才处理截止；未向生产环境安装或修改定时任务。

## 测试与未决项

改前、最终版分别运行同一组 25 个旧网站测试模块，均为 **305 项通过，0 失败、0 错误、0 跳过**；改前 218.560 秒、最终版 234.320 秒。旧断言未改。这不是全站所有测试的数量。新增五个模块 **28/28 通过**，另用仅含基准和本次暂存代码的干净副本再次通过 **28/28**。其他测试范围见 [01 测试结果](#slice01-chapter-01)，隔离数据库验证见 [03 数据库](#slice01-chapter-03)，剩余限制见 [04 待办](#slice01-chapter-04)。

最终代码在桌面与手机的真实浏览器检查已截图，覆盖报名弹窗、首次候补报名、确认名单和归档后的历史；另用真实本机 HTTP 服务验证无人访问时自动分队。截图和检查范围见 [01](#slice01-chapter-01)。截图保存在交付文档目录以外的本地 `output/`，不作为代码提交。未获得单独授权，不进行公网部署或 Git 推送。

## 下一步

下一批先在隔离库建立“比赛固定双方 → 本届参赛方”的绑定并冻结比赛阵容，再走通一场双方均为临时队的旧比赛链路。不能把新的组号硬塞进旧比赛的报名外键，也不要提前接管正式比分、Swiss 或生产环境。

维护时，改候补优先规则先找 [formation.assign_reserve](../../entrant_slice/formation.py)；改导播输出字段先找 [legacy.py](../../entrant_slice/legacy.py) 和 [legacy_projection.sql](../../entrant_slice/legacy_projection.sql)，不碰分队算法。


---

<a id="slice01-chapter-01"></a>

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
| 旧页面和导播读取 | [兼容用例](../../tests/test_entrant_slice_compatibility.py) **1/1 通过**：使用真实旧 Flask 页面/JSON、导播原 TypeScript 读取代码及 Node SQLite。 | 已计入上述 28 项，不重复相加；不是装机导播。详见 [02](#slice01-chapter-02)。 |
| 报名到确认的 HTTP 全流程 | [端到端用例](../../tests/test_entrant_slice_http.py) **1/1 通过**；Flask 测试客户端与独立时钟进程覆盖管理员登录、旧表单报名、无人访问时到期分队、确认/重复确认、旧页面和导播读取、拒绝路径及外键检查 0 项。 | 已计入上述 28 项；不是浏览器或装机导播实测。 |
| 真实本机服务冒烟 | 在全新隔离目录实际启动 `serve`，首个 HTTP 请求到来前自动分出两队；访问原 `/events/entrant-practice` 返回 200，页面包含正式队名。正常中断后预览和截止子进程均退出。 | 这是另一次本机操作检查，不计入上述 28 项，也不是公网联调。 |
| 数据库命令与重建 | [命令行用例](../../tests/test_entrant_slice_cli.py) **1/1 通过**，覆盖空库、重复迁移、真实写锁超时后的自动恢复、分队不重复、清理和重建。 | 已计入上述 28 项；`status` 读的是新模型，旧页面读取另由兼容和 HTTP 用例验证。见 [03](#slice01-chapter-03)。 |
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


---

<a id="slice01-chapter-02"></a>

# 02 · 接口与兼容结果

**状态：本地隔离兼容检查通过。** 本章列出实际接入的入口和验证范围；没有修改或要求升级导播 APP，实体设备尚未联调。

## 隔离管理入口

[web.py](../../entrant_slice/web.py) 在隔离实例装配以下入口，使用既有管理员会话和防伪检查；这些不是已经上线的公网接口。

| 方法与路径 | 当前用途 |
|---|---|
| `POST /admin/entrant-slice/events` | 创建一届隔离赛事。 |
| `GET /admin/entrant-slice/events/<event_id>` | 查看该届分队、本届参赛方、初始/当前名单及候补。 |
| `POST /admin/entrant-slice/events/<event_id>/<action>` | 分队、关联目录队、归档、核预留、确认初始名单和获准的调整。 |

当前操作名包括 `form-due`、`link-club`、`archive`、`review-reservation`、`confirm-initial`、`adjust-formation`、`assign-reserve` 和 `replace-before-series`。本机预览由独立的截止办理进程处理到期赛事，不改变生产定时任务。

## 旧读取和旧表单

[legacy.py](../../entrant_slice/legacy.py) 仅在隔离预览装配旧读取，面向现有赛事详情与导播赛事列表/详情；[legacy_projection.sql](../../entrant_slice/legacy_projection.sql) 定义投影。旧报名表单由隔离入口接入对应写入，旧接口路径和字段不是新领域身份的命名模板。

| 核对对象 | 最终结果 |
|---|---|
| 赛事详情、旧报名/候补表单 | 组合用例 1/1 通过，使用实际 Flask 旧页面；另有桌面和手机浏览器实拍，见 [测试结果](#slice01-chapter-01)。 |
| `/api/broadcast/events` 和 `/api/broadcast/events/<event_id>` | 组合用例使用旧 JSON 检查新赛事与旧赛事，并核查不存在的赛事响应。 |
| 导播源码实际读取 | 同一组合用例调用 [回放脚本](checks/legacy_director_replay.cjs)，由导播原 TypeScript 读取赛事数据，并使用 Node SQLite；过程检查通过。 |
| 旧合同失败、权限及原有行为 | 组合用例检查访客写入 401、缺防伪信息 403，以及未接管操作 404；旧网站 305 项最终回归和独立旧合同回放也通过。 |
| 装机导播、OBS、真实直播 | 尚未取得实际设备联调结果。 |

此外，以合成数据重新回放旧合同：网站 Flask **20/20 组、133 次请求**，桌面原函数 **21/21 组**，其中 4 组使用网站刚返回的真实回执；预期出现的 500 同时核对了整笔回滚。这组回放验证旧合同，不取代上表中的新数据兼容用例或装机联调。

运行组合兼容用例，在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_entrant_slice_compatibility -v
```

组合结果为 1 个测试用例，不把其中多次 HTTP 请求各算一项。验证中不记录或展示令牌、Cookie、密码等凭据。实际旧合同资料可参照 [Phase 3 接口整理](../../phase3-preparation/02_LEGACY_API_CONTRACTS.md)，但历史记录不能代替本次切片回归。

旧合同回放命令，均在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -B phase3-preparation/fixtures/contracts/contract_replay.py
node --permission --allow-fs-read=. phase3-preparation/fixtures/contracts/director_replay.cjs
.\.venv\Scripts\python.exe -B phase3-preparation/fixtures/contracts/contract_replay.py --acks | node --permission --allow-fs-read=. phase3-preparation/fixtures/contracts/director_replay.cjs --website-acks
```


---

<a id="slice01-chapter-03"></a>

# 03 · 隔离数据库结果

**状态：隔离数据库验证通过。** 本次只建立本切片的隔离数据库，不执行生产数据迁移，不用隔离库覆盖网站数据库。

## 数据与边界

[sandbox.py](../../entrant_slice/sandbox.py) 限定专用本机沙盒并检查标记；[registration.sql](../../entrant_slice/registration.sql) 和 [formation.sql](../../entrant_slice/formation.sql) 定义报名、参赛方及名单相关结构。迁移标记保存在隔离库内，正式初始名单和当前名单分别保存。

分队沿用 [现有平衡函数](../../services/steam_playtime_service.py)，不是迁移或替换原站已有赛事。[命令入口](../../entrant_slice/__main__.py)提供 `init`、`demo`、`status`、`watch`、`due`、`serve`、`set-demo-password`、`confirm` 和 `remove`；默认目录为本交付目录内的 `.sandbox`。指定其他允许的独立目录时，`--workspace` 写在子命令之前。

## 实测结果

| 项目 | 最终结果 |
|---|---|
| 空目录创建隔离库、建立结构 | [命令行用例](../../tests/test_entrant_slice_cli.py)在全新临时目录执行 `init`，创建隔离库及迁移标记。 |
| 重复执行迁移或初始化 | 在空库及已有演示赛事时重复 `init`；迁移记录和赛事数量保持不变。 |
| 创建赛事、报名、分队和确认 | 隔离 HTTP 全流程用例 1/1 通过；管理员实际登录，独立时钟在无人访问页面时完成分队，随后确认与重复确认。另起真实本机服务时，首个请求前已分出两队。 |
| 初始五人保护、当前名单分开查询 | 领域及事务测试覆盖冻结、重复确认、禁止覆盖和赛前调整；旧页面与新模型读取分别检查。 |
| 失败整笔回滚、独立连接竞争 | 事务用例核回滚与竞争；另以真实 SQLite 写锁触发超时，释放后截止进程自动恢复，分队只发生一次。 |
| 关闭进程后删除测试环境、从头重建 | 命令行用例只删除自己新建的临时沙盒，再初始化并确认新库为空，最后移除该临时目录。 |
| 旧站库与历史数据 | 本任务未迁移或覆盖生产数据库及历史资料。 |

[数据库与事务用例](../../tests/test_entrant_slice_transactions.py)和命令行用例均计入 [01 的 28 项](#slice01-chapter-01)，不重复相加。`status` 读取新模型；旧页面和导播的读取由另行的兼容测试验证。

## 本机演示

以下命令在项目根目录运行，只使用本切片的隔离数据，不连接生产网站。若默认 `.sandbox` 已有本工具的演示赛事，`demo` 会沿用该赛事，不会清空数据或重新计算截止时间。

1. 创建演示赛事，记下终端显示的赛事编号；下面设置本机演示管理员密码时，密码输入不会显示，也不要写进命令或文档：

```powershell
.\.venv\Scripts\python.exe -B -m entrant_slice demo --seconds 120
.\.venv\Scripts\python.exe -B -m entrant_slice set-demo-password --account entrant-demo-admin
```

2. 如需体验旧报名页面，可另外设置演示队长账号；要尝试首次独立候补报名，可设置尚未报名的 `entrant-demo-12` 账号：

```powershell
.\.venv\Scripts\python.exe -B -m entrant_slice set-demo-password --account entrant-demo-captain
.\.venv\Scripts\python.exe -B -m entrant_slice set-demo-password --account entrant-demo-12
```

3. 启动本机预览，在浏览器打开 `http://127.0.0.1:5091/events/entrant-practice`：

```powershell
.\.venv\Scripts\python.exe -B -m entrant_slice serve --port 5091
```

`serve` 必须保持运行，随它启动的独立进程才会到期自动分队；页面不用一直打开。关闭 `serve` 后自动办理也会停止，重新启动后才继续检查。端口被占用时，换一个未占用端口并使用终端显示的地址。

4. 等终端提示已完成分队后，保持第一个终端和预览运行，另开一个位于项目根目录的 PowerShell。输入步骤 1 显示的赛事编号，然后按提示输入账号 `entrant-demo-admin` 和刚才设置的密码，核对名单后输入 `YES` 冻结初始五人：

```powershell
$eventId = Read-Host '输入演示赛事编号'
.\.venv\Scripts\python.exe -B -m entrant_slice confirm --event $eventId
```

刷新赛事页面即可查看确认后的队伍。要停止本机预览，在第一个终端按 `Ctrl+C`；这也会停止其截止办理进程。`remove` 只适用于确认不再需要的本工具专用沙盒，不会自动清除用户已有的其他目录。


---

<a id="slice01-chapter-04"></a>

# 04 · 未完成与后续事项

**状态：本地隔离验收完成。** 下面保留尚未验证的真实环境和不属于本次范围的事项；已完成的测试见 [01](#slice01-chapter-01)。

## 已知限制

- 隔离预览只接管本切片允许的页面和操作，不是整站预览。生产站点、生产数据库和生产定时任务未启用本实现。
- 到期自动分队依赖本机 `serve` 附带的独立进程，或单独运行 `watch`；两者都停止时不会自动办理。重新启动后继续检查到期赛事。
- 导播兼容已验证原 TypeScript 读取和旧协议回放，但真实装机导播、OBS、游戏及公网未联调。
- 原有 305 项是选定的 25 个测试模块，不是全站完整测试。Ruff/Pyright 通过范围为本切片代码及指定测试、检查脚本，不代表旧站全库零问题。
- [11 张截图](../../output/ui-audit/entrant-slice-01/)仅保存在本地 `output/`，未作为代码提交；其他机器若没有这批截图，对应链接不可用。

## 办赛时的处理

- 如果散人不足以补齐已有的不满员队伍，本次分队不产生半成品，原报名保留；不会私自拆队，也不会把独立候补自动转为首发。需要管理员处理，本切片不提供截止后新增普通报名的补录入口。
- 截止后、分队尚未完成时，管理员可用 `review-reservation` 核实预留位：有证据且与原先预留的 Steam 身份一致时认领，否则可记录理由并释放该位置，再重试分队。
- 新组号与旧比赛的报名外键不能直接互用；下一批应先解决本届参赛方与比赛固定双方的绑定，不能硬填编号。

## 不在本次范围

- 比赛、正式赛果、统计、Swiss、奖项和 Demo 的全面改造。
- 全站前端重构、数据库迁移、真实生产切换或导播 APP 重写。
- 历史数据正式迁移、真实安装版导播和 OBS 联调，需分别具备材料和授权。
