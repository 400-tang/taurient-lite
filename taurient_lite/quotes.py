"""行情抓取。

刻意把「拿字节」和「解析字节」分成两个函数：:func:`fetch_json` 碰网络，
:func:`parse_quote` 是纯函数。测试只针对后者，注入一段假响应即可覆盖
所有解析分支，不需要联网，也不会因为对方限流而变成随机失败的测试。

数据源是 Yahoo Finance 的 chart 端点：不需要 API key，返回结构化 JSON，
并且带 ``regularMarketTime``，所以「数据是什么时候的」是数据自己说的，
不是我们从当前日期倒推的。代价是这个端点未受官方支持，可能被限流或改动，
所以 :func:`fetch_many` 允许部分失败并把失败原因带回去，由调用方决定
是跳过整个板块还是继续。**任何情况下都不手填数字。**
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=1d&interval=1d"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

#: 收盘时点按美东呈现。夏令时是 -4，冬令时 -5；这里只用于给人看的标签，
#: 一小时的偏差不影响判断，所以不引入 tz 数据库依赖。
EASTERN = dt.timezone(dt.timedelta(hours=-4))


class QuoteError(RuntimeError):
    """取价失败。"""


@dataclass(frozen=True, slots=True)
class Quote:
    ticker: str
    price: float
    change_pct: float
    market_time: int


def parse_quote(ticker: str, payload: object) -> Quote:
    """从 chart 端点的响应里取出报价。

    对方返回的结构一旦变化，这里会抛 :class:`QuoteError` 而不是产出
    一个看似合理的错误数字——行情错了比没有行情危险得多。
    """
    try:
        meta = payload["chart"]["result"][0]["meta"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise QuoteError(f"{ticker}：响应结构不对，取不到 meta（{exc}）") from exc

    try:
        price = float(meta["regularMarketPrice"])
        change = float(meta["regularMarketChangePercent"])
        stamp = int(meta["regularMarketTime"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QuoteError(f"{ticker}：meta 里的字段缺失或不是数字（{exc}）") from exc

    return Quote(ticker=ticker, price=price, change_pct=change, market_time=stamp)


def fetch_json(url: str, timeout: float = 15.0) -> object:
    """拿一段 JSON。唯一碰网络的地方。"""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


# ----------------------------------------------------------------- 后端回退
#
# 云端定时任务跑在一个网络出口受限的沙箱里：出站流量被强制走一个策略
# 代理，除了包管理器、GitHub 和 Anthropic 自己的 API，其余目的地在
# CONNECT 阶段就被 403 拒绝。直连 Yahoo 在那个环境里必然失败。
#
# 而 Render 上的后端是普通云主机，外网不受限，它已经把同一份取数逻辑
# 暴露成了 /api/quotes/live。所以直连失败时改问后端要，是让「有网的
# 那一端负责取数」——这本来就是当初做这个后端的意义。


def fetch_quote(
    ticker: str,
    *,
    retries: int = 3,
    fetcher: Callable[[str], object] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
) -> Quote:
    """取单只报价，失败时退避重试。

    ``fetcher`` 和 ``sleep`` 都可注入，测试里换成假实现就能覆盖重试路径
    而不真的等待。
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return parse_quote(ticker, fetcher(ENDPOINT.format(ticker)))
        except (urllib.error.URLError, OSError, ValueError, QuoteError) as exc:
            last = exc
            if attempt < retries - 1:
                sleep(1.5 * (attempt + 1))
    raise QuoteError(f"{ticker} 取价失败：{last}")


def fetch_many(
    tickers: Sequence[str],
    *,
    fetcher: Callable[[str], object] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[Quote], list[str]]:
    """批量取价，允许部分失败。

    :return: ``(成功的报价, 失败原因)``。一只都没成功时由调用方决定
        是跳过整个板块还是报错退出。
    """
    quotes: list[Quote] = []
    failures: list[str] = []
    for ticker in tickers:
        try:
            quotes.append(fetch_quote(ticker, fetcher=fetcher, sleep=sleep))
        except QuoteError as exc:
            failures.append(str(exc))
    return quotes, failures


