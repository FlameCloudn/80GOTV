"""Create the private-preview event without filling in any competition details."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import get_db  # noqa: E402
from services.arg_event_service import ensure_arg_event  # noqa: E402


def main():
    conn = get_db()
    try:
        event_id = ensure_arg_event(conn)
        conn.commit()
        print(f"特殊赛事已准备，编号：{event_id}；仅填写指定名称、状态和赛制。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
