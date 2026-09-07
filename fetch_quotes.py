#!/usr/bin/env python3
"""抓取七巨头（以及自选股）的收盘价与单日涨跌，写进当天的简报 JSON。

    python3 fetch_quotes.py 2026-09-06        # 写入 briefs/2026-09-06.json 的 mag7 字段
    python3 fetch_quotes.py --print NVDA TSLA # 只打印，不写文件

数据来自 Yahoo Finance 的 chart 端点。这是个未文档化的公开接口，不需要 API key，
被广泛使用但不受官方支持，有可能被限流或改动。它比抓网页强的地方在于返回结构化
JSON，并且带 regularMarketTime 时间戳，所以数据时点是数据自己说的，不是我们推断的。
真要一个有 SLA 的源，就换成 Polygon 或 Finnhub，把 quote() 换掉即可，其余不用动。
"""

import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRIEFS = ROOT / "briefs"
CONFIG = ROOT / "config.json"

ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=1d&interval=1d"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
ET = dt.timezone(dt.timedelta(hours=-4))          # 收盘时点按美东显示


def quote(ticker, retries=3):
    """返回 (price, change_pct, market_time_epoch)。失败时抛异常。"""
    url = ENDPOINT.format(ticker)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                meta = json.load(r)["chart"]["result"][0]["meta"]
            return (
                round(float(meta["regularMarketPrice"]), 2),
                round(float(meta["regularMarketChangePercent"]), 2),
                int(meta["regularMarketTime"]),
            )
        except (urllib.error.URLError, KeyError, TypeError, ValueError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{ticker} 取价失败：{last}")


def asof_label(epoch):
    t = dt.datetime.fromtimestamp(epoch, ET)
    return f"收盘 · {t.strftime('%a %-m/%-d')} {t.strftime('%H:%M')} ET"


def main():
    argv = sys.argv[1:]
    if "--print" in argv:
        tickers = [a for a in argv if a != "--print"]
        for t in tickers:
            p, c, ts = quote(t)
            print(f"{t:6} ${p:>9,.2f}  {c:+.2f}%   {asof_label(ts)}")
        return

    if not argv:
        found = sorted(BRIEFS.glob("*.json"))
        if not found:
            sys.exit("briefs/ 里没有任何 JSON")
        date = found[-1].stem
    else:
        date = argv[0]

    target = BRIEFS / f"{date}.json"
    if not target.exists():
        sys.exit(f"找不到 {target}，先写好当天的简报 JSON 再跑这个。")

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    brief = json.loads(target.read_text(encoding="utf-8"))

    rows, stamps, failed = [], [], []
    for t in cfg["mag7"]:
        try:
            price, chg, ts = quote(t)
        except RuntimeError as exc:
            failed.append(str(exc))
            continue
        rows.append({"ticker": t, "price": f"{price:,.2f}", "change_pct": chg})
        stamps.append(ts)

    if not rows:
        sys.exit("一个都没取到，检查网络或者端点是否还可用。\n" + "\n".join(failed))

    m7 = brief.get("mag7", {})
    m7["rows"] = rows
    m7["asof"] = asof_label(max(stamps))
    m7["source"] = "Yahoo Finance chart endpoint"
    brief["mag7"] = m7

    target.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    up = sum(1 for r in rows if r["change_pct"] >= 0)
    print(f"写入 {target}")
    print(f"  {len(rows)} 只，{up} 涨 {len(rows)-up} 跌，{m7['asof']}")
    for r in sorted(rows, key=lambda x: x["change_pct"], reverse=True):
        print(f"    {r['ticker']:6} ${r['price']:>10}  {r['change_pct']:+.2f}%")
    for f in failed:
        print(f"  取价失败：{f}")


if __name__ == "__main__":
    main()
