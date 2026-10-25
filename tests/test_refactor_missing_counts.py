from html.parser import HTMLParser

from services.performance_service import refresh_player_performance
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat


class _TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current = []
        elif tag == "td" and self.current is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.current is not None and self.cell is not None:
            self.current.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


class MissingCountRankingTests(StatsDatabaseCase):
    def test_known_negative_value_sorts_before_unknown_cache_zero(self):
        from routes.stats import _player_rankings

        self.record()
        known_id = self.conn.execute(
            "INSERT INTO players(nickname) VALUES('Known value')"
        ).lastrowid
        add_stat(
            self.conn,
            self.match_id,
            known_id,
            self.team1,
            "Mirage",
            rating=-0.25,
            adr=-1,
            rounds_played=20,
        )
        refresh_player_performance(self.conn, [known_id])
        filters = {"time": "all", "map": "all", "side": "both", "event": None}
        for order in ("rating", "adr"):
            with self.subTest(order=order):
                rows = _player_rankings(self.conn, filters, order=order)
                self.assertEqual(rows[0]["id"], known_id)
                self.assertIsNone(rows[-1][order])

    def record(self, value=None, **overrides):
        values = {
            field: value
            for field in (
                "kills",
                "deaths",
                "assists",
                "rounds_played",
                "clutches_won",
                "first_kills",
                "first_deaths",
                "t_kills",
                "ct_kills",
                "t_deaths",
                "ct_deaths",
                "rating",
                "adr",
                "kast",
                "impact",
                "headshot_percentage",
            )
        }
        values.update(overrides)
        add_stat(self.conn, self.match_id, self.player_id, self.team1, "Mirage", **values)
        refresh_player_performance(self.conn, [self.player_id])
        self.conn.commit()

    def rankings(self, filtered=False, side="both"):
        from routes.stats import _player_rankings

        filters = {
            "time": "all",
            "map": "all",
            "side": side,
            "event": self.event_id if filtered else None,
        }
        return _player_rankings(self.conn, filters)[0]

    def html_row(self, path):
        from app import app

        response = app.test_client().get(path)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        parser = _TableRows()
        parser.feed(response.get_data(as_text=True))
        return next(row for row in parser.rows if row and "Audit Player" in row[0])

    def test_cached_and_filtered_null_counts_stay_unknown(self):
        self.record()
        for filtered in (False, True):
            with self.subTest(filtered=filtered):
                row = self.rankings(filtered=filtered)
                for field in (
                    "kills",
                    "deaths",
                    "rounds",
                    "kd_diff",
                    "kd",
                    "clutch",
                    "first_kills",
                    "first_deaths",
                    "opening_success",
                ):
                    self.assertIsNone(row[field], field)

    def test_cached_and_filtered_recorded_zero_counts_remain_zero(self):
        self.record(0)
        for filtered in (False, True):
            with self.subTest(filtered=filtered):
                row = self.rankings(filtered=filtered)
                for field in (
                    "kills",
                    "deaths",
                    "rounds",
                    "kd_diff",
                    "clutch",
                    "first_kills",
                    "first_deaths",
                ):
                    self.assertEqual(row[field], 0, field)
                self.assertIsNone(row["kd"])
                self.assertIsNone(row["opening_success"])

    def test_one_unknown_operand_does_not_produce_a_difference_or_success_rate(self):
        self.record(kills=4, first_kills=1)
        for filtered in (False, True):
            with self.subTest(filtered=filtered):
                row = self.rankings(filtered=filtered)
                self.assertEqual(row["kills"], 4)
                self.assertIsNone(row["deaths"])
                self.assertIsNone(row["kd_diff"])
                self.assertIsNone(row["kd"])
                self.assertIsNone(row["opening_success"])

    def test_superseded_recorded_count_does_not_make_current_unknown_available(self):
        self.record()
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            kills=30,
            deaths=10,
            rounds_played=20,
            data_status="superseded",
        )
        refresh_player_performance(self.conn, [self.player_id])
        self.assertIsNone(self.rankings()["kills"])
        self.assertIsNone(self.rankings()["rounds"])

    def test_side_filter_does_not_invent_missing_kills_or_deaths(self):
        self.record()
        for side in ("t", "ct"):
            with self.subTest(side=side):
                row = self.rankings(side=side)
                self.assertIsNone(row["kills"])
                self.assertIsNone(row["deaths"])
                self.assertIsNone(row["kd_diff"])

    def test_overview_rankings_keep_missing_counts(self):
        from routes.stats import _overview_context

        self.record()
        row = _overview_context(
            self.conn, {"time": "all", "map": "all", "side": "both", "event": None}
        )["top_players"][0]
        self.assertIsNone(row["kills"])
        self.assertIsNone(row["deaths"])
        self.assertIsNone(row["kd_diff"])

    def test_public_tables_show_dashes_for_unknown_counts_without_failing(self):
        self.record()
        for path, first_metric in (
            ("/stats?tab=players", 3),
            ("/stats/overview/best-players", 2),
            ("/stats/overview/kd", 3),
        ):
            with self.subTest(path=path):
                row = self.html_row(path)
                self.assertTrue(all(value == "-" for value in row[first_metric:]), row)

    def test_public_tables_retain_real_zero_difference_and_rating(self):
        self.record(0)
        row = self.html_row("/stats?tab=players")
        self.assertEqual(row[3], "0")
        self.assertEqual(row[4], "+0")
        self.assertEqual(row[-1], "0.00")

    def test_zero_kd_with_recorded_deaths_is_not_hidden_as_missing(self):
        self.record(0, deaths=10)
        row = self.html_row("/stats/overview/kd")
        self.assertEqual(row[3], "0")
        self.assertEqual(row[5], "0.00")
