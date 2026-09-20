"""《方法论 Part1》七步财报阅读法的评估引擎。

七步是有序且有因果的：前一步的结论通过 context 改变后一步的权重和解读
（现金不实 -> 估值打折；SBC 重大 -> 估值改用扣除 SBC 的口径）。

每条规则给两个阈值：``fail_at`` 得 0 分，``pass_at`` 得满分，中间线性插值；
``pass_at < fail_at`` 自动表示越小越好。缺失的指标不计入分母，只记进 skipped，
同时按**规则级**报告覆盖率 —— 数据不全不会被无端压分，但分数有多可信是透明的。

行业口径（:class:`Profile`）：七步的**问题**与商业模式无关，坏掉的只是载体。
硬件把现金锁在存货里，订阅生意相反 —— 客户年度预付在给公司垫资。不适用的
规则**不能删**（删掉就是"缺数据 = 高分"），必须换成等价问法。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable

from .metrics import Metrics


# 红旗判断用的比较符
_OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


class RuleError(ValueError):
    """规则文件写错时抛出。"""


@dataclass
class Rule:
    metric: str
    label: str
    weight: float = 1.0
    pass_at: float = 0.0
    fail_at: float = 0.0
    category: str = "其他"
    unit: str = "ratio"        # ratio(小数) | percent | times | number
    note: str = ""

    def score(self, value: float) -> float:
        """线性插值到 [0, 1]。"""
        span = self.pass_at - self.fail_at
        if span == 0:
            raise RuleError(f"规则 {self.metric} 的 pass_at 与 fail_at 不能相同")
        return max(0.0, min(1.0, (value - self.fail_at) / span))


@dataclass
class RedFlag:
    metric: str
    op: str
    value: float
    message: str
    penalty: float = 0.0       # 直接从总分里扣的分数

    def triggered(self, actual: float) -> bool:
        if self.op not in _OPS:
            raise RuleError(f"红旗 {self.metric} 使用了未知比较符 {self.op}")
        return _OPS[self.op](actual, self.value)




@dataclass
class RuleScore:
    """单条规则的打分明细。"""

    metric: str
    label: str
    category: str
    unit: str
    value: float
    score: float               # 0-1
    weight: float
    pass_at: float
    fail_at: float
    note: str = ""

    @property
    def weighted(self) -> float:
        return self.score * self.weight




# ---------------------------------------------------------------------------
# 规则加载
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------


def score_rules(metrics: Metrics, rules: list[Rule]) -> tuple[list[RuleScore], list[str], float, float]:
    """对一组规则打分，返回 (明细, 缺数据的规则, 已打分权重, 加权得分)。"""
    details: list[RuleScore] = []
    skipped: list[str] = []
    scored_weight = 0.0
    earned = 0.0
    for rule in rules:
        value = metrics.get(rule.metric)
        if value is None:
            skipped.append(f"{rule.label}（{rule.metric}）")
            continue
        detail = RuleScore(
            metric=rule.metric, label=rule.label, category=rule.category, unit=rule.unit,
            value=value, score=rule.score(value), weight=rule.weight,
            pass_at=rule.pass_at, fail_at=rule.fail_at, note=rule.note,
        )
        details.append(detail)
        scored_weight += rule.weight
        earned += detail.weighted
    return details, skipped, scored_weight, earned


def check_flags(metrics: Metrics, flags: list[RedFlag]) -> tuple[list[str], float]:
    """返回 (触发的红旗文案, 合计扣分)。"""
    hit: list[str] = []
    penalty = 0.0
    for flag in flags:
        value = metrics.get(flag.metric)
        if value is not None and flag.triggered(value):
            hit.append(flag.message)
            penalty += flag.penalty
    return hit, penalty






# ===========================================================================
# 方法论引擎（《方法论 Part1》的七步阅读顺序）
#
# 和上面的通用规则集不同，这里的七个步骤是 **有序且有因果** 的：
#   第 1 步的结论会改变第 7 步怎么读（现金不实 -> 估值指标不可信）
#   第 2 步的结论会改变用哪个收益率做估值（SBC 重大 -> 用扣除 SBC 的口径）
# 所以用带上下文传递的分步引擎，而不是再写一个扁平的 JSON 规则集。
# ===========================================================================


@dataclass
class Stage:
    """方法论中的一步。"""

    key: str
    order: int
    title: str
    question: str                                   # 这一步到底在问什么
    weight: float
    rules: list[Rule]
    red_flags: list[RedFlag] = field(default_factory=list)
    gate: str = ""                                  # 非空表示这是关口，不过会影响后续解读
    gate_threshold: float = 50.0
    interpret: Callable[[dict, dict], list[str]] | None = None   # (指标值, 上下文) -> 结论
    adapt: Callable[[list[Rule], dict, dict], list[Rule]] | None = None  # 按上下文调整权重


@dataclass
class StageResult:
    key: str
    order: int
    title: str
    question: str
    weight: float
    score: float = 0.0
    coverage: float = 0.0
    details: list[RuleScore] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.order,
            "key": self.key,
            "title": self.title,
            "question": self.question,
            "score": round(self.score, 1),
            "coverage": round(self.coverage, 3),
            "findings": self.findings,
            "flags": self.flags,
            "skipped": self.skipped,
            "details": [
                {"metric": d.metric, "label": d.label, "value": d.value, "unit": d.unit,
                 "score": round(d.score, 3), "weight": d.weight,
                 "pass_at": d.pass_at, "fail_at": d.fail_at}
                for d in self.details
            ],
        }


@dataclass
class MethodologyReport:
    ticker: str
    name: str
    profile: str = "hardware"
    profile_label: str = ""
    score: float = 0.0
    raw_score: float = 0.0
    grade: str = "-"
    verdict: str = ""
    coverage: float = 0.0            # 规则级加权覆盖率
    stage_coverage: float = 0.0      # 有数据的步骤占比
    stages: list[StageResult] = field(default_factory=list)
    gate_warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def flags(self) -> list[str]:
        return [f for st in self.stages for f in st.flags]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "framework": "方法论 Part1",
            "profile": self.profile,
            "profile_label": self.profile_label,
            "score": round(self.score, 1),
            "raw_score": round(self.raw_score, 1),
            "grade": self.grade,
            "verdict": self.verdict,
            "coverage": round(self.coverage, 3),
            "stage_coverage": round(self.stage_coverage, 3),
            "gate_warnings": self.gate_warnings,
            "flags": self.flags,
            "notes": self.notes,
            "stages": [st.to_dict() for st in self.stages],
        }


# ---------------------------------------------------------------------------
# 各步的结论生成：把数字翻译成方法论里那句话，并把结论写进 context 供后续步骤使用
# ---------------------------------------------------------------------------


def _pct(v: float | None, digits: int = 1) -> str:
    return "N/A" if v is None else f"{v * 100:.{digits}f}%"


def _x(v: float | None) -> str:
    return "N/A" if v is None else f"{v:.2f}x"


def _money(v: float | None) -> str:
    """金额按十亿/百万缩放，报表原值直接打印没法读。"""
    if v is None:
        return "N/A"
    for scale, suffix in ((1e12, "万亿"), (1e9, "十亿"), (1e6, "百万")):
        if abs(v) >= scale:
            return f"{v / scale:+,.1f}{suffix}"
    return f"{v:+,.0f}"


def _read_cash(v: dict, ctx: dict) -> list[str]:
    """第 1 步：营业利润 ≠ 经营现金流，只认 FCF = OCF - Capex。"""
    out = []
    fcf_margin, conv = v.get("fcf_margin"), v.get("cash_conversion")
    if fcf_margin is not None:
        out.append(f"自由现金流利润率 {_pct(fcf_margin)}（经营现金流扣掉资本开支后的真实剩余）")
    if conv is not None:
        verdict = "利润基本落袋" if conv >= 1 else "利润没有完全转化成现金"
        out.append(f"经营现金流/净利润 {_x(conv)} —— {verdict}")
    if v.get("depreciation_to_ocf") is not None:
        out.append(f"折旧摊销贡献了经营现金流的 {_pct(v['depreciation_to_ocf'])}，"
                   f"这部分是账面加回而非经营改善")
    capex_ocf = v.get("capex_to_ocf")
    if capex_ocf is not None:
        heavy = capex_ocf >= 0.5
        out.append(f"资本开支占用 {_pct(capex_ocf)} 的经营现金流"
                   + ("，属于重资产模式，现金被持续吃掉" if heavy else "，生意不算吃钱"))
        ctx["capex_heavy"] = heavy
    if v.get("shareholder_yield") is not None:
        line = f"回购+分红对市值的回报率 {_pct(v['shareholder_yield'])}"
        if v.get("capital_return_to_fcf") is not None:
            line += f"，相当于自由现金流的 {_pct(v['capital_return_to_fcf'], 0)}"
            if v["capital_return_to_fcf"] > 1:
                line += "（超出当期产生的现金，靠存量或举债支撑）"
        out.append(line)
    share = v.get("ocf_from_deferred_share")
    if share is not None and abs(share) > 0.05:
        out.append(f"经营现金流里有 {_pct(share, 0)} 来自客户预付款的增量，"
                   f"不是当期利润 —— 增长减速时这块会先消失")
    ctx["fcf_positive"] = (fcf_margin or 0) > 0
    return out


def _read_sbc(v: dict, ctx: dict) -> list[str]:
    """第 2 步：GAAP vs Non-GAAP，焦点是股权激励。"""
    out = []
    sbc_int, haircut = v.get("sbc_intensity"), v.get("fcf_sbc_haircut")
    material = (sbc_int or 0) >= 0.05 or (haircut or 0) >= 0.25
    ctx["sbc_material"] = material
    if sbc_int is not None:
        out.append(f"股权激励占营收 {_pct(sbc_int)}"
                   + ("，规模重大，Non-GAAP 利润率要打折看" if material else "，规模可控"))
    if haircut is not None:
        out.append(f"扣掉 SBC 后自由现金流缩水 {_pct(haircut, 0)}，"
                   f"扣除后的 FCF 利润率为 {_pct(v.get('fcf_ex_sbc_margin'))}")
    if v.get("sbc_to_net_income") is not None:
        out.append(f"SBC 相当于净利润的 {_pct(v['sbc_to_net_income'], 0)}")
    if v.get("share_count_change_3y") is not None:
        change = v["share_count_change_3y"]
        out.append(f"3 年股本{'扩张' if change > 0 else '收缩'} {_pct(abs(change))}，"
                   + ("稀释在实际发生" if change > 0 else "回购覆盖了激励带来的稀释"))
    if material:
        out.append("→ 以 GAAP 口径为准；管理层的 Non-GAAP 调整把一项真实成本挪出了损益表")
    return out


def _read_margin(v: dict, ctx: dict) -> list[str]:
    """第 3 步：毛利率变动拆成量、价/结构两层。"""
    out = []
    change = v.get("gross_margin_change")
    if change is not None:
        out.append(f"毛利率同比变动 {change * 100:+.1f}pp"
                   + ("（改善）" if change > 0 else "（恶化）" if change < 0 else ""))
    share = v.get("gm_price_mix_share")
    if share is not None:
        vol = v.get("gm_volume_effect")
        mix = v.get("gm_price_mix_effect")
        out.append(f"毛利增量拆解：规模效应 {_money(vol)}，价格/产品结构效应 {_money(mix)}，"
                   f"后者占 {_pct(share, 0)}")
        out.append("（财报只能拆到这两层；把价格与产品组合再分开需要出货量数据）")
        ctx["growth_is_volume_only"] = share < 0.1
    lev = v.get("operating_leverage")
    if lev is not None:
        out.append(f"经营杠杆 {_x(lev)}"
                   + ("，收入增长被放大成了利润" if lev > 1 else "，费用增长吞掉了收入增长"))
    gap = v.get("opex_growth_gap")
    if gap is not None:
        out.append(f"营业费用增速比收入增速{'快' if gap > 0 else '慢'} {abs(gap) * 100:.1f}pp"
                   + ("，规模效应正在兑现" if gap < 0 else "，费用在侵蚀增长"))
    return out


def _read_working_capital(v: dict, ctx: dict) -> list[str]:
    """第 4 步：营运资本 = 被锁死在生意里的现金。"""
    out = []
    ratio = v.get("nwc_to_sales")
    if ratio is not None:
        out.append(f"净营运资本/营收 {_pct(ratio)}（每 1 元收入需要占用的资金）"
                   + ("，低于 20% 的健康线" if ratio < 0.20 else "，高于 20% 的健康线"))
    trend = v.get("nwc_to_sales_change")
    if trend is not None:
        out.append(f"该比率同比 {trend * 100:+.1f}pp"
                   + ("，效率在改善" if trend < 0 else "，占用在上升"))
    if v.get("ar_days") is not None:
        days = v["ar_days"]
        out.append(f"应收账款周转 {days:.0f} 天"
                   + ("，客户付款快，议价能力强" if days <= 45 else "，回款偏慢"))
    if v.get("inventory_days") is not None:
        out.append(f"存货周转 {v['inventory_days']:.0f} 天，现金循环周期 "
                   f"{v['cash_conversion_cycle']:.0f} 天"
                   if v.get("cash_conversion_cycle") is not None
                   else f"存货周转 {v['inventory_days']:.0f} 天")
    return out


def _read_working_capital_saas(v: dict, ctx: dict) -> list[str]:
    """第 4 步（订阅口径）：占用谁的钱。

    硬件问"现金被锁进存货和应收多少"，订阅生意的答案通常是反的 —— 客户年度预付
    在给公司垫资。不把递延收入算进来，符号会整个搞错。
    """
    out = []
    ratio = v.get("nwc_incl_deferred_to_sales")
    if ratio is not None:
        if ratio < 0:
            out.append(f"营运资本（含递延收入）/营收 {_pct(ratio)} —— 为负，"
                       f"客户预付在给公司垫资，这门生意不占用自有资金")
        else:
            out.append(f"营运资本（含递延收入）/营收 {_pct(ratio)} —— 为正，"
                       f"订阅生意里不寻常：预收规模不足以覆盖应收")
        bare = v.get("nwc_to_sales")
        if bare is not None:
            out.append(f"（不计递延收入时为 {_pct(bare)}，硬件口径会把符号算反）")
    trend = v.get("nwc_incl_deferred_to_sales_change")
    if trend is not None:
        out.append(f"该比率同比 {trend * 100:+.1f}pp"
                   + ("，客户垫资的比重在上升" if trend < 0 else "，垫资优势在减弱"))
    if v.get("ar_days") is not None:
        days = v["ar_days"]
        out.append(f"应收周转 {days:.0f} 天"
                   + ("，企业级年度开票下属常态区间" if days <= 80
                      else "，高于企业级 SaaS 的常态区间，需看是否放宽了账期换单"))
    pool = v.get("deferred_revenue_to_revenue")
    if pool is not None:
        out.append(f"递延收入相当于营收的 {_pct(pool, 0)}，这是已收钱但未确认的收入池")
    return out


def _read_red_flags_saas(v: dict, ctx: dict) -> list[str]:
    """第 5 步（订阅口径）：没有存货可压，但有等价症状 —— 收入池枯竭。"""
    out = []
    ar_gap = v.get("ar_vs_revenue_gap")
    if ar_gap is not None:
        out.append(f"应收增速比收入增速{'快' if ar_gap > 0 else '慢'} {abs(ar_gap) * 100:.1f}pp"
                   + ("，警惕收入确认激进或多年合同前置" if ar_gap > 0.10 else "，节奏一致"))
    gap = v.get("deferred_vs_revenue_gap")
    if gap is not None:
        if gap < -0.05:
            out.append(f"递延收入增速比收入慢 {abs(gap) * 100:.1f}pp —— "
                       f"未来收入池在枯竭：当期收入靠消耗已签合同撑着，新签没补上")
        else:
            out.append(f"递延收入增速比收入{'快' if gap > 0 else '慢'} {abs(gap) * 100:.1f}pp，"
                       f"收入池与当期收入同步扩张")
    if v.get("accrual_ratio") is not None:
        out.append(f"应计比例 {_pct(v['accrual_ratio'])}"
                   + ("（为负，现金流强于账面利润）" if v["accrual_ratio"] < 0 else ""))
    return out


def _read_red_flags(v: dict, ctx: dict) -> list[str]:
    """第 5 步：应收/存货增速跑赢收入，是造假与压货的探测器。"""
    out = []
    ar_gap, inv_gap = v.get("ar_vs_revenue_gap"), v.get("inventory_vs_revenue_gap")
    if ar_gap is not None:
        out.append(f"应收增速比收入增速{'快' if ar_gap > 0 else '慢'} {abs(ar_gap) * 100:.1f}pp"
                   + ("，警惕渠道压货或收入确认激进" if ar_gap > 0.10 else "，节奏一致"))
    if inv_gap is not None:
        out.append(f"存货增速比收入增速{'快' if inv_gap > 0 else '慢'} {abs(inv_gap) * 100:.1f}pp"
                   + ("，可能是真实需求弱于报表或过度生产" if inv_gap > 0.15 else "，节奏一致"))
    if ar_gap is not None and inv_gap is not None and ar_gap > 0.10 and inv_gap > 0.15:
        out.append("→ 应收与存货同时跑在收入前面，这是最需要回查原始年报的组合")
    return out


def _read_capex_timing(v: dict, ctx: dict) -> list[str]:
    """第 6 步：资本开支和折旧的时间差，会在未来几个季度兑现成利润率压力。"""
    out = []
    ratio = v.get("capex_to_depreciation")
    if ratio is not None:
        out.append(f"资本开支 / 当期折旧 = {_x(ratio)}"
                   + ("，今天花的钱远超今天摊的折旧" if ratio > 2 else "，接近稳态"))
    drag = v.get("future_depreciation_drag")
    if drag is not None and drag > 0:
        out.append(f"两者差额相当于营收的 {_pct(drag)}，"
                   f"这是未来折旧开始计提后对营业利润率的潜在压制幅度")
        if ctx.get("operating_margin_now") is not None:
            out.append(f"（当前营业利润率 {_pct(ctx['operating_margin_now'])}，"
                       f"需要问的是：折旧兑现后还守得住吗）")
    amort_share = v.get("amortization_share_of_da")
    if amort_share is not None and amort_share > 0.3:
        out.append(f"D&A 中 {_pct(amort_share, 0)} 是收购无形资产摊销，"
                   f"已剔除后用物理折旧 {_money(v.get('physical_depreciation'))} 计算 —— "
                   f"并购型公司不做这步会得出相反结论")
    life, change = v.get("implied_useful_life"), v.get("useful_life_change")
    if life is not None:
        line = f"隐含折旧年限约 {life:.1f} 年"
        if change is not None and change > 0.5:
            ppe_growth = v.get("gross_ppe_growth")
            if v.get("useful_life_extension") is not None:
                line += (f"，同比拉长 {change:.1f} 年，而固定资产原值仅增 "
                         f"{_pct(ppe_growth, 0)} —— 基数基本持平却延长年限，指向会计选择")
            elif ppe_growth is not None and ppe_growth > 0.15:
                line += (f"，同比拉长 {change:.1f} 年，但固定资产原值同比 {_pct(ppe_growth, 0)}"
                         f" —— 扩张期新增资产当年只计提部分折旧，年限机械性拉长，不构成会计信号")
            else:
                line += (f"，同比拉长 {change:.1f} 年，固定资产原值同比 {_pct(ppe_growth, 0)}"
                         f" —— 处于模糊地带：机械效应与政策变更都可能，"
                         f"财报摘要分不开，需查 10-K 的 PP&E 附注确认")
        out.append(line)
    return out


def _read_valuation(v: dict, ctx: dict) -> list[str]:
    """第 7 步：报表再好，也要问市场是不是已经把好消息定价进去了。"""
    out = []
    if ctx.get("sbc_material"):
        out.append(f"SBC 重大，估值以扣除 SBC 的口径为准："
                   f"FCF 收益率 {_pct(v.get('fcf_ex_sbc_yield'))}"
                   f"（未扣除时为 {_pct(v.get('fcf_yield'))}）")
    elif v.get("fcf_yield") is not None:
        out.append(f"自由现金流收益率 {_pct(v['fcf_yield'])}")
    fpe, pe = v.get("forward_pe"), v.get("pe")
    if fpe is not None and pe is not None:
        out.append(f"动态市盈率 {fpe:.1f}x vs 静态 {pe:.1f}x"
                   + ("，市场已经把未来的增长提前计入" if fpe < pe else "，市场预期盈利下滑"))
    elif pe is not None:
        out.append(f"静态市盈率 {pe:.1f}x")
    if v.get("deferred_revenue_growth") is not None:
        g = v["deferred_revenue_growth"]
        out.append(f"预收款同比 {g * 100:+.1f}%"
                   + ("，客户提前付钱，需求强度有支撑" if g > 0 else "，预付强度转弱"))
    if ctx.get("growth_is_volume_only"):
        out.append("→ 毛利增长几乎全靠走量，一旦价格见顶（商品化/天花板），估值溢价缺乏支撑")
    if not ctx.get("fcf_positive", True):
        out.append("→ 现金端未过关，任何基于利润的估值倍数都要打折看")
    return out


def _boost_ex_sbc_valuation(rules: list[Rule], v: dict, ctx: dict) -> list[Rule]:
    """SBC 重大时，把估值权重从 GAAP 前的 FCF 收益率挪到扣除 SBC 的口径上。"""
    if not ctx.get("sbc_material"):
        return rules
    out = []
    for r in rules:
        if r.metric == "fcf_yield":
            out.append(replace(r, weight=0.5, note="SBC 重大，权重下调"))
        elif r.metric == "fcf_ex_sbc_yield":
            out.append(replace(r, weight=r.weight + 2, note="SBC 重大，以此口径为准"))
        else:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# 七个步骤的定义
# ---------------------------------------------------------------------------

METHODOLOGY: list[Stage] = [
    Stage(
        key="cash", order=1, weight=4.0,
        title="把利润和现金分开",
        question="营业利润 ≠ 经营现金流。扣掉资本开支后，这门生意到底剩下多少现金？",
        gate="现金端不过关时，后面的毛利率与估值结论都要打折",
        rules=[
            Rule("fcf_margin", "自由现金流利润率", 3, 0.20, 0.0, "现金实质", "percent"),
            Rule("cash_conversion", "经营现金流/净利润", 3, 1.20, 0.70, "现金实质", "times"),
            Rule("capex_to_ocf", "资本开支占经营现金流", 3, 0.15, 0.60, "现金实质", "percent",
                 "Buffett lens：重资产会吃掉本可自由支配的现金"),
            Rule("capex_intensity", "资本开支/营收", 2, 0.05, 0.20, "现金实质", "percent"),
            Rule("positive_fcf_years_ratio", "自由现金流为正的年份占比", 2, 1.0, 0.5,
                 "现金实质", "percent"),
            Rule("shareholder_yield", "回购+分红回报率", 2, 0.05, 0.0, "资本回报", "percent"),
            Rule("capital_return_to_fcf", "股东回报占自由现金流", 1, 0.70, 1.50,
                 "资本回报", "percent", "超过 100% 说明回报不是当期现金支撑的"),
        ],
        red_flags=[
            RedFlag("fcf_margin", "<", 0.0, "自由现金流为负：这门生意当期在净消耗现金", 15),
            RedFlag("capex_to_ocf", ">", 0.80, "资本开支吃掉八成以上经营现金流，重资产拖累明显", 8),
            RedFlag("capital_return_to_fcf", ">", 1.50, "回购分红远超自由现金流，靠存量现金或举债维持", 5),
        ],
        interpret=_read_cash,
    ),
    Stage(
        key="sbc", order=2, weight=3.0,
        title="还原 GAAP 与 Non-GAAP",
        question="管理层加回的股权激励是真成本吗？扣掉它还剩多少现金？",
        gate="SBC 重大时，第 7 步的估值改用扣除 SBC 的口径",
        rules=[
            Rule("sbc_intensity", "股权激励/营收", 3, 0.02, 0.12, "口径还原", "percent",
                 "ASC 718：无现金流出，但股份有真实公允价值并稀释股东"),
            Rule("fcf_sbc_haircut", "SBC 对自由现金流的侵蚀", 3, 0.10, 0.50, "口径还原", "percent"),
            Rule("fcf_ex_sbc_margin", "扣除 SBC 后的 FCF 利润率", 3, 0.15, 0.0, "口径还原", "percent"),
            Rule("share_count_change_3y", "3 年股本变动", 2, -0.05, 0.15, "口径还原", "percent"),
        ],
        red_flags=[
            RedFlag("sbc_intensity", ">", 0.10, "股权激励超过营收 10%，Non-GAAP 利润率严重失真", 8),
            RedFlag("fcf_sbc_haircut", ">", 0.50, "自由现金流有一半以上是靠加回 SBC 撑起来的", 8),
            RedFlag("share_count_change_3y", ">", 0.15, "3 年股本扩张超 15%，稀释在持续发生", 6),
        ],
        interpret=_read_sbc,
    ),
    Stage(
        key="margin", order=3, weight=3.0,
        title="拆解毛利率变动",
        question="毛利率的变化来自涨价、走量，还是产品结构？",
        rules=[
            Rule("gross_margin_change", "毛利率同比变动", 3, 0.02, -0.03, "毛利结构", "percent"),
            Rule("gm_price_mix_share", "价格/结构对毛利增量的贡献", 2, 0.35, 0.0, "毛利结构", "percent",
                 "接近 0 说明毛利增长纯靠走量，缺乏定价权"),
            Rule("operating_leverage", "经营杠杆", 3, 1.50, 0.80, "毛利结构", "times"),
            Rule("opex_growth_gap", "费用增速超出收入增速", 2, -0.02, 0.10, "毛利结构", "percent"),
            Rule("gross_margin_stability", "毛利率波动", 2, 0.01, 0.08, "毛利结构", "percent"),
        ],
        red_flags=[
            RedFlag("gross_margin_change", "<", -0.05, "毛利率同比下滑超 5pp，需查明是降价还是结构恶化", 8),
        ],
        interpret=_read_margin,
    ),
    Stage(
        key="working_capital", order=4, weight=3.0,
        title="营运资本 = 锁在生意里的现金",
        question="每做 1 元收入要占用多少资金？趋势在改善还是恶化？",
        rules=[
            Rule("nwc_to_sales", "净营运资本/营收", 3, 0.10, 0.30, "营运效率", "percent",
                 "（存货 + 应收 - 应付）/ 营收，低于 20% 视为健康"),
            Rule("nwc_to_sales_change", "该比率同比变动", 2, -0.02, 0.03, "营运效率", "percent"),
            Rule("ar_days", "应收周转天数", 3, 35.0, 75.0, "营运效率", "number",
                 "30-40 天说明对客户有议价能力"),
            Rule("inventory_days", "存货周转天数", 2, 45.0, 150.0, "营运效率", "number",
                 "结构性下降意味着走向 JIT 而非囤货"),
            Rule("cash_conversion_cycle", "现金循环周期", 2, 20.0, 120.0, "营运效率", "number"),
        ],
        red_flags=[
            RedFlag("nwc_to_sales", ">", 0.25, "营运资本占用超过营收 25%，大量现金被锁在生意里", 5),
        ],
        interpret=_read_working_capital,
    ),
    Stage(
        key="ar_inventory", order=5, weight=3.0,
        title="用应收/存货增速当造假探测器",
        question="应收和存货是不是跑在了收入前面？",
        rules=[
            Rule("ar_vs_revenue_gap", "应收增速 - 收入增速", 4, -0.02, 0.15, "质量红旗", "percent"),
            Rule("inventory_vs_revenue_gap", "存货增速 - 收入增速", 3, 0.0, 0.20, "质量红旗", "percent"),
            Rule("accrual_ratio", "应计比例", 2, 0.0, 0.10, "质量红旗", "percent"),
        ],
        red_flags=[
            RedFlag("ar_vs_revenue_gap", ">", 0.20, "应收增速比收入快 20pp 以上：警惕渠道压货或收入确认激进", 12),
            RedFlag("inventory_vs_revenue_gap", ">", 0.30, "存货增速比收入快 30pp 以上：真实需求可能弱于报表", 10),
        ],
        interpret=_read_red_flags,
    ),
    Stage(
        key="capex_timing", order=6, weight=2.0,
        title="压力测试资本开支与折旧的时间差",
        question="今天的资本开支明天变成折旧时，利润率还守得住吗？",
        rules=[
            Rule("capex_to_depreciation", "资本开支/折旧", 3, 1.20, 3.50, "折旧时间差", "times"),
            Rule("future_depreciation_drag", "未来折旧对利润率的压制", 3, 0.0, 0.15,
                 "折旧时间差", "percent"),
            Rule("useful_life_extension", "折旧年限变动（已排除扩张干扰）", 2, 0.0, 1.50,
                 "折旧时间差", "number",
                 "拉长服务器等资产的使用年限会美化当期利润；资产基数高速扩张时该判据不可用"),
        ],
        red_flags=[
            RedFlag("capex_to_depreciation", ">", 3.0, "资本开支是折旧的 3 倍以上，未来折旧将集中兑现", 8),
            RedFlag("useful_life_extension", ">", 1.0,
                    "折旧年限被拉长超过 1 年且资产基数未大幅扩张，当期利润含会计美化成分", 8),
        ],
        interpret=_read_capex_timing,
    ),
    Stage(
        key="valuation", order=7, weight=3.0,
        title="估值反证",
        question="报表质量没问题，但市场是不是已经把好消息全定价了？",
        rules=[
            Rule("fcf_ex_sbc_yield", "扣除 SBC 的 FCF 收益率", 3, 0.05, 0.01, "估值反证", "percent"),
            Rule("fcf_yield", "自由现金流收益率", 2, 0.06, 0.015, "估值反证", "percent"),
            Rule("forward_pe", "动态市盈率", 3, 18.0, 45.0, "估值反证", "times",
                 "已经反映未来增长的价格"),
            Rule("pe", "静态市盈率", 2, 18.0, 45.0, "估值反证", "times"),
            Rule("ev_ebitda", "EV/EBITDA", 2, 12.0, 30.0, "估值反证", "times"),
            Rule("peg", "PEG", 2, 1.0, 3.0, "估值反证", "times"),
            Rule("deferred_revenue_growth", "预收款同比增速", 2, 0.25, 0.0, "估值反证", "percent",
                 "客户提前付款的强度"),
        ],
        red_flags=[
            RedFlag("forward_pe", ">", 60.0, "动态市盈率超过 60 倍，好消息已被充分定价", 6),
        ],
        adapt=_boost_ex_sbc_valuation,
        interpret=_read_valuation,
    ),
]

# ===========================================================================
# 行业口径（Profile）
#
# 七步的**问题**是商业模式无关的，坏掉的只是载体：硬件把现金锁在存货里，SaaS 则
# 相反 —— 客户年度预付在给公司垫资。所以不能把不适用的规则删掉（删掉就变成
# "缺数据 = 高分"），必须换成等价问法。骨架不动，只换每一步的规则。
# ===========================================================================


@dataclass
class Profile:
    name: str
    label: str
    description: str
    rules: dict[str, list[Rule]] = field(default_factory=dict)       # stage key -> 替换规则
    red_flags: dict[str, list[RedFlag]] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)          # stage key -> 替换权重
    interpret: dict[str, Callable[[dict, dict], list[str]]] = field(default_factory=dict)
    titles: dict[str, str] = field(default_factory=dict)             # stage key -> 替换标题
    questions: dict[str, str] = field(default_factory=dict)          # stage key -> 替换问题
    notes: list[str] = field(default_factory=list)


def _base(key: str) -> Stage:
    return next(st for st in METHODOLOGY if st.key == key)


HARDWARE_PROFILE = Profile(
    name="hardware", label="硬件/半导体",
    description="《方法论 Part1》的原始口径：存货、应收、资本开支→折旧",
)

SAAS_PROFILE = Profile(
    name="saas", label="软件/订阅",
    description="订阅口径：递延收入替代存货，营运资本应为负，收入池枯竭替代压货",
    rules={
        # 第 1 步：加一条问"经营现金流有多少是客户预付撑起来的"
        "cash": _base("cash").rules + [
            Rule("ocf_from_deferred_share", "经营现金流中客户预付增量占比", 1, 0.10, 0.45,
                 "现金实质", "percent", "增长减速时这块会先消失，不是可持续的现金来源"),
        ],
        # 第 4 步：营运资本必须计入递延收入，应收天数阈值按企业级年度开票放宽
        "working_capital": [
            Rule("nwc_incl_deferred_to_sales", "营运资本(含递延)/营收", 3, -0.25, 0.10,
                 "营运效率", "percent", "订阅生意应为负：客户预付在给公司垫资"),
            Rule("nwc_incl_deferred_to_sales_change", "该比率同比变动", 2, -0.02, 0.05,
                 "营运效率", "percent"),
            Rule("ar_days", "应收周转天数", 3, 60.0, 100.0, "营运效率", "number",
                 "企业级 SaaS 年度开票，60-75 天属常态，看趋势不看绝对值"),
            Rule("deferred_revenue_to_revenue", "递延收入/营收", 2, 0.60, 0.20,
                 "营运效率", "percent", "已收钱未确认的收入池，越厚越好"),
        ],
        # 第 5 步：存货压货 -> 收入池枯竭，这是订阅生意的等价症状
        "ar_inventory": [
            Rule("ar_vs_revenue_gap", "应收增速 - 收入增速", 4, -0.02, 0.15, "质量红旗", "percent"),
            Rule("deferred_vs_revenue_gap", "递延收入增速 - 收入增速", 3, 0.05, -0.15,
                 "质量红旗", "percent",
                 "跑输收入说明未来收入池在枯竭：当期收入靠消耗已签合同撑着"),
            Rule("accrual_ratio", "应计比例", 2, 0.0, 0.10, "质量红旗", "percent"),
        ],
    },
    red_flags={
        "ar_inventory": [
            RedFlag("ar_vs_revenue_gap", ">", 0.20,
                    "应收增速比收入快 20pp 以上：警惕收入确认激进或多年合同前置", 12),
            RedFlag("deferred_vs_revenue_gap", "<", -0.15,
                    "递延收入增速比收入慢 15pp 以上：未来收入池在枯竭", 10),
        ],
    },
    interpret={
        "working_capital": _read_working_capital_saas,
        "ar_inventory": _read_red_flags_saas,
    },
    titles={
        "working_capital": "营运资本 = 占用谁的钱",
        "ar_inventory": "用应收/递延收入增速当造假探测器",
    },
    questions={
        "working_capital": "这门生意占用自有资金，还是靠客户预付运转？趋势在哪个方向？",
        "ar_inventory": "应收是不是跑在收入前面？未来收入池在扩张还是枯竭？",
    },
    weights={
        "sbc": 4.0,            # SBC 是软件公司的震中，权重上调
        "margin": 2.0,         # 定价权判据应看 NRR 与订阅/服务结构，财报摘要给不了
        "capex_timing": 1.0,   # SaaS 的等价物是资本化佣金与软件开发摊销，数据源不提供
    },
    notes=[
        "第 3 步已下调权重：SaaS 的定价权判据是净收入留存(NRR)与订阅/专业服务收入结构，"
        "财报摘要无此粒度，需查 10-K 与业绩电话会",
        "第 6 步已下调权重：SaaS 的「先花钱后进损益表」是资本化销售佣金与软件开发费的摊销，"
        "数据源不提供，资本开支口径只覆盖自建数据中心部分",
    ],
)

PROFILES = {"hardware": HARDWARE_PROFILE, "saas": SAAS_PROFILE}

# 递延收入占营收的下限。达到这个规模，"现金锁在哪"这件事的答案就变了。
SAAS_DEFERRED_THRESHOLD = 0.15
# 存货占营收的上限。微软这类公司有少量硬件存货，但主体是订阅生意，
# 用"有没有存货"判会误判成硬件口径，必须看存货的相对规模。
SAAS_INVENTORY_CEILING = 0.03


def detect_profile(metrics: Metrics) -> Profile:
    """按报表结构识别行业口径。

    判据是两条同时成立：递延收入占营收有实质规模，且几乎没有存货。
    这比行业标签可靠 —— 它直接反映"现金锁在哪"这件事本身。
    """
    deferred = metrics.get("deferred_revenue_to_revenue") or 0
    inventory_share = metrics.get("inventory_to_revenue")
    inventory_light = inventory_share is None or inventory_share <= SAAS_INVENTORY_CEILING
    if deferred >= SAAS_DEFERRED_THRESHOLD and inventory_light:
        return SAAS_PROFILE
    return HARDWARE_PROFILE


def apply_profile(stages: list[Stage], profile: Profile) -> list[Stage]:
    """把 profile 的规则、红旗、权重覆盖到七步骨架上。步骤本身与顺序不变。"""
    return [
        replace(st,
                rules=profile.rules.get(st.key, st.rules),
                red_flags=profile.red_flags.get(st.key, st.red_flags),
                weight=profile.weights.get(st.key, st.weight),
                interpret=profile.interpret.get(st.key, st.interpret),
                title=profile.titles.get(st.key, st.title),
                question=profile.questions.get(st.key, st.question))
        for st in stages
    ]


METHODOLOGY_GRADES = [
    {"min": 85, "grade": "A", "verdict": "七步全部站得住：现金实、口径干净、营运高效、估值不离谱"},
    {"min": 70, "grade": "B", "verdict": "整体过关，但有个别步骤需要回查原始年报"},
    {"min": 55, "grade": "C", "verdict": "报表质量与价格之间存在明显取舍，逐步核对弱项"},
    {"min": 40, "grade": "D", "verdict": "多个步骤亮灯，利润质量或估值存在实质问题"},
    {"min": 0, "grade": "E", "verdict": "现金、口径或营运资本层面已出问题，不宜只看利润表"},
]


def evaluate_methodology(metrics: Metrics, stages: list[Stage] | None = None,
                         profile: Profile | str | None = None) -> MethodologyReport:
    """按《方法论 Part1》的阅读顺序逐步评估。

    上下文（context）在步骤之间单向传递：前一步的结论可以改变后一步的权重和解读，
    这正是这套方法论和普通打分卡的区别。

    profile 为 None 时按报表结构自动识别行业口径（硬件 / 软件订阅）。
    """
    if isinstance(profile, str):
        if profile not in PROFILES:
            raise RuleError(f"未知口径 {profile}，可选：{', '.join(PROFILES)}")
        profile = PROFILES[profile]
    profile = profile or detect_profile(metrics)

    stages = sorted(stages or METHODOLOGY, key=lambda s: s.order)
    stages = apply_profile(stages, profile)
    report = MethodologyReport(ticker=metrics.ticker, name=metrics.name,
                               profile=profile.name, profile_label=profile.label,
                               notes=list(metrics.notes) + list(profile.notes))
    ctx: dict[str, Any] = {"operating_margin_now": metrics.get("operating_margin")}

    total_weight = 0.0
    earned = 0.0
    covered_weight = 0.0
    rule_covered = 0.0
    penalty_total = 0.0

    for stage in stages:
        rules = stage.adapt(stage.rules, metrics.values, ctx) if stage.adapt else stage.rules
        details, skipped, scored_weight, stage_earned = score_rules(metrics, rules)
        rule_weight = sum(r.weight for r in rules)
        flags, penalty = check_flags(metrics, stage.red_flags)

        result = StageResult(
            key=stage.key, order=stage.order, title=stage.title, question=stage.question,
            weight=stage.weight, details=details, skipped=skipped, flags=flags, penalty=penalty,
            coverage=scored_weight / rule_weight if rule_weight else 0.0,
            score=stage_earned / scored_weight * 100 if scored_weight else 0.0,
        )
        if stage.interpret:
            result.findings = [f for f in stage.interpret(metrics.values, ctx) if f]
        ctx[f"{stage.key}_score"] = result.score if scored_weight else None

        if scored_weight:
            earned += result.score * stage.weight
            covered_weight += stage.weight
        # 覆盖率按**规则级**加权：某一步只有一半规则有数据时必须如实反映，
        # 否则会像之前那样在半个测试缺失的情况下报 100%
        rule_covered += result.coverage * stage.weight
        total_weight += stage.weight
        penalty_total += penalty

        if stage.gate and scored_weight and result.score < stage.gate_threshold:
            report.gate_warnings.append(
                f"第 {stage.order} 步「{stage.title}」得分 {result.score:.0f}/100 —— {stage.gate}")
            ctx[f"{stage.key}_gate_failed"] = True

        report.stages.append(result)

    report.raw_score = earned / covered_weight if covered_weight else 0.0
    report.score = max(0.0, report.raw_score - penalty_total)
    report.coverage = rule_covered / total_weight if total_weight else 0.0
    report.stage_coverage = covered_weight / total_weight if total_weight else 0.0
    report.context = ctx

    for band in METHODOLOGY_GRADES:
        if report.score >= band["min"]:
            report.grade, report.verdict = band["grade"], band["verdict"]
            break

    missing = [st.title for st in report.stages if st.coverage == 0]
    if missing:
        report.notes.append(f"以下步骤完全没有数据支撑，未计入总分：{'、'.join(missing)}")
    return report
