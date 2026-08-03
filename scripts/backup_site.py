"""Create or verify a safe 80GOTV data backup."""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import BASE_DIR
from services.backup_service import create_backup_file, verify_backup


def main():
    parser = argparse.ArgumentParser(description="备份 80GOTV 网站资料")
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("BACKUP_DIR", os.path.join(BASE_DIR, ".backups")),
        help="备份保存目录",
    )
    parser.add_argument("--full", action="store_true", help="同时备份大型 Demo 文件")
    parser.add_argument(
        "--keep",
        type=int,
        help="只保留同类型的最近 N 份本站备份；不填写时不清理",
    )
    parser.add_argument("--verify", metavar="ZIP", help="只检查一个已有备份")
    parser.add_argument(
        "--print-path-only",
        action="store_true",
        help="成功后仅输出备份绝对路径，供更新脚本读取",
    )
    args = parser.parse_args()
    if args.verify:
        verify_backup(args.verify)
        print(f"备份检查通过：{Path(args.verify).resolve()}")
        return
    if args.keep is not None and args.keep < 1:
        parser.error("--keep 必须至少为 1")
    output = create_backup_file(
        args.output_dir,
        include_demos=args.full,
        keep=args.keep,
    )
    if args.print_path_only:
        print(output)
    else:
        print(f"备份完成并已检查：{output}")


if __name__ == "__main__":
    main()
