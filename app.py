"""80GOTV 本地开发启动入口。"""

import logging
import os

from src.website.app import create_app
from src.website.runtime.config import validate_production_config
from src.website.runtime.schema import init_tables

validate_production_config()
app = create_app()


def _local_server_options():
    """本地运行：默认 5000 端口；想同时开两份网站时，用环境变量 PORT 换一个端口。"""
    return {
        "debug": False,
        "use_reloader": False,
        "port": int(os.environ.get("PORT") or 5000),
        "host": "127.0.0.1",
    }


if __name__ == "__main__":
    import threading
    from logging.handlers import RotatingFileHandler

    from src.website.runtime.storage import site_paths

    # 日志写到文件，方便调试 — 最多 5MB，保留 3 个历史文件
    log_dir = site_paths().root / "logs"
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

    # 本地开发：改完模板后刷新页面就能看到效果，不用重启。
    # 公网由 wsgi.py 启动，不会走到这里，所以不影响线上性能。
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True

    from src.website.runtime.worker import run_background

    shutdown = threading.Event()
    worker = threading.Thread(
        target=run_background, args=(shutdown,), name="site-worker", daemon=True
    )
    worker.start()
    try:
        app.run(**_local_server_options())
    finally:
        shutdown.set()
        worker.join()
