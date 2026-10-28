"""Keep admin match names, scores and temporary rosters together."""

import json

from services.match_roster_service import freeze_match_roster
from tests.test_match_identity_rules import PageNodes
from tests.test_pro_logic_regressions import ProDatabaseCase


class DotAdminMatchDisplayTests(ProDatabaseCase):
    def _match(self):
        return dict(
            self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        )

    def _page(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return PageNodes(response.get_data(as_text=True))

    def _custom_match(self, *, snapshot=False, multiple=False):
        other_id = self.conn.execute(
            "INSERT INTO players(nickname,steam_id) VALUES('Other Player','222')"
        ).lastrowid
        left = [None, None, self.player_id]
        right = [None, None, None, None, other_id]
        if multiple:
            extra_id = self.conn.execute(
                "INSERT INTO players(nickname,steam_id) VALUES('Extra Player','333')"
            ).lastrowid
            left[0] = extra_id
        if snapshot:
            self.conn.commit()
            self.conn.execute("PRAGMA foreign_keys=OFF")
        self.conn.execute(
            """UPDATE matches SET team1_id=?,team2_id=?,team1_players=?,team2_players=?,
                   status='completed',team1_score=2,team2_score=0 WHERE id=?""",
            (
                -1 if snapshot else None,
                -2 if snapshot else None,
                json.dumps(left),
                json.dumps(right),
                self.match_id,
            ),
        )
        if snapshot:
            match = self._match()
            match.update(team1_name="Team 4", t1s="T4", team2_name="Team 3", t2s="T3")
            freeze_match_roster(self.conn, match, confirmed=True)
        self.conn.commit()
        return other_id

    def test_admin_list_keeps_scores_with_sorted_real_teams(self):
        self.conn.execute(
            "UPDATE teams SET name='Zulu',short_name='Z' WHERE id=?", (self.team_ids[0],)
        )
        self.conn.execute(
            "UPDATE teams SET name='Alpha',short_name='A' WHERE id=?", (self.team_ids[1],)
        )
        self.conn.execute(
            "UPDATE matches SET team1_score=2,team2_score=0 WHERE id=?", (self.match_id,)
        )
        self.conn.commit()
        before = self._match()
        page = self._page("/admin/matches")
        row = next(
            node for node in page.nodes if node["attrs"].get("id") == f"match-{self.match_id}"
        )
        self.assertIn("Alpha VS Zulu", row["text"])
        self.assertIn("0 : 2", row["text"])
        self.assertEqual(self._match(), before)

    def test_admin_list_preserves_zero_and_missing_scores(self):
        self.conn.execute(
            "UPDATE matches SET team1_score=NULL,team2_score=0 WHERE id=?", (self.match_id,)
        )
        self.conn.commit()
        page = self._page("/admin/matches")
        self.assertIn("- : 0", " ".join(node["text"] for node in page.by_class("nowrap")))

    def test_edit_uses_confirmed_snapshot_names_and_scores_without_writing(self):
        self._custom_match(snapshot=True)
        before = self._match()
        for path in ("/admin/matches", f"/admin/matches/edit/{self.match_id}"):
            with self.subTest(path=path):
                page = self._page(path)
                if path.endswith("matches"):
                    self.assertIn("Team 3 VS Team 4", page.by_class("cell-title")[0]["text"])
                else:
                    score = " ".join(page.by_class("score-callout")[0]["text"].split())
                    self.assertIn("Team 3 0 : 2 Team 4", score)
        self.assertEqual(self._match(), before)

    def test_sparse_custom_players_name_the_recorded_score(self):
        self._custom_match()
        before = self._match()
        page = self._page(f"/admin/matches/edit/{self.match_id}")
        score = " ".join(page.by_class("score-callout")[0]["text"].split())
        self.assertIn("Other Player 0 : 2 Pro Player", score)
        self.assertNotIn("TBD", score)
        self.assertEqual(self._match(), before)

    def test_locked_form_uses_snapshot_players_instead_of_stale_selected_json(self):
        other_id = self._custom_match(snapshot=True)
        self.conn.execute(
            "UPDATE matches SET team1_players=?,team2_players=? WHERE id=?",
            (json.dumps([self.player_id] * 6), json.dumps([other_id] * 4), self.match_id),
        )
        self.conn.commit()
        before = self._match()
        page = self._page(f"/admin/matches/edit/{self.match_id}")
        self.assertEqual(
            [node["text"].strip() for node in page.by_class("player-tag")],
            ["Pro Player", "Other Player"],
        )
        self.assertEqual(self._match(), before)

    def test_unnamed_custom_group_is_labeled_without_inventing_a_team(self):
        self._custom_match(multiple=True)
        before = self._match()
        page = self._page(f"/admin/matches/edit/{self.match_id}")
        score = page.by_class("score-callout")[0]["text"]
        self.assertIn("自选阵容 A", score)
        self.assertIn("Other Player", score)
        self.assertNotIn("TBD", score)
        self.assertNotIn("Team 1", score)
        self.assertEqual(self._match(), before)

    def test_empty_custom_roster_remains_pending(self):
        self.conn.execute(
            """UPDATE matches SET team1_id=NULL,team2_id=NULL,
                   team1_players='[null,null]',team2_players='[]' WHERE id=?""",
            (self.match_id,),
        )
        self.conn.commit()
        page = self._page(f"/admin/matches/edit/{self.match_id}")
        score = page.by_class("score-callout")[0]["text"]
        self.assertEqual(score.count("TBD"), 2)
        self.assertNotIn("自选阵容", score)

    def test_confirmed_map_picks_follow_canonical_sides_not_display_positions(self):
        self._custom_match(snapshot=True)
        self.conn.execute(
            """UPDATE matches SET map1='de_mirage',map1_t1=13,map1_t2=4,
                   map1_picked_by='t2',map2='de_inferno',map2_t1=13,map2_t2=9,
                   map2_picked_by='t1',bp_process=? WHERE id=?""",
            ("T3 PICK MIRAGE\nT4 PICK INFERNO", self.match_id),
        )
        self.conn.commit()
        before = self._match()
        page = self._page(f"/matches/{self.match_id}")
        self.assertEqual(
            [node["text"].strip() for node in page.by_class("ms-pick-left")][:2],
            ["选图", ""],
        )
        self.assertEqual(
            [node["text"].strip() for node in page.by_class("ms-pick-right")][:2],
            ["", "选图"],
        )
        steps = page.by_class("is-pick")
        self.assertIn("MIRAGE", steps[0]["text"].upper())
        self.assertIn("T3", steps[0]["text"])
        self.assertIn("INFERNO", steps[1]["text"].upper())
        self.assertIn("T4", steps[1]["text"])
        self.assertEqual(self._match(), before)
