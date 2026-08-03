#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/80gotv/app}"
VENV_DIR="${VENV_DIR:-/srv/80gotv/venv}"
BACKUP_DIR="${BACKUP_DIR:-/srv/80gotv/backups}"
APP_USER="${APP_USER:-80gotv}"
BRANCH="${1:-main}"
ENV_FILE="${ENV_FILE:-/srv/80gotv/data/.env}"
HEALTH_HOST="${HEALTH_HOST:-80gotv.cn}"
OLD_REV=""
UPDATED=0
TEST_DB=""
BACKUP_FILE=""
DATABASE_PATH_VALUE="$APP_DIR/cs_site.db"
APP_ENV=()

if [[ "$(id -u)" -ne 0 ]]; then
    echo "请用管理员权限运行：sudo bash $APP_DIR/deploy/update.sh"
    exit 1
fi

cd "$APP_DIR"

run_as_app_user() {
    sudo -u "$APP_USER" -- "$@"
}

load_app_env() {
    local line key value
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "更新已停止：找不到环境变量文件 $ENV_FILE"
        return 1
    fi
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ ! "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            echo "更新已停止：环境变量文件中存在不规范的 KEY=VALUE 行。"
            return 1
        fi
        key="${line%%=*}"
        value="${line#*=}"
        if [[ "$value" == \"*\" && ${#value} -ge 2 ]]; then
            value="${value:1:${#value}-2}"
        elif [[ "$value" == \'*\' && ${#value} -ge 2 ]]; then
            value="${value:1:${#value}-2}"
        fi
        APP_ENV+=("$key=$value")
        if [[ "$key" == "DATABASE_PATH" && -n "$value" ]]; then
            DATABASE_PATH_VALUE="$value"
        fi
    done < "$ENV_FILE"
}

cleanup_test_db() {
    if [[ -n "$TEST_DB" ]]; then
        run_as_app_user rm -f -- "$TEST_DB" "$TEST_DB-wal" "$TEST_DB-shm" "$TEST_DB-journal"
        TEST_DB=""
    fi
}

rollback() {
    local exit_code=$?
    trap - ERR
    cleanup_test_db
    if [[ "$UPDATED" -eq 1 && -n "$OLD_REV" ]]; then
        echo "更新失败，正在退回上一个可用版本：$OLD_REV"
        systemctl stop 80gotv-web 80gotv-live || true
        if [[ -n "$BACKUP_FILE" && -f "$BACKUP_FILE" ]]; then
            if ! run_as_app_user env "${APP_ENV[@]}" \
                "$VENV_DIR/bin/python" "$APP_DIR/scripts/restore_site.py" \
                "$BACKUP_FILE" --database-only "$DATABASE_PATH_VALUE"; then
                echo "警告：数据库自动恢复失败，请使用备份手动恢复：$BACKUP_FILE"
            fi
        fi
        run_as_app_user git -C "$APP_DIR" reset --hard "$OLD_REV"
        run_as_app_user "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements-production.txt"
        systemctl start 80gotv-web 80gotv-live
        if curl --fail --silent --retry 20 --retry-delay 1 -H "Host: $HEALTH_HOST" http://127.0.0.1:8000/healthz >/dev/null; then
            echo "已恢复旧版本。数据备份保存在：$BACKUP_DIR"
        else
            echo "旧版本也未恢复，请保留现场并查看 deploy/README.md 的恢复说明。"
        fi
    fi
    exit "$exit_code"
}

trap rollback ERR

load_app_env

if [[ -n "$(run_as_app_user git -C "$APP_DIR" status --porcelain)" ]]; then
    echo "更新已停止：服务器代码目录里有未保存的改动。"
    echo "请先检查 git status，避免覆盖服务器上的修改。"
    exit 1
fi

OLD_REV="$(run_as_app_user git -C "$APP_DIR" rev-parse HEAD)"

echo "第 1 步：备份数据库、头像和上传图片，并检查备份。"
BACKUP_FILE="$(run_as_app_user env "${APP_ENV[@]}" \
    "$VENV_DIR/bin/python" "$APP_DIR/scripts/backup_site.py" \
    --output-dir "$BACKUP_DIR" --print-path-only)"
echo "备份完成并已检查：$BACKUP_FILE"

echo "第 2 步：下载新代码。"
run_as_app_user git -C "$APP_DIR" fetch origin "$BRANCH"
run_as_app_user git -C "$APP_DIR" merge --ff-only "origin/$BRANCH"
UPDATED=1

echo "第 3 步：安装本次更新需要的程序。"
run_as_app_user "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements-production.txt"
run_as_app_user env "${APP_ENV[@]}" \
    "$VENV_DIR/bin/python" "$APP_DIR/scripts/build_frontend_images.py"

echo "第 4 步：检查 Python 文件。"
run_as_app_user "$VENV_DIR/bin/python" -m compileall -q \
    "$APP_DIR/app.py" "$APP_DIR/web_app.py" "$APP_DIR/wsgi.py" "$APP_DIR/live_worker.py" \
    "$APP_DIR/blueprints" "$APP_DIR/routes" "$APP_DIR/services" "$APP_DIR/utils"

echo "第 5 步：使用临时数据库运行全部测试。"
TEST_DB="$(run_as_app_user mktemp /tmp/80gotv-test-XXXXXX.db)"
run_as_app_user env "${APP_ENV[@]}" DATABASE_PATH="$TEST_DB" FLASK_ENV=testing \
    TURSO_URL= TURSO_TOKEN= SECRET_KEY=deployment-test-secret SESSION_COOKIE_SECURE=false \
    "$VENV_DIR/bin/python" -m unittest discover -s "$APP_DIR/tests" -t "$APP_DIR" -p "test_*.py"
cleanup_test_db

echo "第 6 步：暂停服务并升级正式数据库。"
systemctl stop 80gotv-live 80gotv-web
run_as_app_user env "${APP_ENV[@]}" \
    "$VENV_DIR/bin/python" "$APP_DIR/scripts/migrate_database.py"

echo "第 7 步：启动网站和数据直播。"
systemctl start 80gotv-web 80gotv-live

echo "第 8 步：确认网站已经恢复。"
for _ in {1..20}; do
    if curl --fail --silent -H "Host: $HEALTH_HOST" http://127.0.0.1:8000/healthz >/dev/null; then
        trap - ERR
        cleanup_test_db
        echo "更新完成，网站、数据库和测试均正常。"
        exit 0
    fi
    sleep 1
done

echo "新版本没有通过健康检查。"
false
