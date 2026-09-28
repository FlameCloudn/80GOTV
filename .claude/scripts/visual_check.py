"""调用 Kimi K2.6 视觉能力分析网页截图。前置：pip install playwright openai"""

import base64
import json
import os
import subprocess
import sys
import tempfile

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

KIMI_DEFAULT_PROMPT = """你是一个专业网页设计审查助手。这是 80GOTV（CS2 电竞赛事网站）的页面截图。

请按以下结构分析：

1) 整体印象
- 配色风格和统一性
- 专业度 / 电竞氛围
- 最突出问题

2) 布局分析
- 分区是否清晰
- 比例是否协调
- 对齐和间距

3) 内容审查
- 空状态（暂无数据等）
- 可读性
- 信息优先级

4) 改进建议（3-5条，按优先级排，简单可操作）

用中文回复，直接给结论，不要自我介绍。"""


def take_screenshot(url="http://127.0.0.1:5000/", output="tmp_visual.png", full_page=False):
    """用系统 Edge 浏览器截图"""
    node_code = f"""
    const {{ chromium }} = require('playwright');
    (async () => {{
      const browser = await chromium.launch({{ channel: 'msedge', headless: true }});
      const page = await browser.newPage();
      await page.setViewportSize({{ width: 1280, height: 800 }});
      await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: 15000 }});
      await page.screenshot({{ path: '{output}', fullPage: {str(full_page).lower()} }});
      console.log('ok');
      await browser.close();
    }})();
    """
    r = subprocess.run(["node", "-e", node_code], capture_output=True, text=True, timeout=30)
    return "ok" in r.stdout


def compress_image(input_path, output_path, max_width=1024):
    """缩小截图，加快上传"""
    try:
        from PIL import Image

        img = Image.open(input_path)
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        img.save(output_path, "PNG", optimize=True)
        return output_path
    except ImportError:
        return input_path


def ask_kimi_about_image(image_path, question=None):
    """把图片发给 Kimi K2.6 分析"""
    if question is None:
        question = KIMI_DEFAULT_PROMPT

    compressed = image_path + ".compressed.png"
    final_path = compress_image(image_path, compressed, max_width=800)

    with open(final_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    body = {
        "model": "kimi-k2.6",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": question},
                ],
            }
        ],
        "max_tokens": 2000,
    }

    fd, tmpf = tempfile.mkstemp(suffix=".json", prefix="kimi_req_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f)

        result = subprocess.run(
            [
                "curl",
                "-s",
                "https://api.moonshot.cn/v1/chat/completions",
                "-H",
                "Content-Type: application/json",
                "-H",
                f"Authorization: Bearer {KIMI_KEY}",
                "-d",
                f"@{tmpf}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        resp = json.loads(result.stdout)
        if "choices" not in resp:
            return f"API错误: {json.dumps(resp, ensure_ascii=False)[:300]}"
        return resp["choices"][0]["message"]["content"]
    finally:
        if os.path.exists(tmpf):
            os.remove(tmpf)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000/"
    question = sys.argv[2] if len(sys.argv) > 2 else KIMI_DEFAULT_PROMPT

    print(f"截图中: {url}")
    if not take_screenshot(url):
        print("截图失败（Flask 启动了吗？）")
        sys.exit(1)
    print("截图完成")

    print("Kimi 分析中...")
    result = ask_kimi_about_image("tmp_visual.png", question)
    print("=" * 50)
    print(result)
    print("=" * 50)

    # 清理临时截图
    for tmp in ("tmp_visual.png", "tmp_visual.png.compressed.png"):
        if os.path.exists(tmp):
            os.remove(tmp)
