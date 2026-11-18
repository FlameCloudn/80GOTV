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

[数据库与事务用例](../../tests/test_entrant_slice_transactions.py)和命令行用例均计入 [01 的 28 项](01_TEST_RESULTS.md)，不重复相加。`status` 读取新模型；旧页面和导播的读取由另行的兼容测试验证。

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
