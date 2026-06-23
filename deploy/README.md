# 80GOTV 公网部署说明

这套文件让本地版和公网版互不影响：

- 本地仍用 `python app.py`。
- 公网使用 `wsgi.py`，不会开启调试模式。
- 数据直播由 `live_worker.py` 单独运行，避免重复启动。
- 数据库、头像、Demo 和上传图片放在 `/srv/80gotv/data`，不跟着代码更新。

## 第一次部署

等云服务器和域名买好后再执行，推荐 Ubuntu 24.04。

1. 安装基础程序：

```bash
sudo apt update
sudo apt install -y git python3-venv curl unzip caddy
```

2. 建立专用账号和目录：

```bash
sudo useradd --system --create-home --home-dir /srv/80gotv --shell /bin/bash 80gotv
sudo -u 80gotv git clone https://github.com/FlameCloudn/80GOTV.git /srv/80gotv/app
sudo -u 80gotv bash /srv/80gotv/app/deploy/prepare_server.sh
```

3. 填写 `/srv/80gotv/data/.env`。所有“请设置”和“你的域名”都必须替换。

4. 安装 Linux 版 Demo 分析程序。版本在真正部署时重新确认：

```bash
cd /tmp
curl -LO https://github.com/akiver/cs-demo-analyzer/releases/download/v1.10.0/linux-x64.zip
unzip linux-x64.zip
sudo install -m 755 csda /usr/local/bin/csda
```

5. 安装网站服务：

```bash
sudo cp /srv/80gotv/app/deploy/80gotv-web.service /etc/systemd/system/
sudo cp /srv/80gotv/app/deploy/80gotv-live.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now 80gotv-web 80gotv-live
```

6. 把 `deploy/Caddyfile.example` 中的域名替换后复制到 `/etc/caddy/Caddyfile`，然后检查并启动 HTTPS：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## 从本地迁移正式资料

第一次上线时，只迁移以下内容：

- `cs_site.db`
- `static/avatars`
- `static/demos`
- `static/uploads`

迁移前先停止公网服务，资料复制完成后再启动。具体复制命令要根据购买的服务器地址生成，不提前写死。

## 日常更新

固定顺序是：本地修改、本地测试、上传 GitHub、服务器更新。

服务器执行：

```bash
sudo bash /srv/80gotv/app/deploy/update.sh
```

更新脚本会先备份，再下载代码、检查文件、重启并访问 `/healthz`。服务器代码目录如果有手动修改，脚本会停止，不会覆盖。脚本需要管理员权限来重启网站服务，但拉取代码和安装 Python 依赖时仍会使用 `80gotv` 专用账号。

## 备份

日常备份不包含大型 Demo：

```bash
cd /srv/80gotv/app
/srv/80gotv/venv/bin/python scripts/backup_site.py
```

完整备份包含 Demo：

```bash
cd /srv/80gotv/app
/srv/80gotv/venv/bin/python scripts/backup_site.py --full
```

备份脚本不会删除旧备份，也不会把含密钥的 `.env` 放进压缩包。正式上线后再增加“每天日常备份、每周完整备份、复制到另一处”的定时任务。

恢复备份会覆盖现有资料，因此这里不提供自动恢复命令。需要恢复时先检查备份内容，再由管理员确认执行。
