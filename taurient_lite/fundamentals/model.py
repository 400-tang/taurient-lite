"""规范化后的财报数据容器，以及数据源行标签到规范字段名的映射。

这里**不碰网络**。联网取数在仓库根目录的 ``scan_fundamentals.py`` 里，那是整条
基本面链路上唯一需要第三方依赖（yfinance）的地方，只在 GitHub Actions 上跑——
云端任务的沙箱出站白名单里没有 Yahoo。这个包保持零依赖，和 ``taurient_lite``
其余部分同一条纪律。

映射表放在这里而不是取数脚本里，是因为它定义的是**口径**：metrics 用哪个字段名、
一个字段对应数据源的哪几行、按什么优先级取。口径属于分析逻辑，不属于网络层。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 字段映射：canonical key -> 数据源中可能出现的行标签（按优先级从高到低）
# ---------------------------------------------------------------------------

INCOME_ITEMS: dict[str, list[str]] = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "cost_of_revenue": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported"],
    "operating_expense": ["Operating Expense"],
    "rnd": ["Research And Development"],
    "sga": ["Selling General And Administration"],
    "ebit": ["EBIT"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "pretax_income": ["Pretax Income"],
    "tax_provision": ["Tax Provision"],
    "net_income": ["Net Income Common Stockholders", "Net Income"],
    "diluted_eps": ["Diluted EPS"],
    "diluted_shares": ["Diluted Average Shares", "Basic Average Shares"],
}

BALANCE_ITEMS: dict[str, list[str]] = {
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets"],
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    "short_term_investments": ["Other Short Term Investments"],
    "receivables": ["Accounts Receivable", "Receivables"],
    "inventory": ["Inventory"],
    "accounts_payable": ["Accounts Payable", "Payables"],
    "total_liabilities": ["Total Liabilities Net Minority Interest"],
    "current_liabilities": ["Current Liabilities"],
    "total_debt": ["Total Debt"],
    "long_term_debt": ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"],
    "net_debt": ["Net Debt"],
    "equity": ["Stockholders Equity", "Common Stock Equity"],
    "retained_earnings": ["Retained Earnings"],
    "tangible_book_value": ["Tangible Book Value"],
    "invested_capital": ["Invested Capital"],
    "working_capital": ["Working Capital"],
    "shares_outstanding": ["Ordinary Shares Number", "Share Issued"],
    # 方法论第 6 步：资本开支 -> 折旧的时间差，需要 PPE 原值来反推折旧年限
    "gross_ppe": ["Gross PPE"],
    "net_ppe": ["Net PPE"],
    "accumulated_depreciation": ["Accumulated Depreciation"],
    # 方法论第 7 步：预收款（客户提前付钱）是需求强度的先行信号
    "deferred_revenue": ["Current Deferred Revenue", "Current Deferred Liabilities"],
}

CASHFLOW_ITEMS: dict[str, list[str]] = {
    "operating_cash_flow": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure", "Purchase Of PPE"],
    "free_cash_flow": ["Free Cash Flow"],
    "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "buybacks": ["Repurchase Of Capital Stock", "Common Stock Payments"],
    "depreciation": ["Depreciation And Amortization", "Depreciation Amortization Depletion"],
    # 第 6 步问的是"capex 变成折旧"的时间差，分母必须是**物理资产折旧**。
    # 并购型公司的 D&A 绝大部分是无形资产摊销（AVGO：8.78B 中 8.20B 是摊销），
    # 混进来会把 capex/折旧 算成假稳态。
    "depreciation_only": ["Depreciation"],
    "amortization_intangibles": ["Amortization Of Intangibles", "Amortization Cash Flow"],
    "stock_comp": ["Stock Based Compensation"],
}

STATEMENT_ITEMS = {
    "income": INCOME_ITEMS,
    "balance": BALANCE_ITEMS,
    "cashflow": CASHFLOW_ITEMS,
}


class DataFetchError(RuntimeError):
    """数据源不可用、标的不存在或报表为空时抛出。"""


# ---------------------------------------------------------------------------
# 规范化后的数据容器
# ---------------------------------------------------------------------------


@dataclass
class FinancialData:
    """一只标的的规范化财报数据。所有序列都按 **时间由新到旧** 排列。"""

    ticker: str
    name: str = ""
    currency: str = ""
    sector: str = ""
    period: str = "annual"          # annual | quarterly
    periods: list[str] = field(default_factory=list)   # 报告期末日期 ISO 字符串
    income: dict[str, list[float | None]] = field(default_factory=dict)
    balance: dict[str, list[float | None]] = field(default_factory=dict)
    cashflow: dict[str, list[float | None]] = field(default_factory=dict)
    market: dict[str, float | None] = field(default_factory=dict)
    source: str = ""
    fetched_at: str = ""

    # -- 取数接口 ----------------------------------------------------------
    def series(self, item: str, n: int | None = None) -> list[float | None]:
        """按 canonical 字段名取一条时间序列（新 -> 旧），字段不存在返回空列表。"""
        for statement in (self.income, self.balance, self.cashflow):
            if item in statement:
                values = statement[item]
                return values[:n] if n else list(values)
        return []

    def latest(self, item: str, offset: int = 0) -> float | None:
        """取最近一期（offset=1 即上一期）的值。"""
        values = self.series(item)
        if offset < len(values):
            return values[offset]
        return None

    def clean_series(self, item: str, n: int | None = None) -> list[float]:
        """取序列并丢掉缺失值，用于 CAGR、标准差等需要连续数据的计算。"""
        return [v for v in self.series(item, n) if v is not None]

    @property
    def n_periods(self) -> int:
        return len(self.periods)

    # -- 序列化 ------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "currency": self.currency,
            "sector": self.sector,
            "period": self.period,
            "periods": self.periods,
            "income": self.income,
            "balance": self.balance,
            "cashflow": self.cashflow,
            "market": self.market,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FinancialData":
        return cls(**{k: payload[k] for k in payload if k in cls.__dataclass_fields__})

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load(cls, path: str) -> "FinancialData":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------




def _num(value: Any) -> float | None:
    """把 numpy/pandas 的值转成 float，NaN / 非数值一律变 None。"""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) or math.isinf(out) else out




# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------








