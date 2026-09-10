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


def _brief_tab(brief: Brief, config: Config) -> str:
    """「简报」标签页：盘面加分层新闻。板块顺序即阅读顺序。

    每个板块在没有数据时自己返回空串，这里不需要写任何条件分支。
    """
    return C.join(
        [
            C.mag7_panel(brief.mag7),
            C.watchlist_panel(config.watchlist, brief),
            C.tape_panel(brief.tape),
            C.all_tiers(brief),
        ]
    )


def render_body(brief: Brief, config: Config) -> str:
    """页面主体：报头，标签页（简报 / 日历 / 异动），页脚。

    某一块数据为空时 :func:`~taurient_lite.components.tabs.tabs` 会退化成
    只出剩下的标签页；三块全空就连标签栏都不显示——空标签页毫无意义。

    异动排在日历之后，是因为它的时效性最弱：日历讲的是「今天之后会
    发生什么」，异动讲的是「昨天收盘时发生了什么」，而简报永远第一。
    """
    brief_html = _brief_tab(brief, config)
    calendar_html = C.calendar_tab(brief)
    momentum_html = C.momentum_tab(brief.momentum)

    panels = [("brief", "简报", brief_html)]
    if calendar_html:
        panels.append(("calendar", "日历", calendar_html))
    if momentum_html:
        panels.append(("momentum", "异动", momentum_html))

    return C.join(
        [
            '<div class="sheet">',
            C.masthead(brief),
            C.tabs(panels),
            C.colophon(),
            "</div>",
        ]
    )


def render_html(brief: Brief, config: Config) -> str:
    """完整页面。"""
    return C.join([render_head(), render_body(brief, config)])
