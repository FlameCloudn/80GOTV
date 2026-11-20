"""Load the Vite build manifest without exposing the manifest or source tree."""

import json
import re
from functools import lru_cache
from pathlib import Path

from flask import abort, send_from_directory, url_for
from markupsafe import Markup

MANIFEST_PATH = Path(".vite/manifest.json")
_BUILT_FILENAME = re.compile(
    r"[a-zA-Z0-9_.-]+-[a-zA-Z0-9_-]{12}\.(?:js|css|woff2|otf|png|jpg|webp|svg)\Z"
)


def read_build(dist):
    """Validate the candidate and return its manifest, logical entries and files."""
    path = dist / MANIFEST_PATH
    if not path.is_file():
        raise RuntimeError("找不到前端构建清单，请先运行 npm run build。")
    return _read_build(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _read_build(path, _mtime):
    manifest, entries, files = parse_build_manifest(path.read_bytes())
    dist = path.parents[1]
    for name in files:
        if not (dist / name).is_file():
            raise RuntimeError(f"前端构建文件丢失：{name}")
    return manifest, entries, files


def parse_build_manifest(data):
    manifest = json.loads(data)
    entries = {}
    files = set()
    for key, chunk in manifest.items():
        for name in (chunk["file"], *chunk.get("css", ()), *chunk.get("assets", ())):
            if not _BUILT_FILENAME.fullmatch(name):
                raise RuntimeError(f"前端构建文件名称无效：{name}")
            files.add(name)
        for field in ("imports", "dynamicImports"):
            for dependency in chunk.get(field, ()):
                if dependency not in manifest:
                    raise RuntimeError(f"前端构建清单缺少依赖：{dependency}")
        if chunk.get("isEntry"):
            entries[chunk["name"]] = key
    if not entries:
        raise RuntimeError("前端构建清单没有页面入口。")
    return manifest, entries, files


def register_frontend_assets(app):
    dist = Path(app.root_path) / "frontend" / "dist"
    read_build(dist)

    @app.get("/assets/build/<name>")
    def frontend_asset(name):
        # Keep content-addressed files from the previous release available.
        if not _BUILT_FILENAME.fullmatch(name):
            abort(404)
        response = send_from_directory(dist, name, max_age=31536000)
        response.cache_control.immutable = True
        return response

    @app.template_global()
    def frontend_entry(name):
        manifest, entries, _ = read_build(dist)
        if name not in entries:
            raise RuntimeError(f"前端未构建模板使用的入口：{name}")
        emitted = set()
        seen = set()
        tags = []

        def emit(filename, template):
            if filename not in emitted:
                tags.append(Markup(template).format(url_for("frontend_asset", name=filename)))
                emitted.add(filename)

        def visit(key, *, entry=False):
            if key in seen:
                return
            seen.add(key)
            chunk = manifest[key]
            for dependency in chunk.get("imports", ()):
                visit(dependency)
            filename = chunk["file"]
            for css in chunk.get("css", ()):
                emit(css, '<link rel="stylesheet" href="{}">')
            if filename.endswith(".css"):
                emit(filename, '<link rel="stylesheet" href="{}">')
            elif entry:
                emit(filename, '<script type="module" src="{}"></script>')
            else:
                emit(filename, '<link rel="modulepreload" href="{}">')

        visit(entries[name], entry=True)
        return Markup("\n").join(tags)
