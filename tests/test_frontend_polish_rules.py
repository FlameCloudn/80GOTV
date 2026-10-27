"""2026-10-26 前端打磨的样式与模板规则。真实浏览器里的效果见 tests/e2e/frontend-polish.spec.js。"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class FrontendPolishRuleTests(unittest.TestCase):
    def test_titles_use_balanced_wrapping_without_changing_nowrap_titles(self):
        css = read("static/css/app.css")
        rule = re.search(r":where\(h1, h2, h3, h4,[^)]*\) \{ text-wrap-style: balance; \}", css)
        self.assertIsNotNone(rule)
        for selector in (".news-title", ".cell-title", ".mh-team-name", ".report-team-name"):
            self.assertIn(selector, rule.group(0))
        # 只改“怎么折”，不用会改掉单行省略号的 text-wrap 简写（只在不认识 text-wrap-style 的浏览器里退回）
        self.assertRegex(
            css,
            r"@supports not \(text-wrap-style: balance\) \{\s*:where\(h1, h2, h3, h4\) \{ text-wrap: balance; \}",
        )

    def test_panel_head_wraps_instead_of_squeezing_the_title(self):
        css = read("static/css/app.css")
        head = re.search(r"\.panel-head \{([^}]*)\}", css).group(1)
        self.assertIn("flex-wrap: wrap", head)

    def test_scrollable_strips_mark_hidden_edges(self):
        css = read("static/css/app.css")
        js = read("static/js/main.js")
        self.assertIn(".has-more-end {", css)
        self.assertIn(".has-more-start {", css)
        self.assertIn("var SELECTOR = '.tabs, .player-initial-filter';", js)
        self.assertIn("var scrollable = hidden > 16;", js)

    def test_news_detail_translates_interface_but_keeps_author_content(self):
        i18n = read("static/js/i18n.js")
        ignored = re.search(r"var ignored = \[(.*?)\]\.join", i18n, re.S).group(1)
        self.assertNotIn("'.news-detail'", ignored)
        template = read("templates/news_detail.html")
        for marked in (
            '<h1 class="news-detail-title" data-i18n-ignore>',
            "<span data-i18n-ignore>{{ news.author }}</span>",
            '<div class="prose news-content" data-i18n-ignore>',
        ):
            self.assertIn(marked, template)
        # 还没开打的关联比赛不显示 0 : 0
        self.assertIn("related_match.status in ('completed', 'live')", template)

    def test_dates_follow_the_page_language(self):
        events = read("templates/events.html")
        self.assertIn("{{ ym[:4] }}年{{ ym[5:7]|int }}月", events)
        i18n = read("static/js/i18n.js")
        self.assertIn(r"[/^(\d{4})年(\d{1,2})月$/g", i18n)
        matches = read("templates/matches.html")
        # 比赛页侧栏：只有赛事名不翻译，日期跟着语言
        self.assertIn(
            '<span class="match-filter-name" data-i18n-ignore>{{ e.name }}</span>', matches
        )
        self.assertNotRegex(
            matches, r'filter_url\(event=e\.id\|string\) \}\}"[^>]*data-i18n-ignore'
        )

    def test_errors_use_the_shared_floating_toast(self):
        # 服务器提示统一走共用模板（右上角浮动），各页面不再自己放整块错误栏
        for path in (
            "templates/base.html",
            "templates/login.html",
            "templates/change_password.html",
        ):
            html = read(path)
            self.assertIn('{% include "_flash_toasts.html" %}', html, path)
            self.assertNotIn("get_flashed_messages", html, path)
        self.assertIn("_flash_toasts.html", read("templates/admin/_flashes.html"))
        self.assertIn('{% include "admin/_flashes.html" %}', read("templates/admin/login.html"))
        for path in (
            "templates/base.html",
            "templates/admin/_layout.html",
            "templates/admin/login.html",
            "templates/login.html",
            "templates/change_password.html",
        ):
            html = read(path)
            self.assertIn("static/css/toast.css", html, path)
            self.assertIn("static/js/site_dialogs.js", html, path)
        toast = read("templates/_flash_toasts.html")
        self.assertIn("server-toast alert alert-{{ kind }}", toast)
        self.assertIn('role="alert"', toast)
        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
            if path.name not in ("_flash_toasts.html", "_design_tokens.html")
        )
        for gone in (
            "alert alert-error",
            "alert-{{ category",
            "fbMsg",
            "editorMessage",
            "guessFormError",
            "bingoFormError",
            "bp-password-error",
        ):
            self.assertNotIn(gone, templates)
        # 错误、警告不会自动消失
        self.assertIn(
            "var DURATION = { success: 6000, info: 6000, warning: 0, error: 0 };",
            read("static/js/site_dialogs.js"),
        )

    def test_team_logo_uploads_promise_ten_mb_png_jpg_jpeg_gif(self):
        for path in (
            "templates/admin/teams_form.html",
            "templates/event_detail.html",
            "templates/_event_registration_list.html",
        ):
            html = read(path)
            inputs = re.findall(r'<input[^>]*name="(?:logo|team_logo)"[^>]*>', html, re.S)
            self.assertEqual(len(inputs), 1, path)
            self.assertNotIn("webp", inputs[0].lower(), path)
            self.assertIn(
                'accept="image/png,image/jpeg,image/gif,.png,.jpg,.jpeg,.gif"', inputs[0], path
            )
            self.assertIn('data-max-bytes="10485760"', inputs[0], path)
            self.assertIn("10MB", html, path)
            self.assertNotIn("WebP", html, path)
            self.assertNotRegex(html, r"最大 [25]MB", path)
        self.assertNotIn("WebP", read("static/js/i18n.js"))

    def test_map_tables_show_names_without_cropped_thumbnails(self):
        # 地图统计表里 48x24 的地图小图裁出来只是色块，只显示地图名
        for path in ("templates/event_stats.html", "templates/stats.html"):
            html = read(path)
            self.assertNotIn("stats-map-thumb", html, path)
        self.assertNotIn(".stats-map-thumb", read("static/css/pages/stats.css"))
        self.assertIn(
            "<td><b>{{ ms.map_name|map_display }}</b></td>", read("templates/event_stats.html")
        )
        self.assertIn(
            "<td><b>{{ map_stat.map_name|map_display }}</b></td>", read("templates/stats.html")
        )

    def test_badge_lists_share_column_widths(self):
        # BP 步骤 / 选边、比赛页侧栏状态、获奖名单：各行共用列宽，徽标按最宽的定宽，后面的文字对齐
        match_css = read("static/css/pages/match.css")
        for rule in (
            ".bp-step { grid-column: 1 / -1; grid-template-columns: subgrid; }",
            ".bp-side-row { grid-column: 1 / -1; grid-template-columns: subgrid; }",
            ".sidebar-status-list > .list-row { display: grid; grid-column: 1 / -1; grid-template-columns: subgrid; }",
            ".bp-act, .bp-side-row .badge { justify-self: stretch; justify-content: center; }",
        ):
            self.assertIn(rule, match_css)
        self.assertEqual(
            read("templates/match_detail.html").count('<div class="list sidebar-status-list">'), 2
        )
        awards_css = read("static/css/pages/dashboard.css")
        self.assertIn(
            ".award-medal-row { display: grid; grid-column: 1 / -1; grid-template-columns: subgrid; }",
            awards_css,
        )
        self.assertIn(".award-medal-row .badge { grid-column: 4; }", awards_css)


if __name__ == "__main__":
    unittest.main()
