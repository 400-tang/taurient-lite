"""请求时现场取数，让页面上的数字不必等第二天的定时任务。

**这一层只存在于后端。** 云端定时任务跑在出站白名单沙箱里，连不了 Yahoo
和 Nasdaq，所以简报 JSON 里存的永远是「上一个收盘」的快照。Render 上的
服务没有这个限制，于是同一份页面在这里可以是活的：盘中打开就是盘中的
数字，不用等明天早上。

**为什么要缓存。** ``/`` 每次请求都重新渲染，不缓存的话每刷新一次就打
一次 Yahoo（七次请求）和 Nasdaq（一次七千行的响应）——既慢，也很快会被
限流。TTL 取几十秒到几分钟：比人的刷新间隔长，比行情的有效期短。

**取不到就退回存档，绝不报错。** 实时数据是锦上添花，拿不到时页面应该
照常显示昨天的收盘价，而不是变成一个 502。所有失败都在这里被咽掉，
调用方只会拿到 ``None``。
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any, Callable

from taurient_lite.quotes import (
    Quote,
    QuoteError,
    asof_label,
    build_mag7_block,
    fetch_quote,
)
from .company import CompanyError, fetch_company
from taurient_lite.sectors import (
    EASTERN,
    SectorError,
    fetch_market_block,
    is_market_open,
)

#: 七巨头的缓存时长。行情每秒都在变，但人的刷新间隔远长于此，
#: 45 秒足够让连续几次刷新只打一次 Yahoo。
QUOTES_TTL = 45.0

#: 板块热力的缓存时长。一次请求要拉七千多行、几兆的响应，比行情贵得多，
#: 而板块层面的涨跌在几分钟里不会有实质变化，所以放到 5 分钟。
SECTORS_TTL = 300.0


class _Cached:
    """一个值加它的时间戳。线程安全，因为 uvicorn 会并发处理请求。

    失败也要记时间戳（``value`` 留 None）：Nasdaq 挂掉的时候，不记的话
    每个请求都会去重试一次，页面从「慢一点」变成「每次都卡满超时」。
    """

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._value: Any = None
        self._at: float = 0.0

    def get(self, produce: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            if self._at and now - self._at < self.ttl:
                return self._value
        # 取数放在锁外：一次 Nasdaq 请求可能要几秒，占着锁会把并发请求全堵住。
        # 代价是缓存过期的瞬间可能有两个请求同时去取，重复一次远比串行阻塞便宜。
        try:
            value = produce()
        except (QuoteError, SectorError, CompanyError, OSError):
            value = None
        with self._lock:
            self._value = value
            self._at = time.monotonic()
        return value


#: 公司资料的缓存时长。简介、行业、评级、财报都是按天甚至按季变的，
#: 放半小时都嫌短；这里取 10 分钟只是为了让偶发的上游故障能自己恢复。
COMPANY_TTL = 600.0

_quotes_cache = _Cached(QUOTES_TTL)
_sectors_cache = _Cached(SECTORS_TTL)

#: 每只票一个缓存槽。个股页是按代码访问的，共用一个槽会让两个人同时
#: 看不同股票时互相把对方的数据挤掉，等于缓存完全失效。
_company_caches: dict[str, _Cached] = {}
_company_lock = threading.Lock()


def quote_asof(epoch: int) -> str:
    """报价的时点标签，按是不是盘中给不同的措辞。

    ``quotes.asof_label`` 固定写「收盘 · ...」，因为它服务的是盘前跑的每日
    快照，那时候这么写是对的。**但现场取数会发生在交易时段内**，这时候
    再写「收盘」就是在陈述一个还没发生的事实——跟热力图那个
    「截至周六收盘」是同一类错误，所以在这一层按时段改写。
    """
    moment = dt.datetime.fromtimestamp(epoch, EASTERN)
    if is_market_open(moment):
        return f"盘中 · {moment.strftime('%-m/%-d')} {moment.strftime('%H:%M')} ET"
    return asof_label(epoch)


def _fetch_mag7(symbols: tuple[str, ...], previous: dict | None) -> dict | None:
    """把配置里的名单挨个查一遍，拼成简报里 ``mag7`` 的形状。

    **一只都查不到才算失败。** 个别代码被限流是常态，剩下的照样能画；
    但一只都没有就说明 Yahoo 整个不通，这时候该退回存档而不是画一张空表。

    ``previous`` 是简报里那份存档，传进去只为保住人写的 ``note``——数字可以
    现场刷新，那句解读不行，它是当天写简报的人对盘面的判断。
    """
    quotes: list[Quote] = []
    for symbol in symbols:
        try:
            quotes.append(fetch_quote(symbol))
        except QuoteError:
            continue
    if not quotes:
        return None

    block = build_mag7_block(quotes, previous)
    latest = max((q.market_time for q in quotes if q.market_time), default=0)
    if latest:
        block["asof"] = quote_asof(latest)
    return block


def live_mag7(
    symbols: tuple[str, ...], previous: dict | None = None
) -> dict | None:
    """七巨头的实时报价块，取不到返回 None。"""
    if not symbols:
        return None
    return _quotes_cache.get(lambda: _fetch_mag7(symbols, previous))


def live_company(symbol: str):
    """一只票的公司资料，取不到返回 None。"""
    symbol = symbol.upper()
    with _company_lock:
        cache = _company_caches.get(symbol)
        if cache is None:
            cache = _Cached(COMPANY_TTL)
            _company_caches[symbol] = cache
    return cache.get(lambda: fetch_company(symbol))


def live_market(now: dt.datetime | None = None) -> dict | None:
    """板块热力的实时数据块，取不到返回 None。"""
    return _sectors_cache.get(lambda: fetch_market_block(now))
