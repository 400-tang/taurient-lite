"""异动探测测试：解析、指标、阶段判定、排序。

:mod:`taurient_lite.momentum` 除了 :func:`parse_chart_bars` 之外全是纯函数，
所以这里用**合成的日线序列**直接断言判定结果，不联网也不用夹具文件。
合成序列的好处是每个测试都能精确构造出想要的形态——一个 60 天的窄幅
盘整接一根放量突破，用真实数据是碰运气，用生成器是三行代码。
"""

from __future__ import annotations

import datetime as dt
import unittest

from taurient_lite.momentum import (
    BREAKOUT_LOOKBACK,
    EXTENDED_MA20_GAP,
    IGNITION_MIN_RVOL,
    MIN_BARS,
    MIN_DOLLAR_VOLUME,
    Bars,
    MomentumError,
    active_run,
    breakout_flags,
    classify,
    evaluate,
    parse_chart_bars,
    rank,
    score,
)

START = dt.date(2026, 1, 5)


def make_bars(
    closes: list[float],
    *,
    ticker: str = "TEST",
    volumes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
) -> Bars:
    """从收盘价序列造一份日线。未指定的字段按收盘价推出合理的默认值。"""
    n = len(closes)
    vols = volumes or [1_000_000.0] * n
    return Bars(
        ticker=ticker,
        dates=tuple(START + dt.timedelta(days=i) for i in range(n)),
        opens=tuple(opens or closes),
        highs=tuple(highs or [c * 1.01 for c in closes]),
        lows=tuple(lows or [c * 0.99 for c in closes]),
        closes=tuple(closes),
        volumes=tuple(vols),
    )


def flat_then_breakout(
    *, flat: int = 80, flat_price: float = 100.0, jump: float = 1.20, days: int = 1
) -> Bars:
    """一段窄幅盘整之后放量突破，突破维持 ``days`` 天。最典型的初动形态。"""
    closes = [flat_price + (i % 3) * 0.2 for i in range(flat)]
    closes += [flat_price * jump + i for i in range(days)]
    vols = [1_000_000.0] * flat + [5_000_000.0] * days
    return make_bars(closes, volumes=vols)


class ParseTest(unittest.TestCase):
    def payload(self, **over) -> dict:
        base = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1767571200, 1767657600, 1767744000],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10.0, 11.0, 12.0],
                                    "high": [10.5, 11.5, 12.5],
                                    "low": [9.5, 10.5, 11.5],
                                    "close": [10.2, 11.2, 12.2],
                                    "volume": [100, 200, 300],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        base.update(over)
        return base

    def test_parses_all_rows(self):
        bars = parse_chart_bars("X", self.payload())
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars.closes[-1], 12.2)
        self.assertEqual(bars.volumes[0], 100.0)

    def test_drops_rows_with_null(self):
        """停牌日的 ``None`` 整根丢弃，而不是前值填充。

        填充会造出一根成交量为零的假 K 线，把相对成交量一起带偏。
        """
        payload = self.payload()
        payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][1] = None
        bars = parse_chart_bars("X", payload)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars.closes, (10.2, 12.2))

    def test_bad_structure_raises(self):
        with self.assertRaises(MomentumError):
            parse_chart_bars("X", {"chart": {"result": []}})

    def test_all_null_raises(self):
        payload = self.payload()
        payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [None] * 3
        with self.assertRaises(MomentumError):
            parse_chart_bars("X", payload)


class BreakoutTest(unittest.TestCase):
    def test_flags_only_after_lookback(self):
        bars = make_bars([100.0] * 30)
        self.assertEqual(breakout_flags(bars, lookback=BREAKOUT_LOOKBACK), [False] * 30)

    def test_detects_breakout(self):
        bars = flat_then_breakout()
        flags = breakout_flags(bars)
        self.assertTrue(flags[-1])
        self.assertFalse(flags[-2])

    def test_run_start_is_first_day_not_latest(self):
        """连创新高时，起点应是这波的第一天，而不是最近一天。

        取最近一次突破会让年龄恒为 0，正好丢掉这个模块唯一关心的信息。
        """
        bars = flat_then_breakout(days=5)
        run = active_run(bars)
        self.assertIsNotNone(run)
        start, _ = run
        self.assertEqual(len(bars) - 1 - start, 4)

    def test_broken_run_is_not_active(self):
        """突破位失守之后，这波就结束了，不能再算成运行中的趋势。"""
        closes = [100.0] * 80 + [130.0] + [90.0] * 10
        bars = make_bars(closes, volumes=[1_000_000.0] * 91)
        self.assertIsNone(active_run(bars))

    def test_no_breakout_returns_none(self):
        self.assertIsNone(active_run(make_bars([100.0] * 90)))


class ClassifyTest(unittest.TestCase):
    def kw(self, **over):
        base = dict(
            breakout_age=0,
            rvol=5.0,
            ext_ma20=0.05,
            run_from_base=0.1,
            close=100.0,
            ma20=95.0,
        )
        base.update(over)
        return base

    def test_fresh_breakout_with_volume_is_ignition(self):
        self.assertEqual(classify(**self.kw()), "ignition")

    def test_fresh_breakout_without_volume_is_continuation(self):
        self.assertEqual(
            classify(**self.kw(rvol=IGNITION_MIN_RVOL - 0.5)), "continuation"
        )

    def test_no_breakout_is_base(self):
        self.assertEqual(classify(**self.kw(breakout_age=None)), "base")

    def test_far_from_ma20_is_extended(self):
        self.assertEqual(
            classify(**self.kw(ext_ma20=EXTENDED_MA20_GAP + 0.01)), "extended"
        )

    def test_old_breakout_is_extended(self):
        self.assertEqual(classify(**self.kw(breakout_age=30)), "extended")

    def test_doubled_from_base_is_extended(self):
        self.assertEqual(classify(**self.kw(run_from_base=1.5)), "extended")

    def test_veto_beats_freshness(self):
        """否决先于认定：刚突破但已翻倍，判已延伸而不是初动。

        它满足「刚突破」的字面条件，但使用者要的是可介入的时点。
        """
        self.assertEqual(
            classify(**self.kw(breakout_age=0, rvol=9.0, run_from_base=1.4)), "extended"
        )


class EvaluateTest(unittest.TestCase):
    def test_too_few_bars_raises(self):
        with self.assertRaises(MomentumError):
            evaluate(make_bars([100.0] * (MIN_BARS - 1)))

    def test_ignition_end_to_end(self):
        signal = evaluate(flat_then_breakout())
        self.assertEqual(signal.stage, "ignition")
        self.assertEqual(signal.breakout_age, 0)
        self.assertGreater(signal.rvol, IGNITION_MIN_RVOL)

    def test_quiet_stock_is_base(self):
        signal = evaluate(make_bars([100.0 + (i % 3) * 0.1 for i in range(90)]))
        self.assertEqual(signal.stage, "base")
        self.assertIsNone(signal.breakout_age)

    def test_rvol_uses_median_not_mean(self):
        """一次财报天量不该把之后一个月的放量基准抬高。

        均值会被极值拉走，中位数不会——这正是这里用中位数的原因。
        """
        closes = [100.0] * 90
        vols = [1_000_000.0] * 70 + [50_000_000.0] + [1_000_000.0] * 19
        signal = evaluate(make_bars(closes, volumes=vols))
        self.assertAlmostEqual(signal.rvol, 1.0, places=2)

    def test_closing_range_at_high(self):
        closes = [100.0] * 90
        bars = Bars(
            ticker="T",
            dates=tuple(START + dt.timedelta(days=i) for i in range(90)),
            opens=tuple(closes),
            highs=tuple(closes),
            lows=tuple(c * 0.9 for c in closes),
            closes=tuple(closes),
            volumes=tuple([1_000_000.0] * 90),
        )
        self.assertAlmostEqual(evaluate(bars).closing_range, 1.0)

    def test_as_dict_is_json_safe(self):
        payload = evaluate(flat_then_breakout()).as_dict()
        self.assertEqual(payload["stage"], "ignition")
        self.assertIsInstance(payload["date"], str)
        self.assertIsInstance(payload["breakout_age"], int)


class ScoreTest(unittest.TestCase):
    """分数衡量的是「有多早」，不是「有多好」——回测证明后者做不到。"""

    def test_ignition_outranks_extended(self):
        early = evaluate(flat_then_breakout())
        late = evaluate(flat_then_breakout(jump=2.5))
        self.assertEqual(late.stage, "extended")
        self.assertGreater(score(early), score(late))

    def test_extension_penalised_within_stage(self):
        near = evaluate(flat_then_breakout(jump=1.12))
        far = evaluate(flat_then_breakout(jump=1.30))
        self.assertGreater(score(near), score(far))

    def test_volume_does_not_buy_rank(self):
        """量再大也换不来更早的时点，所以不参与排序。"""
        quiet = flat_then_breakout()
        loud = flat_then_breakout()
        loud = Bars(
            **{
                **{f: getattr(loud, f) for f in Bars.__slots__},
                "volumes": loud.volumes[:-1] + (loud.volumes[-1] * 4,),
            }
        )
        self.assertAlmostEqual(score(evaluate(quiet)), score(evaluate(loud)), places=6)


class RankTest(unittest.TestCase):
    def signal(self, ticker: str, **over):
        bars = flat_then_breakout()
        bars = Bars(**{**{f: getattr(bars, f) for f in Bars.__slots__}, "ticker": ticker, **over})
        return evaluate(bars)

    def test_illiquid_filtered_out(self):
        thin = self.signal("THIN", volumes=tuple([100.0] * 81))
        self.assertLess(thin.dollar_volume, MIN_DOLLAR_VOLUME)
        self.assertEqual(rank([thin]), [])

    def test_penny_stock_filtered_out(self):
        penny = evaluate(flat_then_breakout(flat_price=1.0))
        self.assertEqual(rank([penny]), [])

    def test_sorted_by_score_desc(self):
        early = self.signal("EARLY")
        late = evaluate(flat_then_breakout(jump=2.5))
        ordered = rank([late, early])
        self.assertEqual([s.ticker for s in ordered][0], "EARLY")

    def test_limit_applies(self):
        signals = [self.signal(f"T{i}") for i in range(5)]
        self.assertEqual(len(rank(signals, limit=2)), 2)

    def test_score_written_back(self):
        ranked = rank([self.signal("A")])
        self.assertGreater(ranked[0].score, 0)


if __name__ == "__main__":
    unittest.main()


class ApplyMomentumTest(unittest.TestCase):
    """扫描结果写回简报 JSON 的挑选与合并逻辑。

    这两个是纯函数，所以不碰文件系统直接断言。它们值得测的原因很具体：
    ``merge`` 一旦写错，人已经写好的 ``note`` 会被下一次重跑静默冲掉——
    不报错、不告警，只是判断消失了。
    """

    def setUp(self):
        import apply_momentum

        self.mod = apply_momentum

    def row(self, ticker: str, stage: str = "ignition", **over) -> dict:
        return {
            "ticker": ticker,
            "stage": stage,
            "close": 10.0,
            "change_pct": 1.0,
            "rvol": 3.0,
            "breakout_age": 0,
            "ext_ma20": 0.1,
            "run_from_base": 0.2,
            "score": 99.0,
            **over,
        }

    def test_takes_every_ignition(self):
        """初动档不设上限：它通常只有个位数，而且正是这个板块的理由。"""
        rows = [self.row(f"I{i}") for i in range(12)]
        self.assertEqual(len(self.mod.pick(rows)), 12)

    def test_caps_other_stages(self):
        rows = [self.row(f"C{i}", "continuation") for i in range(9)]
        picked = self.mod.pick(rows)
        self.assertEqual(len(picked), self.mod.QUOTA["continuation"])

    def test_drops_base_stage(self):
        """基底档不进简报：近两千只，全带上等于没有筛选。"""
        self.assertEqual(self.mod.pick([self.row("B", "base")]), [])

    def test_keeps_scan_order(self):
        rows = [self.row("A"), self.row("B"), self.row("C")]
        self.assertEqual([r["ticker"] for r in self.mod.pick(rows)], ["A", "B", "C"])

    def test_merge_copies_mechanical_fields(self):
        merged = self.mod.merge([self.row("X", close=42.5)], [])
        self.assertEqual(merged[0]["close"], 42.5)
        self.assertEqual(merged[0]["note"], "")

    def test_merge_drops_non_mechanical_scan_fields(self):
        """``score`` 是排序用的中间量，不该漏进简报 JSON。"""
        self.assertNotIn("score", self.mod.merge([self.row("X")], [])[0])

    def test_merge_preserves_human_judgement(self):
        """重跑不能冲掉人写的判断，否则「补完再跑一次」这条路就断了。"""
        prior = [{"ticker": "X", "note": "早盘有大单成交"}]
        merged = self.mod.merge([self.row("X", close=99.0)], prior)
        self.assertEqual(merged[0]["note"], "早盘有大单成交")
        self.assertEqual(merged[0]["close"], 99.0)  # 数字仍然被刷新

    def test_merge_preserves_sources(self):
        prior = [{"ticker": "X", "sources": [{"name": "CNBC", "url": "https://e.com"}]}]
        self.assertEqual(len(self.mod.merge([self.row("X")], prior)[0]["sources"]), 1)

    def test_merge_ignores_stale_tickers(self):
        """昨天写过、今天没再入选的标的不该被带进来。"""
        prior = [{"ticker": "GONE", "note": "旧的"}]
        merged = self.mod.merge([self.row("NEW")], prior)
        self.assertEqual([m["ticker"] for m in merged], ["NEW"])

    def test_merged_output_passes_schema(self):
        """合并结果必须能直接通过 schema 校验，否则渲染阶段才炸。"""
        from taurient_lite.schema import Momentum

        merged = self.mod.merge([self.row("X"), self.row("Y", "continuation")], [])
        block = Momentum.from_dict(
            {"asof": "2026-09-10", "scanned": 2500, "candidates": merged}, "momentum"
        )
        self.assertEqual(len(block.candidates), 2)
        self.assertEqual(len(block.early), 1)


class MomentumStripTest(unittest.TestCase):
    """首页摘要条。它的存在本身是个产品判断：标签页要点一下才看得见，
    而一个每天不会被点开的早期信号等于没有。"""

    def block(self, stages=("ignition",)):
        from taurient_lite.schema import Momentum

        return Momentum.from_dict(
            {
                "asof": "2026-09-10",
                "scanned": 2500,
                "candidates": [
                    {
                        "ticker": f"T{i}",
                        "stage": s,
                        "close": 10.0,
                        "change_pct": 1.0,
                        "rvol": 3.5,
                    }
                    for i, s in enumerate(stages)
                ],
            },
            "momentum",
        )

    def test_empty_without_data(self):
        from taurient_lite.components.momentum import momentum_strip

        self.assertEqual(momentum_strip(None), "")

    def test_empty_without_ignition(self):
        """只有延续和已延伸时首页不出现——那两档不紧急，占首页版面不值得。"""
        from taurient_lite.components.momentum import momentum_strip

        self.assertEqual(momentum_strip(self.block(("continuation", "extended"))), "")

    def test_shows_only_ignition(self):
        from taurient_lite.components.momentum import momentum_strip

        html = momentum_strip(self.block(("ignition", "continuation", "extended")))
        self.assertIn("T0", html)
        self.assertNotIn("T1", html)
        self.assertNotIn("T2", html)

    def test_links_into_tab(self):
        from taurient_lite.components.momentum import momentum_strip

        self.assertIn('href="#tab-momentum"', momentum_strip(self.block()))

    def test_states_count_only(self):
        """只陈述数量。曾经这里还写「其中 N 只没有新闻报道」，
        那句话的依据只是当天扫到的几十篇，属于过度声称，已删。"""
        from taurient_lite.components.momentum import momentum_strip

        html = momentum_strip(self.block(("ignition", "ignition")))
        self.assertIn("2 只刚进入初动档", html)
        self.assertNotIn("报道", html)

    def test_escapes_ticker(self):
        from taurient_lite.components.momentum import momentum_strip
        from taurient_lite.schema import Momentum

        block = Momentum.from_dict(
            {
                "asof": "x",
                "candidates": [
                    {
                        "ticker": "<script>",
                        "stage": "ignition",
                        "close": 1.0,
                        "change_pct": 0.0,
                        "rvol": 3.0,
                    }
                ],
            },
            "m",
        )
        self.assertNotIn("<script>", momentum_strip(block))


class SessionCutoffTest(unittest.TestCase):
    """未完成交易时段的过滤。

    这是一次真实事故的补丁：定时任务延迟到盘中运行，Yahoo 为当天开出一根
    **还在变动**的 K 线，脚本把半天的成交量当成一整天，产出的文件看上去
    完全正常——不报警、不抛异常，只是数字全错。
    """

    OPEN, CLOSE = 1789738200, 1789761600  # 某个交易日的 13:30 与 20:00 UTC

    def meta(self, market_time, **over):
        base = {
            "regularMarketTime": market_time,
            "currentTradingPeriod": {"regular": {"start": self.OPEN, "end": self.CLOSE}},
        }
        base.update(over)
        return base

    def test_mid_session_returns_start(self):
        from taurient_lite.momentum import session_cutoff

        self.assertEqual(session_cutoff(self.meta(self.OPEN + 3600)), self.OPEN)

    def test_after_close_returns_none(self):
        from taurient_lite.momentum import session_cutoff

        self.assertIsNone(session_cutoff(self.meta(self.CLOSE + 60)))

    def test_missing_metadata_returns_none(self):
        """判断不了就不过滤——宁可用上完整数据，也不要因为缺字段丢掉一天。"""
        from taurient_lite.momentum import session_cutoff

        self.assertIsNone(session_cutoff({}))
        self.assertIsNone(session_cutoff({"regularMarketTime": self.OPEN}))

    def test_partial_bar_is_dropped(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": self.meta(self.OPEN + 3600),
                        "timestamp": [self.OPEN - 86400, self.OPEN],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10.0, 11.0],
                                    "high": [10.5, 11.5],
                                    "low": [9.5, 10.5],
                                    "close": [10.2, 11.2],
                                    "volume": [1000, 50],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        bars = parse_chart_bars("X", payload)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars.closes, (10.2,))

    def test_completed_bar_is_kept(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": self.meta(self.CLOSE + 600),
                        "timestamp": [self.OPEN - 86400, self.OPEN],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10.0, 11.0],
                                    "high": [10.5, 11.5],
                                    "low": [9.5, 10.5],
                                    "close": [10.2, 11.2],
                                    "volume": [1000, 2000],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        self.assertEqual(len(parse_chart_bars("X", payload)), 2)
