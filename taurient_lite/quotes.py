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

    def as_row(self) -> dict[str, object]:
        """转成简报 JSON 里 ``mag7.rows`` 的形态。"""
        return {
            "ticker": self.ticker,
            "price": f"{self.price:,.2f}",
            "change_pct": round(self.change_pct, 2),
        }


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


def parse_backend_quotes(payload: object) -> tuple[list[Quote], list[str]]:
    """解析后端 ``/api/quotes/live`` 的响应。

    后端对单只失败的处理是返回 ``{"ticker": X, "error": ...}`` 而不是
    整个请求失败，所以这里同样允许部分成功，返回 ``(报价, 失败原因)``，
    跟 :func:`fetch_many` 的形状保持一致，调用方不必区分数据来自哪一边。
    """
    if not isinstance(payload, list):
        raise QuoteError(f"后端返回的不是数组，实际是 {type(payload).__name__}")

    quotes: list[Quote] = []
    failures: list[str] = []
    for row in payload:
        if not isinstance(row, dict):
            failures.append(f"后端返回了一个非对象条目：{row!r}")
            continue
        ticker = str(row.get("ticker", "?"))
        if row.get("error"):
            failures.append(f"{ticker}：{row['error']}")
            continue
        try:
            quotes.append(
                Quote(
                    ticker=ticker,
                    price=float(row["price"]),
                    change_pct=float(row["change_pct"]),
                    market_time=int(row["market_time"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(f"{ticker}：后端返回的字段缺失或不是数字（{exc}）")
    return quotes, failures


# ------------------------------------------------------------- 仓库内快照回退
#
# 最后一层，也是云端唯一真正能走通的一层。GitHub Actions 的 runner 外网
# 不受限，在云端任务开始前把行情抓好提交进仓库；任务 clone 仓库时数据
# 就跟着下来了，读文件即可，一次外网都不用发。
#
# 关键是**过期保护**：快照是文件，会一直躺在仓库里，哪天 Actions 挂了
# 没人发现，读到的就是几周前的价格。所以按数据源自报的 market_time 判龄，
# 超期直接当没有——宁可让页面少一个板块，也不能把陈数据当成当天的。


class SnapshotTooOld(QuoteError):
    """仓库里的快照太旧，不能当作当天数据使用。"""


#: 允许的最大天数。5 天能扛过三天连休加一个假日；再长就说明抓取环节
#: 已经坏了一阵子，那更该让板块消失以引起注意，而不是继续糊弄。
DEFAULT_MAX_SNAPSHOT_AGE_DAYS = 5


def load_snapshot_quotes(
    payload: object,
    *,
    now: dt.datetime | None = None,
    max_age_days: int = DEFAULT_MAX_SNAPSHOT_AGE_DAYS,
) -> dict:
    """从快照里取出 ``mag7`` 块，顺带做过期校验。纯函数，不碰磁盘。

    直接返回可以塞进简报 JSON 的 ``mag7`` 结构，而不是 :class:`Quote`
    列表——快照里存的本来就是 :func:`build_mag7_block` 的产物，再拆回
    对象又拼一遍是多余的往返。
    """
    if not isinstance(payload, dict):
        raise QuoteError(f"快照不是一个对象，实际是 {type(payload).__name__}")

    block = payload.get("mag7")
    if not isinstance(block, dict) or not block.get("rows"):
        raise QuoteError("快照里没有可用的 mag7 数据")

    market_time = payload.get("market_time")
    if not isinstance(market_time, int):
        raise QuoteError("快照缺少 market_time，无法判断新鲜度")

    moment = dt.datetime.fromtimestamp(market_time, dt.timezone.utc)
    reference = now or dt.datetime.now(dt.timezone.utc)
    age_days = (reference - moment).days
    if age_days > max_age_days:
        raise SnapshotTooOld(
            f"快照里的行情是 {moment.date()} 的，已经 {age_days} 天没更新，"
            f"超过 {max_age_days} 天上限；抓取环节可能已经坏了，先不用它。"
        )
    return block


def fetch_from_backend(
    backend_url: str,
    *,
    fetcher: Callable[..., object] = fetch_json,
    timeout: float = 90.0,
) -> tuple[list[Quote], list[str]]:
    """从后端取全部七巨头报价。

    默认超时给到 90 秒：Render 免费版闲置 15 分钟会休眠，被唤醒要花
    半分钟到一分钟，用默认的 15 秒会稳定超时在冷启动上。
    """
    url = backend_url.rstrip("/") + "/api/quotes/live"
    return parse_backend_quotes(fetcher(url, timeout=timeout))


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


def asof_label(epoch: int) -> str:
    """把时间戳变成人读的时点标签。"""
    moment = dt.datetime.fromtimestamp(epoch, EASTERN)
    return f"收盘 · {moment.strftime('%a %-m/%-d')} {moment.strftime('%H:%M')} ET"


def build_mag7_block(quotes: Iterable[Quote], previous: dict | None = None) -> dict:
    """把报价拼成简报 JSON 里的 ``mag7`` 块。

    ``previous`` 里的 ``note``（人写的那句解读）会被保留，只有数字被覆盖。
    """
    rows = list(quotes)
    if not rows:
        raise QuoteError("一条报价都没有，不能构造 mag7 块")
    block = dict(previous or {})
    block["rows"] = [q.as_row() for q in rows]
    block["asof"] = asof_label(max(q.market_time for q in rows))
    block["source"] = "Yahoo Finance chart endpoint"
    return block
