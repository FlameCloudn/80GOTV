# 80GOTV

80GOTV 是一个 CS2 赛事网站。观众可以查看赛程、比分、选手统计和荣誉，参与竞猜；赛事管理员可以处理报名、阵容、选图、赛果和 Demo。网站通过 GSI 和 GOTV 接收比赛数据。

## 本机启动

使用 Python 3.12，在项目根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

先在本机的 `.env` 设置独立的登录密钥和管理员密码，再启动网站：

```powershell
.\.venv\Scripts\python.exe scripts/migrate_database.py
.\.venv\Scripts\python.exe scripts/build_frontend_images.py
.\.venv\Scripts\python.exe -m waitress --listen=127.0.0.1:5000 wsgi:app
```

打开 [本地网站](http://127.0.0.1:5000)。需要比赛状态更新时，在第二个终端运行 `.\.venv\Scripts\python.exe live_worker.py`。Linux 正式环境使用 Gunicorn 加载 `wsgi:app`，后台进程单独运行。

仓库只提供网站源码与静态资源。初次启动会建立本地数据库；正式数据、账号、头像、上传的文件和比赛录像不随仓库分发。项目许可证见 [LICENSE](LICENSE)。
