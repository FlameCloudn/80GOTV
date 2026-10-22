"""批量处理已有队标：去背景、裁边、居中成统一规格（和上传时的自动处理完全一样）。

默认只检查、不改动任何东西：
    python scripts/process_team_logos.py
确认报告没问题后，真正处理：
    python scripts/process_team_logos.py --apply

· 处理前把原图备份到 instance/team_logo_originals/；已有备份时直接从备份重新处理，重复运行也安全。
· 处理后的文件沿用原来的文件名（非 PNG 的改存成 .png 并同步修改数据库），数据库里的队标引用不变。
· 队伍资料没有队标、或指向的队标文件不存在，而同名报名队伍有队标时，--apply 会改用报名队标。
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import get_db  # noqa: E402
from services.team_logo_service import (  # noqa: E402
    TEAM_LOGO_DIR,
    logo_relative_path,
    original_logo_path,
    save_processed_logo,
)


def collect_references(conn):
    """数据库里所有引用队标的地方：队伍资料和赛事报名。"""
    refs = []
    for row in conn.execute("SELECT id, name, logo FROM teams WHERE COALESCE(logo, '') != ''"):
        refs.append({"table": "teams", "id": row["id"], "name": row["name"], "value": row["logo"]})
    rows = conn.execute(
        """SELECT id, team_name, team_logo FROM event_registrations
           WHERE COALESCE(team_logo, '') != ''"""
    )
    for row in rows:
        refs.append(
            {
                "table": "event_registrations",
                "id": row["id"],
                "name": row["team_name"],
                "value": row["team_logo"],
            }
        )
    for ref in refs:
        path = logo_relative_path(ref["value"])
        is_local = path.startswith(f"{TEAM_LOGO_DIR}/") and path.count("/") == 1
        ref["filename"] = path.split("/", 1)[1] if is_local else ""
    return refs


def collect_teams_without_logo(conn):
    """队伍资料里还没填队标的队伍。"""
    rows = conn.execute("SELECT id, name FROM teams WHERE COALESCE(logo, '') = ''")
    return [
        {"table": "teams", "id": row["id"], "name": row["name"], "value": "", "filename": ""}
        for row in rows
    ]


def logo_file(root, filename):
    return root / "static" / "uploads" / TEAM_LOGO_DIR / filename


def process_one(root, filename):
    """处理一个队标文件，返回处理后的文件名；失败返回 None。"""
    backup = Path(original_logo_path(str(root), filename))
    source_path = backup if backup.is_file() else logo_file(root, filename)
    target = Path(filename).stem + ".png"
    try:
        with Image.open(source_path) as source:
            return save_processed_logo(source, str(root), filename=target)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        print(f"  处理失败 {filename}：{error}")
        return None


def update_reference(conn, ref, new_value):
    column = "logo" if ref["table"] == "teams" else "team_logo"
    conn.execute(f"UPDATE {ref['table']} SET {column}=? WHERE id=?", (new_value, ref["id"]))


def stored_value(ref, filename):
    """按原表的写法生成新的引用：队伍资料带 team_logos/ 前缀，报名表只存文件名。"""
    return f"{TEAM_LOGO_DIR}/{filename}" if ref["table"] == "teams" else filename


def process_existing(conn, root, refs, apply):
    """处理所有存在的队标文件，返回 (处理数, 失败数)。"""
    done = failed = 0
    for filename in sorted({ref["filename"] for ref in refs if ref["filename"]}):
        if not logo_file(root, filename).is_file():
            continue
        if not apply:
            print(f"  将处理 {filename}")
            continue
        new_name = process_one(root, filename)
        if not new_name:
            failed += 1
            continue
        done += 1
        if new_name != filename:
            for ref in refs:
                if ref["filename"] == filename:
                    update_reference(conn, ref, stored_value(ref, new_name))
                    ref["filename"] = new_name
            logo_file(root, filename).unlink(missing_ok=True)
        print(f"  已处理 {filename}")
    return done, failed


def find_registration_logo(root, refs, team_name):
    """找同名（不分大小写、忽略首尾空格）报名队伍的队标，文件必须真的存在。"""
    key = str(team_name or "").strip().casefold()
    for ref in refs:
        if ref["table"] != "event_registrations" or not ref["filename"]:
            continue
        same_name = str(ref["name"] or "").strip().casefold() == key
        if same_name and logo_file(root, ref["filename"]).is_file():
            return ref["filename"]
    return None


def repair_missing(conn, root, refs, empty_teams, apply):
    """队伍资料没有队标、或指向的文件不存在时，改用同名报名队伍的队标。返回补齐数。"""
    repaired = 0
    broken = [
        ref
        for ref in refs
        if ref["table"] == "teams"
        and ref["filename"]
        and not logo_file(root, ref["filename"]).is_file()
    ]
    for ref in broken + empty_teams:
        reason = "的队标文件不存在" if ref["filename"] else "还没有队标"
        filename = find_registration_logo(root, refs, ref["name"])
        if not filename:
            if ref["filename"]:
                print(f"  队伍「{ref['name']}」{reason}，也没有同名报名队标，需要重新上传")
            continue
        print(f"  队伍「{ref['name']}」{reason} → 改用报名队标 {filename}")
        if apply:
            update_reference(conn, ref, stored_value(ref, filename))
            repaired += 1
    return repaired


def main():
    parser = argparse.ArgumentParser(description="批量处理已有队标（默认只检查）")
    parser.add_argument("--apply", action="store_true", help="真正处理并保存")
    parser.add_argument("--root", default=str(ROOT), help="网站根目录（默认是本项目）")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    conn = get_db()
    try:
        refs = collect_references(conn)
        empty_teams = collect_teams_without_logo(conn)
        print(f"数据库里共有 {len(refs)} 处队标引用。")
        print("一、处理已有队标：")
        done, failed = process_existing(conn, root, refs, args.apply)
        print("二、补齐队伍资料里缺的队标：")
        repaired = repair_missing(conn, root, refs, empty_teams, args.apply)
        if args.apply:
            conn.commit()
            print(f"完成：处理 {done} 个，失败 {failed} 个，补齐队伍队标 {repaired} 处。")
        else:
            print("以上只是检查结果，没有改动任何文件。确认后加 --apply 运行。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
