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
| 赛事详情、旧报名/候补表单 | 组合用例 1/1 通过，使用实际 Flask 旧页面；另有桌面和手机浏览器实拍，见 [测试结果](01_TEST_RESULTS.md)。 |
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
