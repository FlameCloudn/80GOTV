import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StatsUiRegressionTests(unittest.TestCase):
    def test_match_list_keeps_server_rendered_full_team_names(self):
        template = (ROOT / "templates/matches.html").read_text(encoding="utf-8")

        self.assertNotIn("data-front-matches", template)
        self.assertNotIn("static/js/front_api.js", template)
        self.assertIn("{{ m.team1_name if team1_is_assigned else 'TBD' }}", template)
        self.assertIn("{{ m.team2_name if team2_is_assigned else 'TBD' }}", template)

    def test_event_matches_hide_cancelled_rows_and_use_tbd_placeholders(self):
        route = (ROOT / "routes/events.py").read_text(encoding="utf-8")
        template = (ROOT / "templates/event_detail.html").read_text(encoding="utf-8")

        self.assertIn("COALESCE(m.status, '') != 'cancelled'", route)
        self.assertIn("{{ m.team1_name if team1_is_assigned else 'TBD' }}", template)
        self.assertIn("{{ m.team2_name if team2_is_assigned else 'TBD' }}", template)
        self.assertIn("m.match_time|datetime_display if m.match_time else 'TBD'", template)

    def test_history_requires_a_completed_match_with_a_real_score(self):
        route = (ROOT / "routes/matches.py").read_text(encoding="utf-8")
        template = (ROOT / "templates/match_detail.html").read_text(encoding="utf-8")

        self.assertIn("COALESCE(m.status, '') = 'completed'", route)
        self.assertIn("COALESCE(m.team1_score, 0) > 0", route)
        self.assertIn("COALESCE(m.team2_score, 0) > 0", route)
        self.assertIn("style=\"background-image:url('{{ ''|map_image }}')\"", template)
        self.assertIn('<span class="ms-map-name" data-i18n-ignore>TBD</span>', template)

    def test_upcoming_series_renders_every_map_slot_without_data_links(self):
        route = (ROOT / "routes/matches.py").read_text(encoding="utf-8")
        template = (ROOT / "templates/match_detail.html").read_text(encoding="utf-8")

        self.assertNotIn("if idx < 2 and not mn:", route)
        self.assertIn("{% if ms.has_stats %}", template)
        self.assertIn('class="ms-stats-placeholder"', template)

    def test_temporary_match_teams_use_explicit_stat_side(self):
        route = (ROOT / "routes/matches.py").read_text(encoding="utf-8")
        demo_service = (ROOT / "services/demo_service.py").read_text(encoding="utf-8")

        self.assertIn("def _stat_belongs_to_match_side", route)
        self.assertIn('"match_team_side"', demo_service)
        self.assertIn('"A": "t1" if a_to_t1 else "t2"', demo_service)
        self.assertIn('_stat_belongs_to_match_side(row, "t1", t1_key)', route)
        self.assertIn('_stat_belongs_to_match_side(row, "t2", t2_key)', route)

    def test_bracket_uses_current_team_rosters_and_only_marks_real_winners(self):
        detail = (ROOT / "templates/event_detail.html").read_text(encoding="utf-8")
        card = (ROOT / "templates/event_detail_card.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/style_v2.css").read_text(encoding="utf-8")

        self.assertIn("'db_id': t.db_id", detail)
        self.assertIn("team_players_map.get(t1_db_key)", card)
        self.assertIn("team_players_map.get(t2_db_key)", card)
        self.assertNotIn('class="bracket-seed seed-1"', card)
        self.assertNotIn(".bracket-seed.seed-1", css)

    def test_event_participants_use_full_names_logos_and_event_rosters(self):
        route = (ROOT / "routes/events.py").read_text(encoding="utf-8")
        template = (ROOT / "templates/event_detail.html").read_text(encoding="utf-8")

        self.assertIn("t1.logo AS t1_logo, t2.logo AS t2_logo", route)
        self.assertIn("registration_rosters[team_key] = roster", route)
        self.assertIn("registration_logos.get(team_key)", route)
        self.assertNotIn("# 补充所有注册队伍的选手", route)
        self.assertIn('class="event-team-logo"', template)
        self.assertIn("{{ t.name }}", template)
        self.assertIn("'logo': live_team.logo if live_team else None", template)

        popup_template = (ROOT / "templates/event_detail_card.html").read_text(encoding="utf-8")
        self.assertIn('class="bmp-team-mark"', popup_template)
        self.assertIn("'uploads/' ~ t1_logo", popup_template)
        self.assertIn("'uploads/' ~ t2_logo", popup_template)
        self.assertIn('class="bmp-versus"', popup_template)
        self.assertIn("data-i18n-ignore>Lineups</div>", popup_template)

    def test_bracket_popup_roster_columns_are_equal_and_mirrored(self):
        css = (ROOT / "static/css/hltv_refresh.css").read_text(encoding="utf-8")
        popup_rule = re.search(r"\.bracket-match-popup\s*\{([^}]*)\}", css)
        players_rule = re.search(r"\.bracket-match-popup \.bmp-players\s*\{([^}]*)\}", css)
        left_rule = re.search(r"\.bracket-match-popup \.bp-player-row\s*\{([^}]*)\}", css)
        right_rule = re.search(r"\.bracket-match-popup \.bp-player-row-right\s*\{([^}]*)\}", css)

        self.assertIsNotNone(popup_rule)
        assert popup_rule is not None
        self.assertIn("width: 350px", popup_rule.group(1))
        self.assertIn("height: 400px", popup_rule.group(1))
        self.assertIsNotNone(players_rule)
        assert players_rule is not None
        self.assertIn(
            "grid-template-columns: repeat(2, minmax(0, 1fr))",
            players_rule.group(1),
        )
        self.assertIsNotNone(left_rule)
        assert left_rule is not None
        self.assertIn(
            "grid-template-columns: 32px minmax(0, 1fr) 34px",
            left_rule.group(1),
        )
        self.assertIsNotNone(right_rule)
        assert right_rule is not None
        self.assertIn(
            "grid-template-columns: 34px minmax(0, 1fr) 32px",
            right_rule.group(1),
        )

    def test_event_bp_does_not_change_row_width_and_has_no_time_window(self):
        route = (ROOT / "routes/events.py").read_text(encoding="utf-8")
        template = (ROOT / "templates/event_detail.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/hltv_refresh.css").read_text(encoding="utf-8")

        self.assertIn("BP is manually started", route)
        self.assertNotIn("timedelta(minutes=20)", route)
        self.assertIn(">进入 BP<", template)
        self.assertNotIn("BP 暂未开始", template)
        self.assertIn("position: absolute", css)

    def test_match_detail_mobile_stacks_sidebar_below_main_content(self):
        css = (ROOT / "static/css/mobile_hltv.css").read_text(encoding="utf-8")

        self.assertIn("body .layout.match-detail-layout {", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) !important", css)
        self.assertIn("body .layout.match-detail-layout .side-col {", css)
        self.assertIn("flex-direction: column !important", css)

    def test_english_mode_hides_untranslated_first_paint(self):
        base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
        bootstrap = (ROOT / "templates/_i18n_bootstrap.html").read_text(encoding="utf-8")
        games = (ROOT / "templates/games.html").read_text(encoding="utf-8")
        i18n = (ROOT / "static/js/i18n.js").read_text(encoding="utf-8")

        self.assertIn('{% include "_i18n_bootstrap.html" %}', base)
        self.assertIn("i18n-pending", bootstrap)
        self.assertNotIn('class="games-hub" data-i18n-ignore', games)
        self.assertIn("classList.remove('i18n-pending')", i18n)

    def test_result_date_is_kept_on_one_line(self):
        css = (ROOT / "static/css/hltv_refresh.css").read_text(encoding="utf-8")
        result_time_rule = re.search(r"\.result-time\s*\{([^}]*)\}", css)

        self.assertIsNotNone(result_time_rule)
        assert result_time_rule is not None
        self.assertIn("white-space: nowrap !important", result_time_rule.group(1))
        self.assertIn("word-break: keep-all !important", result_time_rule.group(1))

    def test_compare_picker_uses_compact_fixed_avatar_grid(self):
        css = (ROOT / "static/css/stats_hltv.css").read_text(encoding="utf-8")
        slot_rule = re.search(r"\.stats-compare-slot\s*\{([^}]*)\}", css)
        avatar_rule = re.search(
            r"\.stats-compare-slot img,\s*"
            r"\.stats-compare-avatar-fallback,\s*"
            r"\.stats-compare-avatar-empty\s*\{([^}]*)\}",
            css,
        )

        self.assertIsNotNone(slot_rule)
        assert slot_rule is not None
        self.assertIn("grid-template-columns: 44px minmax(0, 1fr)", slot_rule.group(1))
        self.assertIsNotNone(avatar_rule)
        assert avatar_rule is not None
        self.assertIn("width: 44px", avatar_rule.group(1))
        self.assertIn("height: 44px", avatar_rule.group(1))

    def test_overview_labels_render_before_centered_numbers(self):
        template = (ROOT / "templates/stats.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/stats_overview_refresh.css").read_text(encoding="utf-8")

        self.assertIn(
            "<div><span>选手</span><b>{{ overview.total_players }}</b></div>",
            template,
        )
        number_rule = re.search(
            r"\.stats-hltv-shell \.overview-summary-grid > div > b\s*\{([^}]*)\}",
            css,
        )
        self.assertIsNotNone(number_rule)
        assert number_rule is not None
        self.assertIn("font-size: 24px !important", number_rule.group(1))
        self.assertIn("text-align: center", number_rule.group(1))


if __name__ == "__main__":
    unittest.main()
