"""把 :class:`~taurient_lite.schema.Brief` 渲染成 Markdown 存档。

Markdown 那份不是网页的降级版，它有自己的用途：可以 grep、可以 diff、
可以被别的工具消费。所以深度元数据在这里也要完整落盘，只是换成表格
和列表的形态，不做任何取舍。
"""

from __future__ import annotations

from .config import Config
from .schema import (
    TIER_LABEL,
    TIERS,
    Brief,
    HistoricalContext,
    Item,
)
from .components.items import age_badge


def _mag7_section(brief: Brief) -> list[str]:
    if brief.mag7 is None:
        return []
    rows = sorted(brief.mag7.rows, key=lambda r: r.change_pct, reverse=True)
    lines = [
        f"## 七巨头单日涨跌 — {brief.mag7.asof}",
        "",
        "| 代码 | 价格 | 涨跌 |",
        "|---|---|---|",
    ]
    for row in rows:
        sign = "+" if row.change_pct >= 0 else ""
        lines.append(f"| {row.ticker} | `${row.price}` | `{sign}{row.change_pct:.2f}%` |")
    lines.append("")
    if brief.mag7.note:
        lines += [brief.mag7.note, ""]
    if brief.mag7.source:
        lines += [f"*行情来源：{brief.mag7.source}*", ""]
    return lines


def _watchlist_section(brief: Brief, config: Config) -> list[str]:
    if not config.watchlist:
        return []
    hits = brief.ticker_hits()
    matched = [s for s in config.watchlist if s in hits]
    return [
        "## 自选股",
        "",
        f"关注中：`{'` `'.join(config.watchlist)}`",
        "",
        f"今天有新闻：{'、'.join(matched) if matched else '无'}",
        "",
    ]


def _tape_section(brief: Brief) -> list[str]:
    lines = [
        f"## 指数与利率 — {brief.tape.asof}",
        "",
        "| | 水平 | 变化 |",
        "|---|---|---|",
    ]
    for row in brief.tape.rows:
        lines.append(f"| {row.name} | `{row.value}` | {row.change} |")
    lines.append("")
    return lines


def _assets_block(item: Item) -> list[str]:
    """资产波及矩阵。表格形态比网页上的卡片更适合 diff。"""
    if not item.assets:
        return []
    lines = ["**资产波及矩阵**", "", "| 资产类别 | 方向 | 判断强度 | 传导路径 |", "|---|---|---|---|"]
    for impact in item.assets:
        # 用实心方块表示强度档位，纯文本环境下也读得出来。
        bar = "■" * impact.steps + "□" * (3 - impact.steps)
        lines.append(
            f"| {impact.asset_class} | {impact.label} | {bar} | {impact.note or '—'} |"
        )
    lines.append("")
    return lines


def _cross_block(item: Item) -> list[str]:
    if item.cross_source is None:
        return []
    lines = [
        f"**多方信源交叉对比（{item.cross_source.label}）** {item.cross_source.summary}",
        "",
    ]
    angles = [s for s in item.sources if s.angle]
    if angles:
        for source in angles:
            lines.append(f"- {source.name}：{source.angle}")
        lines.append("")
    return lines


def _history_block(history: HistoricalContext | None) -> list[str]:
    if history is None:
        return []
    lines = [f"**历史背景与演进** {history.summary}", ""]
    if history.timeline:
        for entry in history.timeline:
            lines.append(f"- `{entry.when}` {entry.event}")
        lines.append("")
    return lines


def _item_block(item: Item, brief: Brief) -> list[str]:
    lines = [f"### {item.rank:02d}. {item.headline}"]

    chips: list[str] = []
    label, _ = age_badge(item, brief.date)
    if label:
        chips.append(label)
    chips += list(item.tickers) + list(item.sectors)
    if chips:
        lines.append(f"`{'` `'.join(chips)}`")
    lines += ["", item.body, ""]

    if item.why:
        lines += [f"**为什么重要：** {item.why}", ""]
    if item.impact:
        lines += [f"**影响面：** {item.impact}", ""]

    lines += _assets_block(item)
    lines += _cross_block(item)
    lines += _history_block(item.history)

    if item.sources:
        joined = " · ".join(f"[{s.name}]({s.url})" for s in item.sources)
        lines += [f"来源：{joined}", ""]
    return lines


def _calendar_section(brief: Brief) -> list[str]:
    if not brief.calendar:
        return []
    lines = [
        "## 接下来要盯的时间点",
        "",
        "| 时间 | 时刻 | 事件 | 来源 | 权重 |",
        "|---|---|---|---|---|",
    ]
    for entry in brief.calendar:
        sources = " · ".join(f"[{s.name}]({s.url})" for s in entry.sources) or "—"
        lines.append(
            f"| {entry.when} | {entry.time} | {entry.event} | {sources} | {entry.label} |"
        )
    lines.append("")
    return lines


def _momentum_section(brief: Brief) -> list[str]:
    """异动板块。存档里也要有——JSON 是真相来源，两份产物都从它生成，
    漏掉一块就等于承认存档只是网页的降级版。"""
    momentum = brief.momentum
    if momentum is None or not momentum.candidates:
        return []

    head = f"## 价量异动 — {momentum.asof}"
    if momentum.scanned:
        head += f"（扫描 {momentum.scanned} 只）"
    lines = [head, ""]
    if momentum.note:
        lines += [momentum.note, ""]
    lines += [
        "*价量筛选，不是买卖信号：全量回测 5090 次初动信号，20 日胜率 51.4%、"
        "期望 +1.1%，收益集中在少数尾部标的；排序只表示「有多新」，不表示「有多值得买」。*",
        "",
        "| 代码 | 阶段 | 价格 | 涨跌 | 突破 | 相对量 | 乖离 | 自基底 | 新闻 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in momentum.candidates:
        lines.append(
            f"| {c.ticker} | {c.stage_label} | `${c.close:,.2f}` | "
            f"`{c.change_pct:+.2f}%` | {c.age_label} | `{c.rvol:.1f}x` | "
            f"`{c.ext_ma20:+.0%}` | `{c.run_from_base:+.0%}` | {c.coverage_label} |"
        )
    lines.append("")
    for c in momentum.candidates:
        if not c.note:
            continue
        sources = " · ".join(f"[{s.name}]({s.url})" for s in c.sources)
        lines.append(f"- **{c.ticker}** — {c.note}" + (f" {sources}" if sources else ""))
    lines.append("")
    return lines


def render_markdown(brief: Brief, config: Config) -> str:
    """完整的 Markdown 存档。"""
    lines: list[str] = [
        f"# Morning Tape — {brief.date.isoformat()} ({brief.weekday})",
        "",
        f"> {brief.thesis}",
        "",
        f"*{brief.edition} · 扫描 {brief.scanned} 篇，保留 {brief.kept} 条 "
        f"· 生成于 {brief.generated_at}*",
        "",
    ]

    lines += _mag7_section(brief)
    lines += _watchlist_section(brief, config)
    lines += _tape_section(brief)

    for tier in TIERS:
        group = brief.by_tier(tier)
        if not group:
            continue
        lines += [f"## {TIER_LABEL[tier]}", ""]
        for item in group:
            lines += _item_block(item, brief)

    lines += _calendar_section(brief)
    lines += _momentum_section(brief)
    lines += ["---", "*Taurient Lite。新闻摘要，不是投资建议。*"]
    return "\n".join(lines) + "\n"
