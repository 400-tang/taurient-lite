#!/usr/bin/env python3
"""扫描全市场的价量异动，把结果写进仓库供云端任务读取。

**为什么要有这个脚本。** 简报其余部分是新闻驱动的，而新闻天然滞后：
一只票的催化剂先反映在成交量和价格结构上，几天甚至几周之后才成为头条。
等它进入新闻视野，可交易的部分往往已经结束。这个脚本换一层数据——
只吃 OHLCV，不读任何文本——把观察窗口从「新闻发生后」前移到「价量异动时」。

判定逻辑全部在 :mod:`taurient_lite.momentum` 里，是不碰网络的纯函数。
这里只负责三件 I/O：定候选名单、把日线拉回来、把结果写成文件。

**跑在哪。** 和 :mod:`snapshot_market` 同样的理由跑在 GitHub Actions 上：
云端定时任务的沙箱出站受限，连不上 Yahoo；runner 不受限，而 GitHub 又是
沙箱唯一能连通的外部服务，所以让 runner 抓好、提交进仓库，任务 clone 时
带下来。见 .github/workflows/momentum-scan.yml。

用法：

    python3 scan_momentum.py                  # 日常扫描，读 data/universe.txt
    python3 scan_momentum.py --refresh-universe   # 重建流动性名单，每周一次
    python3 scan_momentum.py --limit 200      # 只扫前 200 只，本地调试用
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.config import Config  # noqa: E402
from taurient_lite.momentum import (  # noqa: E402
    MIN_DOLLAR_VOLUME,
    MIN_PRICE,
    MomentumError,
    Signal,
    evaluate,
    parse_chart_bars,
    rank,
)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "momentum_scan.json"
UNIVERSE = ROOT / "data" / "universe.txt"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=1y&interval=1d"
SCREENER = (
    "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    "?scrIds={}&count={}"
)

#: 发现层用的预置筛选器。突破日几乎必然是当日的大涨或大量之一，
#: 所以这几个榜单和「起涨」这件事天然对齐；它们的价值在于能捞到
#: 完全不在名单里的新名字，成本只有几次请求。
SCREENERS = ("day_gainers", "most_actives", "small_cap_gainers")

#: 并发数。给到 6 是在速度和对方限流之间试出来的折中：更高的并发在
#: 上千只的批量里会开始出现 429，反而更慢。
WORKERS = 6

#: 全量名单的来源。Nasdaq 官方的代码目录，纯文本、竖线分隔、无需鉴权。
NASDAQ_LISTS = (
    "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt",
)


# --------------------------------------------------------------------------- 网络


def fetch_json(url: str, timeout: float = 20.0) -> object:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fetch_text(url: str, timeout: float = 30.0) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_signal(ticker: str, *, retries: int = 2) -> Signal | None:
    """取一只票的日线并评估。失败返回 ``None``——批量扫描里单只失败是常态，
    不该让整轮中断；真正的问题会体现在最终的失败计数上。"""
    for attempt in range(retries + 1):
        try:
            return evaluate(parse_chart_bars(ticker, fetch_json(CHART.format(ticker))))
        except MomentumError:
            return None  # 数据不足或结构不对，重试也没用
        except (urllib.error.URLError, OSError, ValueError):
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1) + random.random())
    return None


# --------------------------------------------------------------------------- 名单


def discover() -> list[str]:
    """发现层：从预置筛选器里捞当日异动的代码，包括不在任何名单里的新名字。"""
    found: list[str] = []
    for scr in SCREENERS:
        try:
            payload = fetch_json(SCREENER.format(scr, 100))
            quotes = payload["finance"]["result"][0]["quotes"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError, urllib.error.URLError, OSError, ValueError):
            continue
        found += [q["symbol"] for q in quotes if isinstance(q, dict) and q.get("symbol")]
    return found


def parse_listing(text: str) -> list[str]:
    """从 Nasdaq 代码目录里挑出普通股。

    过滤掉测试证券、ETF，以及带 ``.``/``$`` 的代码——那些是优先股、
    权证、单位这类衍生品种，它们的价量结构跟正股不是一回事。
    """
    lines = [ln for ln in text.splitlines() if "|" in ln]
    if not lines:
        return []
    header = lines[0].split("|")
    rows = [ln.split("|") for ln in lines[1:] if not ln.startswith("File Creation")]

    def col(name: str) -> int | None:
        return header.index(name) if name in header else None

    sym_i = col("Symbol") if col("Symbol") is not None else col("ACT Symbol")
    test_i, etf_i = col("Test Issue"), col("ETF")
    if sym_i is None:
        return []

    out = []
    for row in rows:
        if len(row) <= sym_i:
            continue
        symbol = row[sym_i].strip()
        if not symbol or not symbol.isalnum():
            continue
        if test_i is not None and len(row) > test_i and row[test_i].strip() == "Y":
            continue
        if etf_i is not None and len(row) > etf_i and row[etf_i].strip() == "Y":
            continue
        out.append(symbol)
    return out


def refresh_universe() -> list[str]:
    """重建流动性名单：拉全部上市代码，逐只评估，留下够得着的。

    这一步要发几千次请求，所以**每周跑一次**而不是每天。日常扫描读
    上一次的结果就够了——一只票的流动性不会在一周内发生数量级变化，
    而真正新出现的名字由发现层负责捞回来。
    """
    symbols: list[str] = []
    for url in NASDAQ_LISTS:
        try:
            symbols += parse_listing(fetch_text(url))
        except (urllib.error.URLError, OSError) as exc:
            print(f"取不到 {url}：{exc}", file=sys.stderr)
    symbols = sorted(set(symbols))
    print(f"全部上市普通股 {len(symbols)} 只，开始评估流动性……")

    kept: list[str] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, signal in enumerate(pool.map(fetch_signal, symbols), start=1):
            if signal and signal.dollar_volume >= MIN_DOLLAR_VOLUME and signal.close >= MIN_PRICE:
                kept.append(signal.ticker)
            if i % 500 == 0:
                print(f"  已评估 {i}/{len(symbols)}，达标 {len(kept)}")

    UNIVERSE.parent.mkdir(parents=True, exist_ok=True)
    UNIVERSE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"写入 {UNIVERSE}：{len(kept)} 只达标")
    return kept


def load_universe(config: Config) -> list[str]:
    """日常扫描的名单：流动性名单 + 发现层 + 自选股。三者取并集。"""
    base: list[str] = []
    if UNIVERSE.exists():
        base = [ln.strip() for ln in UNIVERSE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    else:
        print("还没有 data/universe.txt，本轮只扫发现层和自选股；", file=sys.stderr)
        print("跑一次 --refresh-universe 建立流动性名单。", file=sys.stderr)

    merged = dict.fromkeys(base + discover() + list(config.watchlist) + list(config.mag7))
    return list(merged)


# --------------------------------------------------------------------------- 主流程


def scan(symbols: list[str]) -> tuple[list[Signal], int]:
    signals: list[Signal] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, signal in enumerate(pool.map(fetch_signal, symbols), start=1):
            if signal:
                signals.append(signal)
            if i % 500 == 0:
                print(f"  已扫 {i}/{len(symbols)}")
    return signals, len(symbols) - len(signals)


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描全市场价量异动")
    parser.add_argument("--refresh-universe", action="store_true", help="重建流动性名单（每周一次）")
    parser.add_argument("--limit", type=int, default=None, help="只扫前 N 只，调试用")
    parser.add_argument("--top", type=int, default=40, help="写进结果的候选数量上限")
    args = parser.parse_args()

    config = Config.load(ROOT / "config.json")

    if args.refresh_universe:
        refresh_universe()

    symbols = load_universe(config)
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"本轮扫描 {len(symbols)} 只")

    signals, failed = scan(symbols)
    if not signals:
        print("一只都没扫到，不写结果——宁可让页面少一个板块，", file=sys.stderr)
        print("也不要留一份空的或过期的文件冒充当天的扫描。", file=sys.stderr)
        return 1

    ranked = rank(signals, limit=args.top)
    counts: dict[str, int] = {}
    for s in rank(signals):
        counts[s.stage] = counts.get(s.stage, 0) + 1

    payload = {
        "scanned_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": max(s.date for s in signals).isoformat(),
        "note": (
            "由 GitHub Actions 扫描并提交，供云端定时任务读取。stage 只描述这只票"
            "走到这波的第几天，score 衡量的是「有多早」而不是「有多好」——回测显示"
            "本模块无法预测后续涨跌，它的用途是把观察窗口前移，不是给出买卖信号。"
        ),
        "universe_size": len(symbols),
        "evaluated": len(signals),
        "failed": failed,
        "counts": counts,
        "candidates": [s.as_dict() for s in ranked],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"写入 {OUT}")
    print(f"  评估 {len(signals)} 只，失败 {failed} 只，数据日期 {payload['asof']}")
    print(f"  分档：{counts}")
    for s in ranked[:10]:
        age = "—" if s.breakout_age is None else f"{s.breakout_age}日"
        print(
            f"  {s.ticker:6s} {s.stage_label:4s} {s.close:8.2f} "
            f"{s.change_pct:+6.2f}% 量{s.rvol:4.1f}x 突破{age} 乖离{s.ext_ma20:+.0%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
