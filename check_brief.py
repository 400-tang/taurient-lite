#!/usr/bin/env python3
"""命令行入口：发布前的质量门。

    python3 check_brief.py 2026-09-25     # 检查指定日期
    python3 check_brief.py                # 检查最新的一份
    python3 check_brief.py 2026-09-25 --no-market
                                          # 板块热力确实取不到时，跳过这一项

``--no-market`` 是唯一的豁免开关，而且必须显式写出来：数据源挂了是真实会
发生的事，这时正确的做法是少一个板块照常发布，而不是手填数字凑过质量门。

规则全在 :mod:`taurient_lite.quality` 里，这里只负责读文件、打印、给退出码。

退出码：0 全部通过，可以发布；1 有问题，逐条列出，改完再跑；
2 简报本身读不进来（找不到、JSON 坏了、结构校验没过）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.config import Config  # noqa: E402
from taurient_lite.pipeline import Paths, PipelineError, latest_date, load_brief  # noqa: E402
from taurient_lite.quality import check  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    paths = Paths(ROOT)
    no_market = "--no-market" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    try:
        date = args[0] if args else latest_date(paths)
        brief = load_brief(paths, date)
    except PipelineError as exc:
        print(f"读不进简报：{exc}", file=sys.stderr)
        return 2

    raw = json.loads(paths.brief_json(date).read_text(encoding="utf-8"))
    problems = check(brief, raw, Config.load(paths.config))
    if no_market:
        problems = [p for p in problems if not p.path.startswith("market")]

    if not problems:
        print(f"✓ {date} 通过质量门，可以发布")
        return 0

    print(f"✗ {date} 有 {len(problems)} 个问题，改完再跑一次：")
    for problem in problems:
        print(f"  {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
