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

新增测试为[领域](../../tests/test_entrant_slice_domain.py)、[事务](../../tests/test_entrant_slice_transactions.py)、[兼容](../../tests/test_entrant_slice_compatibility.py)、[HTTP 全流程](../../tests/test_entrant_slice_http.py)、[命令行](../../tests/test_entrant_slice_cli.py)，共用[测试数据](../../tests/entrant_slice_fixtures.py)。本交付目录另含[旧导播回放](checks/legacy_director_replay.cjs)、浏览器检查脚本 [Python](checks/browser_smoke.py) / [Node](checks/browser_smoke.cjs) 和用于排除本地沙盒的 [.gitignore](.gitignore)。测试结果见 [01](01_TEST_RESULTS.md)。

前端仅对原有 [赛事详情模板](../../templates/event_detail.html)和[报名列表模板](../../templates/_event_registration_list.html)作与本切片直接相关的局部判断：在隔离赛事中区分普通报名截止、独立候补入口及受保护操作。没有重做布局、组件体系，也没有为本切片修改网站 CSS、页面 JavaScript 或导播 APP。

## 接口与兼容

隔离实例中新增的管理入口、旧页面和旧导播读取边界见 [02 接口兼容](02_API_COMPATIBILITY_RESULTS.md)。这些入口不代表公网新增接口。本机 `serve` 同时启动独立的到期办理进程，不需要访问页面才处理截止；未向生产环境安装或修改定时任务。

## 测试与未决项

改前、最终版分别运行同一组 25 个旧网站测试模块，均为 **305 项通过，0 失败、0 错误、0 跳过**；改前 218.560 秒、最终版 234.320 秒。旧断言未改。这不是全站所有测试的数量。新增五个模块 **28/28 通过**，另用仅含基准和本次暂存代码的干净副本再次通过 **28/28**。其他测试范围见 [01 测试结果](01_TEST_RESULTS.md)，隔离数据库验证见 [03 数据库](03_DATABASE_MIGRATION_RESULTS.md)，剩余限制见 [04 待办](04_OPEN_ISSUES.md)。

最终代码在桌面与手机的真实浏览器检查已截图，覆盖报名弹窗、首次候补报名、确认名单和归档后的历史；另用真实本机 HTTP 服务验证无人访问时自动分队。截图和检查范围见 [01](01_TEST_RESULTS.md)。截图保存在交付文档目录以外的本地 `output/`，不作为代码提交。未获得单独授权，不进行公网部署或 Git 推送。

## 下一步

下一批先在隔离库建立“比赛固定双方 → 本届参赛方”的绑定并冻结比赛阵容，再走通一场双方均为临时队的旧比赛链路。不能把新的组号硬塞进旧比赛的报名外键，也不要提前接管正式比分、Swiss 或生产环境。

维护时，改候补优先规则先找 [formation.assign_reserve](../../entrant_slice/formation.py)；改导播输出字段先找 [legacy.py](../../entrant_slice/legacy.py) 和 [legacy_projection.sql](../../entrant_slice/legacy_projection.sql)，不碰分队算法。
