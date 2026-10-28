import json
from copy import deepcopy

from flask import render_template

from app import app
from tests.test_match_identity_rules import PageNodes
from tests.test_match_roster_linkage import RegisteredMatchCase


class BracketRatingOrderTests(RegisteredMatchCase):
    def _prepare_ratings(self, left=None, right=None):
        ratings = {
            1: left if left is not None else [0.54, 0.88, 0.77, 0.74, 1.09],
            2: right if right is not None else [0.99, 1.28, 1.28, 1.10, 1.16],
        }
        for side, players in self.rosters.items():
            for player, rating in zip(players, ratings[side], strict=True):
                self.conn.execute(
                    """INSERT INTO match_stats(match_id,player_id,match_team_side,map_name,
                           rating,rounds_played,data_status) VALUES(?,?,?,'de_nuke',?,17,'final')""",
                    (self.match_id, player["id"], f"t{side}", rating),
                )
        self.conn.execute(
            """UPDATE matches SET status='completed',bo_format='BO1',team1_score=0,team2_score=1,
                   team1_players=?,team2_players=?,map1_t1=4,map1_t2=13 WHERE id=?""",
            (
                json.dumps([player["id"] for player in self.rosters[1]]),
                json.dumps([player["id"] for player in self.rosters[2]]),
                self.match_id,
            ),
        )
        self.node = {
            "id": "UB_R1_M1",
            "team1": "first",
            "team2": "second",
            "score1": 0,
            "score2": 1,
            "match_id": self.match_id,
            "status": "completed",
        }
        bracket = {
            "tournament": {
                "type": "double_elim",
                "total_teams": 4,
                "teams": [
                    {"id": "first", "db_id": self.team_ids[0], "name": "Pro Team 0"},
                    {"id": "second", "db_id": self.team_ids[1], "name": "Pro Team 1"},
                ],
                "rounds": [{"name": "UB Round 1", "matches": [self.node]}],
            }
        }
        self.conn.execute(
            "UPDATE events SET bracket_data=? WHERE id=?", (json.dumps(bracket), self.event_id)
        )
        self.conn.commit()

    def _page(self):
        response = self.client.get(f"/events/{self.event_id}")
        self.assertEqual(response.status_code, 200)
        return PageNodes(response.get_data(as_text=True))

    def _ratings(self, page):
        return [node["text"].strip() for node in page.by_class("bp-player-rating")]

    def _render_card(self, context, *, swap=False, extra=False, empty=False):
        node = dict(self.node)
        node.pop("match_id")
        players = {
            str(self.team_ids[side - 1]): deepcopy(
                context["match_players_map"][self.match_id][side]
            )
            for side in (1, 2)
        }
        if extra:
            players[str(self.team_ids[0])].append(
                {"id": 999, "nickname": "Bench Player", "rating": 9.99, "slot": 6}
            )
        if empty:
            players = {}
        before = deepcopy(players)
        with app.test_request_context():
            page = PageNodes(
                render_template(
                    "event_detail_card.html",
                    m=node,
                    matches=[],
                    team_map={
                        "first": {
                            "name": "First Team",
                            "short": "ZZZ" if swap else "AAA",
                            "db_id": self.team_ids[0],
                        },
                        "second": {
                            "name": "Second Team",
                            "short": "AAA" if swap else "ZZZ",
                            "db_id": self.team_ids[1],
                        },
                    },
                    team_players_map=players,
                    round_name="UB Round 1",
                )
            )
        self.assertEqual(players, before)
        return page

    def test_completed_match_popup_sorts_each_side_without_changing_saved_slots(self):
        self._prepare_ratings()
        before = self._snapshot()
        with self._event_context() as context:
            source_order = {
                side: [
                    (player["id"], player["slot"])
                    for player in context["match_players_map"][self.match_id][side]
                ]
                for side in (1, 2)
            }
        self.assertEqual(
            self._ratings(self._page()),
            ["1.09", "0.88", "0.77", "0.74", "0.54", "1.28", "1.28", "1.16", "1.10", "0.99"],
        )
        for side in (1, 2):
            self.assertEqual(
                source_order[side],
                [(player["id"], slot) for slot, player in enumerate(self.rosters[side], 1)],
            )
        api = self.client.get(f"/api/broadcast/matches/{self.match_id}").get_json()["match"]
        for side in (1, 2):
            self.assertEqual(
                [player["id"] for player in api[f"team{side}"]["players"]],
                [player["id"] for player in self.rosters[side]],
            )
        self.assertEqual(self._snapshot(), before)

    def test_live_and_upcoming_popups_also_use_descending_event_ratings(self):
        self._prepare_ratings()
        for status in ("live", "upcoming"):
            with self.subTest(status=status):
                self.conn.execute("UPDATE matches SET status=? WHERE id=?", (status, self.match_id))
                self.conn.commit()
                self.assertEqual(
                    self._ratings(self._page())[:5], ["1.09", "0.88", "0.77", "0.74", "0.54"]
                )

    def test_zero_is_known_missing_ratings_are_last_and_ties_keep_their_slots(self):
        self._prepare_ratings(left=[None, 0, 0.8, None, 0.4])
        page = self._page()
        self.assertEqual(self._ratings(page)[:5], ["0.80", "0.40", "0.00", "-", "-"])
        self.assertEqual(
            [node["attrs"].get("data-player-slot") for node in page.by_class("bp-player-name")],
            ["3", "5", "2", "1", "4", "2", "3", "5", "4", "1"],
        )

    def test_fallback_roster_is_sorted_after_selecting_the_five_actual_players(self):
        self._prepare_ratings()
        with self._event_context() as context:
            page = self._render_card(context, extra=True)
        self.assertNotIn(
            "Bench Player", " ".join(node["text"] for node in page.by_class("bp-player-name"))
        )
        self.assertEqual(self._ratings(page)[:5], ["1.09", "0.88", "0.77", "0.74", "0.54"])

    def test_display_side_swap_keeps_sorted_players_with_their_team_and_score(self):
        self._prepare_ratings()
        with self._event_context() as context:
            page = self._render_card(context, swap=True)
        self.assertEqual(self._ratings(page)[:5], ["1.28", "1.28", "1.16", "1.10", "0.99"])
        self.assertEqual(self._ratings(page)[5:], ["1.09", "0.88", "0.77", "0.74", "0.54"])
        self.assertEqual(
            [node["text"].strip() for node in page.by_class("bracket-score")], ["1", "0"]
        )

    def test_empty_popups_keep_five_unknown_places_on_each_side(self):
        self._prepare_ratings()
        with self._event_context() as context:
            page = self._render_card(context, empty=True)
        self.assertEqual(self._ratings(page), ["-"] * 10)
        self.assertEqual(len(page.by_class("bp-player-name")), 10)

    def test_display_sort_returns_a_copy_and_handles_unknown_or_string_ratings(self):
        order = app.jinja_env.filters.get("rating_desc")
        self.assertIsNotNone(order)
        players = [
            {"slot": 1},
            {"slot": 2, "rating": "1.09"},
            {"slot": 3, "rating": 0},
            {"slot": 4, "rating": float("inf")},
        ]
        before = [dict(player) for player in players]
        result = order(players)
        self.assertIsNot(result, players)
        self.assertEqual([player["slot"] for player in result], [2, 3, 1, 4])
        self.assertEqual(players, before)


del RegisteredMatchCase
