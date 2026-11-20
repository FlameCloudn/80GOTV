"""Resolve versioned team logo URLs in the current web application."""

import os

from flask import url_for

from src.website.domains.directory.team_logo_service import logo_relative_path
from src.website.runtime.storage import site_paths


def team_logo_url(value, data_root=None):
    """模板里统一用的队标地址；站内文件带上修改时间做版本号，重新处理后浏览器会拿到新图。"""
    path = logo_relative_path(value)
    if not path:
        return ""
    if path.startswith(("http://", "https://", "/")):
        return path
    url = url_for("static", filename=f"uploads/{path}")
    if data_root:
        full_path = site_paths(data_root).uploads / path
        if os.path.isfile(full_path):
            url = f"{url}?v={int(os.path.getmtime(full_path))}"
    return url
