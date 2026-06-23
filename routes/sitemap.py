"""
/sitemap.xml 路由 — 生成网站地图，方便搜索引擎抓取。
列出所有公开页面：首页、比赛、选手、赛事、新闻。
"""

from flask import make_response

from web_app import app


@app.route("/sitemap.xml")
def sitemap():
    """生成 sitemap.xml 格式的网站地图"""
    # 所有公开页面的路径及其更新频率
    pages = [
        ("/", "daily", "1.0"),  # 首页
        ("/news", "daily", "0.9"),  # 新闻列表
        ("/matches", "hourly", "0.9"),  # 比赛列表（更新最频繁）
        ("/results", "hourly", "0.8"),  # 赛果列表
        ("/events", "daily", "0.8"),  # 赛事列表
        ("/players", "weekly", "0.7"),  # 选手列表
        ("/stats", "weekly", "0.7"),  # 数据统计
        ("/predictions", "weekly", "0.6"),  # 预测
        ("/dashboard", "daily", "0.7"),  # 数据看板
        ("/search", "weekly", "0.5"),  # 搜索页
        ("/forum", "daily", "0.8"),  # 论坛
    ]

    # 站点基础网址（根据实际部署修改）
    base_url = "https://80gotv.com"

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    for path, changefreq, priority in pages:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{base_url}{path}</loc>")
        xml_lines.append(f"    <changefreq>{changefreq}</changefreq>")
        xml_lines.append(f"    <priority>{priority}</priority>")
        xml_lines.append("  </url>")

    xml_lines.append("</urlset>")

    response = make_response("\n".join(xml_lines))
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    return response
