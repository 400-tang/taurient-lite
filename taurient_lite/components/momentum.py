"""异动标签页：按「离起涨点多近」分档陈列，最早的排最前。

**为什么按阶段分组而不是按涨幅排序。** 涨幅榜把「刚突破」和「已经走完」
的票混在一起——它们的涨幅可能一样，对读者的意义却完全相反。分档把这个
区别摆到版面结构上：初动单独成组排在最前，已延伸的沉到底部并且刻意
弱化，读者扫一眼就知道哪些还来得及看，哪些只是记录。

**这里曾经有一个「新闻覆盖度」徽章，被删掉了。** 它标「无报道/零星/
已发酵」，本意是把价量信号和新闻扫描交叉。但标签说不准：依据只是当天
扫到的那几十篇，而「无报道」会被读成「网上没有任何报道」。页面上的
每一个标签都会被当成事实，说不准的标签比没有标签更糟。

**为什么页面上要把回测数字印出来。** 因为一个会被人拿来做决策的页面，
必须把「它有多不可靠」摆在和内容同一个平面上，而不是只写在代码注释里。
全量回测显示初动信号 20 日胜率 51.4%、期望 +1.1%，仅略好过抛硬币；更要紧
的是**排序方向被证伪**——早期度高的那批前向收益反而更差。所以陈列顺序
只表示「有多新」，绝不表示「有多值得买」，这句话必须出现在页面上。
"""

from __future__ import annotations

from ..schema import STAGE_LABEL, STAGES, Momentum, MomentumCandidate
from .base import esc, join, section_head

#: 展示顺序。与 :data:`~taurient_lite.schema.STAGES` 的差别是刻意的：
#: 基底档排在延续之后——它还没突破，观察价值高于紧迫性。
DISPLAY_ORDER: tuple[str, ...] = ("ignition", "continuation", "base", "extended")

STAGE_BLURB: dict[str, str] = {
    "ignition": "突破前高的头几天，量能同步放大",
    "continuation": "突破后两周内，趋势还在但最好的位置已经过去",
    "base": "尚未突破，区间收窄，属于观察名单",
    "extended": "已经走远，列在这里是为了让你认出「这个我已经错过了」",
}

DISCLAIMER = (
    "价量筛选，不是买卖信号。全量回测（2515 只、两年、5090 次初动信号）："
    "20 日胜率 51.4%、期望 +1.1%，仅略好过抛硬币，且收益几乎全部来自极少数"
    "走出趋势的标的，中位数只有 +0.3%。样本未剔除幸存者偏差、区间偏多头、"
    "未计交易成本。同一批数据还显示「越早越好」并不成立——按早期度排序，"
    "最早的一批前向收益反而更差。所以这里的顺序只代表「有多新」，"
    "不代表「有多值得买」，每一条都需要你自己再查一遍基本面与消息面。"
)


def asof_label(momentum: Momentum) -> str:
    """数据时点的说法，一律写成「截至 X 收盘」。

    **不能只写一个光秃秃的日期。** 简报是盘前生成的，所以这里的数字来自
    上一个走完的交易日——挂在一份日期是今天的简报里，一个没有任何限定的
    「+11.98%」必然被读成「今天涨了 12%」。真实发生过：DELL 在 9/11 收盘
    涨 11.98% 进了初动档，读者在 9/14 当天打开页面，而那天它正跌 4%。
    数字没错，是标注没说清它是哪一天的。
    """
    return f"截至 {momentum.asof} 收盘"


def _metric(label: str, value: str, *, tone: str = "") -> str:
    return (
        f'<div class="mo-metric{" " + tone if tone else ""}">'
        f'<span class="mo-metric-k">{esc(label)}</span>'
        f'<span class="mo-metric-v">{esc(value)}</span>'
        "</div>"
    )


def _sources(candidate: MomentumCandidate) -> str:
    if not candidate.sources:
        return ""
    links = " · ".join(
        f'<a href="{esc(s.url)}" target="_blank" rel="noopener">{esc(s.name)}</a>'
        for s in candidate.sources
    )
    return f'<div class="mo-src">{links}</div>'


def candidate_card(candidate: MomentumCandidate, asof: str = "") -> str:
    """一只标的一张卡片。数字在上，人写的判断在下。

    涨跌幅带上日期后缀，因为它是整张卡片最容易被误读的一处——
    详见 :func:`asof_label`。
    """
    direction = "up" if candidate.change_pct >= 0 else "down"
    day = f"{asof[5:]} " if len(asof) >= 10 else ""
    return join(
        [
            f'<div class="mo-card s-{esc(candidate.stage)}">',
            '<div class="mo-head">',
            f'<span class="mo-tk">{esc(candidate.ticker)}</span>',
            f'<span class="mo-px">{esc(f"{candidate.close:,.2f}")}</span>',
            f'<span class="mo-chg {direction}">'
            f'<span class="mo-chg-day">{esc(day)}</span>'
            f'{esc(f"{candidate.change_pct:+.2f}%")}</span>',
            "</div>",
            '<div class="mo-metrics">',
            _metric("突破", candidate.age_label),
            _metric("相对量", f"{candidate.rvol:.1f}x"),
            _metric("乖离", f"{candidate.ext_ma20:+.0%}"),
            _metric("自基底", f"{candidate.run_from_base:+.0%}"),
            "</div>",
            f'<p class="mo-note">{esc(candidate.note)}</p>' if candidate.note else "",
            _sources(candidate),
            "</div>",
        ]
    )


def stage_group(stage: str, candidates: tuple[MomentumCandidate, ...], asof: str = "") -> str:
    """一档。没有标的就整档不出现，不留空壳。"""
    if not candidates:
        return ""
    return join(
        [
            f'<div class="mo-group g-{esc(stage)}">',
            '<div class="mo-group-head">',
            f'<span class="mo-group-name">{esc(STAGE_LABEL[stage])}</span>',
            f'<span class="mo-group-n">{len(candidates)}</span>',
            f'<span class="mo-group-blurb">{esc(STAGE_BLURB[stage])}</span>',
            "</div>",
            "".join(candidate_card(c, asof) for c in candidates),
            "</div>",
        ]
    )


def momentum_strip(momentum: Momentum | None) -> str:
    """首页上的初动摘要条。

    **为什么它必须出现在简报页而不只是标签页里。** 这个模块的全部价值
    是「早」，而标签页需要点一下才看得见——一个每天都不会被点开的
    早期信号，等于没有。所以把最紧的那一档（初动，通常只有个位数）
    压成一条带子放在简报页上，读者每天必然扫过；完整指标留在标签页里，
    想细看再点。

    **只放初动档。** 延续和已延伸也值得看，但它们不紧急；把三档都堆在
    首页会让这条带子变成又一个需要费神筛选的列表，那就重蹈了「看涨幅榜」
    的覆辙——而这个模块存在的理由恰恰是替读者做掉那一层筛选。
    """
    if momentum is None:
        return ""
    early = momentum.early
    if not early:
        return ""

    chips = "".join(
        f'<a class="mo-chip" href="#tab-momentum">'
        f"{esc(c.ticker)}"
        f'<span class="mo-chip-n">{esc(f"{c.rvol:.1f}x")}</span>'
        "</a>"
        for c in early
    )

    foot = (
        f"{len(early)} 只刚进入初动档。数字是相对成交量，"
        "完整指标见「异动」标签页。"
    )

    return join(
        [
            section_head("价量异动", count=len(early), asof=asof_label(momentum)),
            '<div class="mo-strip">',
            f'<div class="mo-strip-grid">{chips}</div>',
            f'<p class="mo-strip-foot">{esc(foot)}</p>',
            "</div>",
        ]
    )


def momentum_tab(momentum: Momentum | None) -> str:
    """异动标签页的完整内容。没有数据或没有候选时返回空串。"""
    if momentum is None or not momentum.candidates:
        return ""

    asof = asof_label(momentum)
    if momentum.scanned:
        asof += f" · 扫描 {momentum.scanned} 只"
    groups = [stage_group(s, momentum.by_stage(s), momentum.asof) for s in DISPLAY_ORDER]
    if not any(groups):
        return ""

    return join(
        [
            section_head("价量异动", asof=asof),
            f'<p class="mo-lede">{esc(momentum.note)}</p>' if momentum.note else "",
            f'<div class="mo-disclaimer">{esc(DISCLAIMER)}</div>',
            '<div class="mo-groups">',
            join(groups),
            "</div>",
        ]
    )


__all__ = [
    "candidate_card",
    "momentum_strip",
    "momentum_tab",
    "stage_group",
    "DISPLAY_ORDER",
    "STAGES",
]
