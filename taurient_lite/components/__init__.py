"""组件层。每个模块负责页面上的一组板块，全部返回 HTML 字符串片段。"""

from .base import attr, classes, esc, join, section_head
from .calendar import calendar_tab
from .depth import asset_matrix, cross_source_card, depth_block, history_card
from .fundamentals import fundamentals_tab
from .heatmap import legend, market_tab, sector_card, stock_href
from .items import age_badge, all_tiers, render_item, tier_section
from .momentum import candidate_card, momentum_strip, momentum_tab, stage_group
from .panels import masthead, mag7_chart, mag7_panel, tape_panel, watchlist_panel
from .tabs import tabs
from .tail import colophon

__all__ = [
    "attr",
    "classes",
    "esc",
    "join",
    "section_head",
    "calendar_tab",
    "candidate_card",
    "momentum_strip",
    "momentum_tab",
    "stage_group",
    "asset_matrix",
    "cross_source_card",
    "depth_block",
    "history_card",
    "fundamentals_tab",
    "legend",
    "market_tab",
    "sector_card",
    "stock_href",
    "age_badge",
    "all_tiers",
    "render_item",
    "tier_section",
    "masthead",
    "mag7_chart",
    "mag7_panel",
    "tape_panel",
    "watchlist_panel",
    "tabs",
    "colophon",
]
