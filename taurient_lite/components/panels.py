"""页首、七巨头图表、自选股、指数行情四个板块。

这四块共同构成简报的「盘面」部分：读者在读任何一条新闻之前，
先在这里拿到当天的数字底色。
"""

from __future__ import annotations

from ..schema import Brief, Mag7, Tape
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


def mag7_chart(mag7: Mag7) -> str:
    """七只权重股的单日涨跌，横向发散条形图。

    形态选择的理由：数据的任务是「带符号的量级在若干具名实体之间比较」，
    对应发散条形。一条零轴、一个对称标度，条形从零轴向左右伸出。

    可达性上有三重编码，颜色只是其中之一：条形方向（左跌右涨）、
    带符号的数值标签、以及行首固定的代码。色觉障碍读者丢掉颜色仍然能读。
    """
    rows = sorted(mag7.rows, key=lambda r: r.change_pct, reverse=True)
    domain = _axis_domain(max(abs(r.change_pct) for r in rows))

    out = ['<section class="mag7">']
    for row in rows:
        direction = row.direction
        # 半幅占轨道的 50%，所以单边宽度是占比乘 50。
        width = abs(row.change_pct) / domain * 50.0
        sign = "+" if row.change_pct >= 0 else ""
        out += [
            '<div class="mag7-row">',
            f'<div class="mag7-tick">{esc(row.ticker)}</div>',
            '<div class="mag7-track">',
            f'<div class="mag7-bar {direction}" style="width:{width:.2f}%"></div>',
            "</div>",
            f'<div class="mag7-price">${esc(row.price)}</div>',
            f'<div class="mag7-val {direction}">{sign}{row.change_pct:.2f}%</div>',
            "</div>",
        ]

    out += [
        '<div class="mag7-axis"><div class="lbl">',
        f"<span>−{domain:.1f}%</span><span>0</span><span>+{domain:.1f}%</span>",
        "</div></div>",
    ]
    if mag7.note:
        out.append(f'<p class="mag7-foot">{esc(mag7.note)}</p>')
    out.append("</section>")
    return join(out)


def mag7_panel(mag7: Mag7 | None) -> str:
    """带标题的完整七巨头板块。取不到行情时整块省掉，不留空壳。"""
    if mag7 is None:
        return ""
    return join(
        [section_head("七巨头单日涨跌", asof=mag7.asof), mag7_chart(mag7)]
    )


# ------------------------------------------------------------------- 自选股


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
