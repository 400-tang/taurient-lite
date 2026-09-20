"""异动探测：从日线价量里找出**刚开始动**的股票。

这个模块回答的问题不是「谁涨得多」，而是「这只票走到这波的第几天」。
两者的区别就是踏空与否的区别：涨幅榜上的名字往往已经走完主升段，
等它进入新闻视野时，可交易的部分基本结束了。所以这里所有的计算都
围绕一件事——**定位起涨点，并且主动把已经延伸的标的降权**。

**为什么用价量而不是新闻。** 简报的其余部分是新闻驱动的，而新闻天然滞后：
催化剂先反映在成交量和价格结构上，几天甚至几周之后才成为头条。想比新闻早，
就必须换一层数据。这也是本模块刻意不读任何文本、只吃 OHLCV 的原因。

**阶段判定优先于强度排序。** 一只放量突破第 1 天的票和一只已经连涨三周的票，
在传统的涨幅/换手排序里可能相邻，但对使用者的意义完全相反。所以先分档
（:data:`STAGES`），再在档内按强度排序，而不是把所有票混在一个分数里比大小。

**这个模块不预测、不建议。** 输出的每一个字段都是对已发生价量的描述性统计，
阶段标签也只是对「已经走了几天」的陈述。多数被标记的标的不会走出趋势，
这是筛选器的常态，不是缺陷；它的价值在于把观察窗口从「新闻发生后」
前移到「价量异动时」，而不在于命中率。

**关于「越早越好」这个出发点，必须记一笔。** 全量回测（2515 只、两年、
5090 次初动信号）显示：初动信号本身 20 日胜率 51.4%、期望 +1.1%，略好过
抛硬币；但**越早并不越好**——按早期度排序，最早的那批期望反而是负的，
而已经涨了 80% 以上的那批期望最高（+4.6%，中位仅 +1.6%，收益集中在尾部）。

这个结论没有改变模块的结构，因为阶段划分本来就是事实陈述而非收益预测：
知道「这只票刚突破三天」和知道「它已经涨了三个月」，对使用者都是有用的
信息，只是**不能把前者当成买入理由**。详见 :func:`score` 的说明。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Any, Sequence

# --------------------------------------------------------------------------- 常量

#: 阶段。顺序即「离起涨点由近到远」，也是展示顺序。
STAGES: tuple[str, ...] = ("base", "ignition", "continuation", "extended")

STAGE_LABEL: dict[str, str] = {
    "base": "基底",
    "ignition": "初动",
    "continuation": "延续",
    "extended": "已延伸",
}

STAGE_NOTE: dict[str, str] = {
    "base": "尚未突破，区间收窄且出现放量迹象，属于观察名单。",
    "ignition": "突破前高的头几天，量能同步放大——这是右侧介入窗口。",
    "continuation": "突破后第二周内，趋势仍在但最容易追高的部分已经过去。",
    "extended": "距均线过远或已走出主升段，此时介入承担的是回撤风险。",
}

#: 突破的参照区间：收盘价超过**此前** 50 个交易日的最高价才算突破。
#: 50 天约等于两个半月，足够长到能把窄幅震荡包进去，又不至于长到
#: 让一只沉寂半年的票因为一次微弱反弹就被判定为突破。
BREAKOUT_LOOKBACK = 50

#: 计算基底区间与「这波已经涨了多少」时回看的长度。
BASE_LOOKBACK = 60

#: 相对成交量的基准窗口。用中位数而不是均值：一次财报日的天量会把
#: 均值抬高好几倍，之后一整个月的真实放量都会被这个均值掩盖掉。
RVOL_WINDOW = 20

#: 判定「已延伸」的三条线，命中任意一条即降档。
#: 数值取自常见的趋势交易实践：距 20 日均线 35% 以上属于典型的乖离过大，
#: 突破后 10 个交易日约两周，自基底翻倍则意味着主升段大概率已经走完。
EXTENDED_MA20_GAP = 0.35
EXTENDED_BREAKOUT_AGE = 10
EXTENDED_RUN_FROM_BASE = 1.0

#: 「初动」的两个条件：突破后 3 天内，且当日放量到基准的 2.5 倍以上。
#: 只看天数不看量会混进一堆缩量假突破，只看量不看天数则会把
#: 连涨三周里某一天的放量也算成起涨。
IGNITION_MAX_AGE = 3
IGNITION_MIN_RVOL = 2.5

#: 突破位的容错。收盘跌破突破位这个比例以上，就认为这波行情结束。
#: 留 5% 是为了容忍洗盘和跳空噪音；一点不留会让几乎每波趋势都在
#: 中途被判死，留太多则等于没有这条线。
RUN_INVALIDATION_SLACK = 0.05

#: 可交易性下限。低于这个日均成交额的标的，即使信号完美也难以进出；
#: 价格下限则用来挡掉仙股——它们的百分比波动在统计上毫无参照意义。
MIN_DOLLAR_VOLUME = 10_000_000.0
MIN_PRICE = 3.0

#: 少于这个根数的日线不足以计算基底与突破，直接不参与评分。
MIN_BARS = BASE_LOOKBACK + 5


class MomentumError(ValueError):
    """价量数据不足或结构不对，无法计算。"""


# --------------------------------------------------------------------------- 数据


@dataclass(frozen=True, slots=True)
class Bars:
    """一只标的的日线序列。全部按时间正序，最后一根是最近的交易日。"""

    ticker: str
    dates: tuple[dt.date, ...]
    opens: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    closes: tuple[float, ...]
    volumes: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.closes)


@dataclass(frozen=True, slots=True)
class Signal:
    """一只标的的异动画像。字段全部是对已发生价量的描述，不含任何预测。"""

    ticker: str
    date: dt.date
    close: float
    change_pct: float
    #: 当日成交量相对 20 日中位量的倍数。
    rvol: float
    #: 20 日日均成交额，可交易性的度量。
    dollar_volume: float
    #: 收盘价距 20 日均线的偏离。
    ext_ma20: float
    #: 收盘价在当日区间里的位置，1.0 表示收在最高点。
    closing_range: float
    #: 突破发生在几个交易日前。0 表示突破就发生在最新这根 K 线上；
    #: ``None`` 表示当前尚未突破 50 日高点。
    breakout_age: int | None
    #: 自基底低点算起这波已经涨了多少。
    run_from_base: float
    #: 突破前 40 日区间的相对宽度，越小说明基底越紧、突破质量越高。
    base_tightness: float
    #: 相对前收的跳空幅度。一次性的大跳空常见于财报或并购这类
    #: 事件驱动，与「趋势起步」形态相似但含义不同，单列出来供人判断。
    gap_pct: float
    stage: str
    score: float

    @property
    def stage_label(self) -> str:
        return STAGE_LABEL[self.stage]

    def as_dict(self) -> dict[str, Any]:
        """转成写进快照 JSON 的形态。浮点统一保留有意义的位数。"""
        return {
            "ticker": self.ticker,
            "date": self.date.isoformat(),
            "close": round(self.close, 2),
            "change_pct": round(self.change_pct, 2),
            "rvol": round(self.rvol, 2),
            "dollar_volume": round(self.dollar_volume),
            "ext_ma20": round(self.ext_ma20, 4),
            "closing_range": round(self.closing_range, 3),
            "breakout_age": self.breakout_age,
            "run_from_base": round(self.run_from_base, 4),
            "base_tightness": round(self.base_tightness, 4),
            "gap_pct": round(self.gap_pct, 2),
            "stage": self.stage,
            "score": round(self.score, 2),
        }


# --------------------------------------------------------------------------- 解析


def session_cutoff(meta: dict) -> int | None:
    """当天这根还没走完时，返回它的起始时间戳；已收盘或判断不了则返回 ``None``。

    **这个函数存在的理由是一次真实的事故。** 扫描本来排在开盘前跑，那时
    最后一根日线必然是上一个完整交易日。但 GitHub Actions 的定时任务会
    严重延迟——实测过 4 到 6 小时——于是扫描落在了盘中，而 Yahoo 这时
    已经为当天开出一根**还在变动**的 K 线。脚本照单全收，把半天的成交量
    当成一整天，算出来的相对成交量、突破、收盘位置全是错的，而且收盘前
    还会继续变。这种错误不报警、不抛异常，产出的文件看上去完全正常。

    判断依据用 Yahoo 自己给的时段信息，不自己推算时区：
    ``currentTradingPeriod.regular`` 给出当天时段的起止，``regularMarketTime``
    是数据自身的时点。后者早于时段结束，就说明这一场还没打完。

    这样处理之后，扫描在什么时候跑都只吃完整交易日的数据——定时任务
    延迟多久都不影响结果的正确性，只影响它新不新。
    """
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = period.get("start"), period.get("end")
    market_time = meta.get("regularMarketTime")
    if not isinstance(start, int) or not isinstance(end, int) or not isinstance(market_time, int):
        return None
    return start if market_time < end else None


def parse_chart_bars(ticker: str, payload: object) -> Bars:
    """从 Yahoo chart 端点的响应里取出日线序列。

    用 ``range=6mo&interval=1d`` 请求同一个 :mod:`~taurient_lite.quotes`
    已经在用的端点，不引入新数据源。

    响应里存在 ``None``（停牌日、假日的占位）。这些行整根丢弃而不是
    前值填充：填充会凭空造出一根成交量为零的 K 线，把相对成交量和
    区间计算一起带偏，而丢弃只是让样本少一天。
    """
    try:
        result = payload["chart"]["result"][0]  # type: ignore[index]
        stamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise MomentumError(f"{ticker}：响应结构不对，取不到日线（{exc}）") from exc

    cutoff = session_cutoff(result.get("meta") or {})

    dates: list[dt.date] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    for i, stamp in enumerate(stamps):
        row = (
            quote.get("open", [])[i:i + 1],
            quote.get("high", [])[i:i + 1],
            quote.get("low", [])[i:i + 1],
            quote.get("close", [])[i:i + 1],
            quote.get("volume", [])[i:i + 1],
        )
        if any(not cell or cell[0] is None for cell in row) or stamp is None:
            continue
        if cutoff is not None and int(stamp) >= cutoff:
            continue  # 今天这场还没打完，这根不能算
        opens.append(float(row[0][0]))
        highs.append(float(row[1][0]))
        lows.append(float(row[2][0]))
        closes.append(float(row[3][0]))
        volumes.append(float(row[4][0]))
        dates.append(dt.datetime.fromtimestamp(int(stamp), dt.timezone.utc).date())

    if not closes:
        raise MomentumError(f"{ticker}：日线序列为空")

    return Bars(
        ticker=ticker,
        dates=tuple(dates),
        opens=tuple(opens),
        highs=tuple(highs),
        lows=tuple(lows),
        closes=tuple(closes),
        volumes=tuple(volumes),
    )


# --------------------------------------------------------------------------- 指标


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def breakout_flags(bars: Bars, lookback: int = BREAKOUT_LOOKBACK) -> list[bool]:
    """逐日标记「今天的收盘价是否高于此前 ``lookback`` 天的最高价」。

    参照区间**不含当日**，否则每一天都会拿自己的高点跟自己比。
    """
    flags = [False] * len(bars)
    for i in range(lookback, len(bars)):
        prior_high = max(bars.highs[i - lookback:i])
        flags[i] = bars.closes[i] > prior_high
    return flags


def active_run(bars: Bars, lookback: int = BREAKOUT_LOOKBACK) -> tuple[int, float] | None:
    """找到**当前仍然有效**的那波行情，返回 ``(起点下标, 突破位)``。

    分两步，缺一不可：

    1. 从最后一根往回扫，找最近一个「今天突破、昨天没突破」的位置。
       直接取「最近一次突破日」是不行的——一只连创新高的票每天都在突破，
       那样算出来的年龄恒为 0，正好丢掉了这个模块唯一关心的信息。
    2. 检查这波是否还活着：突破之后任何一天收盘显著跌回突破位以下，
       这波就算结束了，返回 ``None``。

    第 2 步是拿真实数据试出来的。只做第 1 步的话，一只三个月前突破、
    此后早已回落盘整的票会被算成「运行了 74 天的趋势」，进而被判成
    已延伸——但它其实既没在趋势里，也谈不上延伸，正确的归属是重新
    进入基底。**突破位失守就是一波行情的终点**，这条线不划，
    阶段判定就会被陈年旧事污染。

    回撤后再度突破则会被认定为一次新的起点。这是刻意的：重新站上前高
    本身就是一个可交易的时点，而它是否已经涨过头，由乖离与涨幅两个
    指标另行把关，不需要在这里重复判断。
    """
    flags = breakout_flags(bars, lookback)
    last = len(bars) - 1
    for i in range(last, -1, -1):
        if not (flags[i] and (i == 0 or not flags[i - 1])):
            continue
        level = max(bars.highs[max(0, i - lookback):i]) if i else bars.highs[0]
        floor = level * (1 - RUN_INVALIDATION_SLACK)
        if all(c >= floor for c in bars.closes[i:last + 1]):
            return i, level
        return None
    return None


def evaluate(bars: Bars) -> Signal:
    """把一只标的的日线序列压成一份 :class:`Signal`。纯函数，不碰网络。"""
    if len(bars) < MIN_BARS:
        raise MomentumError(
            f"{bars.ticker}：只有 {len(bars)} 根日线，少于 {MIN_BARS} 根，不足以判断基底"
        )

    last = len(bars) - 1
    close = bars.closes[last]
    prev_close = bars.closes[last - 1]
    high, low = bars.highs[last], bars.lows[last]

    change_pct = (close / prev_close - 1) * 100 if prev_close else 0.0
    gap_pct = (bars.opens[last] / prev_close - 1) * 100 if prev_close else 0.0

    base_volume = _median(bars.volumes[last - RVOL_WINDOW:last])
    rvol = bars.volumes[last] / base_volume if base_volume else 0.0

    ma20 = _mean(bars.closes[last - RVOL_WINDOW + 1:last + 1])
    ext_ma20 = (close / ma20 - 1) if ma20 else 0.0

    span = high - low
    closing_range = (close - low) / span if span else 1.0

    dollar_volume = _mean(
        [c * v for c, v in zip(bars.closes[last - RVOL_WINDOW:last], bars.volumes[last - RVOL_WINDOW:last])]
    )

    run = active_run(bars)
    start = run[0] if run else None
    breakout_age = last - start if start is not None else None

    # 基底 = 起涨之前那段区间。尚未突破时就用最近一段，此时它描述的是
    # 「当前盘整区」，同样是判断收窄程度需要的东西。
    anchor = start if start is not None else last
    window_lo = max(0, anchor - BASE_LOOKBACK)
    base_lows = bars.lows[window_lo:anchor] or bars.lows[window_lo:anchor + 1]
    base_highs = bars.highs[window_lo:anchor] or bars.highs[window_lo:anchor + 1]
    base_low = min(base_lows)
    base_high = max(base_highs)

    run_from_base = (close / base_low - 1) if base_low else 0.0
    base_tightness = (base_high / base_low - 1) if base_low else 0.0

    stage = classify(
        breakout_age=breakout_age,
        rvol=rvol,
        ext_ma20=ext_ma20,
        run_from_base=run_from_base,
        close=close,
        ma20=ma20,
    )

    return Signal(
        ticker=bars.ticker,
        date=bars.dates[last],
        close=close,
        change_pct=change_pct,
        rvol=rvol,
        dollar_volume=dollar_volume,
        ext_ma20=ext_ma20,
        closing_range=closing_range,
        breakout_age=breakout_age,
        run_from_base=run_from_base,
        base_tightness=base_tightness,
        gap_pct=gap_pct,
        stage=stage,
        score=0.0,
    )


def classify(
    *,
    breakout_age: int | None,
    rvol: float,
    ext_ma20: float,
    run_from_base: float,
    close: float,
    ma20: float,
) -> str:
    """把各项指标归到一个阶段。

    **判定顺序本身就是设计的一部分：先否决，再认定。** 「已延伸」的三条
    否决线跑在最前面，所以一只突破第 1 天但已经从基底翻倍的票会被判成
    已延伸而不是初动——它满足「刚突破」的字面条件，但使用者要的是
    可介入的时点，不是形态上的相似。
    """
    if breakout_age is not None:
        extended = (
            ext_ma20 > EXTENDED_MA20_GAP
            or breakout_age > EXTENDED_BREAKOUT_AGE
            or run_from_base > EXTENDED_RUN_FROM_BASE
        )
        if extended:
            return "extended"
        if breakout_age <= IGNITION_MAX_AGE and rvol >= IGNITION_MIN_RVOL:
            return "ignition"
        return "continuation"

    return "base"


# --------------------------------------------------------------------------- 排序


#: 各阶段的基准分。分档之间拉开足够的距离，保证「初动」永远排在
#: 「已延伸」之前，无论后者的量能有多夸张——量能大小不能换来
#: 更早的介入时点，而这个列表的用途只有一个：找更早的时点。
STAGE_BASE_SCORE: dict[str, float] = {
    "ignition": 100.0,
    "continuation": 60.0,
    "base": 40.0,
    "extended": 10.0,
}


#: 乖离舒适区。超过这个幅度，介入点已经离基底太远——**这是一个关于
#: 位置的陈述，不是关于收益的预测**，两者在这个模块里被反复证明无关。
COMFORT_EXT_MA20 = 0.15


def score(signal: Signal) -> float:
    """**早期度**：这只票离起涨点还有多近。分数越高越早，仅此而已。

    **这个分数不预测收益，而且千万不要把它反过来读成「分数低的更值得买」。**

    验证过程本身值得留在这里。最初的版本给放量、收在高位、基底紧各记
    一份加分，理由听起来都很顺（参与度、买盘坚决、浮筹少）。第一次回测
    用了 59 只手挑的高波动标的、153 次信号，结论是排序反了，于是加分项
    被全部删掉，只留下阶段、天数、乖离这三个可直接观测的量。

    后来在**全量样本**（2515 只、两年、5090 次初动信号）上重验，结论
    没有变好，只是变得更清楚了：

    * 按本分数排序，最高的四分之一 20 日期望 **-0.2%**，最低的四分之一
      **+1.9%**——排序依然是反的。
    * 单因子同样反直觉：乖离大于 30% 的一组期望 +2.9%，高于乖离小于 15%
      的 +0.9%；自基底已涨超 80% 的一组期望 +4.6%，远高于涨幅不到 30%
      的 +0.2%。**「越早越好」这个本模块的出发点，数据不支持。**
    * 但那几组高期望的中位数是负的（高乖离组中位 -0.2%），收益几乎全部
      来自极少数尾部标的。所以「那就追强势」同样不是一个能照做的结论，
      它只是把赌注换了个方向。

    三次验证指向同一件事：**这个模块能可靠回答的只有「发生了什么、
    走到第几天」，回答不了「接下来会怎样」。** 分数因此只决定名单的
    陈列顺序，让读者先看到新出现的东西；靠前不代表更值得买。

    被删掉的那些指标仍然全部保留在 :class:`Signal` 里照常展示——
    它们是有用的观察材料，只是不构成排序依据。
    """
    base = STAGE_BASE_SCORE[signal.stage]

    # 天数惩罚封顶，否则一只跑了三个月的票会被扣到负分，把它和
    # 「同为已延伸但刚走两周」的票之间的次序彻底打乱——两者都不该追，
    # 但排序仍要有意义。
    age_penalty = min(signal.breakout_age or 0, EXTENDED_BREAKOUT_AGE * 2) * 1.5
    ext_penalty = max(0.0, signal.ext_ma20 - COMFORT_EXT_MA20) * 60.0
    run_penalty = max(0.0, signal.run_from_base - 0.3) * 10.0

    return base - age_penalty - ext_penalty - run_penalty


def tradable(signal: Signal) -> bool:
    """流动性与价格门槛。信号再漂亮，进不去出不来也没有意义。"""
    return signal.dollar_volume >= MIN_DOLLAR_VOLUME and signal.close >= MIN_PRICE


def rank(signals: Sequence[Signal], *, limit: int | None = None) -> list[Signal]:
    """过滤、打分、排序，返回可以直接展示的名单。"""
    scored = [replace(s, score=score(s)) for s in signals if tradable(s)]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit] if limit else scored
