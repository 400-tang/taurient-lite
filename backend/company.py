"""个股的公司信息：简介、关键统计、分析师评级、财报超预期。

**数据源是 Nasdaq，不是 Yahoo。** Yahoo 的 quoteSummary 现在要 crumb 加
cookie，不带就直接 429，拿它当常规数据源等于把页面架在一个随时会塌的
东西上。Nasdaq 这几个端点不需要鉴权，只要一个正常的 User-Agent——和
:mod:`taurient_lite.sectors` 用的是同一个域名，失败模式一致，排查时不用
分两套心智。

**四个端点各取一块，任何一块挂掉都不影响其余。** 页面上这几个板块是
并列的，没有依赖关系；把它们打包成一次「全有或全无」的请求，等于让
最不稳的那个决定整页的成败。所以每块单独抓、单独失败、单独缺席。

网络与解析分开：``parse_*`` 全是纯函数，测试注入一段假响应就能覆盖
全部分支，不联网也不受对方限流影响——和 ``backend.search`` 同一个路数。
"""

from __future__ import annotations

import json
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE = "https://api.nasdaq.com/api"

PROFILE_URL = BASE + "/company/{symbol}/company-profile"
SUMMARY_URL = BASE + "/quote/{symbol}/summary?assetclass=stocks"
RATINGS_URL = BASE + "/analyst/{symbol}/ratings"
EARNINGS_URL = BASE + "/company/{symbol}/earnings-surprise"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

#: 关键统计里要展示的字段，以及中文标签。**顺序就是版面顺序。**
#:
#: 白名单而不是照单全收：这个端点会返回股息支付日、交易所代码这类
#: 对「今天该不该多看一眼」毫无帮助的字段，全列出来只会稀释真正重要的
#: 那几个。缺字段就少一格，不占位——版面上一个写着 N/A 的格子，
#: 传达的信息量是零，占的注意力却和有数字的一样多。
STAT_FIELDS: tuple[tuple[str, str], ...] = (
    ("PreviousClose", "前收盘"),
    ("ShareVolume", "成交量"),
    ("AverageVolume", "平均成交量"),
    ("FiftTwoWeekHighLow", "52 周高/低"),
    ("MarketCap", "市值"),
    ("OneYrTarget", "一年目标价"),
    ("Yield", "股息率"),
    ("AnnualizedDividend", "年化股息"),
)

#: 明显是占位的值，一律当成没有。
BLANKS = {"", "N/A", "n/a", "--", "NA", "0", "$0.00", "0.00%"}


class CompanyError(RuntimeError):
    """抓取或解析失败。调用方决定是降级还是报错。"""


@dataclass(frozen=True, slots=True)
class Profile:
    """公司简介。"""

    name: str = ""
    description: str = ""
    industry: str = ""
    sector: str = ""
    region: str = ""
    url: str = ""

    @property
    def empty(self) -> bool:
        return not (self.description or self.industry or self.sector)


@dataclass(frozen=True, slots=True)
class Ratings:
    """分析师评级。

    **没有买/持有/卖出的百分比分布。** Nasdaq 这个端点只给一个平均评级和
    参与的券商名单，给不了 Robinhood 那种「92% Buy」的环形图。与其按
    券商数量编一个看起来像那么回事的比例，不如把能拿到的如实摆出来。
    """

    mean: str = ""
    count: int = 0
    summary: str = ""
    brokers: tuple[str, ...] = ()
    changes: tuple[dict, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.mean or self.count)


@dataclass(frozen=True, slots=True)
class Quarter:
    """一个季度的财报表现。"""

    fiscal_end: str
    reported: str
    eps: float | None
    consensus: float | None
    surprise_pct: float | None

    @property
    def beat(self) -> bool | None:
        """超预期与否。两个数缺一个就返回 None，不猜。"""
        if self.eps is None or self.consensus is None:
            return None
        return self.eps >= self.consensus


@dataclass(frozen=True, slots=True)
class Company:
    """一只股票的全部公司信息。每块都可能缺席。"""

    symbol: str
    profile: Profile = field(default_factory=Profile)
    stats: tuple[tuple[str, str], ...] = ()
    ratings: Ratings = field(default_factory=Ratings)
    quarters: tuple[Quarter, ...] = ()

    @property
    def empty(self) -> bool:
        """四块全缺时页面应该整段省掉，而不是渲染一排空标题。"""
        return (
            self.profile.empty and not self.stats
            and self.ratings.empty and not self.quarters
        )


# ------------------------------------------------------------------ 解析


def _val(node: Any) -> str:
    """Nasdaq 把每个字段包成 ``{"label": ..., "value": ...}``，这里只取值。"""
    if isinstance(node, dict):
        node = node.get("value")
    if node is None:
        return ""
    text = str(node).strip()
    return "" if text in BLANKS else text


def _num(raw: Any) -> float | None:
    """解析数字。拿不到返回 None——绝不用 0 顶替，那是在造一个事实。"""
    if raw is None:
        return None
    text = str(raw).strip().replace("$", "").replace(",", "").replace("%", "")
    if not text or text in BLANKS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_profile(payload: Any) -> Profile:
    data = (payload or {}).get("data") or {}
    if not isinstance(data, dict):
        return Profile()
    return Profile(
        name=_val(data.get("CompanyName")),
        description=_val(data.get("CompanyDescription")),
        industry=_val(data.get("Industry")),
        sector=_val(data.get("Sector")),
        region=_val(data.get("Region")),
        url=_val(data.get("CompanyUrl")),
    )


#: 需要压缩成中文数量级的字段。市值动辄十几位数字，原样摆进格子会直接
#: 溢出到隔壁——实测 NVDA 的 5,356,707,000,000 盖住了旁边的一年目标价。
COMPACT_FIELDS = {"MarketCap"}


def compact_number(text: str) -> str:
    """把一长串数字压成「5.36 万亿」这种读得出来的形式。

    解析不出来就原样返回：宁可版面难看一点，也不要因为一个没见过的格式
    把数字改错——这一格里写的是事实，不是装饰。
    """
    value = _num(text)
    if value is None:
        return text
    for scale, unit in ((1e12, "万亿"), (1e8, "亿"), (1e4, "万")):
        if abs(value) >= scale:
            return f"{value / scale:,.2f} {unit}"
    return text


def parse_stats(payload: Any) -> tuple[tuple[str, str], ...]:
    data = ((payload or {}).get("data") or {}).get("summaryData") or {}
    if not isinstance(data, dict):
        return ()
    out = []
    for key, label in STAT_FIELDS:
        value = _val(data.get(key))
        if not value:
            continue
        if key in COMPACT_FIELDS:
            value = compact_number(value)
        out.append((label, value))
    return tuple(out)


def parse_ratings(payload: Any) -> Ratings:
    data = (payload or {}).get("data") or {}
    if not isinstance(data, dict):
        return Ratings()
    brokers = tuple(str(b) for b in (data.get("brokerNames") or []) if b)
    changes = tuple(
        c for c in (data.get("upgradesDowngrades") or []) if isinstance(c, dict)
    )
    return Ratings(
        mean=_val(data.get("meanRatingType")),
        count=len(brokers),
        summary=_val(data.get("ratingsSummary")),
        brokers=brokers,
        changes=changes,
    )


def parse_earnings(payload: Any) -> tuple[Quarter, ...]:
    table = ((payload or {}).get("data") or {}).get("earningsSurpriseTable") or {}
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list):
        return ()
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fiscal = _val(row.get("fiscalQtrEnd"))
        if not fiscal:
            continue
        out.append(
            Quarter(
                fiscal_end=fiscal,
                reported=_val(row.get("dateReported")),
                eps=_num(row.get("eps")),
                consensus=_num(row.get("consensusForecast")),
                surprise_pct=_num(row.get("percentageSurprise")),
            )
        )
    return tuple(out)


# ------------------------------------------------------------------ 抓取


def fetch_json(url: str, timeout: float = 12.0) -> Any:
    """拿一段 JSON。唯一碰网络的地方。"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CompanyError(f"取 {url} 失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise CompanyError(f"{url} 返回的不是 JSON：{exc}") from exc


def fetch_company(symbol: str, timeout: float = 12.0) -> Company:
    """抓齐四块。**任何一块失败都只是那一块缺席**，不影响其余。

    页面上这几个板块是并列的，没有依赖关系。打包成一次「全有或全无」
    的请求，等于让最不稳的那个决定整页的成败。

    **四个请求并发。** 串行跑实测首屏要十秒——四段各两三秒的等待前后相加，
    而它们之间没有任何依赖，纯粹是白等。并发之后总耗时就是最慢的那一个。
    线程而不是异步：这四个调用都是阻塞的 urllib，套一层线程池是标准库里
    最省事的办法，不必为四个请求把整条链路改成 async。
    """
    symbol = symbol.upper()

    def grab(url: str, parse, fallback):
        try:
            return parse(fetch_json(url.format(symbol=symbol), timeout))
        except (CompanyError, KeyError, TypeError, ValueError):
            return fallback

    jobs = (
        (PROFILE_URL, parse_profile, Profile()),
        (SUMMARY_URL, parse_stats, ()),
        (RATINGS_URL, parse_ratings, Ratings()),
        (EARNINGS_URL, parse_earnings, ()),
    )
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        profile, stats, ratings, quarters = list(
            pool.map(lambda job: grab(*job), jobs)
        )

    return Company(
        symbol=symbol,
        profile=profile,
        stats=stats,
        ratings=ratings,
        quarters=quarters,
    )
