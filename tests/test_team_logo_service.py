"""队标自动处理：去纯色背景、保留图案内部同色区域、去水印碎块、统一尺寸和地址。"""

import io
import os
import random
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from PIL import Image, ImageDraw
from werkzeug.datastructures import FileStorage

from app import app
from services.team_logo_service import (
    TEAM_LOGO_SIZE,
    logo_relative_path,
    original_logo_path,
    process_logo_image,
    team_logo_static_path,
    team_logo_url,
)
from utils.db_helpers import remove_uploaded_team_logo, save_uploaded_team_logo


def ring_logo(background=(255, 255, 255), ring=(0, 0, 0), inner=(255, 255, 255), size=200):
    """纯色底上画一个圆环，圆环里面和背景同色（模拟“图案里面的白色”）。"""
    image = Image.new("RGB", (size, size), background)
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 40, size - 40, size - 40), fill=ring)
    draw.ellipse((70, 70, size - 70, size - 70), fill=inner)
    return image


def rgba_at(image, x, y):
    """取一个像素的 (R, G, B, A)。"""
    pixel = image.getpixel((x, y))
    assert isinstance(pixel, tuple)
    return pixel


def alpha_at(image, x, y):
    return rgba_at(image, x, y)[3]


def rgba_pixels(image):
    """整张图每个像素的 (R, G, B, A)。"""
    return [pixel for pixel in image.get_flattened_data() if isinstance(pixel, tuple)]


def visible_box(image, threshold=0):
    """透明度大于 threshold 的部分占的范围 (左, 上, 右, 下)。"""
    alpha = image.getchannel("A")
    if threshold:
        alpha = alpha.point([0] * (threshold + 1) + [255] * (255 - threshold))
    box = alpha.getbbox()
    assert box is not None
    return box


class ProcessLogoImageTests(unittest.TestCase):
    def test_white_background_becomes_transparent_but_enclosed_white_stays(self):
        result = process_logo_image(ring_logo())
        self.assertEqual(result.size, (TEAM_LOGO_SIZE, TEAM_LOGO_SIZE))
        self.assertEqual(alpha_at(result, 2, 2), 0)
        centre = rgba_at(result, TEAM_LOGO_SIZE // 2, TEAM_LOGO_SIZE // 2)
        self.assertEqual(centre[3], 255)
        self.assertGreater(min(centre[:3]), 240)

    def test_black_background_is_removed_too(self):
        logo = ring_logo(background=(6, 8, 12), ring=(40, 140, 220), inner=(200, 60, 60))
        result = process_logo_image(logo)
        self.assertEqual(alpha_at(result, 2, 2), 0)
        self.assertEqual(alpha_at(result, TEAM_LOGO_SIZE // 2, TEAM_LOGO_SIZE // 2), 255)

    def test_dark_texture_on_dark_background_is_kept(self):
        image = Image.new("RGB", (200, 200), (6, 8, 12))
        draw = ImageDraw.Draw(image)
        # 深蓝色的暗纹，和背景色很接近（算“很淡”）
        draw.rectangle((40, 40, 160, 160), fill=(24, 30, 45))
        draw.ellipse((70, 70, 130, 130), fill=(80, 170, 240))
        result = process_logo_image(image)
        self.assertEqual(alpha_at(result, 2, 2), 0)
        # 暗纹区域仍然保留（不透明的深蓝色像素还有一大片）
        dark_blue = [
            pixel
            for pixel in rgba_pixels(result)
            if pixel[3] > 200 and pixel[0] < 40 and pixel[2] < 70
        ]
        self.assertGreater(len(dark_blue), 10000)

    def test_logo_is_trimmed_and_centred_with_even_margin(self):
        image = Image.new("RGB", (300, 120), (255, 255, 255))
        ImageDraw.Draw(image).rectangle((200, 30, 279, 89), fill=(220, 30, 30))
        result = process_logo_image(image)
        left, top, right, bottom = visible_box(result)
        self.assertAlmostEqual(left, TEAM_LOGO_SIZE - right, delta=2)
        self.assertAlmostEqual(top, TEAM_LOGO_SIZE - bottom, delta=2)
        self.assertLess(left, TEAM_LOGO_SIZE * 0.12)

    def test_transparent_logo_keeps_its_own_transparency(self):
        image = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(image).ellipse((10, 10, 110, 110), fill=(255, 255, 255, 255))
        result = process_logo_image(image)
        self.assertEqual(alpha_at(result, TEAM_LOGO_SIZE // 2, TEAM_LOGO_SIZE // 2), 255)
        self.assertEqual(alpha_at(result, 3, 3), 0)

    def test_busy_photo_background_is_left_alone(self):
        rng = random.Random(7)
        image = Image.new("RGB", (120, 120))
        image.putdata(
            [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(120 * 120)]
        )
        result = process_logo_image(image)
        # 画面本身（去掉外圈留白后）的角上仍然是不透明的
        left, top, _, _ = visible_box(result, threshold=128)
        self.assertEqual(alpha_at(result, left + 1, top + 1), 255)

    def test_plain_single_colour_upload_is_not_erased(self):
        result = process_logo_image(Image.new("RGB", (90, 60), (180, 60, 50)))
        self.assertEqual(alpha_at(result, TEAM_LOGO_SIZE // 2, TEAM_LOGO_SIZE // 2), 255)

    def test_antialiased_edge_has_no_white_halo(self):
        big = Image.new("RGB", (800, 800), (255, 255, 255))
        ImageDraw.Draw(big).ellipse((100, 100, 700, 700), fill=(0, 0, 0))
        result = process_logo_image(big.resize((200, 200), Image.Resampling.LANCZOS))
        halo = [
            pixel for pixel in rgba_pixels(result) if 20 < pixel[3] < 235 and max(pixel[:3]) > 140
        ]
        self.assertEqual(halo, [])

    def test_faint_watermark_near_edge_is_removed_but_bright_detail_is_kept(self):
        image = Image.new("RGB", (240, 240), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((50, 30, 190, 180), fill=(0, 0, 0))
        for x in range(10, 52, 9):  # 一排淡灰色的小“字”，模拟网站水印
            draw.rectangle((x, 224, x + 5, 232), fill=(232, 232, 232))
        draw.ellipse((195, 30, 207, 42), fill=(230, 20, 20))  # 主体旁边的红点
        result = process_logo_image(image)
        pixels = rgba_pixels(result)
        reds = [p for p in pixels if p[3] > 200 and p[0] > 180 and p[1] < 80]
        greys = [p for p in pixels if p[3] > 60 and 150 < p[0] == p[1] == p[2]]
        self.assertTrue(reds)
        self.assertEqual(greys, [])


class LogoPathTests(unittest.TestCase):
    def test_every_stored_form_maps_to_one_relative_path(self):
        for value in (
            "a.png",
            "team_logos/a.png",
            "uploads/team_logos/a.png",
            "/static/uploads/team_logos/a.png",
            "static\\uploads\\team_logos\\a.png",
        ):
            self.assertEqual(logo_relative_path(value), "team_logos/a.png", value)
        self.assertEqual(logo_relative_path(""), "")
        self.assertEqual(logo_relative_path(None), "")
        self.assertEqual(
            logo_relative_path("https://cdn.example/x.png"), "https://cdn.example/x.png"
        )
        self.assertEqual(logo_relative_path("/static/images/x.png"), "/static/images/x.png")

    def test_static_path_and_url(self):
        self.assertEqual(team_logo_static_path("a.png"), "/static/uploads/team_logos/a.png")
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "static", "uploads", "team_logos")
            os.makedirs(folder)
            Image.new("RGBA", (4, 4)).save(os.path.join(folder, "a.png"))
            with app.test_request_context():
                url = team_logo_url("a.png", root)
                missing = team_logo_url("b.png", root)
        self.assertTrue(url.startswith("/static/uploads/team_logos/a.png?v="))
        self.assertEqual(missing, "/static/uploads/team_logos/b.png")


class SaveUploadedLogoTests(unittest.TestCase):
    def upload(self, image, name="logo.png", fmt="PNG"):
        data = io.BytesIO()
        image.save(data, format=fmt)
        data.seek(0)
        return FileStorage(stream=data, filename=name)

    def test_upload_is_processed_backed_up_and_removable(self):
        with tempfile.TemporaryDirectory() as root:
            filename = save_uploaded_team_logo(self.upload(ring_logo(), "logo.jpg", "JPEG"), root)
            assert filename is not None
            self.assertTrue(filename.endswith(".png"))
            saved = os.path.join(root, "static", "uploads", "team_logos", filename)
            with Image.open(saved) as logo:
                self.assertEqual(logo.size, (TEAM_LOGO_SIZE, TEAM_LOGO_SIZE))
                self.assertEqual(logo.mode, "RGBA")
                self.assertEqual(alpha_at(logo, 1, 1), 0)
            self.assertTrue(os.path.isfile(original_logo_path(root, filename)))
            remove_uploaded_team_logo(root, filename)
            self.assertFalse(os.path.exists(saved))
            self.assertFalse(os.path.exists(original_logo_path(root, filename)))

    def test_fake_image_is_rejected(self):
        fake = FileStorage(stream=io.BytesIO(b"not an image"), filename="fake.png")
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(save_uploaded_team_logo(fake, root))


class ProcessExistingLogosScriptTests(unittest.TestCase):
    def test_script_processes_files_and_repairs_missing_team_logo(self):
        import scripts.process_team_logos as script

        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "static", "uploads", "team_logos")
            os.makedirs(folder)
            ring_logo().save(os.path.join(folder, "reg.png"))
            ring_logo(ring=(200, 30, 30)).save(os.path.join(folder, "bravo.png"))
            database = os.path.join(root, "site.db")
            with closing(sqlite3.connect(database)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE teams(id INTEGER PRIMARY KEY, name TEXT, logo TEXT);
                    CREATE TABLE event_registrations(id INTEGER PRIMARY KEY, team_name TEXT, team_logo TEXT);
                    INSERT INTO teams VALUES(1, 'Alpha', 'team_logos/missing.png');
                    INSERT INTO teams VALUES(2, 'Bravo', '');
                    INSERT INTO teams VALUES(3, 'Charlie', NULL);
                    INSERT INTO event_registrations VALUES(1, 'alpha', 'reg.png');
                    INSERT INTO event_registrations VALUES(2, ' BRAVO ', 'bravo.png');
                    """
                )
                conn.commit()

            def connect():
                conn = sqlite3.connect(database)
                conn.row_factory = sqlite3.Row
                return conn

            with patch.object(script, "get_db", connect):
                with patch("sys.argv", ["process_team_logos.py", "--root", root]):
                    script.main()  # 只检查：不改动
                with Image.open(os.path.join(folder, "reg.png")) as unchanged:
                    self.assertEqual(unchanged.size, (200, 200))
                with closing(sqlite3.connect(database)) as conn:
                    self.assertEqual(
                        conn.execute("SELECT logo FROM teams WHERE id=2").fetchone()[0], ""
                    )
                with patch("sys.argv", ["process_team_logos.py", "--root", root, "--apply"]):
                    script.main()
                    script.main()  # 重复运行也安全：仍然从原图备份处理
            with Image.open(os.path.join(folder, "reg.png")) as processed:
                self.assertEqual(processed.size, (TEAM_LOGO_SIZE, TEAM_LOGO_SIZE))
            with Image.open(original_logo_path(root, "reg.png")) as backup:
                self.assertEqual(backup.size, (200, 200))
            with closing(sqlite3.connect(database)) as conn:
                logos = dict(conn.execute("SELECT id, logo FROM teams").fetchall())
            self.assertEqual(logos[1], "team_logos/reg.png")  # 文件丢了 → 改用同名报名队标
            self.assertEqual(logos[2], "team_logos/bravo.png")  # 没填队标 → 补上同名报名队标
            self.assertIsNone(logos[3])  # 没有同名报名队标的保持原样


if __name__ == "__main__":
    unittest.main()
