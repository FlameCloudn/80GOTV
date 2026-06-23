#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/80gotv/app}"
DATA_DIR="${DATA_DIR:-/srv/80gotv/data}"
VENV_DIR="${VENV_DIR:-/srv/80gotv/venv}"
BACKUP_DIR="${BACKUP_DIR:-/srv/80gotv/backups}"

if [[ ! -f "$APP_DIR/requirements-production.txt" ]]; then
    echo "错误：没有在 $APP_DIR 找到网站代码。"
    exit 1
fi

echo "正在准备独立资料目录……"
mkdir -p "$DATA_DIR/static/avatars" "$DATA_DIR/static/demos" \
    "$DATA_DIR/static/uploads" "$DATA_DIR/instance" "$DATA_DIR/logs" "$BACKUP_DIR"
touch "$DATA_DIR/cs_site.db"

make_link() {
    local source="$1"
    local target="$2"
    if [[ -L "$target" ]]; then
        echo "已存在连接：$target"
        return
    fi
    if [[ -e "$target" ]]; then
        echo "错误：$target 已有文件或目录。为避免覆盖资料，脚本已经停止。"
        exit 1
    fi
    ln -s "$source" "$target"
    echo "已连接资料目录：$target"
}

make_link "$DATA_DIR/cs_site.db" "$APP_DIR/cs_site.db"
make_link "$DATA_DIR/static/avatars" "$APP_DIR/static/avatars"
make_link "$DATA_DIR/static/demos" "$APP_DIR/static/demos"
make_link "$DATA_DIR/static/uploads" "$APP_DIR/static/uploads"
make_link "$DATA_DIR/instance" "$APP_DIR/instance"
make_link "$DATA_DIR/logs" "$APP_DIR/logs"

if [[ ! -f "$DATA_DIR/.env" ]]; then
    cp "$APP_DIR/deploy/env.production.example" "$DATA_DIR/.env"
    echo "已生成配置文件：$DATA_DIR/.env"
    echo "请先填写域名和所有密钥，再启动网站。"
fi
make_link "$DATA_DIR/.env" "$APP_DIR/.env"

echo "正在建立 Python 运行环境……"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements-production.txt"

echo "服务器基础目录准备完成。"
echo "下一步请按照 deploy/README.md 配置服务和 HTTPS。"
