"""公网数据直播后台进程。"""

import signal
import threading

from models import init_tables
from utils.live_poller import start_poller, stop_poller

_shutdown = threading.Event()


def _request_shutdown(_signum, _frame):
    _shutdown.set()


def main():
    init_tables()
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    start_poller()
    print("数据直播后台程序已启动。", flush=True)
    _shutdown.wait()
    stop_poller()
    print("数据直播后台程序已停止。", flush=True)


if __name__ == "__main__":
    main()
