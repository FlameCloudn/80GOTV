# 80GOTV

80GOTV 是一个 CS2 赛事网站。观众可以查看赛程、比分、选手统计和荣誉，参与竞猜；赛事管理员可以处理报名、阵容、选图、赛果和 Demo。网站也支持接收 GSI 和 GOTV 比赛数据。

## 本机启动

安装 Python 3.12 和 Node.js 22.13 或以上版本，在网站目录的 PowerShell 中运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$dataRoot = .\.venv\Scripts\python.exe -c "from src.website.runtime.storage import default_data_root; print(default_data_root())"
New-Item -ItemType Directory -Force $dataRoot | Out-Null
if (!(Test-Path (Join-Path $dataRoot '.env'))) {
    Copy-Item .env.example (Join-Path $dataRoot '.env')
}
```

打开数据目录中的 `.env`，给 `SECRET_KEY` 填一个随机长字符串，并设置自己的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`。配置文件不会随网站源码分发，不要提交到 Git。

```powershell
npm ci
npm run build
.\.venv\Scripts\python.exe scripts/build_frontend_images.py
.\.venv\Scripts\python.exe app.py
```

打开 [本地网站](http://127.0.0.1:5000)，用完按 `Ctrl+C`。初次启动会在数据目录创建空库。可以用环境变量 `SITE_DATA_ROOT` 指定另一个数据目录。更新前端源码后，重新运行 `npm run build`。

## 运行与资料

Linux 正式环境使用 `requirements-production.txt` 安装依赖，构建前端后先运行 `python scripts/migrate_database.py`，再用 Gunicorn 加载 `wsgi:app`。比赛更新进程单独运行 `python live_worker.py`。Node.js 只用于构建前端，不必在运行网页或比赛更新时启动。

需要接收比赛数据时，使用 [GSI 配置示例](integrations/gamestate_integration_80gotv.cfg.example) 并设置自己的 `GSI_TOKEN`，或运行 [GOTV Relay](integrations/gotv_relay/relay.py) 并设置自己的 `GOTV_SECRET`。

本仓库不包含正式数据库、账号、头像、上传资料和比赛录像。项目许可证见 [LICENSE](LICENSE)；国旗字体的许可证见 [Twemoji Country Flags](static/fonts/country-flags/LICENSE.md)。
