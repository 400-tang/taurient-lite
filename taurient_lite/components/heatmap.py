"""市场标签页：行业热力图。

**它回答的问题和其他板块都不一样。** 新闻回答「发生了什么」，异动回答
「哪只票的价量结构变了」，热力图回答的是「今天钱往哪个方向流」——这是
一个只能用版面、不能用文字表达的问题。十二个行业、上百只票的涨跌，
写成列表要滚三屏，画成色块一眼就看完。

**为什么按市值定块的大小。** 涨跌幅本身已经由颜色表达了，块的大小必须
承载另一个维度，否则就是把同一个信息说两遍。市值回答的是「这个涨跌有
多大分量」——一只 200 亿的小票涨 5%，和苹果涨 5%，对板块的意义差了两个
数量级，而等大的网格会把它们画成一样重要。

**为什么不做成「涨幅榜」。** 涨幅榜天然只给极值，而极值几乎全是微型股和
消息股，看多了会系统性地把注意力推向最不具代表性的那一批。热力图的
版面里，大公司天然占大块，这正是它比排行榜诚实的地方。
"""

from __future__ import annotations

from ..schema import HEAT_FLAT_PCT, Market, SectorBlock
from ..theme import HEAT_BOX
from ..treemap import squarify
from .base import attr, esc, join

#: 每个行业最多画几块。超过这个数，后面的块会小到只剩色块，
#: 既读不出代码也读不出数字，只是把画布填满。
MAX_TILES: int = 14

#: 块与块之间的缝隙（占画布宽度的百分比）。
TILE_GAP: float = 0.7

#: 文字降级阈值，单位是画布百分比。换算依据：一张卡片宽约 300px，
#: 画布高约 186px，所以 15% × 16% ≈ 45px × 30px，刚好放得下代码加涨跌幅；
#: 11% × 9% ≈ 33px × 17px，只放得下代码。再小就什么都不放。
FULL_W, FULL_H = 15.0, 16.0
COMPACT_W, COMPACT_H = 11.0, 9.0

#: 放大字号的阈值。大块用小字会显得空，也丢掉了「这块更重要」的层级——
#: 块的大小已经说了它的分量，字号跟上去才不矛盾。
LARGE_W, LARGE_H = 26.0, 28.0

#: 图例上标出来的档位。只标两端和中间，标满十一档反而没人看。
LEGEND_STOPS: tuple[tuple[str, str], ...] = (
    ("d5", "-3%"),
    ("d3", ""),
    ("d1", ""),
    ("flat", "0"),
    ("u1", ""),
    ("u3", ""),
    ("u5", "+3%"),
)


def _direction(change_pct: float) -> str:
    """文字的涨跌方向。只有三种，不带幅度——理由见 theme 里 ``.sec-chg``
    的注释：色阶是给背景设计的，拿来当文字色会让小幅度直接消失。"""
    if change_pct != change_pct or abs(change_pct) < HEAT_FLAT_PCT:
        return "flat"
    return "up" if change_pct > 0 else "down"


def _fit(width: float, height: float) -> str:
    """按块的大小决定文字的档位：放大、正常、只留代码、纯色块。"""
    if width >= LARGE_W and height >= LARGE_H:
        return "lg"
    if width >= FULL_W and height >= FULL_H:
        return ""
    if width >= COMPACT_W and height >= COMPACT_H:
        return "compact"
    return "bare"


def sector_card(block: SectorBlock) -> str:
    """一个行业的卡片：标题行加一张树图。"""
    tiles = sorted(block.tiles, key=lambda t: -t.market_cap)[:MAX_TILES]
    if not tiles:
        return ""

    rects = squarify(
        [t.market_cap for t in tiles], box_w=HEAT_BOX[0], box_h=HEAT_BOX[1]
    )

    cells = []
    for tile, rect in zip(tiles, rects):
        if rect.width <= 0 or rect.height <= 0:
            continue
        fit = _fit(rect.width, rect.height)
        # title 属性是降级块的唯一出路：色块本身读不出是谁，悬停至少能问出来。
        hint = f"{tile.ticker} {tile.signed}"
        if tile.name:
            hint = f"{tile.ticker} · {tile.name} {tile.signed}"
        cells.append(
            f'<div class="tile {tile.level}{" " + fit if fit else ""}" '
            f'style="{rect.style(gap=TILE_GAP)}"{attr("title", hint)}>'
            f'<span class="tile-tk">{esc(tile.ticker)}</span>'
            f'<span class="tile-ch">{esc(tile.signed)}</span>'
            f"</div>"
        )

    return join(
        [
            '<article class="sec-card">',
            '<div class="sec-card-head">',
            f'<span class="sec-name">{esc(block.name)}</span>',
            f'<span class="sec-n">{len(tiles)}</span>',
            f'<span class="sec-chg {_direction(block.change_pct)}">'
            f"{esc(block.signed)}</span>",
            "</div>",
            '<div class="heat">',
            "".join(cells),
            "</div>",
            "</article>",
        ]
    )


def legend() -> str:
    """色阶图例。

    **没有图例的热力图是不可读的。** 读者能看出「绿=涨」，但看不出
    「这个绿是 0.5% 还是 5%」——而后者才是这张图真正的信息。同时它也
    承担了钳位说明：色阶到 ±3% 就到头了，再深的颜色不代表更大的涨跌。
    """
    bits = ['<div class="heat-legend">']
    for level, label in LEGEND_STOPS:
        if label:
            bits.append(f'<span class="lg-label">{esc(label)}</span>')
        # 用 swatch 而不是 tile：tile 是绝对定位的，放进流式布局里会全部
        # 叠在一起。色阶本身靠 .sw-<档位> 复用同一批 token。
        bits.append(f'<i class="swatch sw-{level}"></i>')
    bits.append('<span class="lg-label">色阶在 ±3% 处封顶</span>')
    bits.append("</div>")
    return "".join(bits)


def market_tab(market: Market | None) -> str:
    """「市场」标签页的全部内容。没有数据就返回空串，标签页自动消失。"""
    if market is None or not market.sectors:
        return ""

    cards = [sector_card(b) for b in market.ranked]
    cards = [c for c in cards if c]
    if not cards:
        return ""

    note = market.note or (
        "块的大小按市值，颜色按当日涨跌幅，行业按当日强弱从左到右排。"
        "每块都带符号数字，不依赖颜色也能读。"
    )

    return join(
        [
            '<section class="board">',
            '<div class="board-head">',
            '<h2 class="board-title">板块热力</h2>',
            f'<span class="board-asof">截至 {esc(market.asof)} 收盘</span>',
            "</div>",
            '<div class="sec-rail">',
            join(cards),
            "</div>",
            legend(),
            f'<p class="board-note">{esc(note)}</p>',
            "</section>",
        ]
    )
