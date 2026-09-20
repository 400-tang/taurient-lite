"""把一只标的的全部分析结果压成写进 ``data/fundamentals_scan.json`` 的一行。

**为什么要压。** 完整的七步报告带着每条规则的明细、阈值和上下文，一只标的就有
上百个字段；简报 JSON 是每天归档的真相来源，不该背这么重的东西。页面需要的
只是：总分、每一步的分数和最要紧的几句结论、红旗、估值位置。明细留在扫描时
的计算里，需要时重跑即可。

**结论文字直接存成字符串，而不是存数字让渲染层再拼。** 七步的解读逻辑（什么
情况下说"客户在垫资"、什么情况下说"符号算反"）在 :mod:`.methodology` 里，是跑过
测试的。让渲染层根据数字重新组织语言，等于把这套判断再实现一遍——两份实现
迟早会说出不一样的话。
"""

from __future__ import annotations

from typing import Any

from .methodology import MethodologyReport
from .model import FinancialData
from .reversion import ReversionCase

#: 每一步最多带几句结论进简报。七步各三句已经是二十来句，再多页面就读不完了；
#: 引擎输出的结论按重要性排序（先说结论，再说佐证），截前几句不会丢掉要点。
MAX_FINDINGS = 3


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def valuation_row(case: ReversionCase | None) -> dict[str, Any] | None:
    """估值位置。没有可用的锚时整块省略，而不是写一堆 null。"""
    if case is None or not case.anchor:
        return None
    return {
        "anchor": case.anchor_label,
        "current": _round(case.current, 2),
        "median": _round(case.median, 2),
        "percentile": _round(case.percentile, 3),
        "multiple_upside": _round(case.multiple_upside, 3),
        "regime_change": case.regime_change,
        "verdict": case.verdict,
        "span_days": case.span_days,
    }


def summarize(report: MethodologyReport, data: FinancialData,
              case: ReversionCase | None = None) -> dict[str, Any]:
    """一只标的 -> 一行。"""
    return {
        "ticker": report.ticker,
        "name": report.name,
        "profile": report.profile,
        "profile_label": report.profile_label,
        # 三家公司的"最新年报"往往不是同一个 12 个月（NVDA 止于 1 月、AVGO 止于
        # 10 月），页面上必须把这个日期印出来，否则横向比较会被默认成同期。
        "fiscal_end": data.periods[0] if data.periods else "",
        "currency": data.currency,
        "score": round(report.score, 1),
        "raw_score": round(report.raw_score, 1),
        "grade": report.grade,
        "verdict": report.verdict,
        "coverage": round(report.coverage, 3),
        "gate_warnings": list(report.gate_warnings),
        "flags": list(report.flags),
        "stages": [
            {
                "step": st.order,
                "key": st.key,
                "title": st.title,
                # 一步完全没数据时分数写 null，不写 0——"没法判断"和"判断为差"
                # 是两件事，页面要能区分。
                "score": round(st.score, 1) if st.coverage else None,
                "coverage": round(st.coverage, 3),
                "findings": st.findings[:MAX_FINDINGS],
            }
            for st in report.stages
        ],
        "valuation": valuation_row(case),
    }
