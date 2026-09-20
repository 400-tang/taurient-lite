"""基本面标签页：按《方法论 Part1》七步法看一组公司的账能不能信、贵不贵。

**版面顺序就是阅读顺序。** 先一张矩阵——每行一只标的、每列一步——让读者一眼
看出「谁在哪一步掉了分」；再按总分排列的卡片，折叠着，展开才是七步的逐条结论。
矩阵回答「比较」，卡片回答「为什么」。

**总分不是第一信息。** 这套方法论本质是证伪工具，七步里五步在找理由否掉一家
公司，所以一只标的「在哪一步、因为什么被扣分」比它的总分重要得多。矩阵因此
把七个分项摊开，而不是只给一个数；红旗单独成列，不混进分数里。

**页面上印出来的三条限制**，每一条都来自一次真实的误读风险：

* 财年不同步——三家的「最新年报」常常不是同一个 12 个月，所以每张卡片都印
  财年止于哪天；
* 行业口径——软件公司的营运资本是负的（客户在垫资），用硬件口径会把符号算反，
  所以每只标的都标着用的是哪套口径；
* 估值位置是**用户设定的假设层**，不是方法论的结论——方法论第 7 步只做否决、
  不给锚，所以那一行单独标注，基本面发生量级变化时直接不给回归空间。
"""

from __future__ import annotations

from ..schema import Fundamentals, FundamentalsRow, FundamentalsStage, FundamentalsValuation
from .base import esc, join, section_head

#: 矩阵列头。按 stage key 取，而不是用引擎输出的完整标题——完整标题在软件口径
#: 下会换（「营运资本 = 占用谁的钱」），但列头要在不同口径的行之间对齐。
STAGE_SHORT: dict[str, str] = {
    "cash": "现金",
    "sbc": "口径",
    "margin": "毛利",
    "working_capital": "营运",
    "ar_inventory": "红旗",
    "capex_timing": "折旧",
    "valuation": "估值",
}
STAGE_ORDER: tuple[str, ...] = tuple(STAGE_SHORT)

#: 低于这个分数的格子用「需要注意」的红标出来。和七步法的关口阈值一致。
WEAK_SCORE = 40.0

DISCLAIMER = (
    "报表质量排序，不是买卖信号，也不是目标价。七步法本质是证伪工具——七步里五步"
    "在找理由否掉一家公司，所以先看「在哪一步掉了分」，再看总分。数据来自 Yahoo "
    "Finance 的二手汇编，不是原始申报文件；三家公司的「最新年报」常常不是同一个 "
    "12 个月，卡片上印着各自的财年截止日。估值那一行是叠加在方法论之上的假设"
    "（回到自身历史中位数），不是方法论本身的结论。"
)


# --------------------------------------------------------------------------- 格式


def _pct(value: float | None, digits: int = 0) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _x(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}x"


def _fiscal(row: FundamentalsRow) -> str:
    """财年截止，写到月：同一个月内的差异不影响横向比较，写到日只会显得啰嗦。"""
    return f"财年止于 {row.fiscal_end[:7]}" if row.fiscal_end else ""


# --------------------------------------------------------------------------- 矩阵


def _stage_cell(stage: FundamentalsStage | None) -> str:
    """一格。宽度随分数填充，低分标红，没数据画破折号而不是 0。"""
    if stage is None or stage.score is None:
        return '<td class="fu-cell fu-nodata" title="这一步没有数据">—</td>'
    weak = " fu-weak" if stage.score < WEAK_SCORE else ""
    return (
        f'<td class="fu-cell{weak}" style="--fill:{stage.score:.0f}%" '
        f'title="{esc(stage.title)}">{stage.score:.0f}</td>'
    )


def matrix(rows: tuple[FundamentalsRow, ...]) -> str:
    """每行一只标的，每列一步。按总分排序。"""
    if not rows:
        return ""
    head = "".join(f'<th scope="col">{esc(STAGE_SHORT[k])}</th>' for k in STAGE_ORDER)
    body = []
    for row in sorted(rows, key=lambda r: r.score, reverse=True):
        by_key = {st.key: st for st in row.stages}
        cells = "".join(_stage_cell(by_key.get(k)) for k in STAGE_ORDER)
        flags = (
            f'<span class="fu-flagn">{len(row.flags)}</span>' if row.flags else ""
        )
        body.append(
            "<tr>"
            f'<th scope="row"><a class="fu-tk" href="#fu-{esc(row.ticker)}">'
            f"{esc(row.ticker)}</a>"
            f'<span class="fu-prof p-{esc(row.profile)}">{esc(row.profile_label)}</span></th>'
            f'<td class="fu-total">{row.score:.1f}<span class="fu-grade">{esc(row.grade)}</span></td>'
            f"{cells}"
            f'<td class="fu-flags">{flags}</td>'
            "</tr>"
        )
    return join(
        [
            '<div class="fu-matrix-wrap">',
            '<table class="fu-matrix">',
            "<thead><tr>"
            '<th scope="col">代码</th><th scope="col">总分</th>'
            f'{head}<th scope="col">红旗</th>'
            "</tr></thead>",
            f"<tbody>{''.join(body)}</tbody>",
            "</table>",
            "</div>",
        ]
    )


# --------------------------------------------------------------------------- 卡片


def valuation_line(valuation: FundamentalsValuation | None) -> str:
    """估值在自身历史中的位置。标明是假设层；锚失效时不给回归空间。"""
    if valuation is None:
        return ""
    label = '<span class="fu-val-k">估值位置 · 假设层</span>'
    position = (
        f"{esc(valuation.anchor)} {_x(valuation.current)}，"
        f"自身历史中位 {_x(valuation.median)}，处于 {_pct(valuation.percentile)} 分位"
    )
    if valuation.regime_change:
        tail = "基本面在窗口内发生量级变化，历史中位数指向的已是另一家公司，不给回归空间"
        cls = " fu-val-void"
    elif valuation.multiple_upside is not None:
        tail = f"若回到中位数，倍数变动 {valuation.multiple_upside * 100:+.0f}%"
        cls = ""
    else:
        tail, cls = "", ""
    return join(
        [
            f'<div class="fu-val{cls}">',
            label,
            f'<span class="fu-val-v">{position}</span>',
            f'<span class="fu-val-t">{esc(tail)}</span>' if tail else "",
            "</div>",
        ]
    )


def stage_block(stage: FundamentalsStage) -> str:
    """七步中的一步：步号、标题、分数，下面是引擎写好的结论。"""
    score = "无数据" if stage.score is None else f"{stage.score:.0f}"
    weak = " fu-weak" if stage.score is not None and stage.score < WEAK_SCORE else ""
    findings = "".join(f"<li>{esc(f)}</li>" for f in stage.findings)
    return join(
        [
            '<div class="fu-stage">',
            '<div class="fu-stage-head">',
            f'<span class="fu-step">{stage.step}</span>',
            f'<span class="fu-stage-t">{esc(stage.title)}</span>',
            f'<span class="fu-stage-s{weak}">{esc(score)}</span>',
            "</div>",
            f'<ul class="fu-find">{findings}</ul>' if findings else "",
            "</div>",
        ]
    )


def row_card(row: FundamentalsRow) -> str:
    """一只标的一张卡片。

    常显的是结论、关口警告、红旗和估值位置——这些决定要不要往下看；七步的
    逐条结论收在折叠里，想知道「为什么」再展开。
    """
    warnings = "".join(f"<li>{esc(w)}</li>" for w in row.gate_warnings)
    flags = "".join(f"<li>{esc(f)}</li>" for f in row.flags)
    penalty = (
        f'<span class="fu-pen">红旗扣 {row.penalty:.1f}</span>' if row.penalty >= 0.05 else ""
    )
    return join(
        [
            f'<article class="fu-card" id="fu-{esc(row.ticker)}">',
            '<div class="fu-head">',
            f'<span class="fu-card-tk">{esc(row.ticker)}</span>',
            f'<span class="fu-name">{esc(row.name)}</span>',
            f'<span class="fu-score">{row.score:.1f}<span class="fu-grade">{esc(row.grade)}</span></span>',
            "</div>",
            '<div class="fu-meta">',
            f'<span class="fu-prof p-{esc(row.profile)}">{esc(row.profile_label)}口径</span>',
            f"<span>{esc(_fiscal(row))}</span>" if row.fiscal_end else "",
            f"<span>规则覆盖率 {_pct(row.coverage)}</span>",
            penalty,
            "</div>",
            f'<p class="fu-verdict">{esc(row.verdict)}</p>' if row.verdict else "",
            f'<p class="fu-note">{esc(row.note)}</p>' if row.note else "",
            f'<ul class="fu-gate">{warnings}</ul>' if warnings else "",
            f'<ul class="fu-redflags">{flags}</ul>' if flags else "",
            valuation_line(row.valuation),
            '<details class="fu-more">',
            "<summary>七步明细</summary>",
            '<div class="fu-stages">',
            join(stage_block(st) for st in sorted(row.stages, key=lambda s: s.step)),
            "</div>",
            "</details>",
            "</article>",
        ]
    )


# --------------------------------------------------------------------------- 整页


def fundamentals_tab(fundamentals: Fundamentals | None) -> str:
    """基本面标签页的完整内容。没有数据时返回空串，标签页不出现。"""
    if fundamentals is None or not fundamentals.rows:
        return ""

    asof = f"截至 {fundamentals.asof} 扫描"
    if fundamentals.scanned:
        asof += f" · {len(fundamentals.rows)}/{fundamentals.scanned} 只"
    rows = sorted(fundamentals.rows, key=lambda r: r.score, reverse=True)

    return join(
        [
            section_head("七步法基本面", asof=asof),
            f'<p class="fu-lede">{esc(fundamentals.note)}</p>' if fundamentals.note else "",
            f'<div class="fu-disclaimer">{esc(DISCLAIMER)}</div>',
            matrix(fundamentals.rows),
            '<p class="fu-legend">格子里是每一步的得分（0-100），低于 40 标红；'
            "「—」表示这一步没有数据，不是 0 分。点代码跳到下面的卡片。</p>",
            '<div class="fu-cards">',
            join(row_card(r) for r in rows),
            "</div>",
            f'<p class="fu-source">数据：{esc(fundamentals.source)}</p>'
            if fundamentals.source else "",
        ]
    )


__all__ = [
    "fundamentals_tab",
    "matrix",
    "row_card",
    "stage_block",
    "valuation_line",
    "STAGE_ORDER",
    "STAGE_SHORT",
]
