"""FINRA 空头持仓数据：官方一手来源，替代二手网站互相矛盾的百分比。

背景：不同财经网站报的空头占比经常对不上（同一只票，有的说 28%，
有的说 34%），根源是它们都从同一份 FINRA 数据衍生，只是抓取和刷新的
时间点不同。FINRA 自己按 Rule 4560 每月两次收集全市场（不只是 OTC）
的空头持仓，是这些数字的唯一源头。直接查它，就不会有「哪家网站更准」
这种伪问题——只有「这是哪个结算日的快照」这个真问题，而这个日期
FINRA 会明确告诉你。

**这里刻意不算「占流通盘百分比」。** 那需要股本数据，而 Yahoo 现有
的行情端点不提供这个字段，另开一个端点又会重新引入「未文档接口随时
可能挂」的老问题——为了一个衍生指标去多接一个不稳定的源头不划算。
FINRA 自己发布的是原始股数、较上期的变化、以及回补天数，这些已经是
比二手网站的百分比更可信的东西，如实呈现就够了。

**接口不是文档化的公开 API，是通过实测确认的。** FINRA 官方 PDF 文档
只详细写了 OTC 专属那个数据集（``group/otcMarket/name/EquityShortInterest``），
覆盖全市场（含纽交所、纳斯达克）的数据集实际叫
``group/otcMarket/name/consolidatedShortInterest``，这是逐字段试出来的，
不是官方文档白纸黑字写的，所以字段名如果哪天变动这里会直接报错而不是
悄悄返回错的数字——这跟 ``quotes.py`` 对 Yahoo 端点的态度一致。
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Sequence

ENDPOINT = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

#: 一次性拉够长的历史（FINRA 每月两次），确保客户端能在返回结果里找到
#: 真正最新的一期——接口不支持在不知道具体日期的情况下按日期排序
#: （实测过，指定 sortFields 但不把 settlementDate 也设成 EQUAL 会报 400），
#: 所以策略是拉一个足够大的样本，本地取 settlementDate 最大的一条。
DEFAULT_LOOKBACK_RECORDS = 400

#: 面向人的引用页面，不是原始 JSON 端点——点开能看到搜索框，
#: 比甩一个 API 链接给读者更有用。
CITATION_URL = "https://www.finra.org/finra-data/browse-catalog/equity-short-interest/data"


class ShortInterestError(RuntimeError):
    """取数或解析失败。"""


@dataclass(frozen=True, slots=True)
class ShortInterestRecord:
    """一期结算的空头持仓快照。"""

    symbol: str
    issue_name: str
    settlement_date: dt.date
    current_shares: int
    previous_shares: int
    change_percent: float
    days_to_cover: float
    avg_daily_volume: int

    @property
    def change_shares(self) -> int:
        return self.current_shares - self.previous_shares

    def as_citation(self) -> str:
        """一句话摘要，附结算日，供写进新闻条目的 body 或 note。"""
        sign = "+" if self.change_percent >= 0 else ""
        return (
            f"{self.symbol} 空头持仓 {self.current_shares:,} 股"
            f"（{self.settlement_date.isoformat()} 结算，较上期 {sign}{self.change_percent:.2f}%，"
            f"回补天数 {self.days_to_cover:.2f}）"
        )


def _parse_record(symbol: str, raw: dict) -> ShortInterestRecord:
    try:
        return ShortInterestRecord(
            symbol=str(raw["symbolCode"]),
            issue_name=str(raw["issueName"]),
            settlement_date=dt.date.fromisoformat(raw["settlementDate"]),
            current_shares=int(raw["currentShortPositionQuantity"]),
            previous_shares=int(raw["previousShortPositionQuantity"]),
            change_percent=float(raw["changePercent"]),
            days_to_cover=float(raw["daysToCoverQuantity"]),
            avg_daily_volume=int(raw["averageDailyVolumeQuantity"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ShortInterestError(
            f"{symbol}：响应记录字段缺失或格式不对（{exc}）"
        ) from exc


def parse_records(symbol: str, payload: object) -> list[ShortInterestRecord]:
    """把 FINRA 的响应体解析成记录列表。

    真实响应有三种形状：一个 JSON 数组（正常情况，可能为空）、一个带
    ``statusCode`` 的错误对象（请求本身被拒，比如字段名写错）、或者
    HTTP 204 时完全没有响应体（无匹配数据，:func:`fetch_json` 会把它
    转成 ``[]`` 再传进来）。
    """
    if isinstance(payload, dict) and "statusCode" in payload:
        message = payload.get("message", "未知错误")
        raise ShortInterestError(f"{symbol}：FINRA 拒绝了这个请求（{message}）")
    if not isinstance(payload, list):
        raise ShortInterestError(f"{symbol}：响应不是预期的数组，实际是 {type(payload).__name__}")
    return [_parse_record(symbol, row) for row in payload]


def fetch_json(url: str, body: dict, timeout: float = 20.0) -> object:
    """发一次 POST，唯一碰网络的地方。204 No Content 当作空数组处理。"""
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status == 204:
            return []
        raw = response.read()
        return json.loads(raw) if raw else []


def _query_body(symbol: str, limit: int) -> dict:
    return {
        "compareFilters": [
            {"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": symbol}
        ],
        "limit": limit,
    }


def fetch_latest(
    symbol: str,
    *,
    lookback: int = DEFAULT_LOOKBACK_RECORDS,
    retries: int = 3,
    fetcher: Callable[[str, dict], object] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
) -> ShortInterestRecord:
    """取一只股票最新一期的空头持仓。失败时退避重试。"""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            payload = fetcher(ENDPOINT, _query_body(symbol, lookback))
            records = parse_records(symbol, payload)
            if not records:
                raise ShortInterestError(f"{symbol}：FINRA 没有这只股票的空头持仓记录")
            return max(records, key=lambda r: r.settlement_date)
        except (urllib.error.URLError, OSError, ValueError, ShortInterestError) as exc:
            last = exc
            if attempt < retries - 1:
                sleep(1.5 * (attempt + 1))
    raise ShortInterestError(f"{symbol} 取空头持仓失败：{last}")


def fetch_many(
    symbols: Sequence[str],
    *,
    fetcher: Callable[[str, dict], object] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[ShortInterestRecord], list[str]]:
    """批量取，允许部分失败，返回 (成功记录, 失败原因)。"""
    records: list[ShortInterestRecord] = []
    failures: list[str] = []
    for symbol in symbols:
        try:
            records.append(fetch_latest(symbol, fetcher=fetcher, sleep=sleep))
        except ShortInterestError as exc:
            failures.append(str(exc))
    return records, failures
