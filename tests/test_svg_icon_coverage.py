import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICON_SCRIPT = ROOT / "static" / "js" / "svg_icons.js"

# 网页中会当作图案显示的符号范围；版权符号不属于图标。
TEXT_SYMBOLS = {
    0x2139,
    0x2190,
    0x2195,
    0x23F3,
    0x25B6,
    0x2630,
    0x2694,
    0x2699,
    0x26A0,
    0x2705,
    0x2713,
    0x2715,
    0x274C,
    0x2764,
    0x2795,
}


def website_files():
    patterns = (
        "templates/**/*.html",
        "static/js/*.js",
        "static/css/*.css",
        "static/replay_tool/assets/*.js",
    )
    for pattern in patterns:
        yield from ROOT.glob(pattern)


def emoji_codepoints(text):
    for char in text:
        codepoint = ord(char)
        if 0x1F000 <= codepoint <= 0x1FAFF or codepoint in TEXT_SYMBOLS:
            yield codepoint


class SvgIconCoverageTests(unittest.TestCase):
    def test_every_website_emoji_has_an_svg_mapping(self):
        icon_source = ICON_SCRIPT.read_text(encoding="utf-8")
        mapped = {int(value, 16) for value in re.findall(r"add\(0x([0-9a-f]+),", icon_source, re.I)}

        missing = {}
        for file_path in website_files():
            if file_path == ICON_SCRIPT:
                continue
            source = file_path.read_text(encoding="utf-8")
            for codepoint in emoji_codepoints(source):
                if codepoint not in mapped:
                    missing.setdefault(chr(codepoint), set()).add(
                        file_path.relative_to(ROOT).as_posix()
                    )

        details = ", ".join(
            f"{symbol}: {sorted(files)}" for symbol, files in sorted(missing.items())
        )
        self.assertFalse(missing, f"这些图案缺少 SVG：{details}")

    def test_replay_tool_loads_svg_replacement(self):
        replay_html = (ROOT / "static" / "replay_tool" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/static/js/svg_icons.js", replay_html)
        self.assertIn("window.location.pathname === '/replay-tool/'", replay_html)


if __name__ == "__main__":
    unittest.main()
