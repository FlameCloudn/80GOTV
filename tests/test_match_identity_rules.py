import json
from datetime import datetime, timezone
from html.parser import HTMLParser

from flask import render_template

from app import app
from blueprints.admin_matches import _match_roster_selected
from routes.broadcast import _team_players
from routes.live import _roster_profiles_by_steamid, _roster_side_by_steamid
from services.match_service import supplement_temp_teams
from tests.test_pro_logic_regressions import ProDatabaseCase
from utils.match_utils import get_map_half_scores


class PageNodes(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self.nodes.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for node in self.stack:
            node["text"] += data

    def by_class(self, name):
        return [node for node in self.nodes if name in node["attrs"].get("class", "").split()]


class MatchIdentityRulesTests(ProDatabaseCase):
    def _match(self):
        return dict(
            self.conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        )

    def _registered_roster(self):
        registration_id = self.conn.execute(
            "INSERT INTO event_registrations(event_id,team_name,creator_user_id) VALUES(?,?,?)",
            (self.event_id, "Pro Team 0", self.user_id),
        ).lastrowid
        player_ids = []
        for slot, name in enumerate(("Zulu", "Alpha", "Echo", "Bravo", "Delta")):
            steam_id = str(200 + slot)
            player_id = self.conn.execute(
                "INSERT INTO players(nickname,steam_id,team_id) VALUES(?,?,?)",
                (name, steam_id, self.team_ids[0]),
            ).lastrowid
            player_ids.append(player_id)
            self.conn.execute(
                "INSERT INTO event_registration_slots(registration_id,slot_index,player_name,steam_id) VALUES(?,?,?,?)",
                (registration_id, slot, name, steam_id),
            )
        self.conn.commit()
        return player_ids

    def test_current_bp_overrides_conflicting_old_side_metadata(self):
        match = {
            "map1": "de_nuke",
            "map_halves": json.dumps({"0": {"opening_ct_team": "t2", "side_source": "gsi"}}),
            "bp_state": json.dumps(
                {"picks": [{"map": "de_nuke", "side": "CT", "side_team": "t1"}]}
            ),
        }
        result = get_map_half_scores(match, 0)
        self.assertEqual(result["opening_ct_team"], "t1")
        self.assertEqual(result["side_source"], "website_bp")

    def test_unverified_side_metadata_cannot_substitute_for_a_bp_decision(self):
        match = {"map1": "de_nuke", "map_halves": json.dumps({"0": {"opening_ct_team": "t1"}})}
        result = get_map_half_scores(match, 0)
        self.assertIsNone(result["opening_ct_team"])

    def test_registration_slots_override_alphabetical_team_membership(self):
        expected = self._registered_roster()
        roster = _team_players(self.conn, self._match(), 1)
        self.assertEqual([player["id"] for player in roster], expected)
        self.assertEqual([player["slot"] for player in roster], [1, 2, 3, 4, 5])
        self.assertEqual(_match_roster_selected(self.conn, self._match(), 1), expected)
        profiles = _roster_profiles_by_steamid(self.conn, self._match())
        self.assertEqual([profiles[str(200 + slot)]["slot"] for slot in range(5)], [1, 2, 3, 4, 5])

    def test_unconfigured_membership_does_not_create_player_numbers(self):
        self.assertEqual(_team_players(self.conn, self._match(), 1), [])
        self.assertEqual(_match_roster_selected(self.conn, self._match(), 1), [])
        self.assertEqual(_roster_profiles_by_steamid(self.conn, self._match()), {})
        self.assertEqual(_roster_side_by_steamid(self.conn, self._match()), {})

    def test_explicit_admin_slots_take_priority_and_empty_slots_do_not_shift_players(self):
        registered = self._registered_roster()
        self.conn.execute(
            "UPDATE matches SET team1_players=? WHERE id=?",
            (json.dumps([registered[4], None, registered[0]]), self.match_id),
        )
        self.conn.commit()
        roster = _team_players(self.conn, self._match(), 1)
        actual_players = [player for player in roster if player["id"]]
        self.assertEqual(
            [player["id"] for player in actual_players], [registered[4], registered[0]]
        )
        self.assertEqual([player["slot"] for player in actual_players], [1, 3])

    def test_custom_roster_does_not_invent_a_team_name_from_a_side_number(self):
        other = self.conn.execute(
            "INSERT INTO players(nickname) VALUES('Another Player')"
        ).lastrowid
        match = self._match()
        match.update(team1_id=None, team1_players=json.dumps([self.player_id, other]))
        filled = supplement_temp_teams(match, self.conn)
        self.assertNotIn(filled["team1_name"], ("TEAM 1", "Team 1", "队伍1"))
        self.assertNotEqual(filled["t1s"], "T1")

    def test_match_display_compares_the_full_abbreviation_without_changing_storage(self):
        from utils.match_display import match_opponents

        match = {
            "team1_id": 101,
            "team1_name": "Zulu",
            "t1s": "ABZ",
            "team1_score": 13,
            "team2_id": 102,
            "team2_name": "Alpha",
            "t2s": "ABA",
            "team2_score": 7,
        }
        before = dict(match)
        opponents = match_opponents(match)
        self.assertEqual([opponent["side"] for opponent in opponents], ["t2", "t1"])
        self.assertEqual([opponent["score"] for opponent in opponents], [7, 13])
        self.assertEqual([opponent["id"] for opponent in opponents], [102, 101])
        self.assertEqual(match, before)

    def test_identical_abbreviations_keep_the_admin_order_and_unknowns_stay_pending(self):
        from utils.match_display import match_opponents

        opponents = match_opponents(
            {"team1_name": "First", "t1s": "ABC", "team2_name": "Second", "t2s": "abc"}
        )
        self.assertEqual([opponent["side"] for opponent in opponents], ["t1", "t2"])
        unknown = match_opponents({"team1_name": None, "team2_name": "Actual", "t2s": "Z"})
        self.assertEqual([opponent["name"] for opponent in unknown], ["Actual", "TBD"])

    def _reverse_alphabetical_match(self, status="live"):
        self.conn.execute(
            "UPDATE teams SET name='Zulu Brigade',short_name='ABZ' WHERE id=?", (self.team_ids[0],)
        )
        self.conn.execute(
            "UPDATE teams SET name='Alpha Corps',short_name='ABA' WHERE id=?", (self.team_ids[1],)
        )
        self.conn.execute(
            "UPDATE matches SET status=?,team1_score=2,team2_score=1,map1_t1=13,map1_t2=7 WHERE id=?",
            (status, self.match_id),
        )
        self.conn.commit()

    def test_match_pages_keep_each_score_with_its_sorted_real_team(self):
        self._reverse_alphabetical_match()
        for suffix, name_class in (
            ("", "mh-team-name"),
            ("/report", "report-team-name"),
            ("/detailed", "match-detailed-score-team"),
        ):
            with self.subTest(page=suffix or "match"):
                response = self.client.get(f"/matches/{self.match_id}{suffix}")
                self.assertEqual(response.status_code, 200)
                page = PageNodes(response.get_data(as_text=True))
                names = [node["text"].strip() for node in page.by_class(name_class)]
                self.assertIn("Alpha Corps", names[0])
                self.assertIn("Zulu Brigade", names[1])
                if not suffix:
                    self.assertEqual(
                        [node["text"].strip() for node in page.by_class("mh-team-score")],
                        ["1", "2"],
                    )
        original = self._match()
        self.assertEqual((original["team1_id"], original["team1_score"]), (self.team_ids[0], 2))
        legacy = self.client.get(f"/matches/{self.match_id}/live")
        self.assertEqual(legacy.status_code, 302)
        self.assertTrue(legacy.location.endswith(f"/matches/{self.match_id}#data-live"))

    def test_sorted_vote_controls_still_submit_the_original_team_and_score_fields(self):
        self._reverse_alphabetical_match(status="upcoming")
        client = self._user_client()
        page = PageNodes(client.get(f"/matches/{self.match_id}").get_data(as_text=True))
        controls = page.by_class("vote-btn")
        self.assertEqual([node["attrs"]["data-vote"] for node in controls], ["t2", "t1"])
        inputs = page.by_class("vote-score-inp")
        self.assertEqual([node["attrs"]["id"] for node in inputs], ["score2", "score1"])
        response = client.post(
            f"/matches/{self.match_id}/vote",
            data={"csrf_token": "pro-logic-csrf", "voted_for": "t2", "score1": "1", "score2": "2"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        row = self.conn.execute(
            "SELECT voted_for,score1_guess,score2_guess FROM match_votes WHERE match_id=?",
            (self.match_id,),
        ).fetchone()
        self.assertEqual(tuple(row), ("t2", 1, 2))

    def test_other_public_and_admin_match_views_render_after_ordering_change(self):
        self._reverse_alphabetical_match(status="completed")
        self._add_map_stat()
        paths = [
            "/",
            "/matches",
            "/results",
            f"/events/{self.event_id}",
            "/search?q=Pro",
            "/stats?tab=matches",
            f"/players/{self.player_id}",
            f"/stats/players/{self.player_id}",
            f"/teams/{self.team_ids[0]}",
            "/predictions",
            "/admin",
            "/admin/matches",
            f"/admin/matches/edit/{self.match_id}",
            f"/admin/matches/{self.match_id}/stats",
            f"/admin/matches/{self.match_id}/import-demo",
        ]
        for path in paths:
            with self.subTest(page=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_missing_short_field_is_filled_from_the_configured_team_abbreviation(self):
        self._reverse_alphabetical_match()
        match = self._match()
        match.update(team1_name="Zulu Brigade", team2_name="Alpha Corps")
        self.assertEqual(supplement_temp_teams(match, self.conn)["t1s"], "ABZ")

    def test_bracket_card_orders_names_map_scores_and_rosters_together(self):
        node = {
            "team1": "first",
            "team2": "second",
            "score1": 2,
            "score2": 1,
            "maps": [{"name": "de_nuke", "t1": 13, "t2": 7}],
        }
        before = json.dumps(node)
        team_map = {
            "first": {"name": "Zulu Brigade", "short": "ABZ"},
            "second": {"name": "Alpha Corps", "short": "ABA"},
        }
        with app.test_request_context():
            page = PageNodes(
                render_template(
                    "event_detail_card.html",
                    m=node,
                    team_map=team_map,
                    team_players_map={},
                    matches=[],
                    round_name="Final",
                )
            )
        self.assertEqual(
            [item["text"].strip() for item in page.by_class("bracket-name")],
            ["Alpha Corps", "Zulu Brigade"],
        )
        self.assertEqual(
            [item["text"].strip() for item in page.by_class("bracket-score")], ["1", "2"]
        )
        self.assertEqual(page.by_class("bmp-map-s1")[0]["text"], "7")
        self.assertEqual(page.by_class("bmp-map-s2")[0]["text"], "13")
        self.assertEqual(page.by_class("bracket-seed"), [])
        self.assertEqual(json.dumps(node), before)

    def test_test_match_creation_keeps_the_admins_explicit_empty_slots(self):
        response = self.client.post(
            "/admin/matches/add",
            data={
                "csrf_token": "pro-logic-csrf",
                "event_id": self.event_id,
                "match_time": "2030-01-02T18:00",
                "bo_format": "BO1",
                "status": "upcoming",
                "is_test_mode": "1",
                "side1_type": "players",
                "side1_p3": self.player_id,
                "side2_type": "players",
            },
        )
        self.assertEqual(response.status_code, 302)
        match = dict(self.conn.execute("SELECT * FROM matches ORDER BY id DESC LIMIT 1").fetchone())
        self.assertEqual(
            json.loads(match["team1_players"]), [None, None, None, str(self.player_id)]
        )
        roster = _team_players(self.conn, match, 1)
        self.assertEqual(
            [(player["id"], player["slot"]) for player in roster if player["id"]],
            [(self.player_id, 4)],
        )

    def test_registration_requires_an_explicit_position_instead_of_defaulting_to_one(self):
        self.conn.execute("UPDATE events SET registration_open=1 WHERE id=?", (self.event_id,))
        self.conn.execute(
            "UPDATE users SET steam_id64='76561198000000123' WHERE id=?", (self.user_id,)
        )
        self.conn.commit()
        client = self._user_client()
        page = PageNodes(client.get(f"/events/{self.event_id}").get_data(as_text=True))
        choices = [node for node in page.nodes if node["attrs"].get("name") == "my_slot"]
        self.assertEqual(len(choices), 5)
        self.assertTrue(all("checked" not in node["attrs"] for node in choices))
        data = {"csrf_token": "pro-logic-csrf", "team_name": "Explicit Slots"}
        self.assertEqual(
            client.post(f"/events/{self.event_id}/register", data=data).status_code, 302
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM event_registrations").fetchone()[0], 0
        )
        data["my_slot"] = "3"
        self.assertEqual(
            client.post(f"/events/{self.event_id}/register", data=data).status_code, 302
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT slot_index FROM event_registration_slots WHERE user_id=?", (self.user_id,)
            ).fetchone()[0],
            3,
        )

    def test_live_endpoint_reads_registration_positions_when_no_admin_roster_was_saved(self):
        self._registered_roster()
        state = {
            "gsi_received_at": datetime.now(timezone.utc).isoformat(),
            "gsi": {
                "map": {
                    "name": "de_nuke",
                    "phase": "live",
                    "round": 1,
                    "team_ct": {"name": "Pro Team 0", "score": 1},
                    "team_t": {"name": "Pro Team 1", "score": 0},
                },
                "allplayers": {
                    str(200 + slot): {
                        "name": "Wrong live name",
                        "team": "CT",
                        "observer_slot": 9 - slot,
                        "state": {"health": 100},
                        "match_stats": {"kills": 1, "deaths": 0},
                    }
                    for slot in range(5)
                },
            },
        }
        self.conn.execute(
            "INSERT INTO live_match_data(match_id,live_state) VALUES(?,?)",
            (self.match_id, json.dumps(state)),
        )
        self.conn.commit()
        response = self.client.get(f"/api/live/{self.match_id}")
        self.assertEqual(response.status_code, 200)
        players = response.get_json()["players_t1"]
        self.assertEqual(
            {player["steamid"]: player["roster_slot"] for player in players},
            {str(200 + slot): slot + 1 for slot in range(5)},
        )
