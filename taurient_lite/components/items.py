"""新闻条目与分层区块。"""

from __future__ import annotations

import datetime as dt

from ..schema import TIER_LABEL, TIERS, Brief, Item
from .base import esc, join, section_head
from .depth import depth_block

#: 分层对应的 CSS 类。索引从 1 开始，与 ``t1``/``t2``/``t3`` 对齐。
TIER_CLASS: dict[str, str] = {tier: f"t{i}" for i, tier in enumerate(TIERS, start=1)}


def age_badge(item: Item, today: dt.date) -> tuple[str, str]:
    """时效徽章的文字与样式类。

    没有 ``published`` 时返回两个空串，调用方据此省掉徽章——与其显示
    「未知」不如什么都不显示，前者会让读者误以为是数据错误。
    """
    age = item.age_days(today)
    if age is None:
        return "", ""
    if age <= 0:
        return "今天", "fresh"
    if age == 1:
        return "昨天", "fresh"
    if age == 2:
        return "2 天前", "aging"
    return f"{age} 天前", "stale"


def item_meta(item: Item, today: dt.date) -> str:
    """标题下方那一行：时效徽章、股票代码、板块标签。"""
    bits = ['<div class="meta">']
    label, style = age_badge(item, today)
    if label:
        bits.append(f'<span class="age {style}">{esc(label)}</span>')
    for ticker in item.tickers:
        bits.append(f'<span class="tag tk">{esc(ticker)}</span>')
    for sector in item.sectors:
        bits.append(f'<span class="tag">{esc(sector)}</span>')
    bits.append("</div>")
    # 一个标签都没有时不要留一个空的 flex 容器，它会撑出一段幽灵间距。
    return "".join(bits) if len(bits) > 2 else ""


def sources_block(item: Item) -> str:
    """折叠的信源列表。带 ``angle`` 的会把角度一并列出。"""
    if not item.sources:
        return ""
    rows = []
    for source in item.sources:
        link = (
            f'<a href="{esc(source.url)}" target="_blank" rel="noopener">'
            f"{esc(source.name)}</a>"
        )
        rows.append(f"<li>{link}{'　' + esc(source.angle) if source.angle else ''}</li>")
    return join(
        [
            f'<details class="srcs"><summary>{len(item.sources)} 个来源</summary>',
            f'<ul>{"".join(rows)}</ul>',
            "</details>",
        ]
    )


def render_item(item: Item, today: dt.date) -> str:
    """一条完整的新闻条目。"""
    tier_class = TIER_CLASS[item.tier]
    parts = [
        f'<article class="item {tier_class}" id="item-{item.rank}">',
        f'<div class="rank">{item.rank:02d}</div>',
        "<div>",
        f"<h3>{esc(item.headline)}</h3>",
        item_meta(item, today),
        f"<p>{esc(item.body)}</p>",
    ]
    if item.why:
        parts.append(
            '<div class="why"><span class="lbl">为什么重要</span>'
            f"<p>{esc(item.why)}</p></div>"
        )
    if item.impact:
        parts.append(f'<div class="impact">{esc(item.impact)}</div>')

    parts.append(depth_block(item))
    parts.append(sources_block(item))
    parts.append("</div></article>")
    return join(parts)


def tier_section(brief: Brief, tier: str) -> str:
    """某一层的标题加全部条目。该层为空时返回空串。"""
    group = brief.by_tier(tier)
    if not group:
        return ""
    return join(
        [
            section_head(
                TIER_LABEL[tier], tier_class=TIER_CLASS[tier], count=len(group)
            ),
            join(render_item(item, brief.date) for item in group),
        ]
    )


def all_tiers(brief: Brief) -> str:
    """按 :data:`~taurient_lite.schema.TIERS` 的顺序渲染三层。"""
    return join(tier_section(brief, tier) for tier in TIERS)
