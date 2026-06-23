#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/80gotv/app}"
VENV_DIR="${VENV_DIR:-/srv/80gotv/venv}"
BACKUP_DIR="${BACKUP_DIR:-/srv/80gotv/backups}"
APP_USER="${APP_USER:-80gotv}"
BRANCH="${1:-main}"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "请用管理员权限运行：sudo bash $APP_DIR/deploy/update.sh"
    exit 1
fi

cd "$APP_DIR"

run_as_app_user() {
    sudo -u "$APP_USER" -- "$@"
}

if [[ -n "$(run_as_app_user git -C "$APP_DIR" status --porcelain)" ]]; then
    echo "更新已停止：服务器代码目录里有未保存的改动。"
    echo "请先检查 git status，避免覆盖服务器上的修改。"
    exit 1
fi

echo "第 1 步：备份数据库、头像和上传图片。"
run_as_app_user "$VENV_DIR/bin/python" "$APP_DIR/scripts/backup_site.py" --output-dir "$BACKUP_DIR"

echo "第 2 步：下载新代码。"
run_as_app_user git -C "$APP_DIR" fetch origin "$BRANCH"
run_as_app_user git -C "$APP_DIR" merge --ff-only "origin/$BRANCH"

echo "第 3 步：安装本次更新需要的程序。"
run_as_app_user "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements-production.txt"

echo "第 4 步：检查 Python 文件。"
run_as_app_user "$VENV_DIR/bin/python" -m compileall -q \
    "$APP_DIR/app.py" "$APP_DIR/web_app.py" "$APP_DIR/wsgi.py" "$APP_DIR/live_worker.py" \
    "$APP_DIR/blueprints" "$APP_DIR/routes" "$APP_DIR/services" "$APP_DIR/utils"

echo "第 5 步：重启网站和数据直播。"
systemctl restart 80gotv-web 80gotv-live

echo "第 6 步：确认网站已经恢复。"
for _ in {1..20}; do
    if curl --fail --silent http://127.0.0.1:8000/healthz >/dev/null; then
        echo "更新完成，网站和数据库检查正常。"
        exit 0
    fi
    sleep 1
done

echo "更新没有通过检查，请查看：sudo systemctl status 80gotv-web"
exit 1
