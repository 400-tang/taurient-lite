#!/usr/bin/env python3
"""命令行入口：抓全市场的行业分类与市值，算成板块热力数据。

    python3 fetch_sectors.py                  # 写 data/sectors.json
    python3 fetch_sectors.py --apply          # 顺带写进最新一份简报
    python3 fetch_sectors.py --apply 2026-09-18
    python3 fetch_sectors.py --print          # 只打印，不写文件

真正的逻辑全在 :mod:`taurient_lite.sectors` 里，这里只负责解析参数、打印
结果、把异常翻译成人能看懂的退出信息——跟 ``fetch_quotes.py`` 同一个分工。
后端要现场抓一份实时数据时走的是同一批函数，不必把这段再实现一遍。

和 ``snapshot_market.py`` 同一个理由跑在 GitHub Actions 上：云端定时任务的
沙箱连不了外网，runner 可以。

退出码：0 成功；1 失败（网络错误或数据格式变了）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.pipeline import Paths, PipelineError, latest_date  # noqa: E402
from taurient_lite.sectors import SectorError, fetch_market_block  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "sectors.json"


def main(argv: list[str]) -> int:
    args = [a for a in argv if a not in {"--print", "--apply"}]
    print_only = "--print" in argv
    apply = "--apply" in argv

    try:
        block = fetch_market_block()
    except SectorError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    for s in block["sectors"]:
        cap = s["market_cap"] / 1e12
        print(f"{s['name']:>6}  {s['change_pct']:+6.2f}%  "
              f"市值 {cap:6.2f} 万亿  {len(s['tiles'])} 只")
    print(f"\n时点：{block['session']} · {block['asof']}")

    if print_only:
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(block, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"已写入 {OUT}")

    if apply:
        paths = Paths(ROOT)
        try:
            date = args[0] if args else latest_date(paths)
        except PipelineError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        target = paths.brief_json(date)
        if not target.exists():
            print(f"错误：找不到 {target}", file=sys.stderr)
            return 1
        brief = json.loads(target.read_text(encoding="utf-8"))
        brief["market"] = block
        target.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print(f"已写入 {target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
