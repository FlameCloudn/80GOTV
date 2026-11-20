"""Website 的持久资料路径。公开 URL 和备份包内的历史名字与磁盘布局无关。"""

import os
from dataclasses import dataclass
from pathlib import Path

from flask import current_app, has_app_context

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def default_data_root():
    if override := os.environ.get("SITE_DATA_ROOT"):
        return Path(override).expanduser().resolve()
    if SOURCE_ROOT.parent.name == "products":
        return SOURCE_ROOT.parent.parent / "state/local/website"
    return SOURCE_ROOT.parent / (SOURCE_ROOT.name + "-state")


def backup_root():
    if override := os.environ.get("BACKUP_DIR"):
        return Path(override).expanduser().resolve()
    if SOURCE_ROOT.parent.name == "products":
        return SOURCE_ROOT.parent.parent / "backups/website"
    return SOURCE_ROOT.parent / (SOURCE_ROOT.name + "-backups")


@dataclass(frozen=True)
class SitePaths:
    root: Path

    @property
    def database(self):
        return self.root / "db/cs_site.db"

    @property
    def avatars(self):
        return self.root / "media/public/avatars"

    @property
    def uploads(self):
        return self.root / "media/public/uploads"

    @property
    def logo_originals(self):
        return self.root / "media/private/team-logo-originals"

    @property
    def demos(self):
        return self.root / "media/private/demos/legacy"

    @property
    def managed_demos(self):
        return self.root / "media/private/demos/managed"

    @property
    def csda_records(self):
        return self.root / "records/legacy-analysis/csda_cache"

    @property
    def analysis(self):
        return self.root / "records/legacy-analysis/demo-analysis"

    @property
    def cache(self):
        return self.root / "cache"


def site_paths(root=None):
    if root is None and has_app_context():
        root = current_app.config.get("SITE_DATA_ROOT")
    return SitePaths(default_data_root() if root is None else Path(root).resolve())
