import json
from copy import deepcopy
from unittest.mock import patch

from config import Config
from tests.test_match_roster_linkage import RegisteredMatchCase


class BroadcastSessionFollowupTests(RegisteredMatchCase):
    def setUp(self):
        super().setUp()
        self.conn.execute(
            "UPDATE matches SET status='live',map2='de_mirage',map3='de_ancient' WHERE id=?",
            (self.match_id,),
        )
        self.conn.commit()

    def _live(self, session_id, sequence, map_name="de_nuke"):
        payload = {
            "map": {
                "name": map_name,
                "phase": "live",
                "round": 0,
                "team_ct": {"name": "Pro Team 0", "score": 0},
                "team_t": {"name": "Pro Team 1", "score": 0},
            },
            "round": {"phase": "live"},
            "_80gotv": {
                "session_id": session_id,
                "frame_seq": sequence,
                "team_ct": "team1",
                "team_t": "team2",
            },
            "allplayers": {
                player["steam_id"]: {
                    "name": f"Live {side}-{index}",
                    "team": "CT" if side == 1 else "T",
                }
                for side, players in self.rosters.items()
                for index, player in enumerate(players)
            },
        }
        with (
            patch.object(Config, "GSI_TOKEN", "roster-linkage-test"),
            patch("routes.live_ingest.rate_limit", return_value=True),
        ):
            return self.client.post(
                f"/api/broadcast/matches/{self.match_id}/live",
                json=payload,
                headers={"X-80GOTV-Token": "roster-linkage-test"},
            )

    def _first_result(self):
        self.assertEqual(self._live("director-old", 100).status_code, 200)
        payload = {
            **self._result(),
            "session_id": "director-old",
            "frame_seq": 101,
            "result_id": "saved-nuke",
        }
        response = self._post_result(payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return payload

    def _reconnect(self):
        row = self.conn.execute(
            "SELECT live_state FROM live_match_data WHERE match_id=?", (self.match_id,)
        ).fetchone()
        state = json.loads(row[0])
        state["gsi_received_at"] = "2000-01-01T00:00:00+00:00"
        self.conn.execute(
            "UPDATE live_match_data SET live_state=? WHERE match_id=?",
            (json.dumps(state), self.match_id),
        )
        self.conn.commit()
        self.assertEqual(self._live("director-new", 1, "de_mirage").status_code, 200)

    def test_new_session_low_sequence_can_settle_the_next_map(self):
        self._first_result()
        self._reconnect()
        payload = {
            **self._result(),
            "session_id": "director-new",
            "frame_seq": 2,
            "result_id": "saved-mirage",
            "map_name": "de_mirage",
        }
        response = self._post_result(payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        rows = self.conn.execute(
            "SELECT map_name,COUNT(*) FROM match_stats WHERE data_status='final' GROUP BY map_name"
        ).fetchall()
        self.assertEqual({row[0]: row[1] for row in rows}, {"de_nuke": 10, "de_mirage": 10})

    def test_saved_old_session_retry_remains_idempotent_after_reconnect(self):
        payload = self._first_result()
        self._reconnect()
        before = self._snapshot()
        response = self._post_result(payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(response.get_json()["duplicate"])
        self.assertEqual(self._snapshot(), before)

    def test_same_session_out_of_order_result_is_still_rejected(self):
        self._first_result()
        payload = {
            **self._result(),
            "session_id": "director-old",
            "frame_seq": 99,
            "result_id": "older-mirage",
            "map_name": "de_mirage",
        }
        before = self._snapshot()
        self.assertEqual(self._post_result(payload).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_old_session_cannot_submit_a_new_result_after_new_session_takes_over(self):
        payload = self._first_result()
        self._reconnect()
        payload.update(result_id="late-old-result", frame_seq=200)
        before = self._snapshot()
        self.assertEqual(self._post_result(payload).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def test_replayed_result_id_with_changed_content_is_not_accepted_as_retry(self):
        original = self._first_result()
        self._reconnect()
        changed = deepcopy(original)
        changed["players"][0]["kills"] += 1
        before = self._snapshot()
        response = self._post_result(changed)
        self.assertEqual(response.status_code, 409)
        self.assertIn("同一结算编号", response.get_json()["msg"])
        self.assertEqual(self._snapshot(), before)
