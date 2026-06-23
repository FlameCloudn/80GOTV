"""Dark-theme match poster generator using Pillow."""

import io

from PIL import Image, ImageDraw, ImageFont

from utils.helpers import map_display_name

W, H = 750, 1050
BG = (22, 22, 40)
CARD_BG = (32, 32, 55)
ACCENT = (88, 129, 188)
GOLD = (222, 155, 55)
GREEN = (34, 197, 94)
RED = (239, 68, 68)
WHITE = (240, 240, 245)
MUTED = (150, 150, 170)
DIVIDER = (60, 60, 90)

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"


def _font(size, bold=False):
    path = "C:/Windows/Fonts/msyhbd.ttc" if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _draw_centered(draw, text, y, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (W - tw) / 2
    draw.text((x, y), text, font=font, fill=fill)
    return y + (bbox[3] - bbox[1])


def _draw_left(draw, text, x, y, font, fill):
    draw.text((x, y), text, font=font, fill=fill)
    bbox = draw.textbbox((0, 0), text, font=font)
    return y + (bbox[3] - bbox[1])


def _draw_right(draw, text, x, y, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((x - tw, y), text, font=font, fill=fill)
    return y + (bbox[3] - bbox[1])


def _poster_date(value):
    try:
        from datetime import datetime

        dt_val = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return f"{dt_val.year}年{dt_val.month}月{dt_val.day}日"
    except Exception:
        return str(value or "")[:10]


def _short_text(draw, text, max_width, font):
    text = str(text or "-")
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "...", font=font) > max_width:
        text = text[:-1]
    return text + "..."


def generate_match_poster(match, map_scores, player_ratings=None):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    y = 40

    # Event name
    event_name = match.get("event_name") or ""
    if event_name:
        fn = _font(20)
        y = _draw_centered(draw, event_name.upper(), y, fn, MUTED)
        y += 24

    # Divider line
    y += 8
    draw.line([(120, y), (W - 120, y)], fill=DIVIDER, width=1)
    y += 32

    # Team names
    t1_name = match.get("team1_name") or "队伍 1"
    t2_name = match.get("team2_name") or "队伍 2"
    t1s = match.get("t1s") or t1_name[:3]
    t2s = match.get("t2s") or t2_name[:3]

    # Team 1 left
    draw.text((80, y), t1s, font=_font(28, bold=True), fill=WHITE)
    # VS
    vs_text = "VS"
    _draw_centered(draw, vs_text, y + 4, _font(16), MUTED)
    # Team 2 right
    t2_bbox = draw.textbbox((0, 0), t2s, font=_font(28, bold=True))
    t2w = t2_bbox[2] - t2_bbox[0]
    draw.text((W - 80 - t2w, y), t2s, font=_font(28, bold=True), fill=WHITE)

    y += 50

    # Full names
    fn_name = _font(18)
    _draw_centered(draw, f"{t1_name}    vs    {t2_name}", y, fn_name, MUTED)
    y += 36

    # Score
    s1 = match.get("team1_score") or 0
    s2 = match.get("team2_score") or 0
    score_text = f"{s1} : {s2}"
    fn_score = _font(72, bold=True)
    _draw_centered(draw, score_text, y, fn_score, WHITE)
    y += 80

    # Format + date
    bo = match.get("bo_format") or "BO3"
    match_time = match.get("match_time") or ""
    date_str = _poster_date(match_time) if match_time else ""
    meta_text = f"{bo}  ·  {date_str}"
    _draw_centered(draw, meta_text, y, _font(18), MUTED)
    y += 48

    # Map scores section
    draw.line([(60, y), (W - 60, y)], fill=DIVIDER, width=1)
    y += 28
    _draw_centered(draw, "MAP SCORES", y, _font(14), ACCENT)
    y += 32

    if map_scores:
        fn_map = _font(18)
        fn_map_bold = _font(18, bold=True)
        for ms in map_scores:
            map_name = map_display_name(ms.get("name") or "TBA")
            t1 = ms.get("t1") or 0
            t2 = ms.get("t2") or 0
            played = ms.get("played")

            col_w = 540
            x0 = (W - col_w) / 2

            draw.text((x0, y), map_name, font=fn_map, fill=WHITE)

            if played:
                score_str = f"{t1} : {t2}"
                _draw_centered(draw, score_str, y, fn_map_bold, WHITE)
            else:
                _draw_centered(draw, "-", y, fn_map, MUTED)

            # Win indicator
            if played and t1 != t2:
                wx = x0 + col_w + 8
                bbox = draw.textbbox((0, 0), map_name, font=fn_map)
                wy = y + (bbox[3] - bbox[1] - 16) / 2
                draw.text((wx, wy), "胜", font=_font(14, bold=True), fill=GREEN)

            y += 32

    ratings = player_ratings or []
    t1_key = match.get("team1_id") or -1
    t2_key = match.get("team2_id") or -2
    t1_ratings = [r for r in ratings if r.get("team_id") == t1_key][:5]
    t2_ratings = [r for r in ratings if r.get("team_id") == t2_key][:5]
    if t1_ratings or t2_ratings:
        y += 18
        draw.line([(60, y), (W - 60, y)], fill=DIVIDER, width=1)
        y += 20
        _draw_centered(draw, "RATING", y, _font(14), ACCENT)
        y += 30
        fn_rating = _font(15)
        fn_rating_bold = _font(15, bold=True)
        for index in range(max(len(t1_ratings), len(t2_ratings))):
            if index < len(t1_ratings):
                row = t1_ratings[index]
                draw.text(
                    (78, y),
                    _short_text(draw, row.get("nickname"), 165, fn_rating),
                    font=fn_rating,
                    fill=WHITE,
                )
                _draw_right(
                    draw, f"{float(row.get('rating') or 0):.2f}", 330, y, fn_rating_bold, ACCENT
                )
            if index < len(t2_ratings):
                row = t2_ratings[index]
                draw.text(
                    (420, y),
                    f"{float(row.get('rating') or 0):.2f}",
                    font=fn_rating_bold,
                    fill=ACCENT,
                )
                _draw_right(
                    draw,
                    _short_text(draw, row.get("nickname"), 165, fn_rating),
                    672,
                    y,
                    fn_rating,
                    WHITE,
                )
            y += 25

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
