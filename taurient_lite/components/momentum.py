"""异动标签页：按「离起涨点多近」分档陈列，最早的排最前。

**为什么按阶段分组而不是按涨幅排序。** 涨幅榜把「刚突破」和「已经走完」
的票混在一起——它们的涨幅可能一样，对读者的意义却完全相反。分档把这个
区别摆到版面结构上：初动单独成组排在最前，已延伸的沉到底部并且刻意
弱化，读者扫一眼就知道哪些还来得及看，哪些只是记录。

**为什么每张卡片都要显示新闻覆盖度。** 这是整个板块唯一不能被通用选股器
复制的信息。价量谁都能算，但「今天扫了 90 篇新闻，这只票一次都没出现」
只有这条每天在读新闻的流水线知道。覆盖度在这里是**反着读的**：无报道
说明市场还没注意到，是最早的线索；已发酵说明消息面已经跑在前面了。

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


def candidate_card(candidate: MomentumCandidate) -> str:
    """一只标的一张卡片。数字在上，人写的判断在下。"""
    direction = "up" if candidate.change_pct >= 0 else "down"
    return join(
        [
            f'<div class="mo-card s-{esc(candidate.stage)}">',
            '<div class="mo-head">',
            f'<span class="mo-tk">{esc(candidate.ticker)}</span>',
            f'<span class="mo-px">{esc(f"{candidate.close:,.2f}")}</span>',
            f'<span class="mo-chg {direction}">{esc(f"{candidate.change_pct:+.2f}%")}</span>',
            f'<span class="mo-cov c-{esc(candidate.coverage)}">'
            f"{esc(candidate.coverage_label)}</span>",
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


def stage_group(stage: str, candidates: tuple[MomentumCandidate, ...]) -> str:
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
            "".join(candidate_card(c) for c in candidates),
            "</div>",
        ]
    )


def momentum_tab(momentum: Momentum | None) -> str:
    """异动标签页的完整内容。没有数据或没有候选时返回空串。"""
    if momentum is None or not momentum.candidates:
        return ""

    asof = f"{momentum.asof} · 扫描 {momentum.scanned} 只" if momentum.scanned else momentum.asof
    groups = [stage_group(s, momentum.by_stage(s)) for s in DISPLAY_ORDER]
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


__all__ = ["candidate_card", "momentum_tab", "stage_group", "DISPLAY_ORDER", "STAGES"]
