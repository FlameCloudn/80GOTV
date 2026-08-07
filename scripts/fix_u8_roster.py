"""One-off data fix: move lan1193 (player 8) onto the U8 team and replace
player 29 (old member) in every U8 match roster. Creates a timestamped
database copy before making changes."""

import datetime
import json
import shutil
import sqlite3

db = "/srv/80gotv/data/cs_site.db"
ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
backup = db + ".before-lan-" + ts
shutil.copy2(db, backup)

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

team_id = cur.execute("SELECT team1_id FROM matches WHERE id=20").fetchone()["team1_id"]
cur.execute("UPDATE players SET team_id=? WHERE id=8", (team_id,))
cur.execute("UPDATE players SET team_id=NULL WHERE id=29")

rows = cur.execute("SELECT id, team1_players FROM matches WHERE team1_id=?", (team_id,)).fetchall()
for match in rows:
    ids = []
    if match["team1_players"]:
        try:
            ids = json.loads(match["team1_players"])
        except (TypeError, ValueError, json.JSONDecodeError):
            ids = []
    if not ids:
        ids = [
            row["id"]
            for row in cur.execute(
                "SELECT id FROM players WHERE team_id=? ORDER BY nickname COLLATE NOCASE LIMIT 5",
                (team_id,),
            )
        ]
    if 29 in ids:
        ids = [8 if value == 29 else value for value in ids]
    if 8 not in ids:
        ids = ids[:4] + [8]
    cur.execute(
        "UPDATE matches SET team1_players=? WHERE id=?",
        (json.dumps(ids), match["id"]),
    )

conn.commit()
print("backup=", backup)
print("team_id=", team_id)
for match in cur.execute("SELECT id, team1_players FROM matches WHERE team1_id=?", (team_id,)):
    print("match", match["id"], match["team1_players"])
conn.close()
