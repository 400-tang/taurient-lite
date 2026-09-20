#!/usr/bin/env python3
"""按《方法论 Part1》七步法扫一组公司的财报，把结果写进仓库供简报读取。

**为什么要有这个标签页。** 简报其余部分回答「今天发生了什么」，价量异动回答
「哪些票在动」，都是按天变化的东西。基本面回答的是另一个问题：**这家公司的账
能不能信、贵不贵**——它一个季度才变一次，但每次看一只票时都该先过一遍。

判定逻辑全部在 :mod:`taurient_lite.fundamentals` 里，是不碰网络的纯函数。这里
只负责 I/O：定名单、从 Yahoo 拉报表和价格、把结果写成文件。

**这是整条流水线里唯一装了第三方依赖的脚本。** 取年报/季报三大表要处理 Yahoo
的 crumb/cookie 鉴权和字段名漂移，yfinance 已经把这些做好了，用 urllib 重写
一遍的维护成本远高于装一个包。代价被刻意限制在这一个文件：``taurient_lite``
包本身仍然零依赖，渲染、测试、云端任务都不需要 yfinance。

**跑在哪。** 和异动扫描同样的理由跑在 GitHub Actions 上——云端任务的沙箱连
不上 Yahoo。见 .github/workflows/fundamentals-scan.yml。财报一个季度才更新一次，
所以每周跑一次就够。

用法：

    python3 scan_fundamentals.py              # 扫 config.json 的 fundamentals 名单
    python3 scan_fundamentals.py NVDA TSM     # 只扫指定代码
    python3 scan_fundamentals.py --print      # 只打印，不写文件

退出码：0 全部成功；1 一只都没扫成；2 部分失败（成功的照常写入）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.config import Config  # noqa: E402
from taurient_lite.fundamentals import metrics as metrics_mod  # noqa: E402
from taurient_lite.fundamentals import reversion  # noqa: E402
from taurient_lite.fundamentals.methodology import evaluate_methodology  # noqa: E402
from taurient_lite.fundamentals.model import (  # noqa: E402
    BALANCE_ITEMS,
    CASHFLOW_ITEMS,
    INCOME_ITEMS,
    DataFetchError,
    FinancialData,
    _num,
)
from taurient_lite.fundamentals.summary import summarize  # noqa: E402
from taurient_lite.fundamentals.valuation import (  # noqa: E402
    Bands,
    FundamentalPoint,
    build_bands,
    ttm_points,
)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "fundamentals_scan.json"

#: 年报取几期。七步法里最长的窗口是 3 年 CAGR（要 4 期），多取一期给估值带
#: 的阶梯补历史；Yahoo 本身通常也只给 4-5 期。
ANNUAL_PERIODS = 6
#: 季报取几期。只用来滚 TTM，Yahoo 实测最多给 7 期，12 是"有多少要多少"。
QUARTERLY_PERIODS = 12
#: 估值带回溯年数。
BAND_YEARS = 5


# --------------------------------------------------------------------------- 取数


def _extract(df: Any, aliases_map: dict[str, list[str]], n: int) -> dict[str, list[float | None]]:
    """按别名表从 DataFrame 抽取各字段，对齐到 n 期。"""
    out: dict[str, list[float | None]] = {}
    index = set(df.index) if df is not None and not df.empty else set()
    for key, aliases in aliases_map.items():
        row = next((a for a in aliases if a in index), None)
        if row is None:
            continue
        values = [_num(v) for v in df.loc[row].tolist()][:n]
        values += [None] * (n - len(values))
        out[key] = values
    return out


class Fetcher:
    """一次扫描共用的取数器。汇率按币种对缓存——十只票里六只 USD/TWD 没必要问六次。"""

    def __init__(self) -> None:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise DataFetchError(
                "未安装 yfinance。这是基本面扫描唯一的第三方依赖：pip install yfinance"
            ) from exc
        self.yf = yf
        self._fx: dict[tuple[str, str], float | None] = {}

    def fx(self, base: str, quote: str) -> float | None:
        """当期汇率。拿不到返回 None——宁可让估值指标缺失，也不给错一个量级的数。"""
        key = (base, quote)
        if key not in self._fx:
            try:
                hist = self.yf.Ticker(f"{base}{quote}=X").history(period="5d")
                closes = hist["Close"].dropna() if hist is not None else []
                self._fx[key] = float(closes.iloc[-1]) if len(closes) else None
            except Exception:
                self._fx[key] = None
        return self._fx[key]

    def statements(self, tk: Any, info: dict, ticker: str, period: str,
                   limit: int) -> FinancialData:
        quarterly = period == "quarterly"
        income = tk.quarterly_income_stmt if quarterly else tk.income_stmt
        balance = tk.quarterly_balance_sheet if quarterly else tk.balance_sheet
        cashflow = tk.quarterly_cashflow if quarterly else tk.cashflow
        if income is None or income.empty:
            raise DataFetchError(f"{ticker}: Yahoo 没有返回{'季' if quarterly else '年'}度利润表")

        n = min(limit, income.shape[1])
        return FinancialData(
            ticker=ticker.upper(),
            name=info.get("longName") or info.get("shortName") or ticker.upper(),
            currency=info.get("financialCurrency") or info.get("currency") or "",
            sector=info.get("sector") or "",
            period=period,
            periods=[c.strftime("%Y-%m-%d") for c in list(income.columns)[:n]],
            income=_extract(income, INCOME_ITEMS, n),
            balance=_extract(balance, BALANCE_ITEMS, n),
            cashflow=_extract(cashflow, CASHFLOW_ITEMS, n),
            source="yfinance",
            fetched_at=dt.datetime.now().isoformat(timespec="seconds"),
        )

    def market(self, info: dict) -> dict[str, Any]:
        """市场数据。市值按报价币种计、报表按财报币种计，两者不同却直接相除，
        估值指标会错一个汇率的量级（TSM 的 TWD/USD 约 32 倍），所以这里一次性
        折算到财报币种，折不了就明确置空。"""
        price_ccy = (info.get("currency") or "").upper()
        fin_ccy = (info.get("financialCurrency") or "").upper()
        mismatch = bool(price_ccy and fin_ccy and price_ccy != fin_ccy)
        fx = self.fx(price_ccy, fin_ccy) if mismatch else 1.0
        cap = _num(info.get("marketCap"))
        return {
            "price": _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice")),
            "market_cap": cap,
            "market_cap_financial": cap * fx if cap is not None and fx else None,
            "price_currency": price_ccy,
            "financial_currency": fin_ccy,
            "fx_to_financial": fx,
            "currency_mismatch": mismatch,
            "shares_outstanding": _num(info.get("sharesOutstanding")),
            "forward_pe": _num(info.get("forwardPE")),
            "trailing_pe": _num(info.get("trailingPE")),
        }

    def bands(self, tk: Any, ticker: str, annual: FinancialData,
              quarterly: FinancialData | None, market: dict) -> Bands | None:
        """历史估值带。拿不到价格历史时返回 None，估值那一块在页面上整块省略。"""
        hist = tk.history(period=f"{BAND_YEARS}y", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        # auto_adjust=False：市值 = 价格 × 股数，复权价会系统性压低历史市值
        prices = [(idx.date(), float(v)) for idx, v in hist["Close"].items() if v == v]
        points = ttm_points(quarterly, annual)
        scale, caveats = _calibration(market, points, prices)
        return build_bands(ticker.upper(), points, prices, name=annual.name, scale=scale,
                           price_currency=market.get("price_currency", ""),
                           financial_currency=market.get("financial_currency", ""),
                           caveats=caveats)

    def fetch(self, ticker: str) -> tuple[FinancialData, Bands | None]:
        tk = self.yf.Ticker(ticker)
        try:
            info = tk.info or {}
        except Exception:
            info = {}
        annual = self.statements(tk, info, ticker, "annual", ANNUAL_PERIODS)
        annual.market = self.market(info)
        try:
            quarterly = self.statements(tk, info, ticker, "quarterly", QUARTERLY_PERIODS)
        except DataFetchError:
            quarterly = None
        try:
            bands = self.bands(tk, ticker, annual, quarterly, annual.market)
        except Exception:
            bands = None
        return annual, bands


def _calibration(market: dict, points: list[FundamentalPoint],
                 prices: list[tuple[dt.date, float]]) -> tuple[float, list[str]]:
    """求校准系数：让「价格 × 报表股数」等于财报币种下的当期市值。

    中概和台股 ADR 是三重错配的重灾区——财报记 CNY/TWD、ADR 报价 USD、1 ADS
    往往等于若干普通股。用当期市值反解一个常数，一次性吸收全部三项；它对全序列
    是同一个常数，所以对分位数无影响，只修正倍数的绝对水平。
    """
    caveats: list[str] = []
    cap = market.get("market_cap_financial")
    last_price = prices[-1][1] if prices else None
    shares = next((p.shares for p in reversed(points) if p.shares), None)
    if cap is None or not last_price or not shares:
        caveats.append("拿不到当期市值，倍数按「价格 × 报表股数」直接计算，绝对水平可能失真")
        return 1.0, caveats
    if market.get("currency_mismatch"):
        caveats.append(f"报价币种 {market['price_currency']} 与财报币种 "
                       f"{market['financial_currency']} 不同，已按当期汇率统一折算")
    scale = cap / (last_price * shares)
    if abs(scale - 1.0) > 0.05:
        caveats.append(f"股数/币种校准系数 {scale:.3f}（ADR 的 ADS 比例与汇率已一并吸收）")
    return scale, caveats


# --------------------------------------------------------------------------- 分析


def analyze(data: FinancialData, bands: Bands | None) -> dict[str, Any]:
    """一只标的：七步法 + 估值位置 -> 一行。"""
    m = metrics_mod.compute(data)
    report = evaluate_methodology(m)
    case = None
    if bands is not None:
        anchor, _ = reversion.pick_anchor(bands)
        growth = reversion.growth_for(anchor, m) if anchor else None
        case = reversion.assess(bands, quality_score=report.score,
                                quality_grade=report.grade, growth=growth)
    return summarize(report, data, case)


def main() -> int:
    parser = argparse.ArgumentParser(description="按方法论七步法扫描一组公司的财报")
    parser.add_argument("tickers", nargs="*", help="只扫这些代码（默认读 config.json）")
    parser.add_argument("--print", action="store_true", help="只打印，不写文件")
    args = parser.parse_args()

    config = Config.load(ROOT / "config.json")
    tickers = [t.upper() for t in args.tickers] or list(config.fundamentals_symbols)
    if not tickers:
        print("名单为空：config.json 里既没有 fundamentals 也没有 watchlist", file=sys.stderr)
        return 1

    try:
        fetcher = Fetcher()
    except DataFetchError as exc:
        print(exc, file=sys.stderr)
        return 1

    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for ticker in tickers:
        try:
            data, bands = fetcher.fetch(ticker)
            rows.append(analyze(data, bands))
            print(f"  {ticker:6} {rows[-1]['score']:5.1f} {rows[-1]['grade']}  "
                  f"{rows[-1]['profile_label']}", file=sys.stderr)
        except Exception as exc:  # 一只失败不能拖垮整批
            failed.append({"ticker": ticker, "error": str(exc)})
            print(f"  {ticker:6} 失败：{exc}", file=sys.stderr)

    if not rows:
        return 1

    payload = {
        "asof": dt.date.today().isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": f"yfinance {getattr(fetcher.yf, '__version__', '')}".strip(),
        "scanned": len(tickers),
        "rows": sorted(rows, key=lambda r: r["score"], reverse=True),
        "failed": failed,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.print:
        print(text)
    else:
        OUT.write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {OUT.relative_to(ROOT)}（{len(rows)} 只）", file=sys.stderr)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
