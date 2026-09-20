"""指标计算层。

输入规范化后的 FinancialData，输出一个扁平的指标字典 + 少量历史序列。
约定：
  - 比率类统一用 **小数**（0.42 表示 42%），展示时再乘 100，避免阈值写混
  - 任何一个中间量缺失，该指标返回 None，而不是 0（0 会被打分规则误判为“很差”）
  - 增长率用 CAGR，基期为负或为 0 时返回 None（数学上没有意义）
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from .model import FinancialData

# 固定资产原值增速的两道门：低于 CLEAN 才敢把年限拉长归因于会计政策；
# 超过 AMBIGUOUS 基本可断定是新增资产当年未充分计提造成的机械效应。
PPE_EXPANSION_CLEAN = 0.08
PPE_EXPANSION_AMBIGUOUS = 0.15


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def div(numerator: float | None, denominator: float | None) -> float | None:
    """安全除法：任一为 None 或分母为 0 时返回 None。"""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def avg(*values: float | None) -> float | None:
    """对非空值取均值（用于期初期末平均，如平均净资产）。"""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def cagr(series: list[float], years: int | None = None) -> float | None:
    """年复合增长率。series 按新 -> 旧排列。"""
    if len(series) < 2:
        return None
    window = series[: (years + 1)] if years else series
    if len(window) < 2:
        return None
    latest, oldest = window[0], window[-1]
    n = len(window) - 1
    if oldest is None or oldest <= 0 or latest is None or latest <= 0:
        return None
    return (latest / oldest) ** (1 / n) - 1


def yoy(series: list[float | None]) -> float | None:
    """最近一期同比增速。"""
    if len(series) < 2 or series[0] is None or series[1] in (None, 0):
        return None
    return series[0] / abs(series[1]) - 1


def positive_ratio(series: list[float]) -> float | None:
    """序列中为正的比例，用于“连续 N 年盈利/自由现金流为正”这类稳定性判断。"""
    if not series:
        return None
    return sum(1 for v in series if v > 0) / len(series)


def stdev(series: list[float]) -> float | None:
    return statistics.pstdev(series) if len(series) >= 2 else None


@dataclass
class Metrics:
    """一只标的的全部指标。values 供打分使用，history 供展示趋势。"""

    ticker: str
    name: str = ""
    period: str = "annual"
    periods: list[str] = field(default_factory=list)
    values: dict[str, float | None] = field(default_factory=dict)
    history: dict[str, list[float | None]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def get(self, key: str) -> float | None:
        return self.values.get(key)

    def available(self) -> dict[str, float]:
        return {k: v for k, v in self.values.items() if v is not None}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "period": self.period,
            "periods": self.periods,
            "values": self.values,
            "history": self.history,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------


def compute(data: FinancialData) -> Metrics:
    """计算全部指标。"""
    m = Metrics(ticker=data.ticker, name=data.name, period=data.period, periods=data.periods)
    v = m.values

    rev = data.series("revenue")
    ni = data.series("net_income")
    ocf = data.series("operating_cash_flow")
    capex = data.series("capex")
    fcf_hist = _fcf_series(data)

    # -- 盈利能力 ----------------------------------------------------------
    v["gross_margin"] = div(data.latest("gross_profit"), data.latest("revenue"))
    v["operating_margin"] = div(data.latest("operating_income"), data.latest("revenue"))
    v["net_margin"] = div(data.latest("net_income"), data.latest("revenue"))
    v["fcf_margin"] = div(fcf_hist[0] if fcf_hist else None, data.latest("revenue"))

    # ROE / ROA 用期初期末平均，避免回购或增发把单期分母打歪
    v["roe"] = div(data.latest("net_income"), avg(data.latest("equity"), data.latest("equity", 1)))
    v["roa"] = div(data.latest("net_income"),
                   avg(data.latest("total_assets"), data.latest("total_assets", 1)))
    v["roic"] = _roic(data)

    # -- 成长性 ------------------------------------------------------------
    v["revenue_yoy"] = yoy(rev)
    v["net_income_yoy"] = yoy(ni)
    v["revenue_cagr_3y"] = cagr([x for x in rev if x is not None], 3)
    v["revenue_cagr_5y"] = cagr([x for x in rev if x is not None], 5)
    v["net_income_cagr_3y"] = cagr([x for x in ni if x is not None], 3)
    v["eps_cagr_3y"] = cagr(data.clean_series("diluted_eps"), 3)
    v["fcf_cagr_3y"] = cagr([x for x in fcf_hist if x is not None], 3)

    # -- 盈利质量 ----------------------------------------------------------
    # 经营现金流 / 净利润：长期显著小于 1 说明利润没转化成现金（应收、存货堆积）
    v["cash_conversion"] = div(data.latest("operating_cash_flow"), data.latest("net_income"))
    v["accrual_ratio"] = _accrual_ratio(data)
    v["rnd_intensity"] = div(data.latest("rnd"), data.latest("revenue"))
    v["capex_intensity"] = div(abs(capex[0]) if capex and capex[0] is not None else None,
                               data.latest("revenue"))
    v["gross_margin_stability"] = _margin_stability(data)
    v["profitable_years_ratio"] = positive_ratio([x for x in ni if x is not None])
    v["positive_fcf_years_ratio"] = positive_ratio([x for x in fcf_hist if x is not None])

    # -- 杠杆与流动性 ------------------------------------------------------
    v["debt_to_equity"] = div(data.latest("total_debt"), data.latest("equity"))
    v["net_debt_to_ebitda"] = div(_net_debt(data), data.latest("ebitda"))
    v["current_ratio"] = div(data.latest("current_assets"), data.latest("current_liabilities"))
    v["quick_ratio"] = _quick_ratio(data)
    v["interest_coverage"] = _interest_coverage(data)
    v["liabilities_to_assets"] = div(data.latest("total_liabilities"), data.latest("total_assets"))

    # -- 估值 --------------------------------------------------------------
    v.update(_valuation(data, fcf_hist))

    # -- 股东回报 ----------------------------------------------------------
    v["dividend_payout"] = _payout(data)
    v["buyback_yield"] = _buyback_yield(data)
    v["share_count_change_3y"] = _share_change(data)

    # -- 方法论 Part1 专用指标（现金还原 / SBC / 毛利拆解 / 营运资本 / 折旧时间差）--
    v.update(_methodology_metrics(data, fcf_hist))

    # -- 历史序列（给表格/图表用）------------------------------------------
    m.history = {
        "periods": data.periods,
        "revenue": rev,
        "net_income": ni,
        "operating_cash_flow": ocf,
        "free_cash_flow": fcf_hist,
        "gross_margin": _ratio_series(data, "gross_profit", "revenue"),
        "operating_margin": _ratio_series(data, "operating_income", "revenue"),
        "net_margin": _ratio_series(data, "net_income", "revenue"),
        "fcf_ex_sbc": _fcf_ex_sbc_series(data, fcf_hist),
        "nwc_to_sales": _nwc_to_sales_series(data),
    }

    if data.n_periods < 3:
        m.notes.append(f"仅有 {data.n_periods} 个报告期，成长性与稳定性指标参考价值有限")
    if not any(v is not None for v in fcf_hist):
        m.notes.append("缺少现金流量表数据，自由现金流相关指标不可用")
    if data.market.get("market_cap") is None and data.market.get("price") is None:
        m.notes.append("缺少市值/价格数据，估值指标不可用")

    return m


# ---------------------------------------------------------------------------
# 各指标的具体实现
# ---------------------------------------------------------------------------


def _fcf_series(data: FinancialData) -> list[float | None]:
    """自由现金流：优先用数据源给的，否则 OCF - |capex| 自己算。"""
    reported = data.series("free_cash_flow")
    ocf = data.series("operating_cash_flow")
    capex = data.series("capex")
    out: list[float | None] = []
    for i in range(data.n_periods):
        value = reported[i] if i < len(reported) else None
        if value is None:
            o = ocf[i] if i < len(ocf) else None
            c = capex[i] if i < len(capex) else None
            value = o - abs(c) if o is not None and c is not None else None
        out.append(value)
    return out


def _net_debt(data: FinancialData) -> float | None:
    reported = data.latest("net_debt")
    if reported is not None:
        return reported
    debt, cash = data.latest("total_debt"), data.latest("cash")
    return debt - cash if debt is not None and cash is not None else None


def _tax_rate(data: FinancialData) -> float:
    """有效税率，异常值夹到 [0, 50%]，缺失时退回 21%。"""
    rate = div(data.latest("tax_provision"), data.latest("pretax_income"))
    if rate is None or not 0 <= rate <= 0.5:
        return 0.21
    return rate


def _roic(data: FinancialData) -> float | None:
    """NOPAT / 投入资本。投入资本优先用数据源口径，否则用 有息负债 + 股东权益。"""
    ebit = data.latest("ebit") or data.latest("operating_income")
    if ebit is None:
        return None
    nopat = ebit * (1 - _tax_rate(data))

    capital = avg(data.latest("invested_capital"), data.latest("invested_capital", 1))
    if capital is None:
        debt, equity = data.latest("total_debt"), data.latest("equity")
        capital = (debt or 0) + equity if equity is not None else None
    return div(nopat, capital)


def _accrual_ratio(data: FinancialData) -> float | None:
    """应计比例 =（净利润 - 经营现金流）/ 总资产。越高说明利润里“纸面成分”越多。"""
    ni, ocf = data.latest("net_income"), data.latest("operating_cash_flow")
    if ni is None or ocf is None:
        return None
    return div(ni - ocf, data.latest("total_assets"))


def _quick_ratio(data: FinancialData) -> float | None:
    ca, inv = data.latest("current_assets"), data.latest("inventory")
    if ca is None:
        return None
    return div(ca - (inv or 0), data.latest("current_liabilities"))


def _interest_coverage(data: FinancialData) -> float | None:
    """利息保障倍数。没有利息支出的公司记为一个很大的值，表示“无偿债压力”。"""
    ebit = data.latest("ebit") or data.latest("operating_income")
    interest = data.latest("interest_expense")
    if ebit is None:
        return None
    if interest is None or interest == 0:
        return 999.0
    return ebit / abs(interest)


def _margin_stability(data: FinancialData) -> float | None:
    """毛利率波动率（总体标准差）。越小说明生意的护城河/定价权越稳。"""
    series = [x for x in _ratio_series(data, "gross_profit", "revenue") if x is not None]
    return stdev(series)


def _ratio_series(data: FinancialData, numerator: str, denominator: str) -> list[float | None]:
    num, den = data.series(numerator), data.series(denominator)
    return [
        div(num[i] if i < len(num) else None, den[i] if i < len(den) else None)
        for i in range(data.n_periods)
    ]


def _market_cap(data: FinancialData) -> float | None:
    """财报币种下的市值。

    所有估值与股东回报指标的分母都是它。报价币种与财报币种不一致时必须先折算，
    否则 PE、FCF 收益率、回购分红回报率会整体错一个汇率的量级。折算不了就返回
    None，让指标显示 N/A —— 错的数比没有数危险。
    """
    cap = data.market.get("market_cap_financial")
    if cap is not None:
        return cap
    if data.market.get("currency_mismatch"):
        return None
    cap = data.market.get("market_cap")
    if cap is not None:
        return cap
    price = data.market.get("price")
    shares = data.market.get("shares_outstanding") or data.latest("shares_outstanding")
    return price * shares if price is not None and shares else None


def _valuation(data: FinancialData, fcf_hist: list[float | None]) -> dict[str, float | None]:
    cap = _market_cap(data)
    ni, rev, equity = data.latest("net_income"), data.latest("revenue"), data.latest("equity")
    fcf = fcf_hist[0] if fcf_hist else None
    ebitda = data.latest("ebitda")
    net_debt = _net_debt(data)
    ev = cap + net_debt if cap is not None and net_debt is not None else None

    out: dict[str, float | None] = {
        "market_cap": cap,
        "pe": div(cap, ni) if (ni or 0) > 0 else None,
        "pb": div(cap, equity) if (equity or 0) > 0 else None,
        "ps": div(cap, rev),
        "ev_ebitda": div(ev, ebitda) if (ebitda or 0) > 0 else None,
        "fcf_yield": div(fcf, cap),
        "earnings_yield": div(ni, cap),
    }
    # PEG：用 3 年净利润 CAGR，增速为负时不计算
    growth = cagr([x for x in data.series("net_income") if x is not None], 3)
    out["peg"] = div(out["pe"], growth * 100) if out["pe"] and growth and growth > 0 else None
    return out


def _payout(data: FinancialData) -> float | None:
    dividends = data.latest("dividends_paid")
    ni = data.latest("net_income")
    if dividends is None or ni is None or ni <= 0:
        return None
    return abs(dividends) / ni


def _buyback_yield(data: FinancialData) -> float | None:
    buybacks = data.latest("buybacks")
    cap = _market_cap(data)
    if buybacks is None or cap is None:
        return None
    return abs(buybacks) / cap


def _share_change(data: FinancialData) -> float | None:
    """3 年股本变动率。负数 = 净回购（对股东有利），正数 = 稀释。"""
    shares = data.clean_series("shares_outstanding") or data.clean_series("diluted_shares")
    if len(shares) < 2:
        return None
    window = shares[:4]
    if window[-1] <= 0:
        return None
    return window[0] / window[-1] - 1


# ---------------------------------------------------------------------------
# 方法论 Part1 指标
#
# 对应 PDF 的七个步骤。这些指标的共同点是：单看一期没意义，必须看"差值"——
# 现金与利润的差、GAAP 与 Non-GAAP 的差、应收与收入增速的差、资本开支与折旧的差。
# ---------------------------------------------------------------------------


def _methodology_metrics(data: FinancialData, fcf_hist: list[float | None]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    rev = data.series("revenue")
    revenue = data.latest("revenue")
    fcf = fcf_hist[0] if fcf_hist else None
    sbc = data.latest("stock_comp")
    ocf = data.latest("operating_cash_flow")
    capex = data.latest("capex")
    dep = data.latest("depreciation")
    cap = _market_cap(data)

    # -- 第 1 步：把利润和现金分开 -----------------------------------------
    out["fcf"] = fcf
    out["capex_to_ocf"] = div(abs(capex) if capex is not None else None, ocf)
    out["ocf_to_operating_income"] = div(ocf, data.latest("operating_income"))
    # 折旧加回后的利润 -> 现金桥：D&A 占经营现金流的比重越高，利润的"含现金量"越依赖折旧
    out["depreciation_to_ocf"] = div(dep, ocf)
    capital_return = _capital_return(data)
    out["capital_return"] = capital_return
    out["shareholder_yield"] = div(capital_return, cap)
    # 股东回报 / 自由现金流：> 1 说明回购分红是借钱或动用存量现金撑起来的
    out["capital_return_to_fcf"] = div(capital_return, fcf) if (fcf or 0) > 0 else None

    # -- 第 2 步：GAAP vs Non-GAAP，重点看股权激励 --------------------------
    out["sbc_intensity"] = div(sbc, revenue)
    out["sbc_to_ocf"] = div(sbc, ocf)
    out["sbc_to_net_income"] = div(sbc, data.latest("net_income"))
    fcf_ex_sbc = fcf - sbc if fcf is not None and sbc is not None else None
    out["fcf_ex_sbc"] = fcf_ex_sbc
    out["fcf_ex_sbc_margin"] = div(fcf_ex_sbc, revenue)
    out["fcf_ex_sbc_yield"] = div(fcf_ex_sbc, cap)
    # 扣掉 SBC 后自由现金流被削掉多少：这就是 Non-GAAP 叙事和现实的差距
    out["fcf_sbc_haircut"] = div(sbc, fcf) if (fcf or 0) > 0 else None

    # -- 第 3 步：毛利率变动拆解 -------------------------------------------
    out.update(_margin_bridge(data))

    # -- 第 4 步：营运资本 = 被锁在生意里的现金 ------------------------------
    # 各组件单独输出，解读层据此说明实际用的公式，避免"净营运资本"这个标签说谎
    out["nwc_receivables"] = data.latest("receivables")
    out["nwc_payables"] = data.latest("accounts_payable")
    out["nwc_inventory"] = data.latest("inventory")
    out["nwc_deferred_revenue"] = data.latest("deferred_revenue")
    out["inventory_to_revenue"] = div(data.latest("inventory"), revenue)

    # SaaS 口径：把递延收入计进营运资本，健康的订阅生意应为负（客户垫资）
    nwc_incl = _nwc(data, 0, include_deferred=True)
    out["nwc_incl_deferred"] = nwc_incl
    out["nwc_incl_deferred_to_sales"] = div(nwc_incl, revenue)
    prior_incl = div(_nwc(data, 1, include_deferred=True), data.latest("revenue", 1))
    out["nwc_incl_deferred_to_sales_change"] = (
        out["nwc_incl_deferred_to_sales"] - prior_incl
        if out["nwc_incl_deferred_to_sales"] is not None and prior_incl is not None else None)

    nwc = _nwc(data, 0)
    out["nwc"] = nwc
    out["nwc_to_sales"] = div(nwc, revenue)
    prior_nwc_ratio = div(_nwc(data, 1), data.latest("revenue", 1))
    current_nwc_ratio = out["nwc_to_sales"]
    out["nwc_to_sales_change"] = (
        current_nwc_ratio - prior_nwc_ratio
        if current_nwc_ratio is not None and prior_nwc_ratio is not None else None
    )
    out["ar_days"] = _days(avg(data.latest("receivables"), data.latest("receivables", 1)), revenue)
    out["inventory_days"] = _days(avg(data.latest("inventory"), data.latest("inventory", 1)),
                                  data.latest("cost_of_revenue"))
    out["payable_days"] = _days(avg(data.latest("accounts_payable"),
                                    data.latest("accounts_payable", 1)),
                                data.latest("cost_of_revenue"))
    if all(out.get(k) is not None for k in ("ar_days", "inventory_days", "payable_days")):
        out["cash_conversion_cycle"] = out["ar_days"] + out["inventory_days"] - out["payable_days"]
    else:
        out["cash_conversion_cycle"] = None

    # -- 第 5 步：应收/存货增速 vs 收入增速，当作造假探测器 -------------------
    revenue_growth = yoy(rev)
    ar_growth = yoy(data.series("receivables"))
    inv_growth = yoy(data.series("inventory"))
    out["ar_growth"] = ar_growth
    out["inventory_growth"] = inv_growth
    # 差值为正 = 应收/存货跑在收入前面，是压货或收入确认激进的典型信号
    out["ar_vs_revenue_gap"] = (
        ar_growth - revenue_growth if ar_growth is not None and revenue_growth is not None else None)
    out["inventory_vs_revenue_gap"] = (
        inv_growth - revenue_growth if inv_growth is not None and revenue_growth is not None else None)

    # -- 第 6 步：资本开支 -> 折旧的时间差 ----------------------------------
    phys_dep = _physical_depreciation(data, 0)
    out["physical_depreciation"] = phys_dep
    out["amortization_share_of_da"] = div(data.latest("amortization_intangibles"), dep)
    out["capex_to_depreciation"] = div(abs(capex) if capex is not None else None, phys_dep)
    # 今年多花的钱迟早要变成折旧，先估算它对未来营业利润率的压制幅度
    out["future_depreciation_drag"] = (
        div(abs(capex) - phys_dep, revenue)
        if capex is not None and phys_dep is not None else None)
    life = _implied_useful_life(data, 0)
    prior_life = _implied_useful_life(data, 1)
    out["implied_useful_life"] = life
    change = life - prior_life if life is not None and prior_life is not None else None
    out["useful_life_change"] = change

    # 隐含年限 = PPE 原值 / 折旧。资产基数快速扩张时，新增资产当年只计提部分折旧，
    # 分子涨得比分母快，年限会**机械性拉长** —— 这和"管理层修改折旧政策"是两回事。
    # 从财报摘要分不开这两者（要看 10-K 的 PP&E 附注），所以扩张期直接置空该判据，
    # 让第 6 步的这条规则缺失，而不是给出一个会指控管理层的假信号。
    ppe_growth = yoy(data.series("gross_ppe"))
    out["gross_ppe_growth"] = ppe_growth
    out["useful_life_extension"] = (
        change if change is not None and ppe_growth is not None
        and ppe_growth <= PPE_EXPANSION_CLEAN else None)

    # -- 第 7 步：估值反证 --------------------------------------------------
    out["forward_pe"] = data.market.get("forward_pe")
    deferred_growth = yoy(data.series("deferred_revenue"))
    out["deferred_revenue_growth"] = deferred_growth
    out["deferred_revenue_to_revenue"] = div(data.latest("deferred_revenue"), revenue)

    # -- SaaS 专用：替代第 5 步失去的"存货那一半" ----------------------------
    # 订阅生意没有存货可压，但有等价症状：递延收入增速跑输收入增速，说明未来
    # 收入池在枯竭 —— 当期收入靠消耗已签合同撑着，而新签没有补上。
    out["deferred_vs_revenue_gap"] = (
        deferred_growth - revenue_growth
        if deferred_growth is not None and revenue_growth is not None else None)
    # 经营现金流里有多少来自客户预付的增量，而非当期利润。增长减速时这块会先消失。
    deferred_delta = (
        data.latest("deferred_revenue") - data.latest("deferred_revenue", 1)
        if data.latest("deferred_revenue") is not None
        and data.latest("deferred_revenue", 1) is not None else None)
    out["ocf_from_deferred_share"] = div(deferred_delta, ocf)
    return out


def _capital_return(data: FinancialData) -> float | None:
    """回购 + 分红的总额（现金流量表里是负数，这里取绝对值）。"""
    parts = [data.latest("buybacks"), data.latest("dividends_paid")]
    present = [abs(x) for x in parts if x is not None]
    return sum(present) if present else None


def _nwc(data: FinancialData, offset: int, include_deferred: bool = False) -> float | None:
    """净营运资本 = 存货 + 应收 - 应付（- 递延收入）。

    include_deferred 是 SaaS 口径的关键：客户年度预付形成的递延收入是**客户给公司
    垫的钱**，必须减掉。不减的话 ServiceNow 会被算成"占用 18.2% 营收的资金"，
    而真实情况是客户净垫资 44% —— 符号是反的，不只是数值不准。

    应收缺失则返回 None（它是唯一不可或缺的组件）；存货与应付缺失按 0 计，
    各组件同时作为独立指标输出，让解读层能说清实际用的是哪个公式。
    """
    ar = data.latest("receivables", offset)
    if ar is None:
        return None
    inv = data.latest("inventory", offset)
    ap = data.latest("accounts_payable", offset)
    nwc = (inv or 0) + ar - (ap or 0)
    if include_deferred:
        nwc -= data.latest("deferred_revenue", offset) or 0
    return nwc


def _nwc_to_sales_series(data: FinancialData) -> list[float | None]:
    return [div(_nwc(data, i), data.latest("revenue", i)) for i in range(data.n_periods)]


def _fcf_ex_sbc_series(data: FinancialData, fcf_hist: list[float | None]) -> list[float | None]:
    sbc = data.series("stock_comp")
    out: list[float | None] = []
    for i in range(data.n_periods):
        f = fcf_hist[i] if i < len(fcf_hist) else None
        s = sbc[i] if i < len(sbc) else None
        out.append(f - s if f is not None and s is not None else None)
    return out


def _days(balance: float | None, flow: float | None) -> float | None:
    """周转天数 = 平均余额 / 年流量 × 365。"""
    ratio = div(balance, flow)
    return ratio * 365 if ratio is not None else None


def _margin_bridge(data: FinancialData) -> dict[str, float | None]:
    """毛利变动拆解。

    报表本身没有量价数据，能严格拆出来的是两层：
      规模效应 = 营收增量 × 上期毛利率        （量增带来的毛利，对应"volume growth"）
      价格/结构效应 = 本期营收 × 毛利率变动    （价格与产品组合，对应"price + mix"）
    两者之和恰好等于毛利增量。要再把价格和结构分开，必须有出货量数据，属于财报之外。
    """
    out: dict[str, float | None] = {}
    rev, rev_prev = data.latest("revenue"), data.latest("revenue", 1)
    gp, gp_prev = data.latest("gross_profit"), data.latest("gross_profit", 1)
    gm, gm_prev = div(gp, rev), div(gp_prev, rev_prev)

    out["gross_margin_change"] = gm - gm_prev if gm is not None and gm_prev is not None else None
    op_m = div(data.latest("operating_income"), rev)
    op_m_prev = div(data.latest("operating_income", 1), rev_prev)
    out["operating_margin_change"] = (
        op_m - op_m_prev if op_m is not None and op_m_prev is not None else None)

    if None not in (rev, rev_prev, gm, gm_prev) and gp is not None and gp_prev is not None:
        volume_effect = (rev - rev_prev) * gm_prev
        price_mix_effect = rev * (gm - gm_prev)
        delta = gp - gp_prev
        out["gm_volume_effect"] = volume_effect
        out["gm_price_mix_effect"] = price_mix_effect
        # 毛利增量里由"价格/结构"贡献的比例：接近 0 说明纯靠卖得更多，护城河存疑
        out["gm_price_mix_share"] = div(price_mix_effect, delta) if delta else None
    else:
        out["gm_volume_effect"] = out["gm_price_mix_effect"] = out["gm_price_mix_share"] = None

    # 经营杠杆：营业利润增速 / 营收增速，> 1 说明收入增长被放大成了利润
    rev_growth = yoy(data.series("revenue"))
    op_growth = yoy(data.series("operating_income"))
    out["operating_leverage"] = (
        div(op_growth, rev_growth) if rev_growth and rev_growth > 0 and op_growth is not None else None)
    opex_growth = yoy(data.series("operating_expense"))
    out["opex_growth_gap"] = (
        opex_growth - rev_growth
        if opex_growth is not None and rev_growth is not None else None)
    return out


def _physical_depreciation(data: FinancialData, offset: int) -> float | None:
    """物理资产折旧。

    优先取单列的 Depreciation；没有就用 D&A 减去无形资产摊销；两者都没有才退回
    D&A 并接受失真。并购型公司（AVGO 的 D&A 中 93% 是收购无形资产摊销）如果不做
    这一步，第 6 步会给出完全相反的结论。
    """
    only = data.latest("depreciation_only", offset)
    if only is not None and only > 0:
        return only
    da = data.latest("depreciation", offset)
    amort = data.latest("amortization_intangibles", offset)
    if da is not None and amort is not None and da > amort > 0:
        return da - amort
    return da


def _implied_useful_life(data: FinancialData, offset: int) -> float | None:
    """隐含折旧年限 = 固定资产原值 / 当期物理折旧。年限被拉长会让当期利润变好看。

    落在 [2, 50] 年之外的结果一律判为口径不可靠而非真实信号 —— 与其给一个
    0.8 年这种显然错误的数去参与打分，不如让该项缺失。
    """
    gross = data.latest("gross_ppe", offset)
    dep = _physical_depreciation(data, offset)
    if gross is None or not dep:
        return None
    life = gross / dep
    return life if 2 <= life <= 50 else None
