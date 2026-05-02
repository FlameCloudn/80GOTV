# 项目配置
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    SECRET_KEY = 'cs2-tournament-secret-key-change-in-production'
    DATABASE = os.path.join(BASE_DIR, 'cs_site.db')
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'dem'}
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB 上传限制