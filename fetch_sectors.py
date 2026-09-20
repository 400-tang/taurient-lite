#!/usr/bin/env python3
"""命令行入口：抓全市场的行业分类与市值，算成板块热力数据。

    python3 fetch_sectors.py                  # 写 data/sectors.json
    python3 fetch_sectors.py --apply          # 顺带写进最新一份简报
    python3 fetch_sectors.py --apply 2026-09-10
    python3 fetch_sectors.py --print          # 只打印，不写文件

**一次请求拿到所有东西。** Nasdaq 的 screener 端点一口气返回七千多只
股票的 ``sector`` / ``marketCap`` / ``pctchange``，不需要鉴权，只要带
一个正常的 User-Agent。这是这个板块能成立的前提——按只去查行业分类
要发七千次请求，那就只能是周更的离线任务，而涨跌幅必须是当天的。

和 ``snapshot_market.py`` 同一个理由跑在 GitHub Actions 上：云端定时
任务的沙箱连不了外网，runner 可以。

退出码：0 成功；1 失败（网络错误或数据格式变了）。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import datetime as dt  # noqa: E402

from taurient_lite.pipeline import Paths, PipelineError, latest_date  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "sectors.json"

SCREENER = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=25&download=true"
)

#: Nasdaq 的接口会拒掉没有 User-Agent 的请求，返回一个 HTML 错误页。
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

#: 每个行业保留市值最大的几只。和 ``components.heatmap.MAX_TILES`` 对齐——
#: 多存的部分只会在渲染时被切掉，白白撑大简报 JSON。
TOP_PER_SECTOR = 14

#: 市值下限（美元）。低于这个数的票在树图里连一个色块都占不满，
#: 却会把大公司的块挤小。一亿是「还算个公司」的粗线。
MIN_CAP = 1e8

#: 要丢掉的行业。``Miscellaneous`` 是个杂项筐，里面什么都有，
#: 画成一个板块会让读者以为它是个真实的行业分类。
SKIP_SECTORS = {"", "Miscellaneous"}

#: 行业名的中文对照。热力图上的块已经全是英文代码了，
#: 板块名再用英文，整个标签页会变成一块读者要先翻译的区域。
SECTOR_CN = {
    "Technology": "科技",
    "Finance": "金融",
    "Health Care": "医疗保健",
    "Consumer Discretionary": "可选消费",
    "Consumer Staples": "必需消费",
    "Industrials": "工业",
    "Energy": "能源",
    "Real Estate": "房地产",
    "Utilities": "公用事业",
    "Basic Materials": "基础材料",
    "Telecommunications": "电信",
}

NOTE = (
    "块的大小按市值，颜色按当日涨跌幅，行业按当日强弱从左到右排。"
    "行业涨跌是市值加权的：简单平均会让一堆微型股盖过苹果，"
    "得出「科技板块大跌」而指数其实在涨的结论。"
)


def last_trading_day(now: dt.datetime) -> dt.date:
    """数据所属的交易日。

    **不能直接用抓取日期。** screener 在盘前返回的是上一个交易日的收盘数据，
    而页面上写的是「截至 X 收盘」——把抓取日期填进去，周六抓一次就会印出
    「截至周六收盘」这种不存在的时点。``momentum.py`` 里记过同一个教训：
    一个没有限定的涨跌幅必然被读成「今天的」。

    工作流排在 12:30 UTC（美东 8:30，开盘前），所以规则是：往前找最近的
    一个工作日，周一往前退到周五。

    **已知局限：不认节假日。** 感恩节这类休市日会把 asof 标成休市当天，
    差一天。要修得准就得引入交易日历，而那是一份需要每年维护的数据；
    在「标注可能差一天」和「引入一个会过期的依赖」之间，这里选了前者，
    并把这个取舍写在这儿，免得以后有人以为是漏写。
    """
    day = now.date()
    # 盘前抓的是昨天的收盘，所以先退一天，再跳过周末。
    day -= dt.timedelta(days=1)
    while day.weekday() >= 5:  # 5=周六, 6=周日
        day -= dt.timedelta(days=1)
    return day


def _num(raw: object) -> float | None:
    """把 ``"$156.47"`` / ``"0.083%"`` / ``"44113407785.00"`` 解析成数字。

    拿不到就返回 None——宁可让一只票缺席热力图，也不要把一个解析失败
    当成 0.0 画成平盘，那是在版面上凭空造一个事实。
    """
    if raw is None:
        return None
    text = str(raw).strip().replace("$", "").replace(",", "").replace("%", "")
    if not text or text in {"--", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_rows() -> list[dict]:
    """拉一次 screener，返回原始行。"""
    req = urllib.request.Request(SCREENER, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PipelineError(f"抓 Nasdaq screener 失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Nasdaq 返回的不是 JSON，接口可能变了：{exc}") from exc

    rows = (payload.get("data") or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        raise PipelineError("Nasdaq 返回里没有 data.rows，接口格式可能变了")
    return rows


def build(rows: list[dict]) -> list[dict]:
    """把原始行聚成行业块，每块带市值加权涨跌和前 N 只成分股。"""
    buckets: dict[str, list[dict]] = {}

    for row in rows:
        sector = (row.get("sector") or "").strip()
        if sector in SKIP_SECTORS:
            continue
        cap = _num(row.get("marketCap"))
        chg = _num(row.get("pctchange"))
        ticker = (row.get("symbol") or "").strip().upper()
        if not ticker or cap is None or chg is None or cap < MIN_CAP:
            continue
        # 代码里带 ^ 或 / 的是优先股、权证一类，不是普通股。
        if any(c in ticker for c in "^/$"):
            continue
        name = (row.get("name") or "").strip()
        for suffix in (" Common Stock", " Common Shares", " Ordinary Shares"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        buckets.setdefault(sector, []).append(
            {"ticker": ticker, "name": name.strip(), "change_pct": round(chg, 2),
             "market_cap": cap}
        )

    out = []
    for sector, members in buckets.items():
        total_cap = sum(m["market_cap"] for m in members)
        if total_cap <= 0:
            continue
        weighted = sum(m["change_pct"] * m["market_cap"] for m in members) / total_cap
        top = sorted(members, key=lambda m: -m["market_cap"])[:TOP_PER_SECTOR]
        out.append(
            {
                "name": SECTOR_CN.get(sector, sector),
                "change_pct": round(weighted, 2),
                "market_cap": total_cap,
                "tiles": top,
            }
        )

    return sorted(out, key=lambda s: -s["market_cap"])


def main(argv: list[str]) -> int:
    args = [a for a in argv if a not in {"--print", "--apply"}]
    print_only = "--print" in argv
    apply = "--apply" in argv

    try:
        sectors = build(fetch_rows())
    except PipelineError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    if not sectors:
        print("错误：一个行业都没聚出来，筛选条件可能过严", file=sys.stderr)
        return 1

    now = dt.datetime.now()
    block = {
        "asof": last_trading_day(now).isoformat(),
        "fetched_at": now.isoformat(timespec="seconds"),
        "source": "Nasdaq screener",
        "note": NOTE,
        "sectors": sectors,
    }

    for s in sectors:
        cap = s["market_cap"] / 1e12
        print(f"{s['name']:>6}  {s['change_pct']:+6.2f}%  "
              f"市值 {cap:6.2f} 万亿  {len(s['tiles'])} 只")

    if print_only:
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(block, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"\n已写入 {OUT}")

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
