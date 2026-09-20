#!/usr/bin/env python3
"""把行情与空头持仓抓成一份快照，写进仓库供云端任务读取。

**这个脚本存在的唯一理由是网络隔离。** 云端定时任务跑在一个出站白名单
制的沙箱里：除了 Anthropic 自己的 API、包管理器源和 GitHub，其余目的地
在 CONNECT 阶段就被网关 403 拒绝。实测过 Yahoo 和自建的 Render 后端，
待遇完全一样，改账号的网络出口设置也没有让它变通。

所以把取数的方向反过来：让 GitHub Actions 的 runner（外网不受限）在
云端任务开始前把数据抓好、提交进仓库，任务 clone 仓库时数据就跟着
下来了，读文件即可，一次外网都不用发。GitHub 恰好是沙箱唯一能连通的
外部服务，这条路完全在现有权限内。

在 GitHub Actions 里跑（见 .github/workflows/market-snapshot.yml），
也可以本地手动跑来更新快照：

    python3 snapshot_market.py

**时点说明。** Actions 排在 12:30 UTC，也就是美东早上 8:30、开盘前一小时，
这时候拿到的是前一个交易日的收盘价——正是盘前简报该展示的东西。快照里
存的 ``market_time`` 是 Yahoo 自己报的时间戳，不是抓取时刻，所以页面上
「收盘 · 周几 几点」这个标签始终说的是数据的真实时点。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.config import Config  # noqa: E402
from taurient_lite.pipeline import Paths  # noqa: E402
from taurient_lite.short_interest import fetch_many as fetch_si_many  # noqa: E402

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "data" / "market_snapshot.json"


def main() -> int:
    paths = Paths(ROOT)
    config = Config.load(paths.config)

    failures: list[str] = []

    # 空头持仓 FINRA 每月才更新两次，天天抓是浪费，但它便宜，而且顺带
    # 让云端任务在写「轧空」类新闻时也有权威数字可用，不必再自己联网。
    #
    # **这个脚本曾经还抓七巨头行情。** 七巨头板块被整个撤掉之后（首页那个
    # 版面位置换成了板块热力图），行情这一半就没有消费者了，留着只是每天
    # 白打七次 Yahoo。
    records, si_failures = fetch_si_many(config.watchlist)
    failures += si_failures

    if not records:
        print("一条空头持仓都没取到，不写快照——宁可让云端任务少一份数据，",
              file=sys.stderr)
        print("也不要把一份空的或过期的快照留在仓库里冒充新数据。", file=sys.stderr)
        for reason in failures:
            print(f"  {reason}", file=sys.stderr)
        return 1

    payload = {
        "fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "由 GitHub Actions 抓取并提交，供云端定时任务读取——那个沙箱连不了 "
            "FINRA。settlement_date 是数据源自己报的时点，不是抓取时刻。"
        ),
        "short_interest": [
            {
                "symbol": r.symbol,
                "issue_name": r.issue_name,
                "settlement_date": r.settlement_date.isoformat(),
                "current_shares": r.current_shares,
                "previous_shares": r.previous_shares,
                "change_percent": r.change_percent,
                "days_to_cover": r.days_to_cover,
            }
            for r in records
        ],
        "failures": failures,
    }

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"写入 {SNAPSHOT}")
    print(f"  空头持仓 {len(records)} 只")
    for reason in failures:
        print(f"  失败：{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
