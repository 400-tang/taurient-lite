"""把 :class:`~taurient_lite.schema.Brief` 渲染成完整的 HTML 页面。

产出的是 Artifact 要求的「片段」形态：不带 ``<!doctype>``、``<html>``、
``<head>``、``<body>``，发布时由平台包进骨架。所以 ``<title>``、字体
``<link>`` 和 ``<style>`` 直接写在最前面。
"""

from __future__ import annotations

from . import components as C
from .config import Config
from .schema import Brief
from .theme import GOOGLE_FONTS, build_css

#: 浏览器标签页与作品集里显示的名字。刻意保持稳定：读者靠它在一堆
#: 页面里认出这一个，改名等于换了一个页面。
PAGE_TITLE = "Morning Tape"


def render_head() -> str:
    """标题、字体、样式表。"""
    return C.join(
        [
            f"<title>{C.esc(PAGE_TITLE)}</title>",
            f'<link rel="stylesheet" href="{C.esc(GOOGLE_FONTS)}">',
            f"<style>{build_css()}</style>",
        ]
    )


def render_body(brief: Brief, config: Config) -> str:
    """页面主体。板块顺序即阅读顺序：先盘面，再新闻，最后日历。

    每个板块在没有数据时自己返回空串，所以这里不需要写任何条件分支，
    也不会产出空标题挂着空内容的骨架。
    """
    return C.join(
        [
            '<div class="sheet">',
            C.masthead(brief),
            C.mag7_panel(brief.mag7),
            C.watchlist_panel(config.watchlist, brief),
            C.tape_panel(brief.tape),
            C.all_tiers(brief),
            C.calendar_panel(brief.calendar),
            C.colophon(),
            "</div>",
        ]
    )


def render_html(brief: Brief, config: Config) -> str:
    """完整页面。"""
    return C.join([render_head(), render_body(brief, config)])
