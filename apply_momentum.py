#!/usr/bin/env python3
"""命令行入口：把价量扫描结果写进当天的简报 JSON。

    python3 apply_momentum.py 2026-09-10     # 写入 briefs/2026-09-10.json
    python3 apply_momentum.py                # 最新的一份
    python3 apply_momentum.py --print        # 只打印候选，不写文件

**这个脚本存在的理由是「别让人抄数字」。** 扫描结果里每只标的有七个
数字（价格、涨跌、相对量、突破天数、乖离、自基底涨幅、阶段），人工
从 JSON 抄进 JSON 是纯粹的机械劳动，而且抄错了没有任何东西会报警——
页面照样渲染，只是数字是错的。所以照搬 ``fetch_quotes.py`` 的分工：
**脚本填数字，人写判断**。

具体来说，``coverage``（新闻覆盖度）和 ``note``（一句话）是每日流水线
交叉新闻之后才能填的，机器填不了；已经填好的这两项在重跑时会被原样
保留，只有数字被覆盖。这样「先跑脚本、再补判断、发现漏了再跑一次」
这条最自然的工作流不会把已经写好的东西冲掉。

退出码：0 成功；1 失败（找不到简报或扫描文件）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite.pipeline import Paths, PipelineError, latest_date  # noqa: E402
from taurient_lite.schema import NEWS_COVERAGE  # noqa: E402

ROOT = Path(__file__).resolve().parent
SCAN = ROOT / "data" / "momentum_scan.json"

#: 从扫描结果里原样复制的字段。**只有这些**——其余的属于人的判断。
MECHANICAL = (
    "ticker",
    "stage",
    "close",
    "change_pct",
    "rvol",
    "breakout_age",
    "ext_ma20",
    "run_from_base",
)

#: 每一档最多带几只进简报。初动档全要——它通常只有个位数，而且正是
#: 这个板块存在的理由；延续档取前几只；已延伸只留一两只做参照，
#: 它的作用是让读者认出「这个我已经错过了」，多了就变成噪音。
QUOTA: dict[str, int] = {"ignition": 99, "continuation": 4, "base": 0, "extended": 2}


def pick(candidates: list[dict]) -> list[dict]:
    """按档位配额挑候选，保持扫描结果本身的顺序。"""
    taken: dict[str, int] = {}
    out = []
    for row in candidates:
        stage = row.get("stage", "")
        limit = QUOTA.get(stage, 0)
        if taken.get(stage, 0) >= limit:
            continue
        taken[stage] = taken.get(stage, 0) + 1
        out.append(row)
    return out


def merge(picked: list[dict], existing: list[dict]) -> list[dict]:
    """用扫描结果覆盖数字，保留人已经写好的 ``coverage`` 与 ``note``。"""
    by_ticker = {c.get("ticker"): c for c in existing}
    merged = []
    for row in picked:
        prior = by_ticker.get(row["ticker"], {})
        entry = {k: row[k] for k in MECHANICAL if k in row}
        entry["coverage"] = prior.get("coverage", "none")
        entry["note"] = prior.get("note", "")
        if prior.get("sources"):
            entry["sources"] = prior["sources"]
        merged.append(entry)
    return merged


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]

    if not SCAN.exists():
        print(f"找不到 {SCAN}。", file=sys.stderr)
        print("先跑 python3 scan_momentum.py，或者等 Actions 把扫描结果提交进来。", file=sys.stderr)
        return 1

    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    picked = pick(scan.get("candidates") or [])

    if not picked:
        print("扫描结果里没有够格的候选，今天不写 momentum 块。")
        print("这是正常结果：多数交易日没有新的突破，页面会自动不显示这个标签页。")
        return 0

    if "--print" in argv:
        for row in picked:
            age = "—" if row.get("breakout_age") is None else f"{row['breakout_age']}日"
            print(
                f"  {row['ticker']:6s} {row['stage']:12s} {row['close']:9.2f} "
                f"{row['change_pct']:+6.2f}%  量{row['rvol']:4.1f}x  突破{age}  "
                f"乖离{row['ext_ma20']:+.0%}"
            )
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

    brief = json.loads(target.read_text(encoding="utf-8"))
    prior_block = brief.get("momentum") or {}
    candidates = merge(picked, prior_block.get("candidates") or [])

    brief["momentum"] = {
        "asof": scan.get("asof", ""),
        "scanned": scan.get("universe_size", 0),
        # 这一句是人写的当天解读，脚本只在它还不存在时留空。
        "note": prior_block.get("note", ""),
        "candidates": candidates,
    }
    target.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    kept: dict[str, int] = {}
    for row in candidates:
        kept[row["stage"]] = kept.get(row["stage"], 0) + 1
    missing = [c["ticker"] for c in candidates if c["coverage"] not in NEWS_COVERAGE or not c["note"]]

    print(f"写入 {target}")
    print(f"  数据日期 {brief['momentum']['asof']}，扫描 {brief['momentum']['scanned']} 只")
    print(f"  带入候选 {len(candidates)} 只：{kept}")
    if missing:
        print(f"  还需要你补 coverage 与 note：{'、'.join(missing)}")
        print("  coverage 依据是「今天扫的新闻里这个代码出现过没有」，别为此专门再搜一轮。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
