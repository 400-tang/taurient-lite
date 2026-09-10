"""简报数据的类型定义、反序列化与校验。

这是整条流水线唯一的真相来源。磁盘上的 JSON 先经过这里变成 dataclass，
之后的渲染层只跟 dataclass 打交道，不再碰裸 dict。这样做有三个好处：

1. 字段拼错、类型写错在解析阶段就炸，而不是渲染到一半产出半张空白页面；
2. 错误信息带完整路径（例如 ``items[3].assets[0].direction``），
   定位一眼可见，不用回头翻 JSON；
3. 渲染层可以放心地写 ``item.assets``，不必到处 ``.get(..., [])`` 兜底。

校验的严格程度是刻意分级的：**结构性错误直接抛异常**（缺必填字段、
枚举值非法、类型不对），**内容性问题只记警告**（时效超限、条数不足、
排名不连续）。前者会让页面出错，后者只是当天的简报质量差一点，
不该阻断发布。警告通过 :meth:`Brief.warnings` 收集，由 CLI 统一打印。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------- 枚举

#: 新闻分层。顺序即渲染顺序，也是重要性顺序。
TIERS: tuple[str, ...] = ("must-read", "worth-knowing", "noise")

TIER_LABEL: dict[str, str] = {
    "must-read": "必读",
    "worth-knowing": "值得知道",
    "noise": "背景噪音",
}

#: 行情方向。``flat`` 用于无涨跌或纯说明性的数字。
DIRECTIONS: tuple[str, ...] = ("up", "down", "flat")

#: 日历条目的权重，决定右侧徽章的样式。
WEIGHTS: tuple[str, ...] = ("high", "mid", "low")

WEIGHT_LABEL: dict[str, str] = {"high": "关键", "mid": "留意", "low": "常规"}

#: 资产波及矩阵里的资产类别。刻意保持粗粒度：
#: 再细就变成个股推荐了，而这个工具明确不做投资建议。
ASSET_CLASSES: tuple[str, ...] = (
    "美股",
    "美债",
    "美元",
    "大宗商品",
    "加密资产",
    "海外股市",
)

#: 波及方向。``mixed`` 表示同一资产类别内部分化，
#: ``none`` 表示明确判断为无影响（比不写更有信息量）。
IMPACT_DIRECTIONS: tuple[str, ...] = ("up", "down", "mixed", "none")

IMPACT_LABEL: dict[str, str] = {
    "up": "利好",
    "down": "利空",
    "mixed": "分化",
    "none": "无影响",
}

#: 判断强度。渲染成条形的填充格数，是颜色之外的第二重编码。
CONVICTIONS: tuple[str, ...] = ("high", "medium", "low")

CONVICTION_STEPS: dict[str, int] = {"high": 3, "medium": 2, "low": 1}

#: 多方信源的一致性。
AGREEMENTS: tuple[str, ...] = ("aligned", "split", "single")

AGREEMENT_LABEL: dict[str, str] = {
    "aligned": "口径一致",
    "split": "存在分歧",
    "single": "单一来源",
}

#: 异动阶段。与 :mod:`taurient_lite.momentum` 里的 ``STAGES`` 一一对应，
#: 在这里重新声明是为了让 schema 保持零内部依赖——它是整条流水线的
#: 根，不该反过来依赖某个具体的计算模块。
STAGES: tuple[str, ...] = ("base", "ignition", "continuation", "extended")

STAGE_LABEL: dict[str, str] = {
    "base": "基底",
    "ignition": "初动",
    "continuation": "延续",
    "extended": "已延伸",
}

#: 一只异动标的当天的新闻覆盖度。**这个字段是反着读的**：覆盖度越低
#: 说明市场越没注意到，这条线索越早；满屏报道则意味着已经晚了。
#: 价量异动由脚本算出，新闻覆盖度只有每天在扫新闻的这条流水线知道，
#: 两者相交才是这个模块相对于任何通用选股器的独有价值。
NEWS_COVERAGE: tuple[str, ...] = ("none", "light", "heavy")

COVERAGE_LABEL: dict[str, str] = {
    "none": "无报道",
    "light": "零星",
    "heavy": "已发酵",
}


class SchemaError(ValueError):
    """简报 JSON 结构非法。

    消息里一定带上出错字段的完整路径，让人不用回头对着 JSON 数行数。
    """


# ------------------------------------------------------------------- 取值助手
#
# 下面这一组函数把「取字段 + 校验类型 + 拼错误路径」收在一处。
# 每个都接受 ``path`` 参数用于拼装错误信息，形如 ``items[2].headline``。


def _require(data: Any, key: str, path: str) -> Any:
    """取必填字段，缺了就抛。"""
    if not isinstance(data, dict):
        raise SchemaError(f"{path or '<root>'} 应该是一个对象，实际是 {type(data).__name__}")
    if key not in data:
        raise SchemaError(f"{_join(path, key)} 是必填字段，但没有找到")
    return data[key]


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _as_str(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{path} 应该是字符串，实际是 {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise SchemaError(f"{path} 不能是空字符串")
    return value


def _as_float(value: Any, path: str) -> float:
    # bool 是 int 的子类，但把 True 当 1.0 只会掩盖数据错误，所以显式挡掉。
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{path} 应该是数字，实际是 {type(value).__name__}")
    return float(value)


def _as_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaError(f"{path} 应该是整数，实际是 {type(value).__name__}")
    return value


def _as_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise SchemaError(f"{path} 应该是数组，实际是 {type(value).__name__}")
    return value


def _as_enum(value: Any, allowed: Sequence[str], path: str) -> str:
    text = _as_str(value, path)
    if text not in allowed:
        raise SchemaError(f"{path} 只能是 {'、'.join(allowed)} 之一，实际是 {text!r}")
    return text


def _as_date(value: Any, path: str) -> dt.date:
    text = _as_str(value, path)
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise SchemaError(f"{path} 应该是 YYYY-MM-DD 格式的日期，实际是 {text!r}") from exc


def _str_list(data: dict, key: str, path: str) -> list[str]:
    """取一个可选的字符串数组，缺省为空列表。"""
    raw = data.get(key)
    if raw is None:
        return []
    return [
        _as_str(v, f"{_join(path, key)}[{i}]")
        for i, v in enumerate(_as_list(raw, _join(path, key)))
    ]


# ----------------------------------------------------------------- 数据结构


@dataclass(frozen=True, slots=True)
class Source:
    """一条新闻的一个信源。"""

    name: str
    url: str
    #: 可选。这家媒体独有的角度，用于交叉对比。留空则只作为出处列出。
    angle: str = ""

    @classmethod
    def from_dict(cls, data: Any, path: str) -> Source:
        return cls(
            name=_as_str(_require(data, "name", path), _join(path, "name")),
            url=_as_str(_require(data, "url", path), _join(path, "url")),
            angle=_as_str(data.get("angle", ""), _join(path, "angle"), allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class AssetImpact:
    """资产波及矩阵里的一格：某个资产类别受到的方向与强度。"""

    asset_class: str
    direction: str
    conviction: str
    #: 一句话说明传导路径。矩阵光有颜色没有因果，这句是必需的。
    note: str = ""

    @property
    def steps(self) -> int:
        """强度对应的填充格数，1 到 3。"""
        return CONVICTION_STEPS[self.conviction]

    @property
    def label(self) -> str:
        return IMPACT_LABEL[self.direction]

    @classmethod
    def from_dict(cls, data: Any, path: str) -> AssetImpact:
        return cls(
            asset_class=_as_enum(
                _require(data, "asset_class", path), ASSET_CLASSES, _join(path, "asset_class")
            ),
            direction=_as_enum(
                _require(data, "direction", path),
                IMPACT_DIRECTIONS,
                _join(path, "direction"),
            ),
            conviction=_as_enum(
                data.get("conviction", "medium"), CONVICTIONS, _join(path, "conviction")
            ),
            note=_as_str(data.get("note", ""), _join(path, "note"), allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class CrossSource:
    """多方信源交叉对比。

    ``agreement`` 说明各家口径是否一致，``summary`` 用一句话点出差异所在。
    真正的价值在 ``split`` 这种情况：不同媒体对同一事实给出不同解读时，
    差异本身就是信息。
    """

    agreement: str
    summary: str

    @property
    def label(self) -> str:
        return AGREEMENT_LABEL[self.agreement]

    @classmethod
    def from_dict(cls, data: Any, path: str) -> CrossSource:
        return cls(
            agreement=_as_enum(
                _require(data, "agreement", path), AGREEMENTS, _join(path, "agreement")
            ),
            summary=_as_str(_require(data, "summary", path), _join(path, "summary")),
        )


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """事件演进脉络上的一个节点。"""

    when: str
    event: str

    @classmethod
    def from_dict(cls, data: Any, path: str) -> TimelineEntry:
        return cls(
            when=_as_str(_require(data, "when", path), _join(path, "when")),
            event=_as_str(_require(data, "event", path), _join(path, "event")),
        )


@dataclass(frozen=True, slots=True)
class HistoricalContext:
    """历史背景与演进脉络。

    ``timeline`` 是真正的时间序列，所以渲染成带编号的竖向时间轴是成立的；
    如果只有一两个节点就别写，一句 ``summary`` 就够。
    """

    summary: str
    timeline: tuple[TimelineEntry, ...] = ()

    @classmethod
    def from_dict(cls, data: Any, path: str) -> HistoricalContext:
        raw = data.get("timeline") or []
        entries = tuple(
            TimelineEntry.from_dict(v, f"{_join(path, 'timeline')}[{i}]")
            for i, v in enumerate(_as_list(raw, _join(path, "timeline")))
        )
        return cls(
            summary=_as_str(_require(data, "summary", path), _join(path, "summary")),
            timeline=entries,
        )


@dataclass(frozen=True, slots=True)
class Item:
    """一条新闻。"""

    rank: int
    tier: str
    headline: str
    body: str
    published: dt.date | None = None
    sectors: tuple[str, ...] = ()
    tickers: tuple[str, ...] = ()
    why: str = ""
    impact: str = ""
    sources: tuple[Source, ...] = ()
    assets: tuple[AssetImpact, ...] = ()
    cross_source: CrossSource | None = None
    history: HistoricalContext | None = None

    @property
    def has_depth(self) -> bool:
        """是否带了深度元数据。决定页面上要不要给它开侧栏。"""
        return bool(self.assets or self.cross_source or self.history)

    def age_days(self, today: dt.date) -> int | None:
        """距简报日期几天。没有 ``published`` 就返回 None。"""
        if self.published is None:
            return None
        return (today - self.published).days

    @classmethod
    def from_dict(cls, data: Any, path: str) -> Item:
        if not isinstance(data, dict):
            raise SchemaError(f"{path} 应该是一个对象，实际是 {type(data).__name__}")

        published_raw = data.get("published")
        published = (
            _as_date(published_raw, _join(path, "published"))
            if published_raw is not None
            else None
        )

        sources = tuple(
            Source.from_dict(v, f"{_join(path, 'sources')}[{i}]")
            for i, v in enumerate(_as_list(data.get("sources") or [], _join(path, "sources")))
        )
        assets = tuple(
            AssetImpact.from_dict(v, f"{_join(path, 'assets')}[{i}]")
            for i, v in enumerate(_as_list(data.get("assets") or [], _join(path, "assets")))
        )

        # 同一个资产类别在一条新闻里出现两次说明判断自相矛盾，直接挡掉。
        seen: set[str] = set()
        for a in assets:
            if a.asset_class in seen:
                raise SchemaError(
                    f"{_join(path, 'assets')} 里 {a.asset_class!r} 出现了不止一次"
                )
            seen.add(a.asset_class)

        cross = data.get("cross_source")
        history = data.get("history")

        return cls(
            rank=_as_int(_require(data, "rank", path), _join(path, "rank")),
            tier=_as_enum(_require(data, "tier", path), TIERS, _join(path, "tier")),
            headline=_as_str(_require(data, "headline", path), _join(path, "headline")),
            body=_as_str(_require(data, "body", path), _join(path, "body")),
            published=published,
            sectors=tuple(_str_list(data, "sectors", path)),
            tickers=tuple(_str_list(data, "tickers", path)),
            why=_as_str(data.get("why", ""), _join(path, "why"), allow_empty=True),
            impact=_as_str(data.get("impact", ""), _join(path, "impact"), allow_empty=True),
            sources=sources,
            assets=assets,
            cross_source=(
                CrossSource.from_dict(cross, _join(path, "cross_source")) if cross else None
            ),
            history=(
                HistoricalContext.from_dict(history, _join(path, "history"))
                if history
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class QuoteRow:
    """七巨头面板里的一行。"""

    ticker: str
    price: str
    change_pct: float

    @property
    def direction(self) -> str:
        return "up" if self.change_pct >= 0 else "down"

    @classmethod
    def from_dict(cls, data: Any, path: str) -> QuoteRow:
        return cls(
            ticker=_as_str(_require(data, "ticker", path), _join(path, "ticker")),
            price=_as_str(_require(data, "price", path), _join(path, "price")),
            change_pct=_as_float(
                _require(data, "change_pct", path), _join(path, "change_pct")
            ),
        )


@dataclass(frozen=True, slots=True)
class Mag7:
    """七巨头单日涨跌面板。"""

    asof: str
    rows: tuple[QuoteRow, ...]
    note: str = ""
    source: str = ""

    @classmethod
    def from_dict(cls, data: Any, path: str) -> Mag7:
        rows = tuple(
            QuoteRow.from_dict(v, f"{_join(path, 'rows')}[{i}]")
            for i, v in enumerate(_as_list(_require(data, "rows", path), _join(path, "rows")))
        )
        if not rows:
            raise SchemaError(f"{_join(path, 'rows')} 不能是空数组；取不到行情就整个省掉 mag7")
        return cls(
            asof=_as_str(_require(data, "asof", path), _join(path, "asof")),
            rows=rows,
            note=_as_str(data.get("note", ""), _join(path, "note"), allow_empty=True),
            source=_as_str(data.get("source", ""), _join(path, "source"), allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class TapeRow:
    """指数与利率面板里的一行。"""

    name: str
    value: str
    change: str
    direction: str

    @classmethod
    def from_dict(cls, data: Any, path: str) -> TapeRow:
        return cls(
            name=_as_str(_require(data, "name", path), _join(path, "name")),
            value=_as_str(_require(data, "value", path), _join(path, "value")),
            change=_as_str(
                _require(data, "change", path), _join(path, "change"), allow_empty=True
            ),
            direction=_as_enum(_require(data, "dir", path), DIRECTIONS, _join(path, "dir")),
        )


@dataclass(frozen=True, slots=True)
class Tape:
    asof: str
    rows: tuple[TapeRow, ...]

    @classmethod
    def from_dict(cls, data: Any, path: str) -> Tape:
        return cls(
            asof=_as_str(_require(data, "asof", path), _join(path, "asof")),
            rows=tuple(
                TapeRow.from_dict(v, f"{_join(path, 'rows')}[{i}]")
                for i, v in enumerate(
                    _as_list(_require(data, "rows", path), _join(path, "rows"))
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """一个日历事件。

    ``when`` 是给人看的自由文本（"Fri 9/11"、"本月晚些"、"10月"），
    ``date`` 是可选的精确日期，供日历网格定位这个事件落在哪一格。
    没有 ``date`` 的条目（日期还没定的会议、粗略的月份预告）落进
    「日期待定」列表，而不会强行摆到网格的某一天上瞎猜。

    ``sources`` 复用新闻条目的同一个 :class:`Source` 结构，理由很直接：
    一个排定的日期（联储会议、财报、发布会）本身就是一条需要出处的事实，
    跟新闻条目里任何一个数字没有本质区别，不该因为它出现在日历里就
    免于「每个数字都能追到来源」这条规则。
    """

    when: str
    time: str
    event: str
    weight: str = "low"
    date: dt.date | None = None
    sources: tuple[Source, ...] = ()

    @property
    def label(self) -> str:
        return WEIGHT_LABEL[self.weight]

    @classmethod
    def from_dict(cls, data: Any, path: str) -> CalendarEntry:
        date_raw = data.get("date")
        sources = tuple(
            Source.from_dict(v, f"{_join(path, 'sources')}[{i}]")
            for i, v in enumerate(_as_list(data.get("sources") or [], _join(path, "sources")))
        )
        return cls(
            when=_as_str(_require(data, "when", path), _join(path, "when")),
            time=_as_str(_require(data, "time", path), _join(path, "time"), allow_empty=True),
            event=_as_str(_require(data, "event", path), _join(path, "event")),
            weight=_as_enum(data.get("weight", "low"), WEIGHTS, _join(path, "weight")),
            date=_as_date(date_raw, _join(path, "date")) if date_raw is not None else None,
            sources=sources,
        )


@dataclass(frozen=True, slots=True)
class MomentumCandidate:
    """一只被价量筛出来的异动标的。

    数字部分由 ``scan_momentum.py`` 算好写进 ``data/momentum_scan.json``，
    每日流水线把它和当天扫到的新闻交叉之后，挑一部分写进简报 JSON。
    所以这里的字段分两类：``stage`` 往下的是机器算的事实，
    ``coverage`` 和 ``note`` 是流水线交叉新闻之后补的判断。
    """

    ticker: str
    stage: str
    close: float
    change_pct: float
    rvol: float
    breakout_age: int | None = None
    ext_ma20: float = 0.0
    run_from_base: float = 0.0
    coverage: str = "none"
    note: str = ""
    sources: tuple[Source, ...] = ()

    @property
    def stage_label(self) -> str:
        return STAGE_LABEL[self.stage]

    @property
    def coverage_label(self) -> str:
        return COVERAGE_LABEL[self.coverage]

    @property
    def age_label(self) -> str:
        """突破后的天数，给人看的写法。未突破时用破折号而不是 0——
        「还没突破」和「今天刚突破」是两件完全不同的事。"""
        if self.breakout_age is None:
            return "—"
        return "当天" if self.breakout_age == 0 else f"{self.breakout_age} 日"

    @classmethod
    def from_dict(cls, data: Any, path: str) -> MomentumCandidate:
        age_raw = data.get("breakout_age")
        sources = tuple(
            Source.from_dict(v, f"{_join(path, 'sources')}[{i}]")
            for i, v in enumerate(_as_list(data.get("sources") or [], _join(path, "sources")))
        )
        return cls(
            ticker=_as_str(_require(data, "ticker", path), _join(path, "ticker")).upper(),
            stage=_as_enum(_require(data, "stage", path), STAGES, _join(path, "stage")),
            close=_as_float(_require(data, "close", path), _join(path, "close")),
            change_pct=_as_float(
                _require(data, "change_pct", path), _join(path, "change_pct")
            ),
            rvol=_as_float(_require(data, "rvol", path), _join(path, "rvol")),
            breakout_age=(
                _as_int(age_raw, _join(path, "breakout_age")) if age_raw is not None else None
            ),
            ext_ma20=_as_float(data.get("ext_ma20", 0.0), _join(path, "ext_ma20")),
            run_from_base=_as_float(
                data.get("run_from_base", 0.0), _join(path, "run_from_base")
            ),
            coverage=_as_enum(
                data.get("coverage", "none"), NEWS_COVERAGE, _join(path, "coverage")
            ),
            note=_as_str(data.get("note", ""), _join(path, "note"), allow_empty=True),
            sources=sources,
        )


@dataclass(frozen=True, slots=True)
class Momentum:
    """异动板块。空的 ``candidates`` 表示当天没有值得看的标的——
    这是完全正常的结果，不是数据缺失：多数交易日里没有新的突破。"""

    asof: str
    scanned: int = 0
    note: str = ""
    candidates: tuple[MomentumCandidate, ...] = ()

    def by_stage(self, stage: str) -> tuple[MomentumCandidate, ...]:
        return tuple(c for c in self.candidates if c.stage == stage)

    @property
    def early(self) -> tuple[MomentumCandidate, ...]:
        """初动档。整个模块存在的理由就是这一档，展示时排在最前。"""
        return self.by_stage("ignition")

    @classmethod
    def from_dict(cls, data: Any, path: str) -> Momentum:
        if not isinstance(data, dict):
            raise SchemaError(f"{path} 应该是一个对象，实际是 {type(data).__name__}")
        candidates = tuple(
            MomentumCandidate.from_dict(v, f"{path}.candidates[{i}]")
            for i, v in enumerate(
                _as_list(data.get("candidates") or [], _join(path, "candidates"))
            )
        )
        return cls(
            asof=_as_str(_require(data, "asof", path), _join(path, "asof")),
            scanned=_as_int(data.get("scanned", 0), _join(path, "scanned")),
            note=_as_str(data.get("note", ""), _join(path, "note"), allow_empty=True),
            candidates=candidates,
        )


@dataclass(frozen=True, slots=True)
class Brief:
    """一天的完整简报。"""

    date: dt.date
    weekday: str
    edition: str
    generated_at: str
    scanned: int
    kept: int
    thesis: str
    tape: Tape
    items: tuple[Item, ...]
    calendar: tuple[CalendarEntry, ...] = ()
    mag7: Mag7 | None = None
    momentum: Momentum | None = None
    #: 覆写时效上限。周日与周一的前瞻版覆盖整个周末，用得上。
    max_age_days: int | None = None

    # -------------------------------------------------------------- 查询接口

    def by_tier(self, tier: str) -> tuple[Item, ...]:
        """按分层取条目，保持原有顺序。"""
        return tuple(i for i in self.items if i.tier == tier)

    def ticker_hits(self) -> dict[str, list[int]]:
        """代码 -> 提及它的条目排名列表。自选股面板靠这个点亮。"""
        hits: dict[str, list[int]] = {}
        for item in self.items:
            for tk in item.tickers:
                hits.setdefault(tk, []).append(item.rank)
        return hits

    def stale_ranks(self, limit: int) -> list[int]:
        """超过时效上限的条目排名。"""
        out = []
        for item in self.items:
            age = item.age_days(self.date)
            if age is not None and age > limit:
                out.append(item.rank)
        return out

    def warnings(self, *, max_age_days: int, min_items: int) -> list[str]:
        """内容质量警告。这些不阻断发布，只是提醒当天的简报成色不够。"""
        notes: list[str] = []

        limit = self.max_age_days if self.max_age_days is not None else max_age_days
        stale = self.stale_ranks(limit)
        if stale:
            joined = "、".join(str(r) for r in stale)
            notes.append(f"第 {joined} 条超过了 {limit} 天的时效上限")

        if len(self.items) < min_items:
            notes.append(f"只有 {len(self.items)} 条，低于 {min_items} 条的下限，扫描可能不够")

        ranks = [i.rank for i in self.items]
        if len(set(ranks)) != len(ranks):
            notes.append("rank 有重复，页面内锚点跳转会失效")
        elif sorted(ranks) != list(range(1, len(ranks) + 1)):
            notes.append(f"rank 应该是 1 到 {len(ranks)} 的连续整数，实际是 {sorted(ranks)}")

        missing = [i.rank for i in self.items if i.published is None]
        if missing:
            joined = "、".join(str(r) for r in missing)
            notes.append(f"第 {joined} 条缺 published，页面上不会有时效徽章")

        no_depth = [i.rank for i in self.by_tier("must-read") if not i.has_depth]
        if no_depth:
            joined = "、".join(str(r) for r in no_depth)
            notes.append(f"必读层第 {joined} 条没有任何深度元数据（资产矩阵/交叉信源/历史脉络）")

        return notes

    # ------------------------------------------------------------ 反序列化

    @classmethod
    def from_dict(cls, data: Any, path: str = "") -> Brief:
        if not isinstance(data, dict):
            raise SchemaError(f"简报根节点应该是一个对象，实际是 {type(data).__name__}")

        items = tuple(
            Item.from_dict(v, f"items[{i}]")
            for i, v in enumerate(_as_list(_require(data, "items", path), "items"))
        )
        if not items:
            raise SchemaError("items 不能是空数组，一条新闻都没有就没必要发布")

        calendar = tuple(
            CalendarEntry.from_dict(v, f"calendar[{i}]")
            for i, v in enumerate(_as_list(data.get("calendar") or [], "calendar"))
        )

        mag7_raw = data.get("mag7")
        momentum_raw = data.get("momentum")
        max_age = data.get("max_age_days")

        return cls(
            date=_as_date(_require(data, "date", path), "date"),
            weekday=_as_str(_require(data, "weekday", path), "weekday"),
            edition=_as_str(_require(data, "edition", path), "edition"),
            generated_at=_as_str(_require(data, "generated_at", path), "generated_at"),
            scanned=_as_int(_require(data, "scanned", path), "scanned"),
            kept=_as_int(_require(data, "kept", path), "kept"),
            thesis=_as_str(_require(data, "thesis", path), "thesis"),
            tape=Tape.from_dict(_require(data, "tape", path), "tape"),
            items=items,
            calendar=calendar,
            mag7=Mag7.from_dict(mag7_raw, "mag7") if mag7_raw else None,
            momentum=Momentum.from_dict(momentum_raw, "momentum") if momentum_raw else None,
            max_age_days=(
                _as_int(max_age, "max_age_days") if max_age is not None else None
            ),
        )
