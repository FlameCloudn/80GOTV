"""为列表头像和手机地图题图生成较小的 WebP 副本。"""

import os
import sys
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.map_quiz_service import ASSET_ROOT, QUESTIONS  # noqa: E402
from utils.db_helpers import create_avatar_thumbnail  # noqa: E402

MAP_MOBILE_WIDTH = 960


def build_avatar_thumbnails():
    avatar_dir = ROOT / "static" / "avatars"
    if not avatar_dir.is_dir():
        return 0
    count = 0
    for source in avatar_dir.iterdir():
        if not source.is_file():
            continue
        if create_avatar_thumbnail(str(ROOT), source.name):
            count += 1
    return count


def build_map_mobile_images():
    count = 0
    output_dir = ASSET_ROOT / "mobile"
    for question in QUESTIONS:
        source_path = ASSET_ROOT / question["image"]
        if not source_path.is_file():
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{source_path.stem}.webp"
        temp_path = output_dir / f".{source_path.stem}.{uuid.uuid4().hex}.tmp"
        try:
            with Image.open(source_path) as source:
                if getattr(source, "is_animated", False):
                    source.seek(0)
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((MAP_MOBILE_WIDTH, MAP_MOBILE_WIDTH), Image.Resampling.LANCZOS)
                image.save(temp_path, format="WEBP", quality=78, method=6)
            os.replace(temp_path, output_path)
            count += 1
        except (OSError, ValueError, UnidentifiedImageError):
            try:
                temp_path.unlink()
            except OSError:
                pass
    return count


def main():
    avatars = build_avatar_thumbnails()
    maps = build_map_mobile_images()
    print(f"已生成头像缩略图 {avatars} 张，手机地图题图 {maps} 张。")


if __name__ == "__main__":
    main()
