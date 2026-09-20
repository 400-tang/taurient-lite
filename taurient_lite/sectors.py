"""板块热力的数据层：抓全市场行业分类与市值，聚成行业块。

**一次请求拿到所有东西。** Nasdaq 的 screener 端点一口气返回七千多只股票的
``sector`` / ``marketCap`` / ``pctchange``，不需要鉴权，只要带一个正常的
User-Agent。这是这个板块能成立的前提——按只去查行业分类要发七千次请求，
那就只能是周更的离线任务，而涨跌幅必须是当天的。

和 :mod:`taurient_lite.quotes` 一样，逻辑放在包里、命令行入口只做参数解析：
后端要在请求时现场取一份实时数据，走的是同一批函数，不必把 CLI 再实现一遍。
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Any

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

#: 美东时区。跟 :mod:`taurient_lite.quotes` 用同一个固定偏移，**同样不处理
#: 夏令时**：冬令时期间判定会早一小时，影响的只是「盘中/收盘」这个措辞，
#: 不影响数字。两处保持一致，将来要修就一起修。
EASTERN = dt.timezone(dt.timedelta(hours=-4))

#: 常规交易时段（美东）。
MARKET_OPEN = dt.time(9, 30)
MARKET_CLOSE = dt.time(16, 0)

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


class SectorError(RuntimeError):
    """抓取或解析失败。消息面向命令行用户，直接打出来就能看懂。"""


def last_trading_day(now: dt.datetime) -> dt.date:
    """``now`` 之前最近一个已经走完的交易日。

    **不能直接用抓取日期。** screener 在盘前返回的是上一个交易日的收盘数据，
    而页面上写的是「截至 X 收盘」——把抓取日期填进去，周六抓一次就会印出
    「截至周六收盘」这种不存在的时点。:mod:`taurient_lite.momentum` 里记过
    同一个教训：一个没有限定的涨跌幅必然被读成「今天的」。

    **已知局限：不认节假日。** 感恩节这类休市日会把日期标成休市当天，
    差一天。要修得准就得引入交易日历，而那是一份需要每年维护的数据；
    在「标注可能差一天」和「引入一个会过期的依赖」之间，这里选了前者，
    并把这个取舍写在这儿，免得以后有人以为是漏写。
    """
    day = now.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:  # 5=周六, 6=周日
        day -= dt.timedelta(days=1)
    return day


def is_market_open(now_et: dt.datetime) -> bool:
    """美东时间 ``now_et`` 是否落在常规交易时段内。"""
    if now_et.weekday() >= 5:
        return False
    return MARKET_OPEN <= now_et.time() < MARKET_CLOSE


def session_of(now: dt.datetime) -> tuple[str, str]:
    """返回 ``(session, asof)``，描述这份数据是什么时点的。

    **这两个值决定页面上那行小字怎么写**，而写错时点比没有时点更糟：
    盘中取到的是还在变的实时价，标成「截至某日收盘」就是在说一个假事实。

    * 交易时段内 → ``("intraday", "14:32 ET")``，页面写「盘中」
    * 其余时间 → ``("close", "2026-09-18")``，页面写「截至 X 收盘」
    """
    now_et = now.astimezone(EASTERN)
    if is_market_open(now_et):
        return "intraday", now_et.strftime("%H:%M ET")
    return "close", last_trading_day(now_et).isoformat()


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


def fetch_rows(timeout: float = 60.0) -> list[dict]:
    """拉一次 screener，返回原始行。"""
    req = urllib.request.Request(SCREENER, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SectorError(f"抓 Nasdaq screener 失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise SectorError(f"Nasdaq 返回的不是 JSON，接口可能变了：{exc}") from exc

    rows = (payload.get("data") or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        raise SectorError("Nasdaq 返回里没有 data.rows，接口格式可能变了")
    return rows


def build_sectors(rows: list[dict]) -> list[dict]:
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


def build_market_block(
    rows: list[dict], now: dt.datetime | None = None
) -> dict[str, Any]:
    """聚成可以直接塞进简报 JSON 的 ``market`` 块。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    sectors = build_sectors(rows)
    if not sectors:
        raise SectorError("一个行业都没聚出来，筛选条件可能过严")

    session, asof = session_of(now)
    return {
        "asof": asof,
        "session": session,
        "fetched_at": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "Nasdaq screener",
        "note": NOTE,
        "sectors": sectors,
    }


def fetch_market_block(now: dt.datetime | None = None) -> dict[str, Any]:
    """抓一次并聚好。网络失败会抛 :class:`SectorError`。"""
    return build_market_block(fetch_rows(), now=now)
