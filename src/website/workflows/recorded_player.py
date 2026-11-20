"""关联录像和导播上报的选手；新身份同时建立待认领账号与选手档案。"""

import secrets

from werkzeug.security import generate_password_hash

from src.website.domains.directory.player_service import record_player_nickname
from src.website.domains.identity.steam_profile_service import enrich_player_from_steam


def resolve_recorded_player(conn, stat):
    """从 demo 数据自动创建用户和选手记录，返回 dict 或 None"""
    name = stat["name"].strip()
    steam_id = str(stat["steam_id"])

    if not name or not steam_id:
        return None

    existing = conn.execute(
        "SELECT id, nickname FROM players WHERE steam_id=?", (steam_id,)
    ).fetchone()
    if existing:
        record_player_nickname(conn, existing["id"], existing["nickname"], "website")
        record_player_nickname(conn, existing["id"], name, "demo")
        enrich_player_from_steam(conn, existing["id"])
        return {
            "id": existing["id"],
            "nickname": existing["nickname"],
            "team_name": None,
            "team_id": None,
            "_new": False,
        }

    username = name[:20]
    base = username
    for attempt in range(10):
        try:
            conn.execute(
                """INSERT INTO users(
                       username, password_hash, steam_id64,
                       is_placeholder, approval_status
                   ) VALUES(?,?,?,1,'pending')""",
                (username, generate_password_hash(secrets.token_hex(8)), steam_id),
            )
            break
        except Exception as exc:
            # Only a taken username can be fixed by choosing another name.
            if "unique constraint" not in str(exc).lower():
                raise
            if not conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                raise
            username = (
                f"{base[:15]}_{steam_id[-4:]}"
                if attempt == 0
                else f"{base[:12]}_{steam_id[-6:]}_{attempt}"
            )
    else:
        raise ValueError("无法为录像选手创建账号，未导入本次数据，请检查后重试")

    conn.execute("INSERT INTO players(nickname, steam_id) VALUES(?,?)", (name, steam_id))
    player_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    record_player_nickname(conn, player_id, name, "demo")
    enrich_player_from_steam(conn, player_id)
    return {"id": player_id, "nickname": name, "team_name": None, "team_id": None, "_new": True}
