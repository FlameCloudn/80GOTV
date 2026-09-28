"""自动刷新浏览器。改代码 → 浏览器自动刷，不用按 F5。

用法:
  python live_preview.py                # 监控所有文件，自动刷新首页
  python live_preview.py /admin/login   # 监控指定页面
  python live_preview.py --port 3000    # 用 3000 端口（需要 vite 等）
"""
import sys, os, time, subprocess
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WATCH_EXTENSIONS = {".py", ".html", ".css", ".js", ".jinja", ".jinja2"}
IGNORE_DIRS = {"__pycache__", ".git", "node_modules", ".backups", "logs", "instance", ".venv", ".claude"}

def get_file_timestamps():
    """扫项目所有文件，返回 {路径: 修改时间}"""
    stamps = {}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in WATCH_EXTENSIONS:
                path = os.path.join(root, f)
                try:
                    stamps[path] = os.path.getmtime(path)
                except OSError:
                    pass
    return stamps

def main():
    url_path = "/"
    port = 5000
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i+1 < len(args):
            port = int(args[i+1]); i += 2
        elif args[i].startswith("/"):
            url_path = args[i]; i += 1
        else:
            i += 1

    url = f"http://127.0.0.1:{port}{url_path}"

    # 检查 Flask 在不在
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
    except:
        print(f"Flask ({port}) 没启动，请先跑 python app.py")
        sys.exit(1)

    print(f"打开浏览器: {url}")
    print("监控文件改动中，改代码自动刷新 (Ctrl+C 退出)\n")

    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()

    try:
        browser = p.chromium.launch(channel='msedge', headless=False)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle")

        # 注入刷新提示条
        page.evaluate("""
            var bar = document.createElement('div');
            bar.id = '__live_reload_bar';
            bar.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:999999;background:#5881bc;color:#fff;text-align:center;padding:3px;font-size:12px;font-family:sans-serif;opacity:0;transition:opacity 0.3s';
            bar.textContent = '已刷新';
            document.body.appendChild(bar);
        """)

        old_stamps = get_file_timestamps()
        last_check = time.time()

        while True:
            time.sleep(1.5)  # 1.5 秒检查一次
            now = time.time()

            new_stamps = get_file_timestamps()
            changes = []

            # 找修改和新文件
            for path, mtime in new_stamps.items():
                if path not in old_stamps:
                    changes.append(("新增", path))
                elif mtime > old_stamps[path] + 0.1:
                    changes.append(("修改", path))

            # 找删除
            for path in old_stamps:
                if path not in new_stamps:
                    changes.append(("删除", path))

            # 有改动就刷新
            if changes:
                # 只显示前 3 个
                shown = changes[:3]
                names = [os.path.relpath(p, ROOT).replace("\\", "/") for _, p in shown]
                ts = time.strftime("%H:%M:%S")
                print(f"  [{ts}] {', '.join(names)}" + (f" ...等 {len(changes)} 个" if len(changes) > 3 else ""))

                page.reload(wait_until="networkidle")
                page.evaluate("""
                    var bar = document.getElementById('__live_reload_bar');
                    if(bar){ bar.style.opacity='1'; setTimeout(function(){ bar.style.opacity='0'; }, 1500); }
                """)

            old_stamps = new_stamps

    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        try: browser.close()
        except: pass
        p.stop()

if __name__ == "__main__":
    main()
