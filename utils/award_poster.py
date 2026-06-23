"""Generate shareable MVP / EVP event data cards with Pillow."""

import io
import math
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1600, 900
BG = (20, 24, 30)
PANEL = (31, 37, 46)
PANEL_2 = (41, 48, 58)
WHITE = (241, 244, 247)
MUTED = (169, 179, 190)
LINE = (71, 82, 96)
GOLD = (231, 188, 91)
GREEN = (62, 202, 145)
WIN = (43, 122, 92)
LOSS = (126, 57, 72)
BRAND_BLUE = (80, 127, 168)


def _font(size, bold=False):
    path = "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _fit_font(draw, text, max_width, start_size, min_size=14, bold=False):
    text = str(text or "")
    for size in range(start_size, min_size - 1, -1):
        font = _font(size, bold)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _font(min_size, bold)


def _fit_text(draw, text, max_width, font):
    """Keep unusually long labels inside their allotted space."""
    text = str(text or "")
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return text + suffix


def _fit_avatar(path, size):
    if path and os.path.isfile(path):
        try:
            image = Image.open(path).convert("RGB")
            return ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS), True
        except OSError:
            pass
    return Image.new("RGB", (size, size), PANEL_2), False


def _fit_brand_icon(base_dir, size):
    path = os.path.join(base_dir, "static", "logos", "80gotv-mark.png")
    if not os.path.isfile(path):
        return None
    try:
        image = Image.open(path).convert("RGB")
        return ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS)
    except OSError:
        return None


def _draw_radar(draw, center, radius, dimensions, accent):
    count = len(dimensions)
    points = []
    for ring in range(1, 6):
        ring_points = []
        for index in range(count):
            angle = -math.pi / 2 + 2 * math.pi * index / count
            ring_points.append(
                (
                    center[0] + math.cos(angle) * radius * ring / 5,
                    center[1] + math.sin(angle) * radius * ring / 5,
                )
            )
        draw.polygon(ring_points, outline=LINE)

    for index, (label, display, value) in enumerate(dimensions):
        angle = -math.pi / 2 + 2 * math.pi * index / count
        edge = (center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius)
        draw.line([center, edge], fill=LINE, width=1)
        points.append(
            (
                center[0] + math.cos(angle) * radius * max(0.08, min(1, value)),
                center[1] + math.sin(angle) * radius * max(0.08, min(1, value)),
            )
        )
        label_pos = (
            center[0] + math.cos(angle) * (radius + 48),
            center[1] + math.sin(angle) * (radius + 48),
        )
        label_font = _font(15, True)
        value_font = _font(18, True)
        label_box = draw.textbbox((0, 0), label, font=label_font)
        value_box = draw.textbbox((0, 0), display, font=value_font)
        draw.text(
            (label_pos[0] - (label_box[2] - label_box[0]) / 2, label_pos[1] - 18),
            label,
            font=label_font,
            fill=MUTED,
        )
        draw.text(
            (label_pos[0] - (value_box[2] - value_box[0]) / 2, label_pos[1] + 1),
            display,
            font=value_font,
            fill=accent,
        )

    draw.polygon(points, fill=accent + (105,), outline=accent)
    draw.line(points + [points[0]], fill=accent, width=6, joint="curve")


def _number(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def generate_award_poster(base_dir, player, event, stats, map_rows, award_type):
    """Return an event-level MVP / EVP PNG card."""
    award_type = "EVP" if str(award_type).upper() == "EVP" else "MVP"
    accent = GREEN if award_type == "EVP" else GOLD
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((34, 34, 790, 866), radius=18, fill=PANEL)
    draw.rounded_rectangle((810, 34, 1566, 866), radius=18, fill=PANEL)
    brand_icon = _fit_brand_icon(base_dir, 54)
    if brand_icon:
        image.paste(brand_icon, (1352, 60))
    draw.text((1526, 70), "80GOTV", font=_font(28, True), fill=BRAND_BLUE, anchor="ra")

    nickname = str(player.get("nickname") or "PLAYER")
    avatar_path = os.path.join(base_dir, "static", "avatars", player.get("avatar") or "")
    avatar, has_avatar = _fit_avatar(avatar_path, 350)
    image.paste(avatar, (62, 62))
    draw.rounded_rectangle((62, 62, 412, 412), radius=14, outline=accent, width=4)
    if not has_avatar:
        initial = nickname[:1].upper() or "?"
        draw.text((237, 237), initial, font=_font(120, True), fill=MUTED, anchor="mm")

    draw.rounded_rectangle((438, 72, 560, 124), radius=8, fill=accent)
    draw.text((499, 98), award_type, font=_font(30, True), fill=BG, anchor="mm")
    nickname_font = _fit_font(draw, nickname, 320, 52, 12, True)
    draw.text(
        (438, 162), _fit_text(draw, nickname, 320, nickname_font), font=nickname_font, fill=WHITE
    )
    team_name = str(player.get("team_name") or "NO TEAM")
    team_font = _fit_font(draw, team_name, 320, 25, 12)
    draw.text((438, 232), _fit_text(draw, team_name, 320, team_font), font=team_font, fill=MUTED)
    event_name = str(event.get("name") or "80GOTV EVENT")
    draw.text(
        (62, 448), event_name, font=_fit_font(draw, event_name, 700, 31, 18, True), fill=WHITE
    )
    draw.text(
        (62, 495),
        f"{int(stats.get('maps', 0) or 0)} MAPS  |  {int(stats.get('kills', 0) or 0)}-{int(stats.get('deaths', 0) or 0)} K-D",
        font=_font(21),
        fill=MUTED,
    )

    headers = [
        ("Score", 62),
        ("Opponent", 166),
        ("Map", 292),
        ("Stage", 448),
        ("K-D", 525),
        ("RATING", 646),
    ]
    for label, x in headers:
        draw.text((x, 558), label, font=_font(14, True), fill=MUTED)
    for index, row in enumerate(map_rows[:3]):
        y = 592 + index * 78
        draw.rounded_rectangle((52, y, 772, y + 64), radius=7, fill=PANEL_2)
        score_for = int(row.get("score_for") or 0)
        score_against = int(row.get("score_against") or 0)
        score_fill = (
            WIN if score_for > score_against else (LOSS if score_for < score_against else LINE)
        )
        draw.rounded_rectangle((62, y + 8, 150, y + 56), radius=6, fill=score_fill)
        draw.text(
            (106, y + 32),
            f"{score_for}-{score_against}",
            font=_font(21, True),
            fill=WHITE,
            anchor="mm",
        )
        opponent = str(row.get("opponent") or "-")
        from utils.helpers import map_display_name

        map_name = map_display_name(row.get("map_name") or "TBA").upper()
        stage = str(row.get("stage") or "-")
        opponent_font = _fit_font(draw, opponent, 110, 18, 11, True)
        map_font = _fit_font(draw, map_name, 142, 18, 11)
        stage_font = _fit_font(draw, stage, 64, 18, 11)
        draw.text(
            (166, y + 21),
            _fit_text(draw, opponent, 110, opponent_font),
            font=opponent_font,
            fill=WHITE,
        )
        draw.text(
            (292, y + 21), _fit_text(draw, map_name, 142, map_font), font=map_font, fill=WHITE
        )
        draw.text(
            (448, y + 21), _fit_text(draw, stage, 64, stage_font), font=stage_font, fill=MUTED
        )
        draw.text(
            (525, y + 21),
            f"{int(row.get('kills') or 0)}-{int(row.get('deaths') or 0)}",
            font=_font(18),
            fill=WHITE,
        )
        draw.text(
            (646, y + 19), f"{_number(row.get('rating')):.2f}", font=_font(21, True), fill=WHITE
        )

    rating = _number(stats.get("rating"))
    adr = _number(stats.get("adr"))
    kast = _number(stats.get("kast"))
    impact = _number(stats.get("impact"))
    kd = _number(stats.get("kd"))
    kpr = _number(stats.get("kpr"))
    dpr = _number(stats.get("dpr"))
    two_k_pct = _number(stats.get("two_k_pct"))
    one_k_pct = _number(stats.get("one_k_pct"))
    rws_basic = _number(stats.get("rws_basic"))
    dmg_delta = _number(stats.get("dmg_delta"))
    kills_delta = _number(stats.get("kills_delta"))
    dimensions = [
        ("RATING 2.0", f"{rating:.2f}", rating / 1.5),
        ("KPR", f"{kpr:.2f}", kpr / 1.0),
        ("ADR", f"{adr:.1f}", adr / 110),
        ("DPR", f"{dpr:.2f}", (1.05 - dpr) / 0.45),
        ("K/D", f"{kd:.2f}", kd / 1.6),
        ("2K+ ROUNDS", f"{two_k_pct:.0f}%", two_k_pct / 30),
        ("1K+ ROUNDS", f"{one_k_pct:.0f}%", one_k_pct / 80),
        ("KAST", f"{kast:.0f}%", kast / 90),
        ("RWS BASIC", f"{rws_basic:.1f}", rws_basic / 15),
        ("DMG Δ/R", f"{dmg_delta:+.1f}", (dmg_delta + 30) / 80),
        ("KILLS Δ/R", f"{kills_delta:+.2f}", (kills_delta + 0.25) / 0.65),
        ("IMPACT", f"{impact:.2f}", impact / 1.5),
    ]
    draw.text((854, 72), "PERFORMANCE OVERVIEW", font=_font(21, True), fill=MUTED)
    _draw_radar(draw, (1188, 390), 198, dimensions, accent)
    draw.rounded_rectangle((850, 756, 1526, 832), radius=8, fill=PANEL_2)
    draw.text(
        (1188, 794),
        event_name,
        font=_fit_font(draw, event_name, 610, 34, 18, True),
        fill=WHITE,
        anchor="mm",
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
