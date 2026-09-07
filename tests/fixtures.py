"""测试用的样本数据构造器。

每个 ``make_*`` 都返回一个**合法的最小对象**，通过关键字参数覆盖单个字段。
这样每个测试只需要说明它关心的那一处差异，其余保持合法，测试意图一眼可见，
也不会因为新增必填字段而让几十个测试同时崩掉。
"""

from __future__ import annotations

from typing import Any


def make_source(**over: Any) -> dict:
    return {"name": "CNBC", "url": "https://example.com/a", **over}


def make_asset(**over: Any) -> dict:
    return {
        "asset_class": "美股",
        "direction": "down",
        "conviction": "high",
        "note": "贴现率上行压缩长久期估值",
        **over,
    }


def make_cross_source(**over: Any) -> dict:
    return {"agreement": "aligned", "summary": "三家口径一致，都把主因归到就业数据。", **over}


def make_history(**over: Any) -> dict:
    return {
        "summary": "从降息预期到加息定价的完整翻转。",
        "timeline": [
            {"when": "2026-07", "event": "市场定价年内两次降息"},
            {"when": "2026-09-04", "event": "非农超预期，加息定价升到 68%"},
        ],
        **over,
    }


def make_item(**over: Any) -> dict:
    return {
        "rank": 1,
        "tier": "must-read",
        "headline": "8 月非农 162k，三倍于预期",
        "body": "美国 8 月新增非农就业 162,000 人，预期仅 53,000 人。",
        "published": "2026-09-04",
        "sectors": ["宏观", "利率"],
        "tickers": ["SPY"],
        "why": "整条收益率曲线要重新定价。",
        "impact": "全市场",
        "sources": [make_source()],
        **over,
    }


def make_deep_item(**over: Any) -> dict:
    """带全套深度元数据的条目。"""
    return make_item(
        assets=[make_asset(), make_asset(asset_class="美债", direction="up")],
        cross_source=make_cross_source(),
        history=make_history(),
        **over,
    )


def make_tape(**over: Any) -> dict:
    return {
        "asof": "收盘 · Fri 9/4",
        "rows": [
            {"name": "S&P 500", "value": "7,718.60", "change": "-0.38%", "dir": "down"},
            {"name": "US 10Y", "value": "4.79%", "change": "新高", "dir": "up"},
        ],
        **over,
    }


def make_mag7(**over: Any) -> dict:
    return {
        "asof": "收盘 · Fri 9/4 16:00 ET",
        "note": "五跌两涨。",
        "rows": [
            {"ticker": "NVDA", "price": "230.36", "change_pct": 0.84},
            {"ticker": "TSLA", "price": "354.08", "change_pct": -5.92},
        ],
        **over,
    }


def make_brief(**over: Any) -> dict:
    return {
        "date": "2026-09-06",
        "weekday": "Sunday",
        "edition": "Week-ahead edition",
        "generated_at": "2026-09-06 15:10 PT",
        "scanned": 78,
        "kept": 2,
        "thesis": "就业数据把叙事从降息翻转到加息。",
        "tape": make_tape(),
        "mag7": make_mag7(),
        "items": [
            make_deep_item(),
            make_item(rank=2, tier="noise", headline="次要新闻", tickers=[]),
        ],
        "calendar": [
            {
                "when": "Fri 9/11",
                "time": "08:30 ET",
                "event": "8 月 CPI",
                "weight": "high",
                "date": "2026-09-11",
                "sources": [make_source(name="BLS")],
            },
            {
                "when": "本月晚些",
                "time": "",
                "event": "9 月 FOMC 决议",
                "weight": "high",
                # 故意不给 date：日期未定的事件应该落进「日期待定」列表，
                # 而不是被伪造一个日期摆上网格。
            },
        ],
        **over,
    }


def make_config(**over: Any) -> dict:
    return {
        "artifact_url": "https://example.com/artifact",
        "timezone": "America/Los_Angeles",
        "freshness": {"max_age_days": 3, "must_read_max_age_days": 2},
        "target_counts": {"total_min": 2},
        "mag7": ["NVDA", "TSLA"],
        "watchlist": {"symbols": ["SPY", "NVDA"]},
        **over,
    }


def yahoo_payload(price: float = 230.36, change: float = 0.836, stamp: int = 1788552000) -> dict:
    """Yahoo chart 端点的最小合法响应。"""
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": price,
                        "regularMarketChangePercent": change,
                        "regularMarketTime": stamp,
                    }
                }
            ]
        }
    }
