"""Pass the original host's actual JSON to the unmodified director functions."""

import json
import secrets
import subprocess
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from config import Config
from tests import test_host_prematch_chain


class HostDirectorConsumerTests(unittest.TestCase):
    def test_sources_and_sync_use_host_responses_without_confirming_live_forwarding(self):
        chain = test_host_prematch_chain.HostPrematchChainTests()
        self.addCleanup(chain.doCleanups)
        chain.setUp()
        with patch.object(Config, "STEAM_WEB_API_KEY", ""):
            initial_match = chain.prepare_through_host()

        # Schedule the same teams in reverse sides via the real admin form, not a rewritten response.
        later = datetime.fromisoformat(chain.match["match_time"]) + timedelta(hours=1)
        players = {
            f"side{side}_p{slot}": player_id
            for side, roster in enumerate(reversed(chain.lineups), 1)
            for slot, player_id in enumerate(roster["current_player_ids"])
        }
        added = chain.post(
            chain.admin,
            "/admin/matches/add",
            data={
                "event_id": chain.event_id,
                "match_time": later.isoformat(),
                "bo_format": "BO1",
                "side1_type": "players",
                "side2_type": "players",
                **players,
            },
        )
        self.assertEqual(added.status_code, 302, added.get_data(as_text=True))
        swapped_match = chain.db.execute(
            "SELECT id FROM matches WHERE event_id=? AND id<>?",
            (chain.event_id, initial_match),
        ).fetchone()[0]
        self.assertEqual(
            chain.post(chain.admin, f"/admin/matches/{swapped_match}/freeze-rosters").status_code,
            302,
        )

        old_event = chain.db.execute(
            "INSERT INTO events(name,slug) VALUES('旧版赛事样例','legacy-director-event')",
        ).lastrowid
        old_registration = chain.db.execute(
            "INSERT INTO event_registrations(event_id,team_name,creator_user_id) VALUES(?, '旧版报名队', ?)",
            (old_event, chain.accounts[0]),
        ).lastrowid
        chain.db.execute(
            """INSERT INTO event_registration_slots(registration_id,slot_index,user_id,player_name,steam_id)
            SELECT ?,0,id,username,steam_id64 FROM users WHERE id=?""",
            (old_registration, chain.accounts[0]),
        )
        chain.db.commit()

        incoming = {}

        def capture(method, path, response):
            self.assertTrue(response.is_json, path)
            incoming[f"{method} {path}"] = {
                "status": response.status_code,
                "json": response.get_json(),
            }

        for path in (
            "/api/broadcast/matches",
            "/api/broadcast/events",
            f"/api/broadcast/events/{old_event}",
            f"/api/broadcast/events/{chain.event_id}",
            f"/api/broadcast/matches/{initial_match}",
            f"/api/broadcast/matches/{swapped_match}",
        ):
            capture("GET", path, chain.visitor.get(path))
        fixture_token = secrets.token_urlsafe(18)
        with patch.object(Config, "GSI_TOKEN", fixture_token):
            headers = {"X-80GOTV-Token": fixture_token}
            probe_path = f"/api/broadcast/matches/{initial_match}/connection-test"
            live_path = f"/api/broadcast/matches/{initial_match}/live"
            probe = chain.visitor.get(probe_path, headers=headers)
            self.assertFalse(probe.get_json()["ready_for_start"])
            capture("GET", probe_path, probe)
            rejected = chain.visitor.post(
                live_path, headers=headers, json={"map": {"name": "de_anubis"}}
            )
            self.assertEqual(rejected.status_code, 409)
            capture("POST", live_path, rejected)
        self.assertEqual(chain.db.execute("SELECT COUNT(*) FROM live_match_data").fetchone()[0], 0)

        expected_teams = [
            {
                "registration": roster["registration_id"],
                "steam": [
                    chain.db.execute("SELECT steam_id FROM players WHERE id=?", (pid,)).fetchone()[
                        0
                    ]
                    for pid in roster["initial_player_ids"]
                ],
            }
            for roster in chain.lineups
        ]
        root = Path(__file__).resolve().parents[1]
        script = "tests/acceptance/slice-02-host-integration/director_consumer.cjs"
        process = subprocess.run(
            ["node", "--permission", "--allow-fs-read=.", script],
            cwd=root,
            input=json.dumps(
                {
                    "responses": incoming,
                    "match": initial_match,
                    "swapped": swapped_match,
                    "event": chain.event_id,
                    "legacy": old_event,
                    "legacyRegistration": old_registration,
                    "teams": expected_teams,
                    "fixtureToken": fixture_token,
                }
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("就绪和转发边界已核对", process.stdout)
