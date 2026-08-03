"""80GOTV 启动入口。具体页面按功能放在 routes/ 目录。"""

import logging

from blueprints.admin import admin_bp
from config import validate_production_config
from models import init_tables

# 导入后，各模块会把自己的页面地址注册到 app。
from routes import (  # noqa: F401,E402
    auth,
    bp,
    broadcast,
    comments,
    events,
    feedback,
    forum,
    front_api,
    games,
    guess_player,
    home,
    live,
    live_ingest,
    map_quiz,
    match_assets,
    matches,
    news,
    notifications,
    player_bingo,
    players,
    search,
    sitemap,
    stats,
)
from utils.live_poller import start_poller
from web_app import app

validate_production_config()
app.register_blueprint(admin_bp)


def _local_server_options():
    return {
        "debug": False,
        "use_reloader": False,
        "port": 5000,
        "host": "127.0.0.1",
    }


if __name__ == "__main__":
    import os
    from logging.handlers import RotatingFileHandler

    from config import BASE_DIR

    # 日志写到文件，方便调试 — 最多 5MB，保留 3 个历史文件
    log_dir = os.path.join(BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "flask.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    init_tables()
    start_poller()

    # 启动快速自检（不阻塞，错误只警告）
    import subprocess
    import sys as _sys
    import threading

    def _startup_check():
        try:
            r = subprocess.run(
                [_sys.executable, ".claude/scripts/verify_changes.py"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode != 0:
                logging.warning("启动自检未通过: %s", r.stdout.strip()[-200:])
            else:
                logging.info("启动自检通过")
        except Exception as e:
            logging.warning("启动自检失败: %s", e)

    threading.Thread(target=_startup_check, daemon=True).start()

    app.run(**_local_server_options())
