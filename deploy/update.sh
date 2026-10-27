#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/srv/80gotv/app}"
VENV_DIR="${VENV_DIR:-/srv/80gotv/venv}"
BACKUP_DIR="${BACKUP_DIR:-/srv/80gotv/backups}"
APP_USER="${APP_USER:-80gotv}"
BRANCH="${1:-main}"
ENV_FILE="${ENV_FILE:-/srv/80gotv/data/.env}"
HEALTH_HOST="${HEALTH_HOST:-80gotv.cn}"
OLD_REV=""
TARGET_REV=""
UPDATED=0
WRITES_STOPPED=0
DEPENDENCIES_CHANGED=0
DATABASE_MIGRATION_STARTED=0
WRITES_RESUMED=0
TEST_DB=""
CHECK_DIR=""
CHECK_PYTHON=""
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

cleanup_candidate() {
    if [[ -n "$CHECK_DIR" ]]; then
        if [[ ! "$CHECK_DIR" =~ ^/tmp/80gotv-update-[[:alnum:]]+$ || -L "$CHECK_DIR" ]]; then
            echo "临时目录位置异常，未自动删除：$CHECK_DIR"
            return 1
        fi
        run_as_app_user rm -rf -- "$CHECK_DIR"
        CHECK_DIR=""
    fi
}

rollback() {
    local exit_code=$?
    trap - ERR
    cd "$APP_DIR"
    if [[ "$WRITES_STOPPED" -eq 1 && -n "$OLD_REV" ]]; then
        echo "更新失败，正在退回上一个可用版本：$OLD_REV"
        systemctl stop 80gotv-web 80gotv-live || true
        if [[ "$DATABASE_MIGRATION_STARTED" -eq 1 && "$WRITES_RESUMED" -eq 0 \
              && -n "$BACKUP_FILE" && -f "$BACKUP_FILE" ]]; then
            if ! run_as_app_user env "${APP_ENV[@]}" \
                "$CHECK_PYTHON" "$CANDIDATE_DIR/scripts/restore_site.py" \
                "$BACKUP_FILE" --database-only "$DATABASE_PATH_VALUE"; then
                echo "警告：数据库自动恢复失败，请使用备份手动恢复：$BACKUP_FILE"
            fi
        elif [[ "$DATABASE_MIGRATION_STARTED" -eq 1 && "$WRITES_RESUMED" -eq 1 ]]; then
            echo "新版本已启动过，本次只退回代码，不覆盖数据库，以免丢失启动后新增的资料。"
        fi
        if [[ "$UPDATED" -eq 1 ]]; then
            if ! run_as_app_user git -C "$APP_DIR" switch --detach "$OLD_REV"; then
                echo "旧代码未能恢复，已保留资料和临时检查目录，请先人工检查。"
                exit "$exit_code"
            fi
        fi
        if [[ "$DEPENDENCIES_CHANGED" -eq 1 ]]; then
            if ! run_as_app_user "$VENV_DIR/bin/python" -m pip install \
                -r "$CHECK_DIR/original-requirements.txt"; then
                echo "旧程序依赖未能恢复，已保留资料和临时检查目录，请先人工检查。"
                exit "$exit_code"
            fi
        fi
        systemctl start 80gotv-web 80gotv-live
        if curl --fail --silent --retry 20 --retry-delay 1 -H "Host: $HEALTH_HOST" http://127.0.0.1:8000/healthz >/dev/null; then
            echo "已恢复旧代码。本轮临时备份（如有）保留在：$BACKUP_DIR"
        else
            echo "旧版本也未恢复，请保留现场并查看 deploy/README.md 的恢复说明。"
        fi
    else
        echo "新版本检查未通过，正式网站代码、模板和运行环境均未切换。"
    fi
    cleanup_candidate || true
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

echo "第 1 步：下载新代码。"
run_as_app_user git -C "$APP_DIR" fetch origin "$BRANCH"
TARGET_REV="$(run_as_app_user git -C "$APP_DIR" rev-parse "origin/$BRANCH")"
run_as_app_user git -C "$APP_DIR" merge-base --is-ancestor "$OLD_REV" "$TARGET_REV"

echo "第 2 步：在独立目录准备新版本，正式网站继续使用旧版。"
CHECK_DIR="$(run_as_app_user mktemp -d /tmp/80gotv-update-XXXXXXXX)"
if [[ ! "$CHECK_DIR" =~ ^/tmp/80gotv-update-[[:alnum:]]+$ || -L "$CHECK_DIR" ]]; then
    echo "更新已停止：未能建立预期的独立检查目录。"
    false
fi
CANDIDATE_DIR="$CHECK_DIR/source"
CHECK_PYTHON="$CHECK_DIR/venv/bin/python"
TEST_DB="$CHECK_DIR/test.db"
run_as_app_user mkdir "$CANDIDATE_DIR"
run_as_app_user git -C "$APP_DIR" archive "$TARGET_REV" \
    | run_as_app_user tar -xf - -C "$CANDIDATE_DIR"
run_as_app_user "$VENV_DIR/bin/python" -m pip list --format=freeze \
    --exclude pip --exclude setuptools --exclude wheel --disable-pip-version-check \
    > "$CHECK_DIR/original-requirements.txt"
run_as_app_user "$VENV_DIR/bin/python" -m venv "$CHECK_DIR/venv"
run_as_app_user "$CHECK_PYTHON" -m pip install -r "$CANDIDATE_DIR/requirements-production.txt"
run_as_app_user "$CHECK_PYTHON" -m pip list --format=freeze \
    --exclude pip --exclude setuptools --exclude wheel --disable-pip-version-check \
    > "$CHECK_DIR/checked-requirements.txt"

echo "第 3 步：检查 Python 文件。"
run_as_app_user "$CHECK_PYTHON" -m compileall -q \
    "$CANDIDATE_DIR/app.py" "$CANDIDATE_DIR/web_app.py" "$CANDIDATE_DIR/wsgi.py" "$CANDIDATE_DIR/live_worker.py" \
    "$CANDIDATE_DIR/blueprints" "$CANDIDATE_DIR/routes" "$CANDIDATE_DIR/services" "$CANDIDATE_DIR/utils"
bash -n "$CANDIDATE_DIR/deploy/update.sh"

echo "第 4 步：使用临时数据库运行全部测试。"
TEST_MODULES=()
while IFS= read -r -d '' TEST_FILE; do
    TEST_MODULE="${TEST_FILE#"$CANDIDATE_DIR"/}"
    TEST_MODULE="${TEST_MODULE%.py}"
    TEST_MODULE="${TEST_MODULE//\//.}"
    TEST_MODULES+=("$TEST_MODULE")
done < <(find "$CANDIDATE_DIR/tests" -type f -name "test_*.py" -print0 | sort -z)
if [[ "${#TEST_MODULES[@]}" -eq 0 ]]; then
    echo "更新已停止：没有找到可运行的测试。"
    false
fi
cd "$CANDIDATE_DIR"
run_as_app_user env DATABASE_PATH="$TEST_DB" FLASK_ENV=testing \
    SMTP_HOST= SMTP_USERNAME= SMTP_PASSWORD= \
    SECRET_KEY=deployment-test-secret SESSION_COOKIE_SECURE=false \
    "$CHECK_PYTHON" "$CANDIDATE_DIR/scripts/build_frontend_images.py"
run_as_app_user env DATABASE_PATH="$TEST_DB" FLASK_ENV=testing \
    TURSO_URL= TURSO_TOKEN= SECRET_KEY=deployment-test-secret SESSION_COOKIE_SECURE=false \
    SMTP_HOST= SMTP_USERNAME= SMTP_PASSWORD= \
    TRUSTED_HOSTS="localhost,127.0.0.1,80gotv.cn,www.80gotv.cn,8.222.223.38,192.168.1.20,gaming-pc,example.trycloudflare.com,demo.trycloudflare.com" \
    SESSION_COOKIE_DOMAIN= SESSION_COOKIE_NAME=80gotv_test_session \
    "$CHECK_PYTHON" -m unittest "${TEST_MODULES[@]}"
cd "$APP_DIR"
if [[ "$(run_as_app_user git -C "$APP_DIR" rev-parse HEAD)" != "$OLD_REV" \
      || "$(run_as_app_user git -C "$APP_DIR" rev-parse "origin/$BRANCH")" != "$TARGET_REV" \
      || -n "$(run_as_app_user git -C "$APP_DIR" status --porcelain)" ]]; then
    echo "更新已停止：检查期间正式代码或待更新版本发生变化，未替换网站。"
    false
fi

echo "第 5 步：暂停写入，保存用于数据库回退的最新快照。"
WRITES_STOPPED=1
systemctl stop 80gotv-live 80gotv-web
if ! BACKUP_FILE="$(run_as_app_user env "${APP_ENV[@]}" \
    "$VENV_DIR/bin/python" "$APP_DIR/scripts/backup_site.py" \
    --output-dir "$BACKUP_DIR" --print-path-only)"; then
    echo "更新已停止：最新资料快照未保存，正式数据库未升级。"
    false
fi
echo "停止写入后的备份已保存并检查：$BACKUP_FILE"

echo "第 6 步：切换已检查的代码和程序，再升级正式数据库。"
UPDATED=1
run_as_app_user git -C "$APP_DIR" merge --ff-only "$TARGET_REV"
DEPENDENCIES_CHANGED=1
run_as_app_user "$VENV_DIR/bin/python" -m pip install -r "$CHECK_DIR/checked-requirements.txt"
run_as_app_user env "${APP_ENV[@]}" \
    "$VENV_DIR/bin/python" "$APP_DIR/scripts/build_frontend_images.py"
DATABASE_MIGRATION_STARTED=1
run_as_app_user env "${APP_ENV[@]}" \
    "$VENV_DIR/bin/python" "$APP_DIR/scripts/migrate_database.py"

echo "第 7 步：启动网站和数据直播。"
# 启动可能部分成功；从这里开始，即使检查失败也不能用快照覆盖新资料。
WRITES_RESUMED=1
systemctl start 80gotv-web 80gotv-live

echo "第 8 步：确认网站已经恢复。"
for _ in {1..20}; do
    if curl --fail --silent -H "Host: $HEALTH_HOST" http://127.0.0.1:8000/healthz >/dev/null; then
        trap - ERR
        cleanup_candidate
        echo "更新完成，网站、数据库和测试均正常。"
        exit 0
    fi
    sleep 1
done

echo "新版本没有通过健康检查。"
false
