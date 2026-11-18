"""Small named, synthetic event for a local operator; never seeds an old event."""

from contextlib import closing

from . import registration
from .sandbox import connect
from .storage import write

SLUG = "entrant-practice"
ADMIN = "entrant-demo-admin"
CAPTAIN = "entrant-demo-captain"


def seed(workspace, *, now: int, duration: int):
    with closing(connect(workspace)) as conn, write(conn):
        found = conn.execute(
            "SELECT e.id FROM events e JOIN entrant_event ee ON e.id=ee.event_id WHERE e.slug=?",
            (SLUG,),
        ).fetchone()
        if found:
            return found[0]
        admin = conn.execute(
            "INSERT INTO admins(username,password_hash) VALUES(?,'disabled') RETURNING id", (ADMIN,)
        ).fetchone()[0]
        club = conn.execute(
            "INSERT INTO teams(name,short_name) VALUES('青岚俱乐部','QL') RETURNING id"
        ).fetchone()[0]
        event = registration.create_event(
            conn,
            "80GOTV 报名练习赛",
            SLUG,
            now + duration,
            admin_id=admin,
            now=now,
            starts_at=now + 86400,
            ends_at=now + 172800,
        )
        accounts = []
        for i, name in enumerate(
            (
                "山风",
                "极光",
                "星野",
                "砂砾",
                "墨点",
                "初霁",
                "北原",
                "清河",
                "落日",
                "澄空",
                "弦月",
                "远帆",
                "青石",
            )
        ):
            steam = str(70000000000000000 + i)
            username = CAPTAIN if not i else "entrant-demo-" + str(i)
            accounts.append(
                conn.execute(
                    """INSERT INTO users(username,password_hash,steam_id64,group_username,is_bashizhong_student)
                         VALUES(?,'disabled',?,?,1)""",
                    (username, steam, name),
                ).lastrowid
            )
            conn.execute(
                """INSERT INTO players(nickname,steam_id,cs2_playtime_minutes,is_bashizhong_student)
                         VALUES(?,?,?,1)""",
                (name, steam, None if i == 1 else i * 83),
            )
        group = registration.create_group(conn, event, accounts[0], "青岚", now=now)
        registration.link_club(conn, event, group, club, admin_id=admin, now=now)
        for slot in (1, 2):
            registration.join_group(conn, event, group, accounts[slot], slot, now=now)
        for account in accounts[3:11]:
            registration.enroll(conn, event, account, "individual", now=now)
        registration.enroll(conn, event, accounts[11], "independent_reserve", now=now)
        # The last synthetic account is deliberately free to try the initial reserve form.
        return event
