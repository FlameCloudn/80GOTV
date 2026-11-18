"""Local operating commands for the opt-in slice; no server config or scheduled task is installed."""

import argparse
import getpass
import json
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from . import formation, sample
from .sandbox import DEFAULT_WORKSPACE, ROOT, connect, create_app, initialize, remove
from .storage import SliceError, write
from .worker import process_due


def main():
    cli = argparse.ArgumentParser(description="80GOTV 参赛生命周期隔离开发")
    cli.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help="本切片的新空目录；绝不接受数据库路径",
    )
    sub = cli.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="从空目录建立隔离库，已有本切片结构不重复迁移")
    sub.add_parser("remove", help="仅删除本工具独占的已标记沙盒，不删除未知文件")
    sub.add_parser("due", help="处理一次所有到期报名")
    demo = sub.add_parser("demo", help="建立一届可复跑的合成演示赛事")
    demo.add_argument("--seconds", type=int, default=120, help="演示报名在多少秒后截止")
    watch = sub.add_parser("watch", help="独立循环处理到期报名，不依赖访问页面")
    watch.add_argument("--interval", type=float, default=2)
    serve = sub.add_parser("serve", help="同时启动本机预览和一份独立的截止办理进程")
    serve.add_argument("--port", type=int, default=5091)
    for name in ("status", "confirm"):
        sub.add_parser(name).add_argument("--event", type=int, required=True)
    password = sub.add_parser(
        "set-demo-password", help="只给演示账号设置本机密码；不在命令行传递密码"
    )
    password.add_argument(
        "--account", choices=(sample.ADMIN, sample.CAPTAIN, "entrant-demo-12"), required=True
    )
    args = cli.parse_args()
    workspace = args.workspace
    if args.command == "remove":
        remove(workspace)
        print("已删除本次隔离环境。")
        return 0
    if args.command in ("init", "demo"):
        initialize(workspace)
    elif not (workspace / ".entrant-sandbox").is_file():
        cli.error("请先使用 init 或 demo 建立隔离环境")
    else:
        # Disable the base site's dotenv and network credentials before importing any legacy helper.
        from .sandbox import _load_config

        _load_config()
    if args.command == "init":
        print("隔离数据库已就绪。")
    elif args.command == "demo":
        if args.seconds < 1:
            cli.error("截止时间须在至少一秒后")
        event = sample.seed(workspace, now=int(time.time()), duration=args.seconds)
        print(f"演示赛事 {event}：/events/{sample.SLUG}；报名、候补与队伍读取均使用隔离数据。")
    elif args.command in ("watch", "due"):
        if args.command == "watch" and not 0.1 <= args.interval <= 3600:
            cli.error("轮询间隔须在 0.1 到 3600 秒之间")
        previous = None
        while True:
            done, blocked = process_due(workspace)
            if done or (blocked and blocked != previous) or args.command == "due":
                print(
                    f"已完成 {len(done)} 届分队，本轮待处理：{json.dumps(blocked, ensure_ascii=False)}",
                    flush=True,
                )
            if args.command == "due":
                return int(bool(blocked))
            previous = blocked
            time.sleep(args.interval)
    elif args.command == "serve":
        from werkzeug.serving import make_server

        app = create_app(workspace)
        server = make_server("127.0.0.1", args.port, app, threaded=True)
        child = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "entrant_slice",
                "--workspace",
                str(workspace.resolve()),
                "watch",
            ],
            cwd=ROOT,
        )
        print(
            f"本机隔离页面：http://127.0.0.1:{server.server_port}/events；按 Ctrl+C 停止。",
            flush=True,
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
            child.terminate()
            child.wait()
    elif args.command == "set-demo-password":
        from werkzeug.security import generate_password_hash

        passwd = getpass.getpass("为这个本机演示账号设置密码（输入不显示）：")
        if len(passwd) < 8:
            cli.error("请使用至少八位的临时密码")
        with closing(connect(workspace)) as conn, write(conn):
            table = "admins" if args.account == sample.ADMIN else "users"
            if not conn.execute(
                f"UPDATE {table} SET password_hash=? WHERE username=?",
                (generate_password_hash(passwd), args.account),
            ).rowcount:
                raise SliceError("演示账号不存在，请先运行 demo")
        print("本机演示账号密码已设置。")
    elif args.command in ("status", "confirm"):
        with closing(connect(workspace)) as conn:
            if args.command == "confirm":
                from werkzeug.security import check_password_hash

                username = input("本机管理员账号：").strip()
                passwd = getpass.getpass("本机管理员密码（输入不显示）：")
                row = conn.execute(
                    "SELECT id,password_hash FROM admins WHERE username=?", (username,)
                ).fetchone()
                if not row or not check_password_hash(row["password_hash"], passwd):
                    raise SliceError("管理员身份未通过", 403)
                batch = conn.execute(
                    "SELECT formation_revision FROM formation_batch WHERE event_id=?", (args.event,)
                ).fetchone()
                rosters = [
                    formation.get_roster(conn, args.event, e[0])
                    for e in conn.execute(
                        "SELECT event_entrant_id FROM event_entrant WHERE event_id=?", (args.event,)
                    )
                ]
                if not batch or not rosters:
                    raise SliceError("没有已分出的参赛队可供确认")
                for r in rosters:
                    print(f"参赛方 {r['event_entrant_id']}：{r['current_player_ids']}")
                if input("确认以上全部初始五人？输入 YES：").strip() != "YES":
                    return 0
                with write(conn):
                    formation.confirm_initial_rosters(
                        conn,
                        args.event,
                        [r["event_entrant_id"] for r in rosters],
                        expected_revision=batch[0],
                        admin_id=row["id"],
                        now=int(time.time()),
                    )
            event = conn.execute(
                "SELECT * FROM entrant_event WHERE event_id=?", (args.event,)
            ).fetchone()
            if not event:
                raise SliceError("没有该届隔离赛事", 404)
            rosters = [
                formation.get_roster(conn, args.event, e[0])
                for e in conn.execute(
                    "SELECT event_entrant_id FROM event_entrant WHERE event_id=?", (args.event,)
                )
            ]
            print(
                json.dumps({"赛事": dict(event), "参赛名单": rosters}, ensure_ascii=False, indent=2)
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SliceError, ValueError) as exc:
        print(f"没有执行：{exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass
