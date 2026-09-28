"""视觉对比 + 参考图分析。

用法:
  python visual_compare.py --compare before.png after.png    # 对比两张图
  python visual_compare.py --compare-url / --before-id old   # 改前改后对比
  python visual_compare.py --reference 参考图.png            # 分析参考图，输出可复制的细节
  python visual_compare.py --snapshot /admin/dashboard       # 截当前页给Kimi看
"""
import sys, os, json, base64, subprocess, tempfile, time

KIMI_KEY = os.environ.get("KIMI_API_KEY", "")
if not KIMI_KEY:
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("KIMI_API_KEY="):
                    KIMI_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

SCRIPTS_DIR = os.path.dirname(__file__)
BASE_URL = "http://127.0.0.1:5000"

def ask_kimi(image_paths, prompt):
    """发送图片给 Kimi，返回文字"""
    content = []
    for path in image_paths:
        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
    content.append({"type": "text", "text": prompt})

    body = {
        "model": "kimi-k2.6",
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 3000
    }

    fd, tmpf = tempfile.mkstemp(suffix=".json", prefix="kimi_cmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f)

        result = subprocess.run([
            "curl", "-s", "https://api.moonshot.cn/v1/chat/completions",
            "-H", "Content-Type: application/json",
            "-H", f"Authorization: Bearer {KIMI_KEY}",
            "-d", f"@{tmpf}"
        ], capture_output=True, text=True, timeout=180)

        resp = json.loads(result.stdout)
        if "choices" not in resp:
            return f"API错误: {json.dumps(resp, ensure_ascii=False)[:300]}"
        return resp["choices"][0]["message"]["content"]
    finally:
        if os.path.exists(tmpf):
            os.remove(tmpf)

def take_snapshot(url_or_path, output="tmp_snapshot.png"):
    """截网页图"""
    url = url_or_path if url_or_path.startswith("http") else BASE_URL + url_or_path

    node_code = f"""
    const {{ chromium }} = require('playwright');
    (async () => {{
      const browser = await chromium.launch({{ channel: 'msedge', headless: true }});
      const page = await browser.newPage();
      await page.setViewportSize({{ width: 1280, height: 800 }});
      await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: 15000 }});
      await page.screenshot({{ path: '{output}', fullPage: false }});
      console.log('ok');
      await browser.close();
    }})();
    """
    r = subprocess.run(["node", "-e", node_code], capture_output=True, text=True, timeout=30)
    return "ok" in r.stdout

def compare_mode(before_path, after_path):
    """对比两张图"""
    print(f"📸 对比：\n  改前: {before_path}\n  改后: {after_path}")
    print("\n👁️ Kimi 分析差异中…")

    result = ask_kimi(
        [before_path, after_path],
        "这是同一网页修改前后的两张截图。请对比分析：\n1. 哪些元素变了（位置、大小、颜色、内容）\n2. 哪些变化是改进，哪些可能有问题\n3. 有没有意外的变化\n4. 列一个变化的清单\n\n用中文回复，直接说结论。"
    )
    print("=" * 50)
    print(result)
    print("=" * 50)

def reference_mode(image_path):
    """分析参考图，输出可复制细节"""
    print(f"📸 参考图: {image_path}")
    print("\n👁️ Kimi 分析中…")

    result = ask_kimi(
        [image_path],
        "这是一张网页UI设计参考图。请尽可能详细地描述它，我需要根据你的描述用代码复刻这个效果。包括：\n\n1. 整体配色（所有颜色，最好是十六进制）\n2. 布局结构（几栏、各区域大小比例）\n3. 字体（大小、粗细、样式）\n4. 间距（padding、margin、gap）\n5. 圆角、阴影、边框等视觉细节\n6. 每个按钮、卡片、输入框的样式\n7. 动画或交互效果（如果有）\n8. 移动端响应式表现\n\n越详细越好。用中文回复。"
    )
    print("=" * 50)
    print(result)
    print("=" * 50)
    print("\n💡 复制上面的描述给 Claude，说「照着这个做一个一样的」就行。")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "--compare" and len(sys.argv) >= 4:
        compare_mode(sys.argv[2], sys.argv[3])

    elif cmd == "--compare-url":
        # 截当前页面当 after，--before-id 指定旧截图
        path = sys.argv[2] if len(sys.argv) > 2 else "/"
        before_id = "old"
        for i, arg in enumerate(sys.argv):
            if arg == "--before-id" and i+1 < len(sys.argv):
                before_id = sys.argv[i+1]

        before_path = f"tmp_before_{before_id}.png"
        after_path = "tmp_after_new.png"

        if not os.path.exists(before_path):
            print(f"⚠️ 未找到旧截图 {before_path}，正在截一张作为「当前」…")
            take_snapshot(path, before_path)
            print("💡 去做你的修改，然后运行: python visual_compare.py --compare-url / --before-id " + before_id)
            sys.exit(0)

        print("📸 截取改后页面…")
        if not take_snapshot(path, after_path):
            print("❌ 截图失败")
            sys.exit(1)
        compare_mode(before_path, after_path)

    elif cmd == "--reference" and len(sys.argv) >= 3:
        reference_mode(sys.argv[2])

    elif cmd == "--snapshot" and len(sys.argv) >= 3:
        path = sys.argv[2]
        output = sys.argv[3] if len(sys.argv) > 3 else "tmp_snapshot.png"
        if take_snapshot(path, output):
            print(f"✅ 截图保存: {output}")
            # 顺便让 Kimi 看一下
            print()
            reference_mode(output)
        else:
            print("❌ 截图失败")

    else:
        print("未知命令。用法见脚本开头。")
