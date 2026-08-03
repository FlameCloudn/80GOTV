import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from services import map_quiz_service
from utils.db_helpers import avatar_static_filename, create_avatar_thumbnail


class FrontendImageTests(unittest.TestCase):
    def test_avatar_thumbnail_size_and_original_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            avatar_dir = root / "static" / "avatars"
            avatar_dir.mkdir(parents=True)
            Image.new("RGB", (800, 400), "#d94141").save(avatar_dir / "player.png")

            thumbnail = create_avatar_thumbnail(str(root), "player.png")

            self.assertEqual(thumbnail, "player.webp")
            thumbnail_path = avatar_dir / "thumbs" / thumbnail
            with Image.open(thumbnail_path) as generated:
                self.assertEqual(generated.size, (160, 80))
                self.assertEqual(generated.format, "WEBP")
            self.assertEqual(
                avatar_static_filename(str(root), "player.png"),
                "avatars/thumbs/player.webp",
            )

            thumbnail_path.unlink()
            self.assertEqual(
                avatar_static_filename(str(root), "player.png"),
                "avatars/player.png",
            )
            self.assertIsNone(avatar_static_filename(str(root), "../player.png"))

    def test_map_mobile_variant_fallback_and_path_safety(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_root = root / "map-quiz"
            mobile_dir = asset_root / "mobile"
            mobile_dir.mkdir(parents=True)
            original = asset_root / "ancient.webp"
            mobile = mobile_dir / "ancient.webp"
            original.write_bytes(b"original")
            mobile.write_bytes(b"mobile")

            unsafe_question = {
                "key": "unsafe",
                "image": "../outside.jpg",
            }
            (root / "outside.jpg").write_bytes(b"outside")
            (mobile_dir / "outside.webp").write_bytes(b"must-not-bypass-check")

            with (
                patch.object(map_quiz_service, "ASSET_ROOT", asset_root),
                patch.dict(
                    map_quiz_service.QUESTION_BY_KEY,
                    {"unsafe": unsafe_question},
                    clear=False,
                ),
            ):
                self.assertEqual(
                    map_quiz_service.question_image_path("mq_11c7a9", "mobile"),
                    mobile.resolve(),
                )
                mobile.unlink()
                self.assertEqual(
                    map_quiz_service.question_image_path("mq_11c7a9", "mobile"),
                    original.resolve(),
                )
                self.assertIsNone(map_quiz_service.question_image_path("unsafe"))
                self.assertIsNone(map_quiz_service.question_image_path("unsafe", "mobile"))
                self.assertIsNone(map_quiz_service.question_image_path("../../unsafe"))


if __name__ == "__main__":
    unittest.main()
