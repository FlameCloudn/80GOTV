# 80GOTV

一个 CS2 赛事信息管理网站，包含前台展示、后台管理、数据直播和 Demo 导入。

第一次接手，先看[网站源码导航](docs/REPOSITORY_STRUCTURE.md)：按页面、API 和数据找到该改的位置。更细的[业务地图](docs/maintenance/MODULE_INVENTORY.md)、[数据归属](docs/maintenance/TARGET_ARCHITECTURE.md)和[历次本地验证](docs/maintenance/PROGRESS.md)也随网站版本保存。

## 主要功能

### 前台

- 新闻、比赛、赛果、赛事和选手资料
- Rating、K/D、ADR 等数据排行
- 比赛预测、评论、论坛和站内通知
- 在线 Ban / Pick
- 比赛数据直播：比分、回合、血量、护甲、金钱、装备、KDA、炸弹状态和比赛日志
- Demo 数据导入、比赛战报和海报

### 后台

- 队伍、选手、赛事、比赛和新闻管理
- 正式队伍或临时五人队比赛
- 上传管理员保存的 Demo，自动识别选手并导入数据
- 设置比赛时间后自动进入直播；只有管理员手动标记后才结束比赛
- 直播状态页：查看 GSI / GOTV 最近一次推送时间、地图、对应比赛和错误原因
- 长期保存比赛日志，比赛结束后仍可读取回合时间线
- 按整场赛事汇总生成 MVP / EVP 数据图片
- 历史昵称管理和重复选手档案合并
- 一键下载数据库、头像、Demo 和上传图片备份

## Windows 启动

在这台电脑上，在网站目录打开 PowerShell。现有本地环境已经配置好：

```powershell
cd E:\Code\Projects\80GOTV\website
.\.venv\Scripts\python.exe app.py
```

全新检出的网站：用 Python 3.12 建立环境，首次才创建配置。不要覆盖已有的 `.env`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

在本机配置中填好管理员密码、登录密钥等，再用上面的启动命令。打开 [本地网站](http://127.0.0.1:5000)，关站在该窗口按 `Ctrl+C`。生产服务仍分别用 `wsgi:app` 和 `live_worker.py`。

## 本地测试

先安装 Python 3.12 和 Node.js 22.13 或以上版本，然后在网站目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
npm ci
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

这会运行网站的 Python 测试，包括赛务和导播数据对接检查。测试使用独立的临时数据，不会使用本地或云端的正式数据库。上面的测试工具不属于网站正式运行所需的依赖。

激活上述环境后，`npm test` 是同一个测试入口。浏览器测试首次运行 `npx playwright install chromium`，然后指定 `$env:E2E_PYTHON=(Resolve-Path .venv/Scripts/python.exe).Path` 再运行 `npm run test:browser`。已有 Edge 的 Windows 也可设置 `$env:PLAYWRIGHT_CHANNEL='msedge'`。图片生成入口是 `python scripts/build_frontend_images.py`。这些是测试依赖，不是网站运行依赖。

## 环境变量

在 `.env` 中填写：

- `SECRET_KEY`：网站登录密钥，请改成随机长字符串。
- `PUBLIC_BASE_URL`：Steam 验证返回地址。本机或 Cloudflare 临时隧道使用 `auto`；固定公网域名填写完整的 `https://` 地址。
- `SESSION_COOKIE_SECURE`：公网 HTTPS 部署时改为 `true`；本机调试保持 `false`。
- `TRUST_PROXY`：使用 Cloudflare Tunnel 等反向代理时改为 `true`；直接在本机运行时保持 `false`。
- `TRUSTED_HOSTS`：公网部署时填写允许访问网站的域名，例如 `cs.example.com`。
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`：首次运行时创建管理员账号。管理员密码必须填写。
- `GOTV_SECRET`：GOTV 中继密钥。
- `GSI_TOKEN`：观战账号数据密钥，必须与 `gamestate_integration_80gotv.cfg` 相同。
- `TURSO_URL` / `TURSO_TOKEN`：可选。不填写时使用本地 `cs_site.db`。
- 需要使用 Turso 云数据库时，再运行 `python -m pip install -r requirements-turso.txt`。Windows 目前还需要安装 Visual Studio C++ Build Tools；使用本地数据库时不需要运行。
- `CSDA_PATH`：可选。也可把解析器放进系统 PATH 或网站的 `resources/tools/`；仍兼容原网站根目录放置的可执行文件。

## 比赛数据直播

网站只做数据直播，不需要视频直播。推荐使用一个单独的 Steam 观战账号采集数据。

1. 从[无密钥的 GSI 配置示例](integrations/gamestate_integration_80gotv.cfg.example)生成 `gamestate_integration_80gotv.cfg`，填入网站地址及自己的 `GSI_TOKEN`。已有的私有配置无需重建。
2. 将文件放入 CS2 的 `game/csgo/cfg` 目录。
3. 使用观战账号进入比赛观察席或 GOTV。
4. 在后台创建比赛并填写开赛时间和地图。
5. 到达开赛时间后，打开 `/matches/<比赛编号>`。

数据直播会显示在已选择地图下方。比赛日志展示本回合击杀、下包和回合结果，并在雷达图上标出阵亡位置。
游戏没有直接返回包点时，网站会根据雷达坐标自动判断 A / B 点。

后台还可以填写比赛服务器地址。网站会用它辅助确认服务器是否在线以及当前地图；选手阵营、血量和击杀仍以观战账号的 GSI 数据为准。

后台首页提供以下办赛工具：

- `直播状态`：排查观战账号是否掉线，以及最近一次失败原因。
- `MVP / EVP 图片`：选择赛事和选手后，按整场赛事数据生成可下载的 PNG 图片。图中的 `RWS Basic` 是本站按胜利回合伤害占比计算的基础版。
- 已经导入过的旧 Demo 需要在后台重新解析一次，才会补上新增的雷达图指标。
- `昵称管理`：查看历史昵称，手动合并重复选手档案。
- `下载备份`：下载包含数据库、头像、Demo 和上传图片的 ZIP。

比赛管理页中的 `结束比赛` 按钮会让比赛停止接收直播覆盖，并可保存比赛日志；误操作后可以使用 `重新开启`。

## Steam 验证

注册和找回密码会跳转到 [Steam Community OpenID](https://steamcommunity.com/openid/) 验证身份。新账号还需要邮箱验证和管理员审核；访客可以直接浏览公开内容，不需要注册。

Demo 导入只接受比赛赛程中已设置的地图，目前不支持同队超过五名选手的录像，会明确拒绝而不是截取部分选手。批量导入中任何一份失败时，整批数据不保存，原有数据保持不变；分析预览不代表统计数据已经导入。

网站会保留选手历史昵称。Steam 昵称变化不会覆盖网站内设置的正式昵称，旧昵称仍可用于 Demo 识别和站内搜索。

## 安全提醒

- 不要提交 `.env`、本地数据库或回放缓存。
- 首次运行前务必修改管理员密码、`SECRET_KEY`、`GOTV_SECRET` 和 `GSI_TOKEN`。
- 如果 CS2 和网站不在同一台电脑，请把 GSI 配置里的 `127.0.0.1` 换成网站电脑的局域网地址。
- 固定公网域名部署时务必使用 HTTPS，并填写 `PUBLIC_BASE_URL`、`SESSION_COOKIE_SECURE=true`、`TRUST_PROXY=true` 和 `TRUSTED_HOSTS`。Cloudflare 临时隧道可使用 `PUBLIC_BASE_URL=auto`。
- 只有确认网站前面有反向代理时，才填写 `TRUST_PROXY=true`。

## 公网部署与更新

本地仍然使用 `python app.py`。公网服务器使用独立的正式启动方式，代码更新不会覆盖数据库、头像、Demo 和上传图片。

服务器准备、日常更新、备份和故障处理步骤见 [`deploy/README.md`](deploy/README.md)。

## 导播与 HUD

网站负责[数据接入和 GOTV 中继](integrations/README.md)。工作区内的 `tools/jts-hud-manager`（导播桌面端）和 `tools/broadcast_hud`（画面层）是相邻的独立仓库；只有制作导播安装包时才需要两者。单独检出本网站就能启动和测试。测试所用的[导播原版样本](tests/fixtures/director/README.md)不参与网站运行。
