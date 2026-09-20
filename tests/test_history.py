"""历史 K 线的解析。

这里最要紧的一组是**空洞处理**。Yahoo 的数组里会夹 ``null``（停牌、数据
缺失、当天还没开盘），把 null 当成 0 画出来就是一根跌到地板的假 K 线——
比缺一根危险得多，因为它看起来像真的，没人会去怀疑它。

网络不在测试范围内：``parse_history`` 是纯函数，注入一段假响应就能覆盖
全部分支，不联网也不受对方限流影响，跟 ``test_quotes`` 同一个路数。
"""

from __future__ import annotations

import unittest

from taurient_lite.history import (
    DEFAULT_RANGE,
    RANGES,
    Bar,
    HistoryError,
    parse_history,
    summarise,
)


def payload(stamps, **series):
    """拼一段 chart 端点形状的响应。缺省给出四价齐全的一根。"""
    n = len(stamps)
    quote = {
        "open": series.get("open", [10.0] * n),
        "high": series.get("high", [11.0] * n),
        "low": series.get("low", [9.0] * n),
        "close": series.get("close", [10.5] * n),
        "volume": series.get("volume", [1000] * n),
    }
    return {"chart": {"result": [{"timestamp": stamps, "indicators": {"quote": [quote]}}]}}


#: 2026-09-16 / 17 / 18 的 UTC 零点。
DAYS = [1789516800, 1789603200, 1789689600]


class TestParseHistory(unittest.TestCase):
    def test_parses_every_bar(self):
        bars = parse_history("AAA", payload(DAYS))
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[0].date, "2026-09-16")
        self.assertEqual(bars[-1].date, "2026-09-18")

    def test_drops_bars_with_a_missing_price(self):
        """四价缺任何一个就整根丢掉，绝不补 0。"""
        bars = parse_history("AAA", payload(DAYS, close=[10.5, None, 10.7]))
        self.assertEqual([b.date for b in bars], ["2026-09-16", "2026-09-18"])

    def test_drops_nan_prices(self):
        bars = parse_history("AAA", payload(DAYS, high=[11.0, float("nan"), 11.2]))
        self.assertEqual(len(bars), 2)

    def test_missing_volume_becomes_zero_not_a_dropped_bar(self):
        """成交量缺失不该丢掉整根：价格才是这张图的主体。"""
        bars = parse_history("AAA", payload(DAYS, volume=[1000, None, 1200]))
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[1].volume, 0)

    def test_bad_structure_raises_instead_of_inventing_data(self):
        for bad in ({}, {"chart": {}}, {"chart": {"result": []}},
                    {"chart": {"result": [{"timestamp": []}]}}):
            with self.assertRaises(HistoryError):
                parse_history("AAA", bad)

    def test_all_bars_broken_raises(self):
        with self.assertRaises(HistoryError):
            parse_history("AAA", payload(DAYS, close=[None, None, None]))


class TestBarShapes(unittest.TestCase):
    def setUp(self):
        self.up = Bar("2026-09-18", 10.0, 12.0, 9.5, 11.0, 5000)
        self.down = Bar("2026-09-18", 11.0, 11.5, 9.0, 10.0, 6000)

    def test_candle_shape_matches_the_chart_library(self):
        self.assertEqual(
            self.up.as_candle(),
            {"time": "2026-09-18", "open": 10.0, "high": 12.0, "low": 9.5, "close": 11.0},
        )

    def test_volume_colour_follows_the_bar_direction(self):
        colors = {"up_color": "#0f0", "down_color": "#f00"}
        self.assertEqual(self.up.as_volume(**colors)["color"], "#0f0")
        self.assertEqual(self.down.as_volume(**colors)["color"], "#f00")

    def test_doji_counts_as_up(self):
        """开盘收盘相等时归到涨的一侧，总得选一边，选法写下来就行。"""
        flat = Bar("2026-09-18", 10.0, 10.0, 10.0, 10.0, 1)
        self.assertEqual(flat.as_volume(up_color="#0f0", down_color="#f00")["color"], "#0f0")


class TestSummarise(unittest.TestCase):
    def test_range_change_uses_first_and_last_close(self):
        bars = [Bar("2026-09-16", 10, 10, 10, 100.0, 1),
                Bar("2026-09-18", 10, 10, 10, 110.0, 1)]
        self.assertAlmostEqual(summarise(bars)["change_pct"], 10.0)

    def test_high_and_low_span_the_whole_range(self):
        bars = [Bar("2026-09-16", 10, 20.0, 5.0, 10, 1),
                Bar("2026-09-18", 10, 15.0, 1.0, 10, 1)]
        stats = summarise(bars)
        self.assertEqual(stats["high"], 20.0)
        self.assertEqual(stats["low"], 1.0)

    def test_empty_input_is_an_empty_dict(self):
        self.assertEqual(summarise([]), {})

    def test_zero_first_close_does_not_divide_by_zero(self):
        bars = [Bar("2026-09-16", 0, 0, 0, 0.0, 1), Bar("2026-09-18", 1, 1, 1, 1.0, 1)]
        self.assertEqual(summarise(bars)["change_pct"], 0.0)


class TestRanges(unittest.TestCase):
    def test_default_range_is_supported(self):
        self.assertIn(DEFAULT_RANGE, RANGES)

    def test_long_ranges_use_coarser_bars(self):
        """5 年用日线会有一千两百多根，缩到一屏后每根不到一个像素。"""
        self.assertEqual(RANGES["5y"], "1wk")
        self.assertEqual(RANGES["6mo"], "1d")


if __name__ == "__main__":
    unittest.main()
