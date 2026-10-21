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
sudo cp /srv/80gotv/app/deploy/80gotv-backup-*.service /etc/systemd/system/
sudo cp /srv/80gotv/app/deploy/80gotv-backup-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now 80gotv-web 80gotv-live
sudo systemctl enable --now 80gotv-backup-daily.timer 80gotv-backup-full.timer
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

### 当前正式站的保留要求（2026-10-21）

站主要求 `80gotv.cn` 不在服务器保留备份文件，也不再自动生成日常、完整备份。此要求覆盖下文通用安装说明中的定时保留设置：两个备份定时器应保持停用，不要随更新重新启用。

部署仍须保护数据库：先制作临时快照，下载到本机项目的 `backups/manual/`，核对 ZIP、数据库完整性和文件校验值，再清理服务器的快照与旧备份。正式的 `/srv/80gotv/data/cs_site.db`、头像、上传文件和 Demo 原件不在清理范围内。

`update.sh` 和手动备份功能仍会生成 ZIP；不能把“定时器停用”理解成这些命令不再生成文件。日后运行它们时，也必须完成下载、验证和服务器清理，不在公网积存副本。下文保留通用备份与恢复用法，便于需要时取回到本机。

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

手动运行且不填写 `--keep` 时，备份脚本不会删除旧备份；定时器保留最近 2 份日常备份和 1 份完整备份，只清理脚本自己生成的同类型旧文件。新备份通过 ZIP 和数据库完整性检查后，才清理旧备份；失败时保留原备份。备份不会包含带密钥的 `.env`。使用 `systemctl list-timers '80gotv-backup-*'` 可以确认下次执行时间。部署前下载并验证数据库备份即可，不需要在服务器保留重复下载副本；仍建议把一份已验证的数据库备份保存在另一台设备。

检查已有备份：

```bash
/srv/80gotv/venv/bin/python scripts/backup_site.py --verify /srv/80gotv/backups/备份文件.zip
```

恢复时先解压到新的空目录，不会覆盖现有资料：

```bash
/srv/80gotv/venv/bin/python scripts/restore_site.py /srv/80gotv/backups/备份文件.zip /srv/80gotv/restore-check
```

确认新目录中的数据库和文件都正确后，再停止服务并人工切换资料目录。

恢复备份会覆盖现有资料，因此这里不提供自动恢复命令。需要恢复时先检查备份内容，再由管理员确认执行。
