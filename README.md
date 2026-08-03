# 80GOTV

一个 CS2 赛事信息管理网站，包含前台展示、后台管理、数据直播和 Demo 导入。

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

第一次运行前，在项目目录打开 `cmd`：

```bat
cd C:\Users\jiuzi\Desktop\80GOTV
copy .env.example .env
python -m pip install -r requirements.txt
python app.py
```

以后启动只需要：

```bat
cd C:\Users\jiuzi\Desktop\80GOTV
python app.py
```

打开 [http://127.0.0.1:5000](http://127.0.0.1:5000)。

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
- `CSDA_PATH`：可选。不填写时自动查找项目根目录下的 `csda.exe`。

## 比赛数据直播

网站只做数据直播，不需要视频直播。推荐使用一个单独的 Steam 观战账号采集数据。

1. 打开 `gamestate_integration_80gotv.cfg`，填写网站地址和 `GSI_TOKEN`。
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

选手注册和找回密码会跳转到 [Steam Community OpenID](https://steamcommunity.com/openid/) 验证身份。游客注册不需要 Steam 验证。

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
