"""平板宽度规则：761–1023px 首页三栏并排，760px 以下左右侧栏成对隐藏。

赛果行规则也在这里检查；真实浏览器中的栏位位置由 tests/e2e/frontend-smoke.spec.js 覆核。
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def media_block(css, width):
    """取出某个 max-width 断点里的规则（只看第一层大括号）。"""
    match = re.search(r"@media \(max-width: %dpx\) \{(.*?)\n\}" % width, css, re.S)
    return match.group(1) if match else ""


class TabletLayoutRuleTests(unittest.TestCase):
    def test_home_keeps_left_column_beside_news_on_tablets(self):
        css = (ROOT / "static/css/pages/home.css").read_text(encoding="utf-8")
        # 1024–1180：三栏都在，两侧栏收窄
        self.assertIn("grid-template-columns: 200px minmax(0, 1fr) 220px", media_block(css, 1180))
        # 761–1023：左右栏、新闻主栏同时并排，主栏保留可读宽度。
        narrow = media_block(css, 1023)
        self.assertIn("grid-template-columns: 160px minmax(350px, 1fr) 180px", narrow)
        self.assertIn('grid-template-areas: "left main right"', narrow)
        self.assertIn("gap: 10px", narrow)
        self.assertIn(".home-left-col { grid-area: left; }", narrow)
        self.assertNotRegex(css, r"\.home-left-col \{[^}]*grid-column: 1 / -1")
        # 手机宽度左右侧栏同时收起，不排到新闻下方。
        mobile = media_block(css, 760)
        self.assertIn('grid-template-areas: "main"', mobile)
        self.assertIn(".home-left-col,\n  .home-right-col { display: none; }", mobile)

    def test_result_and_match_rows_keep_event_on_the_same_line(self):
        css = (ROOT / "static/css/pages/schedule.css").read_text(encoding="utf-8")
        tablet = media_block(css, 1080)
        self.assertIn(
            ".result-row { grid-template-columns: minmax(0, 1fr) minmax(0, 150px) 40px;", tablet
        )
        self.assertIn(
            ".match-schedule-row { grid-template-columns: 70px minmax(0, 1fr) minmax(0, 170px);",
            tablet,
        )
        # 以前的写法：赛事名放到第二行、居中
        self.assertNotIn("grid-row: 2; text-align: center", tablet)
        self.assertNotIn(".match-schedule-meta { grid-column: 2;", tablet)

    def test_results_filter_becomes_a_select_on_portrait_tablets(self):
        css = (ROOT / "static/css/pages/schedule.css").read_text(encoding="utf-8")
        template = (ROOT / "templates/results.html").read_text(encoding="utf-8")
        portrait = media_block(css, 960)
        self.assertIn('class="schedule-layout results-schedule-layout"', template)
        self.assertIn(
            ".results-schedule-layout .results-filter-sidebar { display: none; }", portrait
        )
        self.assertIn(".mobile-result-event-filter {", portrait)

    def test_match_page_map_card_gets_full_width_next_to_sidebar(self):
        css = (ROOT / "static/css/pages/match.css").read_text(encoding="utf-8")
        self.assertIn(
            ".mh-columns { grid-template-columns: minmax(0, 1fr); }", media_block(css, 1100)
        )

    def test_team_page_match_rows_give_names_room_on_portrait_tablets(self):
        css = (ROOT / "static/css/pages/teams.css").read_text(encoding="utf-8")
        # 列宽仍是固定值（各行比分列对齐），只在竖屏平板把赛事列让出 20px 给队名
        self.assertIn(
            ".team-match { grid-template-columns: 96px minmax(0, 1fr) auto minmax(0, 1fr) minmax(0, 200px); }",
            media_block(css, 960),
        )
        self.assertNotIn("fit-content", css)


class AdminTabletLayoutRuleTests(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "static/css/pages/admin.css").read_text(encoding="utf-8")

    def test_admin_nav_wraps_instead_of_hiding_links_on_the_right(self):
        narrow = media_block(self.css, 1100)
        nav_rule = re.search(r"\.admin-sidenav \{[^}]*\}", narrow).group(0)
        self.assertIn("flex-wrap: wrap", nav_rule)
        self.assertNotIn("overflow-x: auto", nav_rule)

    def test_admin_tables_fit_portrait_tablets(self):
        portrait = media_block(self.css, 960)
        self.assertIn(".admin-table .col-actions .row-actions { flex-wrap: wrap; }", portrait)
        self.assertIn(".admin-table .actions-cell { min-width: 200px; }", portrait)
        # 桌面宽度的写法保持不变
        self.assertIn(".admin-table .actions-cell { min-width: 300px; }", self.css)
        template = (ROOT / "templates/admin/matches.html").read_text(encoding="utf-8")
        self.assertIn('<td class="nowrap cell-datetime">', template)


if __name__ == "__main__":
    unittest.main()
