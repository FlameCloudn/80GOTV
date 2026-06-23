# 项目配置
import logging
import os
import secrets

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

_SECRET_FROM_ENV = os.environ.get("SECRET_KEY", "")
if _SECRET_FROM_ENV:
    _SECRET_KEY = _SECRET_FROM_ENV
else:
    _SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY 未设置，已自动生成随机 key。"
        "此 key 仅用于本次运行。生产环境请设置环境变量 SECRET_KEY。"
    )


class Config:
    SECRET_KEY = _SECRET_KEY
    # 本地默认仍使用项目目录中的数据库；公网可把数据库放到独立资料盘。
    DATABASE = os.path.abspath(_DATABASE_PATH or os.path.join(BASE_DIR, "cs_site.db"))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "dem"}
    MAX_CONTENT_LENGTH = 3 * 1024 * 1024 * 1024  # 3GB 上传限制（支持多个大型 Demo）
    GOTV_SECRET = os.environ.get("GOTV_SECRET", "").strip()
    GSI_TOKEN = os.environ.get("GSI_TOKEN", "").strip()
    # auto 会跟随当前访问地址，适合本机调试和 Cloudflare 临时隧道。
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "auto").strip().rstrip("/")
    DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
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
