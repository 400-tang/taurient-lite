#!/usr/bin/env python3
"""命令行入口：把基本面扫描结果写进当天的简报 JSON。

    python3 apply_fundamentals.py 2026-09-10     # 写入 briefs/2026-09-10.json
    python3 apply_fundamentals.py                # 最新的一份
    python3 apply_fundamentals.py --print        # 只打印，不写文件

和 ``apply_momentum.py`` 同一个分工：**脚本填数字，人写判断**。每只标的的
分数、七步结论、红旗都由 ``scan_fundamentals.py`` 算好，这里原样抄进简报；
``note``（一句人写的判断）在重跑时保留，不会被冲掉。

**为什么每天都要抄一份，明明财报一季度才变一次。** 因为简报 JSON 是唯一的
真相来源——网页和 Markdown 存档都只从它生成。今天的存档里如果没有这一块，
一年后回看就不知道「那天页面上显示的基本面是什么」。

退出码：0 成功；1 失败（找不到简报或扫描文件，或扫描结果过期）。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.pipeline import Paths, PipelineError, latest_date  # noqa: E402

ROOT = Path(__file__).resolve().parent
SCAN = ROOT / "data" / "fundamentals_scan.json"

#: 扫描结果允许比简报旧几天。扫描每周跑一次，14 天能扛过一次 Actions 失败；
#: 再旧就说明扫描环节坏了一阵子，那更该让板块消失以引起注意。财报本身一季度
#: 才变，但**市值**每天在变——估值位置、PE、FCF 收益率都依赖它，太旧的扫描
#: 会把两周前的估值当成今天的。
MAX_AGE_DAYS = 14

#: 从扫描结果原样复制的字段。**只有这些**——note 属于人的判断。
MECHANICAL = (
    "ticker",
    "name",
    "profile",
    "profile_label",
    "fiscal_end",
    "currency",
    "score",
    "raw_score",
    "grade",
    "verdict",
    "coverage",
    "gate_warnings",
    "flags",
    "stages",
    "valuation",
)


def merge(rows: list[dict], existing: list[dict]) -> list[dict]:
    """用扫描结果覆盖数字，保留人已经写好的 ``note``。"""
    notes = {r.get("ticker"): r.get("note", "") for r in existing}
    merged = []
    for row in rows:
        entry = {k: row[k] for k in MECHANICAL if k in row}
        entry["note"] = notes.get(row["ticker"], "")
        merged.append(entry)
    return merged


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]

    if not SCAN.exists():
        print(f"找不到 {SCAN}。", file=sys.stderr)
        print("先跑 python3 scan_fundamentals.py，或者等 Actions 把扫描结果提交进来。",
              file=sys.stderr)
        return 1

    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    rows = scan.get("rows") or []
    if not rows:
        print("扫描结果里没有任何标的，不写 fundamentals 块。", file=sys.stderr)
        return 1

    if "--print" in argv:
        for r in rows:
            flags = f"  红旗×{len(r['flags'])}" if r.get("flags") else ""
            print(f"  {r['ticker']:6s} {r['score']:5.1f} {r['grade']}  "
                  f"{r.get('profile_label', ''):8s} 财年止于 {r.get('fiscal_end', '')}{flags}")
        return 0

    paths = Paths(ROOT)
    try:
        date = args[0] if args else latest_date(paths)
    except PipelineError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    target = paths.brief_json(date)
    if not target.exists():
        print(f"找不到 {target}，先写好当天的简报 JSON 再跑这个。", file=sys.stderr)
        return 1

    asof = scan.get("asof", "")
    try:
        age = (dt.date.fromisoformat(date) - dt.date.fromisoformat(asof)).days
    except ValueError:
        age = None
    if age is not None and age > MAX_AGE_DAYS:
        print(f"扫描结果是 {asof} 的，比简报日期 {date} 早了 {age} 天，", file=sys.stderr)
        print(f"超过 {MAX_AGE_DAYS} 天上限——不写进简报。", file=sys.stderr)
        print("先查 GitHub Actions 的「基本面扫描」是不是挂了。", file=sys.stderr)
        return 1

    brief = json.loads(target.read_text(encoding="utf-8"))
    prior = brief.get("fundamentals") or {}
    merged = merge(rows, prior.get("rows") or [])

    brief["fundamentals"] = {
        "asof": asof,
        "scanned": scan.get("scanned", len(rows)),
        "source": scan.get("source", ""),
        "note": prior.get("note", ""),
        "rows": merged,
    }
    target.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"写入 {target}")
    print(f"  扫描日期 {asof}，带入 {len(merged)} 只")
    failed = scan.get("failed") or []
    if failed:
        print(f"  扫描时失败：{'、'.join(f['ticker'] for f in failed)}（页面不会显示它们）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
