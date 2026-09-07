#!/usr/bin/env python3
"""把 TradingView 导出的自选股列表导进 config.json。

TradingView 那边的操作：打开自选列表 → Advanced view → Download list as TXT。
拿到的文件是逗号分隔的符号，通常带交易所前缀，例如：

    ###AI,NASDAQ:NVDA,NASDAQ:TSLA,NYSE:BRK.B

用法：
    python3 import_watchlist.py ~/Downloads/watchlist.txt
    python3 import_watchlist.py ~/Downloads/watchlist.txt --replace

默认是合并进现有列表；--replace 则整个覆盖。

Robinhood 那边没有对应的功能。到 2026 年它仍然没有公开的股票 API，
唯一开放的是加密货币交易 API，股票端点从未文档化且服务条款禁止自动化访问。
所以自选股只能走 TradingView 导出或者直接手工编辑 config.json。
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"

# 交易所前缀、分节标题（###AI 这种）、以及空白都要剥掉。
SECTION = re.compile(r"^###")
VALID = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def parse(text):
    symbols, skipped = [], []
    for raw in re.split(r"[,\n\r\t]+", text):
        tok = raw.strip().upper()
        if not tok or SECTION.match(tok):
            continue
        if ":" in tok:                      # NASDAQ:NVDA → NVDA
            tok = tok.split(":", 1)[1]
        if VALID.match(tok):
            if tok not in symbols:
                symbols.append(tok)
        else:
            skipped.append(tok)
    return symbols, skipped


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    replace = "--replace" in sys.argv

    if not args:
        sys.exit(__doc__)

    src = Path(args[0]).expanduser()
    if not src.exists():
        sys.exit(f"找不到文件：{src}")

    found, skipped = parse(src.read_text(encoding="utf-8", errors="replace"))
    if not found:
        sys.exit("这个文件里没解析出任何有效的股票代码，确认一下是不是 TradingView 导出的 TXT。")

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    old = cfg["watchlist"]["symbols"]

    if replace:
        merged = found
    else:
        merged = old + [s for s in found if s not in old]

    cfg["watchlist"]["symbols"] = merged
    cfg["watchlist"]["source"] = f"tradingview:{src.name}"
    CONFIG.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    added = [s for s in merged if s not in old]
    dropped = [s for s in old if s not in merged]

    print(f"解析出 {len(found)} 个代码，自选股现在共 {len(merged)} 个。")
    if added:
        print(f"  新增：{', '.join(added)}")
    if dropped:
        print(f"  移除：{', '.join(dropped)}")
    if skipped:
        print(f"  跳过了 {len(skipped)} 个无法识别的条目：{', '.join(skipped[:8])}")
    print(f"\n已写入 {CONFIG}。下一次生成简报时会针对这些代码单独跑查询。")


if __name__ == "__main__":
    main()
