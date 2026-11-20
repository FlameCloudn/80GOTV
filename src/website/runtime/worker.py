"""本地网站和独立后台进程共用的现场轮询、报名截止任务。"""

import logging
import signal
import sqlite3
import threading
from contextlib import closing

from src.website.domains.events.formation import run_due_events_once

from .config import validate_production_config
from .database import get_db
from .live_poller import start_poller, stop_poller


def run_background(shutdown):
    start_poller()
    try:
        while not shutdown.is_set():
            try:
                with closing(get_db()) as conn:
                    formed, blocked = run_due_events_once(conn)
                if formed or blocked:
                    logging.getLogger("80gotv").info(
                        "赛事报名截止：已办理 %d 届，待处理赛事 %s", len(formed), list(blocked)
                    )
            except sqlite3.OperationalError:
                logging.getLogger("80gotv").exception("本次截止任务未完成，下轮重新检查")
            shutdown.wait(30)
    finally:
        stop_poller()


def main():
    validate_production_config()
    shutdown = threading.Event()

    def request_shutdown(_signum, _frame):
        shutdown.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    print("数据直播后台程序已启动。", flush=True)
    run_background(shutdown)
    print("数据直播后台程序已停止。", flush=True)


if __name__ == "__main__":
    main()
