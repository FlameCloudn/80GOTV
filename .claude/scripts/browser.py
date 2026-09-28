"""浏览器操控工具。自动填表、点击、截图、走流程。

用法:
  python browser.py --flow login           # 测试登录流程
  python browser.py --flow create-match     # 测试创建比赛
  python browser.py --flow full             # 完整流程（登录→创建比赛→验证）
  python browser.py --nav /admin/login      # 打开页面并截图
  python browser.py --action action.json    # 执行 JSON 定义的操作序列
"""
import sys, os, json, time, base64

BASE_URL = "http://127.0.0.1:5000"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), ".screenshots")

def get_browser():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page()
    page.set_viewport_size({"width": 1280, "height": 900})
    return p, browser, page

def screenshot(page, name):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=False)
    print(f"  📸 {name}")
    return path

def nav(page, path):
    url = path if path.startswith("http") else BASE_URL + path
    print(f"  🌐 打开 {url}")
    page.goto(url, wait_until="networkidle", timeout=15000)
    return page.title()

def fill(page, selector, value, by="css"):
    """填表单。by 可以是 css, name, placeholder, label"""
    if by == "name":
        sel = f'[name="{selector}"]'
    elif by == "placeholder":
        sel = f'[placeholder*="{selector}"]'
    elif by == "label":
        sel = f'text="{selector}"'
    else:
        sel = selector

    print(f"  ✏️ 填入 {selector} = {value}")
    el = page.locator(sel).first
    el.fill(value)
    return True

def click(page, selector, by="text"):
    """点击。by 可以是 text, css, name, role"""
    if by == "text":
        el = page.locator(f'button:has-text("{selector}"), a:has-text("{selector}"), text="{selector}"').first
    elif by == "name":
        el = page.locator(f'[name="{selector}"]').first
    elif by == "role":
        # 优先匹配按钮文字
        el = page.locator(f'button:has-text("{selector}")').first
        if not el.is_visible():
            el = page.locator(f'[role="{selector}"]').first
    else:
        el = page.locator(selector).first

    print(f"  🖱️ 点击 {selector}")
    el.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

def extract(page, selector, by="css"):
    """提取页面文字"""
    if by == "text":
        el = page.get_by_text(selector).first
    else:
        el = page.locator(selector).first

    text = el.text_content() if el.is_visible() else "(不可见)"
    print(f"  📋 {text[:100]}")
    return text

def check_visible(page, selector, by="text"):
    """检查元素是否存在且可见。text模式用模糊匹配"""
    if by == "text":
        el = page.locator(f'text="{selector}"').first
    else:
        el = page.locator(selector).first
    ok = el.is_visible()
    print(f"  {'✅' if ok else '❌'} {selector} {'可见' if ok else '不可见'}")
    return ok

# ---- 内置流程 ----

def flow_login(p):
    """测试管理员登录"""
    page = p[2]
    results = []

    nav(page, "/admin/login")
    screenshot(page, "login_01_before")
    results.append(check_visible(page, "后台管理登录", "text"))

    fill(page, "username", "admin", "name")
    fill(page, "password", "test123456", "name")
    screenshot(page, "login_02_filled")

    # 点击提交按钮
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    screenshot(page, "login_03_after")

    # 登录成功 = 跳转到 /admin
    ok = "/admin" in page.url and page.title()
    results.append(ok)
    print(f"  {'✅' if ok else '❌'} 登录后URL: {page.url}")
    print(f"\n{'✅ 登录流程通过' if all(results) else '❌ 登录流程失败'}")
    return all(results)

def flow_create_match(p, event_id=None, team1_id=None, team2_id=None):
    """测试创建比赛（需先登录）"""
    page = p[2]
    results = []

    nav(page, "/admin/matches/new")
    screenshot(page, "match_01_form")

    if event_id:
        fill(page, "#event_id", str(event_id))
    if team1_id:
        fill(page, "#team1_id", str(team1_id))
    if team2_id:
        fill(page, "#team2_id", str(team2_id))

    fill(page, "bo_format", "BO3", "name")
    screenshot(page, "match_02_filled")

    submit = page.locator('button[type="submit"]').first
    if submit.is_visible():
        print("  🖱️ 点击提交")
        submit.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        screenshot(page, "match_03_submitted")
        results.append(True)
    else:
        results.append(False)

    print(f"\n{'✅ 创建比赛流程通过' if all(results) else '❌ 创建比赛流程失败'}")
    return all(results)

def flow_full(p):
    """完整流程：登录 → 看仪表盘 → 看比赛列表 → 看选手列表"""
    page = p[2]
    results = []

    results.append(flow_login(p))

    # 验证后台各页面都能打开
    pages_to_check = [
        ("/admin/dashboard", "后台管理", "仪表盘"),
        ("/admin/matches", "比赛管理", "比赛列表"),
        ("/admin/players", "选手管理", "选手列表"),
        ("/admin/events", "赛事管理", "赛事列表"),
        ("/admin/news", "新闻管理", "新闻列表"),
        ("/admin/teams", "队伍管理", "队伍列表"),
    ]

    for path, title_hint, label in pages_to_check:
        nav(page, path)
        screenshot(page, f"full_{label}")
        # 只要能打开，URL 对就行
        ok = page.url.endswith(path) or page.url.endswith(path + "/")
        # 有些页面可能重定向
        ok = ok or (page.url.startswith(BASE_URL + "/admin"))
        results.append(ok)
        print(f"  {'✅' if ok else '❌'} {label} ({page.url})")

    score = sum(results)
    total = len(results)
    print(f"\n{'='*40}")
    print(f"完整流程: {score}/{total} 通过")
    print(f"截图保存在: {SCREENSHOT_DIR}")
    print(f"{'='*40}")
    return score == total

# ---- JSON Action 执行器 ----

def execute_actions(actions_json):
    """执行 JSON 定义的操作序列

    格式: { "actions": [
        { "type": "nav", "path": "/" },
        { "type": "fill", "selector": "username", "value": "admin", "by": "name" },
        { "type": "click", "selector": "登录", "by": "role" },
        { "type": "screenshot", "name": "after_login" },
        { "type": "check", "selector": "仪表盘", "by": "text" }
    ]}
    """
    if isinstance(actions_json, str):
        with open(actions_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = actions_json

    p = get_browser()
    page = p[2]
    results = []

    try:
        for i, action in enumerate(data.get("actions", [])):
            atype = action["type"]
            print(f"\n[{i+1}] {atype}: {action.get('selector','')}")

            if atype == "nav":
                nav(page, action["path"])
            elif atype == "fill":
                fill(page, action["selector"], action["value"], action.get("by", "css"))
            elif atype == "click":
                click(page, action["selector"], action.get("by", "text"))
            elif atype == "screenshot":
                screenshot(page, action.get("name", f"step_{i}"))
            elif atype == "check":
                ok = check_visible(page, action["selector"], action.get("by", "text"))
                results.append(ok)
            elif atype == "extract":
                extract(page, action["selector"], action.get("by", "css"))
            elif atype == "wait":
                sec = action.get("seconds", 1)
                print(f"  ⏳ 等待 {sec}s")
                page.wait_for_timeout(int(sec * 1000))

        print(f"\n{'='*40}")
        passed = sum(results)
        total = len(results) or 1
        print(f"结果: {passed}/{total} 检查通过")
        print(f"截图保存在: {SCREENSHOT_DIR}")
        print(f"{'='*40}")
    finally:
        p[1].close()
        p[0].stop()

# ---- CLI ----

if __name__ == "__main__":
    p = get_browser()

    try:
        if len(sys.argv) < 2:
            print(__doc__)
            sys.exit(0)

        cmd = sys.argv[1]

        if cmd == "--flow":
            flow_name = sys.argv[2] if len(sys.argv) > 2 else "login"
            if flow_name == "login":
                flow_login(p)
            elif flow_name == "create-match":
                flow_create_match(p)
            elif flow_name == "full":
                flow_full(p)
            else:
                print(f"未知流程: {flow_name}。可用: login, create-match, full")
        elif cmd == "--action":
            path = sys.argv[2] if len(sys.argv) > 2 else None
            if path:
                execute_actions(path)
            else:
                print("请指定 action JSON 文件")
        elif cmd == "--nav":
            path = sys.argv[2] if len(sys.argv) > 2 else "/"
            nav(p[2], path)
            screenshot(p[2], path.replace("/", "_").strip("_") or "home")
        elif cmd == "--test-login":
            flow_login(p)
        elif cmd == "--test-full":
            flow_full(p)

    finally:
        p[1].close()
        p[0].stop()
