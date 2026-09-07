"""深度元数据的三块微卡片：资产波及矩阵、多方信源交叉对比、历史演进脉络。

这三块是这次升级的核心。它们回答的是同一条新闻的三个不同问题：

* **资产波及矩阵**：这件事会传导到哪几类资产，方向如何，判断有多确定。
* **交叉信源对比**：各家媒体口径是否一致，分歧在哪。分歧本身就是信息。
* **历史演进脉络**：这件事从哪来，走到今天是第几步。

排版上资产矩阵占满宽度（要横向比较六个类别），后两块并排成微卡片
（各自独立成篇，不需要跨块对齐）。
"""

from __future__ import annotations

from ..schema import AssetImpact, CrossSource, HistoricalContext, Item
from .base import esc, join

#: 方向对应的箭头字形。这是颜色之外的第二重编码，色觉障碍读者靠它区分。
#: 用 HTML 实体而不是字面字符，避免文件编码在任何环节被改写后变成乱码。
DIRECTION_GLYPH: dict[str, str] = {
    "up": "&#8593;",     # ↑
    "down": "&#8595;",   # ↓
    "mixed": "&#8644;",  # ⇄
    "none": "&#8212;",   # —
}


def asset_cell(impact: AssetImpact) -> str:
    """矩阵里的一格。

    三重编码：颜色、箭头字形、以及下方的强度格子。任意丢掉一重仍可读。
    """
    glyph = DIRECTION_GLYPH[impact.direction]
    steps = impact.steps
    bars = "".join(
        f'<i class="{"on" if n < steps else ""}"></i>' for n in range(3)
    )
    out = [
        '<div class="asset">',
        '<div class="asset-top">',
        f'<span class="asset-name">{esc(impact.asset_class)}</span>',
        f'<span class="asset-dir {impact.direction}">{glyph} {esc(impact.label)}</span>',
        "</div>",
        f'<div class="conv {impact.direction}">{bars}</div>',
    ]
    if impact.note:
        out.append(f'<p class="asset-note">{esc(impact.note)}</p>')
    out.append("</div>")
    return "".join(out)


def asset_matrix(impacts: tuple[AssetImpact, ...]) -> str:
    """资产波及矩阵。没有数据就整块省掉。"""
    if not impacts:
        return ""
    cells = "".join(asset_cell(i) for i in impacts)
    return join(
        [
            '<div class="depth-head">资产波及矩阵</div>',
            f'<div class="assets">{cells}</div>',
        ]
    )


def cross_source_card(cross: CrossSource, item: Item) -> str:
    """交叉信源对比卡片。

    ``angle`` 字段填了的信源会列出它独有的角度；一个都没填时退化成
    一句总结加信源名，仍然有用。
    """
    angles = [s for s in item.sources if s.angle]
    body = [
        '<div class="card">',
        '<div class="card-head">',
        '<span class="t">多方信源交叉对比</span>',
        f'<span class="agree {cross.agreement}">{esc(cross.label)}</span>',
        "</div>",
        f"<p>{esc(cross.summary)}</p>",
    ]
    if angles:
        body.append('<ul class="tl" style="margin-top:0.55rem">')
        for source in angles:
            body.append(
                f'<li><span class="w">{esc(source.name)}</span>{esc(source.angle)}</li>'
            )
        body.append("</ul>")
    body.append("</div>")
    return "".join(body)


def history_card(history: HistoricalContext) -> str:
    """历史背景与演进脉络卡片。

    ``timeline`` 是真实的时间序列，所以竖轴加节点这个结构编码了真信息：
    最后一个节点用品牌色点亮，读者一眼看到脉络走到哪一步了。
    """
    body = [
        '<div class="card">',
        '<div class="card-head"><span class="t">历史背景与演进</span></div>',
        f"<p>{esc(history.summary)}</p>",
    ]
    if history.timeline:
        body.append('<ul class="tl" style="margin-top:0.55rem">')
        for entry in history.timeline:
            body.append(
                f'<li><span class="w">{esc(entry.when)}</span>{esc(entry.event)}</li>'
            )
        body.append("</ul>")
    body.append("</div>")
    return "".join(body)


def depth_block(item: Item) -> str:
    """一条新闻的全部深度元数据。三块都没有时返回空串。"""
    if not item.has_depth:
        return ""

    cards = []
    if item.cross_source:
        cards.append(cross_source_card(item.cross_source, item))
    if item.history:
        cards.append(history_card(item.history))

    parts = ['<div class="depth">', asset_matrix(item.assets)]
    if cards:
        # 两张都在时并排，只有一张时占满，避免出现半宽的孤立卡片。
        two = " two" if len(cards) == 2 else ""
        parts.append(f'<div class="cards{two}">{"".join(cards)}</div>')
    parts.append("</div>")
    return join(parts)
