"""历史估值带。

方法论第 7 步要问"市场是不是已经把好消息定价了"，但 PDF 只给否决条件、不给锚。
要量化"当前处在自身历史什么位置"，需要一条历史估值时间序列。

数据现实（实测 yfinance）：季报只有 7 期、年报 4 期、日线 5 年。所以基本面那一侧是
**低分辨率阶梯**（约 8 个台阶），价格是日频。分位数因此主要由价格驱动 —— 这对
"市场情绪杀估值"的场景恰好是对的，但基本面快速变化的公司会失真，见 README 限制说明。

前视偏差：财报期末 ≠ 发布日，yfinance 不给发布日，这里统一按滞后天数近似，
否则历史带会用到当时市场还不知道的数字。

这里只有纯计算。取价格历史、算 ADR 股数/币种校准系数都要联网，在
``scan_fundamentals.py`` 里完成后以 ``prices`` 和 ``scale`` 传进 :func:`build_bands`。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
from dataclasses import dataclass, field
from typing import Any

from .model import FinancialData

# 财报期末到市场可知之间的近似滞后
QUARTERLY_LAG_DAYS = 45
ANNUAL_LAG_DAYS = 60

# 估值带口径。方法论的价值锚是自由现金流，所以 p_fcf 是主锚，其余为校验。
MULTIPLES = ("p_fcf", "ps", "ev_ebitda", "pe")



@dataclass
class FundamentalPoint:
    """某个时点市场可知的 TTM 基本面。流量项是 TTM 合计，存量项取期末值。"""

    effective: dt.date          # 市场可知日 = 期末 + 滞后
    period_end: dt.date
    source: str                 # quarterly-ttm | annual
    revenue: float | None = None
    net_income: float | None = None
    fcf: float | None = None
    ebitda: float | None = None
    net_debt: float | None = None
    shares: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        d["effective"] = self.effective.isoformat()
        d["period_end"] = self.period_end.isoformat()
        return d

    @classmethod
    def from_dict(cls, p: dict[str, Any]) -> "FundamentalPoint":
        p = dict(p)
        p["effective"] = dt.date.fromisoformat(p["effective"])
        p["period_end"] = dt.date.fromisoformat(p["period_end"])
        return cls(**p)


@dataclass
class Bands:
    """各口径的历史估值序列。"""

    ticker: str
    name: str = ""
    series: dict[str, list[tuple[dt.date, float]]] = field(default_factory=dict)
    points: list[FundamentalPoint] = field(default_factory=list)
    prices: list[tuple[dt.date, float]] = field(default_factory=list)
    price_currency: str = ""
    financial_currency: str = ""
    share_scale: float = 1.0       # 把"价格 x 报表股数"校准到财报币种市值的系数
    caveats: list[str] = field(default_factory=list)

    # -- 读数 --------------------------------------------------------------
    def values(self, metric: str) -> list[float]:
        return [v for _, v in self.series.get(metric, [])]

    def current(self, metric: str) -> float | None:
        s = self.series.get(metric)
        return s[-1][1] if s else None

    def median(self, metric: str) -> float | None:
        vals = self.values(metric)
        return statistics.median(vals) if vals else None

    def percentile(self, metric: str) -> float | None:
        """当前值在历史分布中的分位。倍数越低越便宜，所以低分位 = 便宜。"""
        vals = self.values(metric)
        cur = self.current(metric)
        if not vals or cur is None or len(vals) < 2:
            return None
        return sum(1 for v in vals if v < cur) / len(vals)

    def last_date(self, metric: str) -> dt.date | None:
        s = self.series.get(metric)
        return s[-1][0] if s else None

    def staleness_days(self, metric: str) -> int | None:
        """该口径最后一个有效观测距最新交易日多少天。

        倍数会"停更"：TTM 自由现金流转负后 P/FCF 不再有意义，序列就此中断，
        但 current() 仍会返回中断前的旧值。不查这个，分位数会拿几个月前的
        估值去和历史比，得出完全错误的结论。
        """
        last = self.last_date(metric)
        if last is None or not self.prices:
            return None
        return (self.prices[-1][0] - last).days

    def span_days(self, metric: str) -> int:
        s = self.series.get(metric)
        return (s[-1][0] - s[0][0]).days if s and len(s) > 1 else 0

    def observations(self, metric: str) -> int:
        return len(self.series.get(metric, []))

    def value_on(self, metric: str, when: dt.date) -> float | None:
        """取 when 当天或之前最近一个观测值。"""
        s = self.series.get(metric) or []
        out = None
        for day, v in s:
            if day > when:
                break
            out = v
        return out

    def market_cap_on(self, when: dt.date) -> float | None:
        """财报币种下的市值（已按 share_scale 校准）。"""
        price = _step_lookup(self.prices, when)
        shares = _last_known(self.points, "shares", when)
        if price is None or not shares:
            return None
        return price * shares * self.share_scale

    def fundamental_on(self, field_name: str, when: dt.date) -> float | None:
        return _last_known(self.points, field_name, when)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "price_currency": self.price_currency,
            "financial_currency": self.financial_currency,
            "share_scale": self.share_scale,
            "caveats": self.caveats,
            "points": [p.to_dict() for p in self.points],
            "prices": [[d.isoformat(), v] for d, v in self.prices],
            "series": {k: [[d.isoformat(), v] for d, v in s] for k, s in self.series.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Bands":
        return cls(
            ticker=payload["ticker"],
            name=payload.get("name", ""),
            price_currency=payload.get("price_currency", ""),
            financial_currency=payload.get("financial_currency", ""),
            share_scale=payload.get("share_scale", 1.0),
            caveats=payload.get("caveats", []),
            points=[FundamentalPoint.from_dict(p) for p in payload.get("points", [])],
            prices=[(dt.date.fromisoformat(d), v) for d, v in payload.get("prices", [])],
            series={k: [(dt.date.fromisoformat(d), v) for d, v in s]
                    for k, s in payload.get("series", {}).items()},
        )

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, path: str) -> "Bands":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


# ---------------------------------------------------------------------------
# 纯计算核心（不碰网络，便于离线测试）
# ---------------------------------------------------------------------------


def _sum_window(values: list[float | None], start: int, size: int = 4) -> float | None:
    """TTM 合计。窗口内任一季度缺失就返回 None —— 补零会凭空压低倍数。"""
    window = values[start:start + size]
    if len(window) < size or any(v is None for v in window):
        return None
    return sum(window)


def ttm_points(quarterly: FinancialData | None, annual: FinancialData | None,
               quarterly_lag: int = QUARTERLY_LAG_DAYS,
               annual_lag: int = ANNUAL_LAG_DAYS) -> list[FundamentalPoint]:
    """把季报滚成 TTM，与年报拼成一条按可知日排序的基本面阶梯。

    7 个季度只能滚出 4 个 TTM 窗口，更早的时间靠年报补 —— 这就是阶梯只有
    8 级左右的原因。同一可知日上季报口径优先（更新）。
    """
    points: list[FundamentalPoint] = []

    if quarterly and quarterly.n_periods >= 4:
        rev = quarterly.series("revenue")
        ni = quarterly.series("net_income")
        ebitda = quarterly.series("ebitda")
        fcf = _fcf_quarters(quarterly)
        for i in range(quarterly.n_periods - 3):
            end = dt.date.fromisoformat(quarterly.periods[i])
            points.append(FundamentalPoint(
                effective=end + dt.timedelta(days=quarterly_lag),
                period_end=end,
                source="quarterly-ttm",
                revenue=_sum_window(rev, i),
                net_income=_sum_window(ni, i),
                fcf=_sum_window(fcf, i),
                ebitda=_sum_window(ebitda, i),
                net_debt=_net_debt(quarterly, i),
                shares=quarterly.latest("shares_outstanding", i),
            ))

    if annual:
        for i in range(annual.n_periods):
            end = dt.date.fromisoformat(annual.periods[i])
            points.append(FundamentalPoint(
                effective=end + dt.timedelta(days=annual_lag),
                period_end=end,
                source="annual",
                revenue=annual.latest("revenue", i),
                net_income=annual.latest("net_income", i),
                fcf=_fcf_annual(annual, i),
                ebitda=annual.latest("ebitda", i),
                net_debt=_net_debt(annual, i),
                shares=annual.latest("shares_outstanding", i),
            ))

    # 同一可知日保留季报口径；其余按时间升序
    best: dict[dt.date, FundamentalPoint] = {}
    for p in points:
        prev = best.get(p.effective)
        if prev is None or (prev.source == "annual" and p.source == "quarterly-ttm"):
            best[p.effective] = p
    return sorted(best.values(), key=lambda p: p.effective)


def build_bands(ticker: str, points: list[FundamentalPoint],
                prices: list[tuple[dt.date, float]], name: str = "",
                scale: float = 1.0, **meta: Any) -> Bands:
    """日线价格 × 基本面阶梯 -> 各口径的历史倍数序列。

    scale 把"价格 × 报表股数"校准到财报币种下的真实市值，一次性吸收 ADR 的
    ADS 比例和汇率差异。它对全序列是同一个常数，所以分位数和"当前/中位"比值
    不受影响，只影响倍数的绝对水平。
    """
    bands = Bands(ticker=ticker, name=name, points=points, share_scale=scale,
                  prices=sorted(prices, key=lambda x: x[0]),
                  **{k: v for k, v in meta.items() if k in
                     ("price_currency", "financial_currency", "caveats")})
    series: dict[str, list[tuple[dt.date, float]]] = {m: [] for m in MULTIPLES}
    if not points:
        bands.series = series
        return bands

    idx = 0
    # 逐字段前向填充：某期只缺 TTM 营收（窗口跨过缺失季度）时，不能把已知的股数、
    # 现金流一并清空 —— 否则整段观测凭空消失，分位数会被幸存样本带偏。
    cur: dict[str, float | None] = {f: None for f in
                                    ("revenue", "net_income", "fcf", "ebitda", "net_debt", "shares")}
    seen = False
    for day, price in bands.prices:
        while idx < len(points) and points[idx].effective <= day:
            for f in cur:
                v = getattr(points[idx], f)
                if v is not None:
                    cur[f] = v
            seen = True
            idx += 1
        if not seen or not cur["shares"] or price is None:
            continue
        cap = price * cur["shares"] * scale
        if (cur["fcf"] or 0) > 0:
            series["p_fcf"].append((day, cap / cur["fcf"]))
        if (cur["revenue"] or 0) > 0:
            series["ps"].append((day, cap / cur["revenue"]))
        if (cur["ebitda"] or 0) > 0 and cur["net_debt"] is not None:
            series["ev_ebitda"].append((day, (cap + cur["net_debt"]) / cur["ebitda"]))
        if (cur["net_income"] or 0) > 0:
            series["pe"].append((day, cap / cur["net_income"]))

    bands.series = series
    return bands


def _fcf_quarters(data: FinancialData) -> list[float | None]:
    reported = data.series("free_cash_flow")
    ocf = data.series("operating_cash_flow")
    capex = data.series("capex")
    out: list[float | None] = []
    for i in range(data.n_periods):
        v = reported[i] if i < len(reported) else None
        if v is None:
            o = ocf[i] if i < len(ocf) else None
            c = capex[i] if i < len(capex) else None
            v = o - abs(c) if o is not None and c is not None else None
        out.append(v)
    return out


def _fcf_annual(data: FinancialData, i: int) -> float | None:
    return _fcf_quarters(data)[i] if i < data.n_periods else None


def _net_debt(data: FinancialData, i: int) -> float | None:
    reported = data.latest("net_debt", i)
    if reported is not None:
        return reported
    debt, cash = data.latest("total_debt", i), data.latest("cash", i)
    if debt is None and cash is None:
        return None
    return (debt or 0) - (cash or 0)


def _step_lookup(series: list[tuple[dt.date, float]], when: dt.date) -> float | None:
    out = None
    for day, v in series:
        if day > when:
            break
        out = v
    return out


def _last_known(points: list[FundamentalPoint], field_name: str,
                when: dt.date) -> float | None:
    """when 之前最近一个非空取值（与 build_bands 的前向填充保持一致）。"""
    out = None
    for p in points:
        if p.effective > when:
            break
        v = getattr(p, field_name, None)
        if v is not None:
            out = v
    return out


# ---------------------------------------------------------------------------
# 取数（唯一碰网络的地方）
# ---------------------------------------------------------------------------






