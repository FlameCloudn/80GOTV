# 项目配置
import logging
import os
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 加载 .env 文件
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# 环境判断：读取 FLASK_ENV，如果=production 则为生产模式
IS_PRODUCTION = os.environ.get("FLASK_ENV", "").strip().lower() == "production"

logger = logging.getLogger("80gotv")
_DATABASE_PATH = os.environ.get("DATABASE_PATH", "").strip()

_PLACEHOLDER_PARTS = (
    "change-me",
    "replace-with",
    "请设置",
    "请换",
    "你的域名",
    "example.com",
)

_SECRET_FROM_ENV = os.environ.get("SECRET_KEY", "")
_SESSION_COOKIE_DOMAIN = os.environ.get("SESSION_COOKIE_DOMAIN", "").strip()
_SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "80gotv_session").strip()
if _SECRET_FROM_ENV:
    _SECRET_KEY = _SECRET_FROM_ENV
else:
    _SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY 未设置，已自动生成随机 key。"
        "此 key 仅用于本次运行。生产环境请设置环境变量 SECRET_KEY。"
    )


class Config:
    IS_PRODUCTION = IS_PRODUCTION
    SECRET_KEY = _SECRET_KEY
    # 本地默认仍使用项目目录中的数据库；公网可把数据库放到独立资料盘。
    DATABASE = os.path.abspath(_DATABASE_PATH or os.path.join(BASE_DIR, "cs_site.db"))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "dem"}
    MAX_CONTENT_LENGTH = 3 * 1024 * 1024 * 1024  # 3GB 上传限制（支持多个大型 Demo）
    GOTV_SECRET = os.environ.get("GOTV_SECRET", "").strip()
    GSI_TOKEN = os.environ.get("GSI_TOKEN", "").strip()
    STEAM_WEB_API_KEY = os.environ.get("STEAM_WEB_API_KEY", "").strip()
    # auto 会跟随当前访问地址，适合本机调试和 Cloudflare 临时隧道。
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "auto").strip().rstrip("/")
    DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtpdm.aliyun.com").strip()
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "80GOTV").strip() or "80GOTV"
    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_DOMAIN = _SESSION_COOKIE_DOMAIN or None
    # 不复用 Flask 默认的 session 名称，避免浏览器残留的旧 Cookie 与主域名 Cookie 冲突。
    SESSION_COOKIE_NAME = _SESSION_COOKIE_NAME or "80gotv_session"
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_REFRESH_EACH_REQUEST = True
    # 生产模式下强制启用安全 Cookie 和关闭调试
    if IS_PRODUCTION:
        SESSION_COOKIE_SECURE = True
        DEBUG = False
    else:
        SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    TRUST_PROXY = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes", "on")
    TRUSTED_HOSTS = [
        host.strip() for host in os.environ.get("TRUSTED_HOSTS", "").split(",") if host.strip()
    ] or None
    MAX_FORM_MEMORY_SIZE = 1024 * 1024
    MAX_FORM_PARTS = 200


def _is_placeholder(value):
    text = str(value or "").strip().casefold()
    return not text or any(part in text for part in _PLACEHOLDER_PARTS)


def _is_valid_public_base_url(value):
    text = str(value or "").strip()
    if _is_placeholder(text) or text.casefold() == "auto":
        return False
    try:
        parsed = urlsplit(text)
        parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
    )


def validate_production_config(config=Config, environ=None):
    """Refuse to start production with missing or example credentials."""
    if not getattr(config, "IS_PRODUCTION", False):
        return

    values = os.environ if environ is None else environ
    unsafe = []
    secret_key = str(values.get("SECRET_KEY", ""))
    if _is_placeholder(secret_key) or len(secret_key) < 32:
        unsafe.append("SECRET_KEY")

    public_url = str(values.get("PUBLIC_BASE_URL", "")).strip()
    if not _is_valid_public_base_url(public_url):
        unsafe.append("PUBLIC_BASE_URL")

    trusted_hosts = [
        host.strip() for host in str(values.get("TRUSTED_HOSTS", "")).split(",") if host.strip()
    ]
    if not trusted_hosts or any(_is_placeholder(host) for host in trusted_hosts):
        unsafe.append("TRUSTED_HOSTS")

    for name in ("ADMIN_PASSWORD",):
        value = str(values.get(name, "")).strip()
        if value and _is_placeholder(value):
            unsafe.append(name)

    for name in (
        "GOTV_SECRET",
        "GSI_TOKEN",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "STEAM_WEB_API_KEY",
    ):
        value = str(values.get(name, "")).strip()
        if _is_placeholder(value):
            unsafe.append(name)

    if unsafe:
        raise RuntimeError("生产配置不安全：" + ", ".join(unsafe))
