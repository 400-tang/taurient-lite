"""页首、七巨头图表、自选股、指数行情四个板块。

这四块共同构成简报的「盘面」部分：读者在读任何一条新闻之前，
先在这里拿到当天的数字底色。
"""

from __future__ import annotations

from ..schema import Brief, Tape
from .base import esc, join, section_head

# --------------------------------------------------------------------------- 页首


def masthead(brief: Brief) -> str:
    """报头。刊名、日期、版次，以及扫描与保留的条数。

    把「扫了多少、留了多少」放在最显眼的地方是刻意的：它让读者知道这份
    简报背后的筛选比例，从而判断该给它多少信任。
    """
    return join(
        [
            '<header class="masthead">',
            "<h1>Morning <em>Tape</em></h1>",
            '<div class="stamp">',
            f"<span><b>{esc(brief.date.isoformat())}</b> {esc(brief.weekday)}</span>",
            f"<span>{esc(brief.edition)}</span>",
            f"<span>扫描 <b>{brief.scanned}</b> 篇 · 保留 <b>{brief.kept}</b> 条</span>",
            f"<span>生成于 {esc(brief.generated_at)}</span>",
            "</div>",
            "</header>",
            f'<p class="lede">{esc(brief.thesis)}</p>',
        ]
    )


# ----------------------------------------------------------------- 七巨头图表


def _axis_domain(peak: float) -> float:
    """把标度上界向上取整到 0.5 的倍数，让轴标签是个整齐的数。

    下界 0.5 保证全员平盘时不会出现除以零，也不会把 0.01% 画成满格。
    """
    return max(0.5, (int(peak / 0.5) + 1) * 0.5)


def watchlist_panel(symbols: tuple[str, ...], brief: Brief) -> str:
    """自选股面板。有新闻的代码点亮并可点击跳到对应条目。

    没配自选股就整块省掉。这比渲染一个空面板诚实。
    """
    if not symbols:
        return ""

    hits = brief.ticker_hits()
    chips = []
    for symbol in symbols:
        ranks = hits.get(symbol)
        if ranks:
            chips.append(
                f'<a class="wl-chip hit" href="#item-{ranks[0]}">{esc(symbol)}'
                f'<span class="cnt">{len(ranks)}</span></a>'
            )
        else:
            chips.append(f'<span class="wl-chip">{esc(symbol)}</span>')

    matched = sum(1 for s in symbols if s in hits)
    if matched:
        foot = (
            f"你的 {len(symbols)} 只自选股里，今天有 {matched} 只出现在新闻中，"
            "点代码跳到对应条目。"
        )
    else:
        foot = f"你的 {len(symbols)} 只自选股今天都没有单独的新闻。"

    return join(
        [
            section_head("自选股", count=len(symbols)),
            '<section class="wl"><div class="wl-grid">',
            "".join(chips),
            "</div>",
            f'<p class="wl-foot">{esc(foot)}</p>',
            "</section>",
        ]
    )


# --------------------------------------------------------------- 指数与利率


def tape_panel(tape: Tape) -> str:
    """指数、收益率、油价的快照。"""
    cells = []
    for row in tape.rows:
        cells += [
            '<div class="tape-cell">',
            f'<div class="k">{esc(row.name)}</div>',
            f'<div class="v">{esc(row.value)}</div>',
            f'<div class="d {row.direction}">{esc(row.change)}</div>',
            "</div>",
        ]
    return join(
        [
            section_head("指数与利率", asof=tape.asof),
            '<section><div class="tape-grid">',
            join(cells),
            "</div></section>",
        ]
    )
