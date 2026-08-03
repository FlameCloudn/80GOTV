"""
数据库操作辅助函数：头像保存、文件验证等
"""

import os
import uuid
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

# Image magic bytes validation
IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
TEAM_LOGO_MAX_DIMENSION = 512
AVATAR_THUMBNAIL_DIMENSION = 160
Image.MAX_IMAGE_PIXELS = 25_000_000


def validate_image_content(file_stream):
    """验证上传文件是否为体积合理的真实图片。"""
    try:
        file_stream.seek(0, os.SEEK_END)
        size = file_stream.tell()
        file_stream.seek(0)
    except (AttributeError, OSError):
        return None
    if size <= 0 or size > MAX_IMAGE_UPLOAD_BYTES:
        return None

    header = file_stream.read(8)
    file_stream.seek(0)
    detected_ext = None
    for sig, ext in IMAGE_SIGNATURES.items():
        if header.startswith(sig):
            detected_ext = ext
            break
    if not detected_ext:
        return None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file_stream) as image:
                image.verify()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ):
        file_stream.seek(0)
        return None
    file_stream.seek(0)
    return detected_ext


def allowed_image_file(filename):
    """检查文件名是否为支持的图片格式。"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in IMAGE_EXTENSIONS


def avatar_thumbnail_filename(filename):
    """返回头像缩略图文件名；不接受带目录的输入。"""
    if not filename or os.path.basename(filename) != filename:
        return None
    stem, _ = os.path.splitext(filename)
    return f"{stem}.webp" if stem else None


def avatar_static_filename(app_root_path, filename, thumbnail=True):
    """返回供 static 使用的安全头像相对路径，缩略图不存在时退回原图。"""
    if not filename or os.path.basename(filename) != filename:
        return None
    if thumbnail:
        thumb_name = avatar_thumbnail_filename(filename)
        if thumb_name:
            thumb_path = os.path.join(app_root_path, "static", "avatars", "thumbs", thumb_name)
            if os.path.isfile(thumb_path):
                return f"avatars/thumbs/{thumb_name}"
    return f"avatars/{filename}"


def create_avatar_thumbnail(app_root_path, filename):
    """从原头像生成 160px WebP 副本；失败时保留并继续使用原图。"""
    thumb_name = avatar_thumbnail_filename(filename)
    if not thumb_name:
        return None
    avatar_dir = os.path.join(app_root_path, "static", "avatars")
    source_path = os.path.join(avatar_dir, filename)
    if not os.path.isfile(source_path):
        return None

    thumb_dir = os.path.join(avatar_dir, "thumbs")
    os.makedirs(thumb_dir, exist_ok=True)
    thumb_path = os.path.join(thumb_dir, thumb_name)
    temp_path = f"{thumb_path}.{uuid.uuid4().hex}.tmp"
    try:
        with Image.open(source_path) as source:
            if getattr(source, "is_animated", False):
                source.seek(0)
            source.load()
            image = ImageOps.exif_transpose(source)
            has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            image.thumbnail(
                (AVATAR_THUMBNAIL_DIMENSION, AVATAR_THUMBNAIL_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            image.save(temp_path, format="WEBP", quality=80, method=6)
        os.replace(temp_path, thumb_path)
        return thumb_name
    except (OSError, ValueError, UnidentifiedImageError):
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return None


def remove_uploaded_avatar(app_root_path, filename):
    """删除站内旧头像，不接受带目录的文件名。"""
    if not filename or os.path.basename(filename) != filename:
        return
    old_path = os.path.join(app_root_path, "static", "avatars", filename)
    if os.path.isfile(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass
    thumb_name = avatar_thumbnail_filename(filename)
    if thumb_name:
        thumb_path = os.path.join(app_root_path, "static", "avatars", "thumbs", thumb_name)
        if os.path.isfile(thumb_path):
            try:
                os.remove(thumb_path)
            except OSError:
                pass


def save_uploaded_avatar(file, app_root_path, old_avatar=None):
    """
    保存上传的头像文件，返回新文件名。
    如果提供了 old_avatar，会删除旧文件。

    返回 (new_filename, ext) 或 (None, None) 如果文件无效。
    """
    if not file or not file.filename:
        return None, None

    if not allowed_image_file(file.filename):
        return None, None

    ext = validate_image_content(file.stream)
    if not ext:
        return None, None

    filename = f"{uuid.uuid4().hex}.{ext}"
    avatar_dir = os.path.join(app_root_path, "static", "avatars")
    os.makedirs(avatar_dir, exist_ok=True)
    file.save(os.path.join(avatar_dir, filename))
    create_avatar_thumbnail(app_root_path, filename)

    # 删除旧头像
    if old_avatar:
        remove_uploaded_avatar(app_root_path, old_avatar)

    return filename, ext


def remove_uploaded_team_logo(app_root_path, filename):
    """删除报名队伍的旧队标，只接受本站生成的纯文件名。"""
    if not filename or os.path.basename(filename) != filename:
        return
    logo_path = os.path.join(app_root_path, "static", "uploads", "team_logos", filename)
    if os.path.isfile(logo_path):
        try:
            os.remove(logo_path)
        except OSError:
            pass


def save_uploaded_team_logo(file, app_root_path):
    """验证并压缩队标，统一保存为不带动画和元数据的 PNG。"""
    if not file or not file.filename or not allowed_image_file(file.filename):
        return None
    if not validate_image_content(file.stream):
        return None

    logo_dir = os.path.join(app_root_path, "static", "uploads", "team_logos")
    os.makedirs(logo_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    logo_path = os.path.join(logo_dir, filename)
    try:
        with Image.open(file.stream) as source:
            if getattr(source, "is_animated", False):
                source.seek(0)
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail(
                (TEAM_LOGO_MAX_DIMENSION, TEAM_LOGO_MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            image.save(logo_path, format="PNG", optimize=True)
    except (OSError, ValueError, UnidentifiedImageError):
        try:
            os.remove(logo_path)
        except OSError:
            pass
        file.stream.seek(0)
        return None
    file.stream.seek(0)
    return filename


def save_news_image(file, app_root_path):
    """
    保存新闻图片，返回 URL 路径。
    返回 (url, error_msg)。
    """
    if not file or not file.filename:
        return None, "空文件"

    if not allowed_image_file(file.filename):
        return None, "仅支持 png/jpg/jpeg/gif"

    ext = validate_image_content(file.stream)
    if not ext:
        return None, "文件内容无效，请上传真实图片"

    news_dir = os.path.join(app_root_path, "static", "uploads", "news")
    os.makedirs(news_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(news_dir, filename))
    return f"/static/uploads/news/{filename}", None
