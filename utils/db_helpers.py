"""
数据库操作辅助函数：头像保存、文件验证等
"""

import os
import uuid
import warnings

from PIL import Image, UnidentifiedImageError

# Image magic bytes validation
IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
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

    # 删除旧头像
    if old_avatar:
        remove_uploaded_avatar(app_root_path, old_avatar)

    return filename, ext


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
