#!/usr/bin/env python3
"""命令行入口：抓七巨头收盘价，写进当天的简报 JSON。

    python3 fetch_quotes.py 2026-09-06        # 写入 briefs/2026-09-06.json
    python3 fetch_quotes.py                   # 最新的一份
    python3 fetch_quotes.py --print NVDA TSLA # 只打印，不写文件

数据来自 Yahoo Finance 的 chart 端点，不需要 API key。这个端点未受官方
支持，可能被限流或改动；取不到就跳过 mag7 板块，**绝不手填数字**。

退出码：0 成功；1 失败（找不到简报、一只都没取到）。部分失败仍返回 0，
失败的那几只会打在输出里。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.config import Config  # noqa: E402
from taurient_lite.pipeline import Paths, PipelineError, latest_date  # noqa: E402
from taurient_lite.quotes import (  # noqa: E402
    QuoteError,
    asof_label,
    build_mag7_block,
    fetch_from_backend,
    fetch_many,
    fetch_quote,
)

ROOT = Path(__file__).resolve().parent


def print_only(tickers: list[str]) -> int:
    """只打印报价，不碰任何文件。用来快速验证端点还活着。"""
    if not tickers:
        print("--print 后面要跟至少一个股票代码", file=sys.stderr)
        return 1
    failed = False
    for ticker in tickers:
        try:
            quote = fetch_quote(ticker)
        except QuoteError as exc:
            print(f"{ticker:6} {exc}", file=sys.stderr)
            failed = True
            continue
        print(
            f"{quote.ticker:6} ${quote.price:>9,.2f}  {quote.change_pct:+.2f}%   "
            f"{asof_label(quote.market_time)}"
        )
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]

    if "--print" in argv:
        return print_only(args)

    paths = Paths(ROOT)
    config = Config.load(paths.config)

    if not config.mag7:
        print("config.json 里的 mag7 是空的，没有要抓的代码", file=sys.stderr)
        return 1

    try:
        date = args[0] if args else latest_date(paths)
    except PipelineError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    target = paths.brief_json(date)
    if not target.exists():
        print(f"找不到 {target}，先写好当天的简报 JSON 再跑这个。", file=sys.stderr)
        return 1

    quotes, failures = fetch_many(config.mag7)
    source = "直连 Yahoo"

    # 直连全军覆没时改问 Render 后端要。云端定时任务的沙箱把出站流量
    # 限制成「仅包管理器」，直连 Yahoo 必然 403；后端跑在普通云主机上，
    # 外网不受限，同一份取数逻辑它那边能跑通。
    if not quotes and config.backend_url:
        print("直连全部失败，改从后端取数……", file=sys.stderr)
        for reason in failures:
            print(f"  {reason}", file=sys.stderr)
        try:
            quotes, failures = fetch_from_backend(config.backend_url)
            source = f"后端 {config.backend_url}"
        except (QuoteError, OSError, ValueError) as exc:
            print(f"后端取数也失败：{exc}", file=sys.stderr)

    if not quotes:
        print("一只都没取到，检查网络或者端点是否还可用。", file=sys.stderr)
        for reason in failures:
            print(f"  {reason}", file=sys.stderr)
        return 1

    brief = json.loads(target.read_text(encoding="utf-8"))
    brief["mag7"] = build_mag7_block(quotes, brief.get("mag7"))
    target.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    up = sum(1 for q in quotes if q.change_pct >= 0)
    print(f"写入 {target}（数据来自{source}）")
    print(f"  {len(quotes)} 只，{up} 涨 {len(quotes) - up} 跌，{brief['mag7']['asof']}")
    for quote in sorted(quotes, key=lambda q: q.change_pct, reverse=True):
        print(f"    {quote.ticker:6} ${quote.price:>10,.2f}  {quote.change_pct:+.2f}%")
    for reason in failures:
        print(f"  取价失败：{reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
