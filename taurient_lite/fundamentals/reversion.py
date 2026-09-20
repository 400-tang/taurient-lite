"""均值回归测算层 —— 显式的假设层，不是方法论的一部分。

《方法论 Part1》第 7 步只做否决（贵就否掉），不给目标价。"回到自身历史中位数"
是叠加在方法论之上的**假设**，所以物理上放在独立模块里：七步的结论判断"这家公司
好不好"，这里回答"便宜是因为烂，还是因为被错杀"。

两者在输出中始终分开标注，不合并成一个分数。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .valuation import Bands

# 主锚是 P/FCF：方法论的价值定义就是自由现金流。FCF 为负或样本太薄时按序退到下一个口径。
ANCHOR_PRIORITY = ("p_fcf", "ps", "ev_ebitda", "pe")
ANCHOR_LABELS = {"p_fcf": "P/FCF", "ps": "P/S", "ev_ebitda": "EV/EBITDA", "pe": "P/E"}
ANCHOR_DRIVER = {"p_fcf": "fcf", "ps": "revenue", "ev_ebitda": "ebitda", "pe": "net_income"}

MIN_OBSERVATIONS = 120          # 少于半年的日观测，分位数没有意义
MAX_STALENESS_DAYS = 20         # 锚必须"当期可算"，不只是"历史样本厚"
MIN_SPAN_DAYS = 500             # 不足约两年的窗口，中位数不足以代表"正常水平"
GROWTH_CLAMP = (-0.15, 0.25)    # 外推增速的夹取区间，防止把短期爆发线性外推
REGIME_RATIO = 3.0              # 基本面变动超过这个倍数，自身历史已不是同一家公司


@dataclass
class Attribution:
    """便宜的归因：价格跌出来的，还是基本面塌出来的。"""

    lookback_days: int
    market_cap_change: float | None = None
    fundamental_change: float | None = None
    multiple_change: float | None = None
    driver: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lookback_days": self.lookback_days,
            "market_cap_change": self.market_cap_change,
            "fundamental_change": self.fundamental_change,
            "multiple_change": self.multiple_change,
            "driver": self.driver,
        }


@dataclass
class ReversionCase:
    ticker: str
    name: str = ""
    anchor: str = ""
    anchor_label: str = ""
    current: float | None = None
    median: float | None = None
    percentile: float | None = None
    observations: int = 0
    span_days: int = 0
    multiple_upside: float | None = None      # 仅倍数修复
    growth: float | None = None
    horizon: float = 1.0
    growth_contribution: float | None = None  # 仅基本面增长
    total_upside: float | None = None
    attribution: Attribution | None = None
    quality_score: float | None = None        # 七步法得分，来自方法论引擎
    quality_grade: str = ""
    regime_change: bool = False               # 基本面已发生量级变化 -> 历史中位数失效
    verdict: str = ""
    cautions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "anchor": self.anchor,
            "anchor_label": self.anchor_label,
            "current": self.current,
            "median": self.median,
            "percentile": self.percentile,
            "observations": self.observations,
            "span_days": self.span_days,
            "assumption": "回归至自身历史中位数",
            "multiple_upside": self.multiple_upside,
            "growth": self.growth,
            "horizon_years": self.horizon,
            "growth_contribution": self.growth_contribution,
            "total_upside": self.total_upside,
            "attribution": self.attribution.to_dict() if self.attribution else None,
            "quality_score": self.quality_score,
            "quality_grade": self.quality_grade,
            "regime_change": self.regime_change,
            "anchor_valid": not self.regime_change,
            "verdict": self.verdict,
            "cautions": self.cautions,
        }


# ---------------------------------------------------------------------------
# 纯计算
# ---------------------------------------------------------------------------


def pick_anchor(bands: Bands, preferred: str | None = None) -> tuple[str | None, list[str]]:
    """选一个**当期仍可计算**且样本够厚的锚。

    两道门缺一不可：样本厚度决定分位数有没有意义，时效性决定"当前值"是不是真的
    当前 —— 分母转负会让倍数序列悄悄停更，只查厚度会拿陈旧倍数当今天的估值。
    """
    notes: list[str] = []
    order = ([preferred] if preferred else []) + [a for a in ANCHOR_PRIORITY if a != preferred]
    for anchor in order:
        if not anchor:
            continue
        label = ANCHOR_LABELS.get(anchor, anchor)
        obs = bands.observations(anchor)
        if obs < MIN_OBSERVATIONS or not bands.median(anchor):
            notes.append(f"{label} 仅 {obs} 个观测，样本不足以定分位，跳过")
            continue
        stale = bands.staleness_days(anchor)
        if stale is not None and stale > MAX_STALENESS_DAYS:
            notes.append(f"{label} 的最后一个有效观测停在 {bands.last_date(anchor)}"
                         f"（{stale} 天前）—— {_stale_reason(bands, anchor)}，跳过")
            continue
        if anchor != ANCHOR_PRIORITY[0]:
            notes.append(f"已退到 {label} 口径")
        return anchor, notes
    return None, notes


def _stale_reason(bands: Bands, anchor: str) -> str:
    """倍数停更的原因，绝大多数情况是分母转负。"""
    field_name = ANCHOR_DRIVER.get(anchor, "")
    if not bands.prices or not field_name:
        return "数据中断"
    value = bands.fundamental_on(field_name, bands.prices[-1][0])
    if value is not None and value <= 0:
        return f"当期 TTM {field_name} 为负（{value:,.0f}），该倍数已无意义"
    return "报表数据中断"


def attribute(bands: Bands, anchor: str, lookback_days: int = 365) -> Attribution:
    """把倍数变化拆成市值变化和基本面变化两段。

    multiple = 市值 / 基本面，所以倍数的变化必然由这两者之一驱动。区分
    "市场杀估值"和"基本面恶化"只能靠这个拆解，看倍数本身看不出来。
    """
    att = Attribution(lookback_days=lookback_days)
    if not bands.prices:
        return att
    today = bands.prices[-1][0]
    then = today - dt.timedelta(days=lookback_days)

    driver_field = ANCHOR_DRIVER.get(anchor, "fcf")
    cap_now, cap_then = bands.market_cap_on(today), bands.market_cap_on(then)
    fund_now, fund_then = bands.fundamental_on(driver_field, today), \
        bands.fundamental_on(driver_field, then)

    if cap_now is not None and cap_then:
        att.market_cap_change = cap_now / cap_then - 1
    if fund_now is not None and fund_then and fund_then > 0:
        att.fundamental_change = fund_now / fund_then - 1
    mult_now, mult_then = bands.current(anchor), bands.value_on(anchor, then)
    if mult_now is not None and mult_then:
        att.multiple_change = mult_now / mult_then - 1

    cap_chg, fund_chg = att.market_cap_change, att.fundamental_change
    if cap_chg is None or fund_chg is None:
        att.driver = "数据不足，无法归因"
    elif cap_chg < -0.05 and fund_chg > 0.05:
        att.driver = "市场杀估值：基本面在涨，价格在跌 —— 典型的预期差形态"
    elif cap_chg < -0.05 and fund_chg < -0.05:
        if abs(fund_chg - cap_chg) < 0.02:
            detail = "，跌幅相当"
        elif fund_chg < cap_chg:
            detail = "，且基本面跌得更快 —— 便宜是有理由的"
        else:
            detail = "，价格跌幅更大"
        att.driver = "双杀：价格和基本面同时下滑" + detail
    elif cap_chg < -0.05:
        att.driver = "价格下跌，基本面基本持平"
    elif fund_chg > 0.05 and cap_chg < fund_chg:
        att.driver = "基本面增长快于股价，估值被动消化"
    else:
        att.driver = "价格与基本面同向变动，无明显错配"
    return att


def detect_regime_change(bands: Bands, anchor: str) -> tuple[bool, str | None]:
    """判断"自身历史"是否还指向同一家公司。

    均值回归的前提是均值有意义。当分母在窗口内发生量级变化（AI 周期里 NVIDIA 的
    自由现金流就是典型），早年的高倍数只是"基数极小"的算术产物，拿它做中位数
    等于假设公司退回上一个时代。这种情况必须显式失效，而不是输出一个漂亮的空间。
    """
    series = bands.series.get(anchor) or []
    if not series or not bands.prices:
        return False, None
    field_name = ANCHOR_DRIVER.get(anchor, "")
    then = bands.fundamental_on(field_name, series[0][0])
    now = bands.fundamental_on(field_name, bands.prices[-1][0])
    if not then or not now or then <= 0 or now <= 0:
        return False, None
    ratio = now / then
    if ratio >= REGIME_RATIO or ratio <= 1 / REGIME_RATIO:
        return True, (f"窗口内 {field_name} 从 {then:,.0f} 变为 {now:,.0f}（{ratio:.1f}x），"
                      f"基本面已发生量级变化 —— 自身历史中位数不构成有效回归锚")
    return False, None


def clamp_growth(growth: float | None) -> tuple[float | None, str | None]:
    """夹取外推增速。把短期爆发线性外推几年是这类测算最常见的自欺方式。"""
    if growth is None:
        return None, None
    low, high = GROWTH_CLAMP
    if growth > high:
        return high, f"基本面增速 {growth:.0%} 已夹取至 {high:.0%}，避免把短期爆发线性外推"
    if growth < low:
        return low, f"基本面增速 {growth:.0%} 已夹取至 {low:.0%}"
    return growth, None


def assess(bands: Bands, quality_score: float | None = None, quality_grade: str = "",
           growth: float | None = None, horizon: float = 1.0,
           preferred_anchor: str | None = None) -> ReversionCase:
    """回归至自身历史中位数的空间测算。

    倍数修复和基本面增长分开计算再相乘，输出时也分开列 —— 合成一个数会掩盖
    "这笔收益到底赌的是估值还是经营"。
    """
    case = ReversionCase(ticker=bands.ticker, name=bands.name, horizon=horizon,
                         quality_score=quality_score, quality_grade=quality_grade)
    case.cautions.extend(bands.caveats)

    anchor, notes = pick_anchor(bands, preferred_anchor)
    if anchor is None:
        case.verdict = "无可用估值锚，样本不足以判断分位"
        case.cautions.extend(notes)
        return case
    case.cautions.extend(notes)

    case.anchor = anchor
    case.anchor_label = ANCHOR_LABELS[anchor]
    case.current = bands.current(anchor)
    case.median = bands.median(anchor)
    case.percentile = bands.percentile(anchor)
    case.observations = bands.observations(anchor)
    case.span_days = bands.span_days(anchor)

    if case.current and case.median:
        case.multiple_upside = case.median / case.current - 1

    g, note = clamp_growth(growth)
    case.growth = g
    if note:
        case.cautions.append(note)
    if g is not None:
        case.growth_contribution = (1 + g) ** horizon - 1

    if case.multiple_upside is not None:
        total = 1 + case.multiple_upside
        if case.growth_contribution is not None:
            total *= 1 + case.growth_contribution
        case.total_upside = total - 1

    case.regime_change, regime_note = detect_regime_change(bands, anchor)
    if regime_note:
        case.cautions.append(regime_note)

    case.attribution = attribute(bands, anchor)
    case.verdict = _classify(case)
    case.cautions.extend(_sample_cautions(case))
    return case


def _classify(case: ReversionCase) -> str:
    """把"质量"和"便宜"交叉分类。单看任何一维都会得出错误结论。"""
    pct, q = case.percentile, case.quality_score
    if pct is None:
        return "分位不可得"
    if case.regime_change:
        return ("回归锚失效：基本面已发生量级变化，历史分位只反映"
                "“公司变了”，不构成低估或高估的证据")
    cheap, rich = pct <= 0.30, pct >= 0.70
    fund_falling = (case.attribution.fundamental_change or 0) < -0.05 if case.attribution else False

    if q is None:
        return ("处于历史低位，但未接入七步质量分，无法区分错杀与陷阱" if cheap
                else "处于历史高位" if rich else "估值居中")
    good = q >= 60
    if cheap and good and not fund_falling:
        return "错配候选：七步质量过关且估值处于历史低位 —— 这是要找的形态"
    if cheap and good and fund_falling:
        return "低估但基本面在退坡：便宜有理由，需确认是周期还是趋势"
    if cheap and not good:
        return "价值陷阱嫌疑：便宜是因为报表本身有问题，不是被错杀"
    if rich and good:
        return "优质但已充分定价：好消息基本反映在价格里"
    if rich and not good:
        return "双高风险：质量存疑且估值处于历史高位"
    return "估值居中" + ("，质量过关" if good else "，质量存疑")


def _sample_cautions(case: ReversionCase) -> list[str]:
    out = []
    if case.span_days and case.span_days < MIN_SPAN_DAYS:
        out.append(f"历史窗口仅 {case.span_days} 天，中位数不足以代表“正常水平”")
    if case.observations and case.observations < 250:
        out.append(f"仅 {case.observations} 个日观测，分位数稳健性有限")
    return out


# 增速口径必须和估值锚一致：用 P/FCF 做锚就得用 FCF 增速，混用等于偷换分母
GROWTH_METRIC = {
    "p_fcf": "fcf_cagr_3y",
    "ps": "revenue_cagr_3y",
    "pe": "net_income_cagr_3y",
    "ev_ebitda": "revenue_cagr_3y",
}


def growth_for(anchor: str, metrics: Any) -> float | None:
    """取与估值锚匹配的基本面增速；主口径缺失时退到营收增速。"""
    key = GROWTH_METRIC.get(anchor)
    value = metrics.get(key) if key else None
    return value if value is not None else metrics.get("revenue_cagr_3y")


def scan(cases: list[ReversionCase]) -> list[ReversionCase]:
    """错配优先排序：先看是不是错配候选，再按便宜程度排。"""
    def key(c: ReversionCase):
        is_candidate = c.verdict.startswith("错配候选")
        return (not is_candidate, c.percentile if c.percentile is not None else 1.0)
    return sorted(cases, key=key)
