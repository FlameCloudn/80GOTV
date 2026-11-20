"""生成并核对图片验证码。"""

import hashlib
import hmac
import io
import os
import secrets
import time

from flask import Response, current_app, session
from PIL import Image, ImageDraw, ImageFont

from src.website.runtime.config import Config
from src.website.web.routing import site_routes

CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


CAPTCHA_MAX_AGE = 5 * 60


def _captcha_digest(nonce, answer):
    key = str(current_app.secret_key or Config.SECRET_KEY).encode("utf-8")
    value = f"{nonce}:{answer.upper()}".encode("utf-8")
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def _generate_captcha():
    """清除旧验证码；图片请求会生成一个新的验证码。"""
    session.pop("captcha_challenge", None)


def _check_captcha(user_input):
    """验证码只能使用一次，且五分钟后自动失效。"""
    challenge = session.pop("captcha_challenge", None) or {}
    if float(challenge.get("expires_at", 0)) < time.time():
        return False
    supplied = str(user_input or "").strip().upper()
    actual = _captcha_digest(challenge.get("nonce", ""), supplied)
    return bool(supplied) and hmac.compare_digest(actual, challenge.get("digest", ""))


@site_routes.route("/captcha/reload")
def reload_captcha():
    _generate_captcha()
    return "", 204


@site_routes.route("/captcha/image")
def captcha_image():
    code = "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(5))
    nonce = secrets.token_hex(16)
    session["captcha_challenge"] = {
        "nonce": nonce,
        "digest": _captcha_digest(nonce, code),
        "expires_at": time.time() + CAPTCHA_MAX_AGE,
    }

    image = Image.new("RGB", (150, 48), (244, 247, 250))
    draw = ImageDraw.Draw(image)
    for _ in range(5):
        color = tuple(150 + secrets.randbelow(70) for _ in range(3))
        draw.line(
            (
                secrets.randbelow(150),
                secrets.randbelow(48),
                secrets.randbelow(150),
                secrets.randbelow(48),
            ),
            fill=color,
            width=1,
        )
    font_path = os.path.join(
        current_app.root_path, "resources", "fonts", "TestTiemposText-Regular.otf"
    )
    angles = (-24, -18, -12, 12, 18, 24)
    colors = (
        (32, 92, 160, 255),
        (155, 48, 66, 255),
        (35, 118, 91, 255),
        (116, 69, 159, 255),
        (177, 92, 28, 255),
        (41, 116, 133, 255),
    )
    for index, char in enumerate(code):
        char_layer = Image.new("RGBA", (40, 48), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_layer)
        font_size = 14 + secrets.randbelow(17)
        try:
            char_font = ImageFont.truetype(font_path, font_size)
        except OSError:
            char_font = ImageFont.load_default()
        bounds = char_draw.textbbox((0, 0), char, font=char_font)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        text_x = (40 - text_width) // 2 - bounds[0]
        text_y = (48 - text_height) // 2 - bounds[1] + secrets.randbelow(5) - 2
        char_draw.text(
            (text_x, text_y),
            char,
            font=char_font,
            fill=secrets.choice(colors),
        )
        char_layer = char_layer.rotate(
            secrets.choice(angles),
            resample=Image.Resampling.BICUBIC,
            expand=False,
        )
        image.paste(char_layer, (5 + index * 28, 0), char_layer)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    response = Response(output.getvalue(), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response
