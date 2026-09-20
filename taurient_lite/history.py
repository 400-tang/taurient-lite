"""历史 K 线：从 Yahoo chart 端点取 OHLCV，解析成干净的日线序列。

跟 :mod:`taurient_lite.quotes` 用的是同一个端点，区别只在参数：那边
``range=1d`` 只为拿一个最新价，这里要的是一整段历史。共用端点的好处是
两边的失败模式一样，排查时不用分两套心智。

**这个模块只负责「把数据取干净」，不负责画图。** 画图在浏览器里由
图表库完成——缩放、拖动、十字光标这些交互，服务端渲染的 SVG 做不了，
硬做就是在用错工具。所以这里的产出是给图表库吃的数据，不是图形。

**空洞必须剔除。** Yahoo 的数组里会夹 ``null``：停牌、数据缺失、或者
当天还没开盘。把 null 当成 0 画出来就是一根跌到地板的假 K 线——比缺一根
危险得多，因为它看起来像真的。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable

from .quotes import HEADERS, QuoteError, fetch_json  # noqa: F401  (HEADERS 供测试替换)

ENDPOINT = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?range={range}&interval={interval}"
)

#: 支持的区间，以及每个区间配多粗的 K 线。
#:
#: 配比是按「一屏大约多少根」定的：5 年用日线会有 1250 根，缩到一屏后
#: 每根不到一个像素，既看不清也白传一堆数据，所以换周线。
RANGES: dict[str, str] = {
    "1mo": "1d",
    "3mo": "1d",
    "6mo": "1d",
    "1y": "1d",
    "5y": "1wk",
}

DEFAULT_RANGE = "6mo"


class HistoryError(QuoteError):
    """取 K 线失败。继承 :class:`~taurient_lite.quotes.QuoteError`，
    调用方想一把捞住所有行情类错误时不必多写一个 except。"""


@dataclass(frozen=True, slots=True)
class Bar:
    """一根 K 线。``date`` 是 ISO 日期，图表库直接认这个格式。"""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int

    def as_candle(self) -> dict[str, Any]:
        """蜡烛图要的形状。"""
        return {
            "time": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }

    def as_volume(self, *, up_color: str, down_color: str) -> dict[str, Any]:
        """成交量柱要的形状。颜色跟着当根 K 线的涨跌走。"""
        return {
            "time": self.date,
            "value": self.volume,
            "color": up_color if self.close >= self.open else down_color,
        }


def _clean(value: Any) -> float | None:
    """把一个可能是 ``None``/``NaN`` 的数字变成 float 或 None。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def parse_history(symbol: str, payload: object) -> list[Bar]:
    """从 chart 端点的响应里取出 K 线序列。

    结构一旦变化就抛 :class:`HistoryError`，而不是产出一段看似合理的
    错误数据——一张画错的图比没有图危险得多，因为没人会去怀疑它。
    """
    try:
        result = payload["chart"]["result"][0]  # type: ignore[index]
        stamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise HistoryError(f"{symbol}：响应结构不对，取不到 K 线（{exc}）") from exc

    if not isinstance(stamps, list) or not stamps:
        raise HistoryError(f"{symbol}：没有任何 K 线数据")

    bars: list[Bar] = []
    for i, stamp in enumerate(stamps):
        try:
            o = _clean(quote["open"][i])
            h = _clean(quote["high"][i])
            low = _clean(quote["low"][i])
            c = _clean(quote["close"][i])
            v = _clean(quote["volume"][i])
        except (KeyError, IndexError, TypeError):
            continue
        # 四个价格缺任何一个，这根就不完整，整根丢掉。补 0 会画出一根
        # 跌到地板的假 K 线，那比缺一根危险得多。
        if None in (o, h, low, c):
            continue
        bars.append(
            Bar(
                date=dt.datetime.fromtimestamp(int(stamp), dt.timezone.utc)
                .date()
                .isoformat(),
                open=round(o, 4),
                high=round(h, 4),
                low=round(low, 4),
                close=round(c, 4),
                volume=int(v) if v is not None else 0,
            )
        )

    if not bars:
        raise HistoryError(f"{symbol}：所有 K 线都缺价格字段")
    return bars


def fetch_history(
    symbol: str,
    *,
    span: str = DEFAULT_RANGE,
    timeout: float = 15.0,
) -> list[Bar]:
    """取一段历史 K 线。``span`` 必须是 :data:`RANGES` 里的键。"""
    if span not in RANGES:
        raise HistoryError(f"不支持的区间 {span!r}，可选：{', '.join(RANGES)}")
    url = ENDPOINT.format(symbol=symbol, range=span, interval=RANGES[span])
    try:
        payload = fetch_json(url, timeout=timeout)
    except OSError as exc:
        raise HistoryError(f"{symbol}：取 K 线失败（{exc}）") from exc
    return parse_history(symbol, payload)


def summarise(bars: Iterable[Bar]) -> dict[str, Any]:
    """这段区间的概览：起止、区间涨跌、最高最低。

    算在服务端而不是丢给前端，是因为这几个数字要和页面上别处的涨跌幅
    用同一套口径——前端自己再算一遍，迟早会出现两个地方数字对不上。
    """
    rows = list(bars)
    if not rows:
        return {}
    first, last = rows[0], rows[-1]
    change = (last.close - first.close) / first.close * 100 if first.close else 0.0
    return {
        "from": first.date,
        "to": last.date,
        "bars": len(rows),
        "last": last.close,
        "change_pct": round(change, 2),
        "high": max(b.high for b in rows),
        "low": min(b.low for b in rows),
    }
