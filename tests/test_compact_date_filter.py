import unittest
from datetime import date

from utils.filters import compact_date_display_filter, relative_date_display_filter


class CompactDateDisplayFilterTests(unittest.TestCase):
    def test_formats_date_with_zero_padding(self):
        self.assertEqual(compact_date_display_filter("2026-7-2"), "2026/07/02")

    def test_keeps_invalid_fallback_compact(self):
        self.assertEqual(compact_date_display_filter("2026-07-21 extra"), "2026/07/21")

    def test_formats_relative_dates(self):
        today = date(2026, 7, 21)
        self.assertEqual(relative_date_display_filter("2026-07-21", today), "今天")
        self.assertEqual(relative_date_display_filter("2026-07-24", today), "3天后")
        self.assertEqual(relative_date_display_filter("2026-07-18", today), "3天前")


if __name__ == "__main__":
    unittest.main()
