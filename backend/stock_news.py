"""某只股票在历史简报里出现过的条目。

**新闻来自你自己的简报，不接第三方新闻源。** 这个选择是这一块最有价值的
地方：简报里的每一条都已经被筛过、去过重、写过「为什么重要」，还标了
分层和涉及的资产。第三方接口给的是一堆未经筛选的标题，塞进个股页只会
变成噪音——而躲开噪音正是这整个项目存在的理由。

代价是覆盖有限：只有被简报扫到过的代码才有内容，冷门票会是空的。空了
就整块不显示，不放一个「暂无新闻」的占位——占位传达的信息量是零，
占的注意力却和有内容时一样多。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: 一只票最多回溯多少条。再多就不是「相关新闻」而是一份档案了。
MAX_ITEMS = 8


@dataclass(frozen=True, slots=True)
class Mention:
    """某一天的简报里提到这只票的一条。"""

    date: str
    rank: int
    tier: str
    title: str
    why: str
    tickers: tuple[str, ...]

    @property
    def tier_label(self) -> str:
        return {"must-read": "必读", "worth-knowing": "值得知道"}.get(
            self.tier, "背景噪音"
        )


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def mentions_for(
    briefs_dir: Path, ticker: str, *, limit: int = MAX_ITEMS
) -> tuple[Mention, ...]:
    """按日期从新到旧找出提到 ``ticker`` 的条目。

    直接读 JSON 而不是走 ``schema.Brief``：这里只要四个字段，而完整校验
    会因为某一天的简报缺一个无关字段就整份抛错——个股页上少几条旧新闻
    是小事，因此拖垮整页不是。
    """
    symbol = ticker.upper()
    found: list[Mention] = []

    for path in sorted(briefs_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = data.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            tickers = [
                str(t).upper() for t in (item.get("tickers") or []) if t
            ]
            if symbol not in tickers:
                continue
            # 字段名以简报 JSON 为准：标题是 headline，不是 title。
            headline = item.get("headline") or item.get("title") or ""
            found.append(
                Mention(
                    date=_as_str(data.get("date")) or path.stem,
                    rank=int(item.get("rank") or 0),
                    tier=_as_str(item.get("tier")),
                    title=_as_str(headline),
                    why=_as_str(item.get("why")),
                    tickers=tuple(tickers),
                )
            )
            if len(found) >= limit:
                return tuple(found)

    return tuple(found)
