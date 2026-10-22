"""发布前的质量门：一份简报能不能上线，由这里说了算。

:meth:`Brief.warnings <taurient_lite.schema.Brief.warnings>` 只提醒不阻断——
那是给人跑流水线时设计的，人看到警告会自己回去补。现在跑流水线的是 agent，
「打印一条警告然后照常发布」等于没有检查。所以这里把同一批规则连同几条新的
机械规则收在一起，**任何一条不过就不许发布**，agent 必须改到全部通过。

**只放机器能判断对错的规则。** 条数够不够、日期对不对、有没有写买卖倾向，
这些有唯一答案，交给代码。主线立不立得住、分层合不合理、``why`` 是不是在
复述新闻——这些需要读懂内容，交给 outcome 评分器（``agents/rubric.md``）。
两边不重叠：评分器只需要确认这个脚本退出码为 0。

**不重复 schema 已经挡住的东西。** 字段类型、枚举值、链接协议在
:mod:`taurient_lite.schema` 解析时就会抛错，走不到这里。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from .config import Config
from .schema import Brief
from .sectors import EASTERN, last_trading_day

#: 带买卖倾向的措辞。简报只陈述发生了什么，不告诉读者该做什么。
#:
#: 刻意只收「对读者下指令」的说法，不收描述市场行为的词——「高盛给予买入
#: 评级」是在报道别人的观点，「资金在加仓 AI 硬件」「不是单纯的抄底」是在
#: 描述盘面，都属于事实。「加仓」「抄底」最初也在表里，拿历史简报一跑，
#: 命中的全是这类描述，于是删掉了：误报多了，agent 只会学会绕开关键词。
ADVICE_PHRASES: tuple[str, ...] = (
    "值得关注",
    "可以考虑",
    "建议买入",
    "建议卖出",
    "建议关注",
    "介入窗口",
    "可以介入",
    "买点",
    "卖点",
)

#: 简报是开盘前生成的，按美东早上 8 点算「那一刻最近走完的交易日」。
#: 取 8 点而不是生成时刻：生成时刻写在 ``generated_at`` 里、格式不受约束，
#: 而日期本身已经足以确定预期的数据日。
BRIEF_CLOCK = dt.time(8, 0)


@dataclass(frozen=True, slots=True)
class Problem:
    """一条不通过的规则。``path`` 指到 JSON 里要改的位置。"""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def expected_data_day(brief_date: dt.date) -> dt.date:
    """这份盘前简报里的行情数据应该是哪个交易日的。"""
    return last_trading_day(dt.datetime.combine(brief_date, BRIEF_CLOCK, tzinfo=EASTERN))


def check(brief: Brief, raw: dict[str, Any], config: Config) -> list[Problem]:
    """检查一份已经通过 schema 解析的简报。

    :param raw: 同一份简报的原始 JSON。有些字段 schema 不收（比如异动候选的
        ``date``），但质量门需要看。
    """
    problems: list[Problem] = []
    problems += _check_warnings(brief, config)
    problems += _check_tiers(brief, config)
    problems += _check_sources(brief)
    problems += _check_market(brief)
    problems += _check_momentum(brief, raw)
    problems += _check_advice(brief)
    return problems


def _check_warnings(brief: Brief, config: Config) -> list[Problem]:
    """原来只打印的警告，现在一律阻断。"""
    return [
        Problem("items", note)
        for note in brief.warnings(
            max_age_days=config.freshness.max_age_days, min_items=config.min_items
        )
    ]


def _check_tiers(brief: Brief, config: Config) -> list[Problem]:
    out = []
    for tier, (low, _high) in config.tier_targets.items():
        count = len(brief.by_tier(tier))
        if count < low:
            out.append(Problem("items", f"{tier} 只有 {count} 条，低于下限 {low}"))

    # 必读层的时效上限比其余更严：已经发酵了几天的事不该排在头版。
    # 前瞻版的 max_age_days 覆写只放宽整体上限，不放宽这一条。
    limit = config.freshness.must_read_max_age_days
    for item in brief.by_tier("must-read"):
        age = item.age_days(brief.date)
        if age is not None and age > limit:
            out.append(Problem(
                f"items[rank={item.rank}].published",
                f"必读层条目发布于 {age} 天前，超过 {limit} 天上限，应降到 noise 层",
            ))
    return out


def _check_sources(brief: Brief) -> list[Problem]:
    """每条新闻至少要有一个来源——「每个数字都要能追到 sources」的最低线。"""
    return [
        Problem(f"items[rank={item.rank}].sources", "没有任何来源")
        for item in brief.items
        if not item.sources
    ]


def _check_market(brief: Brief) -> list[Problem]:
    if brief.market is None:
        return [Problem("market", "缺板块热力块：先跑 fetch_sectors.py --apply <日期>")]
    out = []
    if brief.market.session != "close":
        out.append(Problem(
            "market.session",
            f"是 {brief.market.session!r}，盘前简报只能存收盘数据",
        ))
    want = expected_data_day(brief.date).isoformat()
    if brief.market.asof != want:
        out.append(Problem("market.asof", f"是 {brief.market.asof}，应该是 {want} 的收盘"))
    return out


def _check_momentum(brief: Brief, raw: dict[str, Any]) -> list[Problem]:
    """异动块可以整个省略（当天没有候选是正常的），但写了就必须是当天的。"""
    if brief.momentum is None:
        return []
    out = []
    asof = brief.momentum.asof
    want = expected_data_day(brief.date).isoformat()
    if asof != want:
        out.append(Problem("momentum.asof", f"是 {asof}，应该是 {want}"))

    raw_candidates = (raw.get("momentum") or {}).get("candidates") or []
    for i, (cand, raw_cand) in enumerate(zip(brief.momentum.candidates, raw_candidates)):
        path = f"momentum.candidates[{i}]"
        day = raw_cand.get("date") if isinstance(raw_cand, dict) else None
        if day is None:
            out.append(Problem(f"{path}.date", f"{cand.ticker} 缺数据日期：重跑 apply_momentum.py"))
        elif day != asof:
            out.append(Problem(
                f"{path}.date",
                f"{cand.ticker} 的数据停在 {day}，不是 {asof}，是过期的票，应该删掉",
            ))
        if not cand.note.strip():
            out.append(Problem(f"{path}.note", f"{cand.ticker} 还没写 note"))
    return out


def _texts(brief: Brief):
    """所有简报自己写的文字，连同它们在 JSON 里的位置。"""
    yield "thesis", brief.thesis
    for item in brief.items:
        base = f"items[rank={item.rank}]"
        yield f"{base}.headline", item.headline
        yield f"{base}.body", item.body
        yield f"{base}.why", item.why
        yield f"{base}.impact", item.impact
        for j, asset in enumerate(item.assets):
            yield f"{base}.assets[{j}].note", asset.note
    if brief.momentum is not None:
        yield "momentum.note", brief.momentum.note
        for i, cand in enumerate(brief.momentum.candidates):
            yield f"momentum.candidates[{i}].note", cand.note


def _check_advice(brief: Brief) -> list[Problem]:
    out = []
    for path, text in _texts(brief):
        hits = [p for p in ADVICE_PHRASES if p in text]
        if hits:
            out.append(Problem(path, f"带买卖倾向的措辞：{'、'.join(hits)}"))
    return out
