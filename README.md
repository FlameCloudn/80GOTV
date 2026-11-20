# 80GOTV

80GOTV 是一个 CS2 赛事网站。观众可以查看赛程、比分、选手统计和荣誉，参与竞猜；赛事管理员可以处理报名、阵容、选图、赛果和 Demo。网站支持接收 GSI 和 GOTV 比赛数据。

## 本机启动

安装 Python 3.12 和 Node.js 22.13 或以上版本，在本仓库根目录的 PowerShell 中运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/base.txt
$dataRoot = .\.venv\Scripts\python.exe -c "from src.website.runtime.storage import default_data_root; print(default_data_root())"
New-Item -ItemType Directory -Force $dataRoot | Out-Null
if (!(Test-Path (Join-Path $dataRoot '.env'))) {
    Copy-Item .env.example (Join-Path $dataRoot '.env')
}
```

打开数据目录中的 `.env`，给 `SECRET_KEY` 填一个随机长字符串，再设置自己的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`。不要提交或分享这个文件。默认数据目录位于克隆目录旁；可在上述步骤前设置 `SITE_DATA_ROOT` 另选位置。

```powershell
npm ci
npm run build
.\.venv\Scripts\python.exe -m scripts.database.migrate_database
.\.venv\Scripts\python.exe app.py
```

打开 [本地网站](http://127.0.0.1:5000)，用完按 `Ctrl+C`。新数据库没有实况赛事或录像。更新前端源码后重新运行 `npm run build`。本地生成手机地图题图可运行 `python -m scripts.assets.build_frontend_images`，请使用已安装网站依赖的 Python。

## 运行与资料

Linux 可用 `requirements/production.txt` 安装运行依赖。准备好自己的配置和构建后的前端，先运行 `python -m scripts.database.migrate_database`，再用 Gunicorn 加载 `wsgi:app`。比赛更新和报名截止处理可另起一个进程运行 `python -m src.website.runtime.worker`。Node.js 用于构建前端，不是网站服务器的运行依赖。

需要接收比赛数据时，使用 [GSI 配置示例](integrations/gamestate_integration_80gotv.cfg.example) 并设置自己的 `GSI_TOKEN`，或运行 [GOTV Relay](integrations/gotv_relay/relay.py) 并设置自己的 `GOTV_SECRET`。

这是独立的公开源码版，不包含内部测试、部署工具、真实配置、正式数据库、头像、上传资料或比赛录像。npm 清单中为内部开发保留的测试命令不适用于本公开树。项目许可证见 [LICENSE](LICENSE)；国旗字体的许可证见 [Twemoji Country Flags](static/fonts/country-flags/LICENSE.md)。
