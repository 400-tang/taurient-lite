"""两个渲染器的组装层测试。

组件已经单独测过，这里关心的是**整页的结构性质**：板块顺序、
空数据时不留空壳、以及 Markdown 是否把深度元数据完整落盘。
"""

from __future__ import annotations

import re
import unittest

from taurient_lite.config import Config
from taurient_lite.html_renderer import render_body, render_head, render_html
from taurient_lite.markdown_renderer import render_markdown
from taurient_lite.schema import Brief

from . import fixtures as F


def build(brief_over=None, config_over=None):
    brief = Brief.from_dict(F.make_brief(**(brief_over or {})))
    config = Config.from_dict(F.make_config(**(config_over or {})))
    return brief, config


class TestHtmlHead(unittest.TestCase):
    def test_title_present_and_stable(self):
        self.assertIn("<title>Morning Tape</title>", render_head())

    def test_fonts_come_from_allowed_host(self):
        """Artifact 的 CSP 只放行 fonts.googleapis.com 的样式表。"""
        self.assertIn("https://fonts.googleapis.com/css2?", render_head())

    def test_no_document_skeleton(self):
        """Artifact 会自己包 doctype/head/body，页面里再写一份就重了。"""
        head = render_head()
        for tag in ("<!doctype", "<html", "<head>", "<body"):
            self.assertNotIn(tag, head.lower())


class TestHtmlBody(unittest.TestCase):
    def test_section_order(self):
        brief, config = build()
        html = render_body(brief, config)
        order = [
            html.index("Morning <em>Tape</em>"),
            html.index("七巨头单日涨跌"),
            html.index("自选股"),
            html.index("指数与利率"),
            html.index("必读"),
            html.index("接下来要盯的时间点"),
            html.index("colophon"),
        ]
        self.assertEqual(order, sorted(order))

    def test_mag7_section_absent_when_quotes_missing(self):
        data = F.make_brief()
        del data["mag7"]
        brief, config = build()
        brief = Brief.from_dict(data)
        html = render_body(brief, config)
        self.assertNotIn("七巨头单日涨跌", html)
        # 缺一个板块不该影响别的板块
        self.assertIn("指数与利率", html)

    def test_watchlist_absent_when_not_configured(self):
        brief, _ = build()
        config = Config.from_dict(F.make_config(watchlist={"symbols": []}))
        self.assertNotIn("wl-chip", render_body(brief, config))

    def test_calendar_absent_when_empty(self):
        brief, config = build(brief_over={"calendar": []})
        self.assertNotIn("接下来要盯的时间点", render_body(brief, config))

    def test_depth_metadata_reaches_the_page(self):
        brief, config = build()
        html = render_body(brief, config)
        self.assertIn("资产波及矩阵", html)
        self.assertIn("多方信源交叉对比", html)
        self.assertIn("历史背景与演进", html)

    def test_no_unescaped_injection_from_content(self):
        evil = '<script>alert(1)</script>'
        brief, config = build(brief_over={"thesis": evil})
        self.assertNotIn("<script>alert", render_body(brief, config))


class TestHtmlWhole(unittest.TestCase):
    def test_tags_balanced(self):
        brief, config = build()
        html = render_html(brief, config)
        for tag in ("div", "article", "section", "details", "table"):
            opened = len(re.findall(rf"<{tag}\b", html))
            closed = len(re.findall(rf"</{tag}>", html))
            self.assertEqual(opened, closed, f"<{tag}> 开闭不匹配")

    def test_anchor_targets_exist(self):
        """自选股面板里的每个跳转锚点都必须能落到一个真实条目上。"""
        brief, config = build()
        html = render_html(brief, config)
        for target in set(re.findall(r'href="#(item-\d+)"', html)):
            self.assertIn(f'id="{target}"', html)

    def test_external_links_are_safe(self):
        brief, config = build()
        html = render_html(brief, config)
        for anchor in re.findall(r"<a [^>]*target=\"_blank\"[^>]*>", html):
            self.assertIn('rel="noopener"', anchor)


class TestMarkdown(unittest.TestCase):
    def test_headline_hierarchy(self):
        brief, config = build()
        md = render_markdown(brief, config)
        self.assertTrue(md.startswith("# Morning Tape — 2026-09-06"))
        self.assertIn("## 必读", md)
        self.assertIn("### 01.", md)

    def test_mag7_table_sorted_descending(self):
        brief, config = build()
        md = render_markdown(brief, config)
        self.assertLess(md.index("| NVDA |"), md.index("| TSLA |"))

    def test_asset_matrix_as_table_with_text_strength(self):
        """纯文本环境下强度也要读得出来，所以用方块而不是颜色。"""
        brief, config = build()
        md = render_markdown(brief, config)
        self.assertIn("| 资产类别 | 方向 | 判断强度 | 传导路径 |", md)
        self.assertIn("■■■", md)

    def test_cross_source_and_history_present(self):
        brief, config = build()
        md = render_markdown(brief, config)
        self.assertIn("多方信源交叉对比（口径一致）", md)
        self.assertIn("**历史背景与演进**", md)
        self.assertIn("`2026-07`", md)

    def test_watchlist_reports_matches(self):
        brief, config = build()
        md = render_markdown(brief, config)
        self.assertIn("今天有新闻：SPY", md)

    def test_sections_skipped_when_empty(self):
        data = F.make_brief(calendar=[])
        del data["mag7"]
        brief = Brief.from_dict(data)
        config = Config.from_dict(F.make_config(watchlist={"symbols": []}))
        md = render_markdown(brief, config)
        self.assertNotIn("## 七巨头", md)
        self.assertNotIn("## 自选股", md)
        self.assertNotIn("## 接下来要盯的时间点", md)

    def test_ends_with_boundary_statement(self):
        brief, config = build()
        self.assertIn("不是投资建议", render_markdown(brief, config))

    def test_trailing_newline(self):
        brief, config = build()
        self.assertTrue(render_markdown(brief, config).endswith("\n"))


if __name__ == "__main__":
    unittest.main()
