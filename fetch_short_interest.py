#!/usr/bin/env python3
"""命令行入口：查一只或几只股票在 FINRA 的最新空头持仓快照。

    python3 fetch_short_interest.py AI PATH      # 查指定的几只
    python3 fetch_short_interest.py              # 查 config.json 里的自选股

这是个研究/核实工具，不是像 apply_momentum.py 那样自动写进简报 JSON 的
固定板块——空头持仓只在某条新闻本身是「轧空」「仓位拥挤」这类主题时
才用得上，不是每天都要展示的东西。用法是：写新闻条目时，如果涉及
空头仓位，先跑这个查到权威数字，把输出里的引用文字和来源链接手动
填进那条新闻的 body 和 sources 里。

数据来自 FINRA 的 consolidatedShortInterest 数据集，覆盖全市场（不只是
OTC），每月更新两次。免费、公开、不需要 key，但这个数据集名字是实测
确认的，不在 FINRA 的公开文档里逐字写明——接口形状如果变了，这里会
报错而不是悄悄吐出错的数字。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.config import Config  # noqa: E402
from taurient_lite.pipeline import Paths  # noqa: E402
from taurient_lite.short_interest import (  # noqa: E402
    CITATION_URL,
    ShortInterestError,
    fetch_many,
)

ROOT = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    symbols = [s.upper() for s in argv[1:]]

    if not symbols:
        config = Config.load(Paths(ROOT).config)
        symbols = list(config.watchlist)
        if not symbols:
            print("没传股票代码，config.json 里的自选股也是空的。", file=sys.stderr)
            return 1

    records, failures = fetch_many(symbols)

    for record in sorted(records, key=lambda r: r.symbol):
        print(record.as_citation())
        print(f"  发行方：{record.issue_name}")
        print(
            f"  变化：{record.previous_shares:,} -> {record.current_shares:,} 股"
            f"（{record.change_shares:+,}）"
        )
        print(f"  日均成交量：{record.avg_daily_volume:,} 股")
        print(f"  来源：{CITATION_URL}")
        print()

    for reason in failures:
        print(f"取数失败：{reason}", file=sys.stderr)

    return 1 if failures and not records else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
