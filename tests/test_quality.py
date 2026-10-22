"""发布前质量门。

每个测试从一份**能通过**的简报出发，只改一处，断言那一处被抓出来——
这样既证明规则会报警，也证明它不会对合格的简报误报。
"""

from __future__ import annotations

import copy
import datetime as dt
import unittest

from taurient_lite.config import Config
from taurient_lite.quality import ADVICE_PHRASES, check, expected_data_day
from taurient_lite.schema import Brief

from . import fixtures as F

#: 周二的盘前简报，数据应该是周一收盘的。
DATE = "2026-09-08"
DATA_DAY = "2026-09-07"


def candidate(**over):
    return {
        "ticker": "ABC", "stage": "ignition", "close": 12.3, "change_pct": 8.1,
        "rvol": 3.2, "breakout_age": 0, "ext_ma20": 0.1, "run_from_base": 0.2,
        "date": DATA_DAY, "note": "放量突破 50 日高点。", **over,
    }


def passing_brief() -> dict:
    return F.make_brief(
        date=DATE,
        items=[
            F.make_deep_item(published=DATA_DAY),
            F.make_item(rank=2, tier="noise", headline="次要新闻", tickers=[], published=DATA_DAY),
        ],
        market=F.make_market(asof=DATA_DAY),
        momentum={"asof": DATA_DAY, "scanned": 2500, "note": "", "candidates": [candidate()]},
    )


def run(raw: dict, **config_over) -> list[str]:
    config = Config.from_dict(F.make_config(**config_over))
    return [str(p) for p in check(Brief.from_dict(raw), raw, config)]


class TestBaseline(unittest.TestCase):
    def test_passing_brief_has_no_problems(self):
        self.assertEqual(run(passing_brief()), [])


class TestExpectedDataDay(unittest.TestCase):
    def test_tuesday_brief_wants_monday(self):
        self.assertEqual(expected_data_day(dt.date(2026, 9, 8)), dt.date(2026, 9, 7))

    def test_monday_brief_wants_friday(self):
        self.assertEqual(expected_data_day(dt.date(2026, 9, 21)), dt.date(2026, 9, 18))


class TestWarningsNowBlock(unittest.TestCase):
    def test_too_few_items(self):
        problems = run(passing_brief(), target_counts={"total_min": 5})
        self.assertTrue(any("低于 5 条" in p for p in problems))

    def test_must_read_without_depth(self):
        raw = passing_brief()
        raw["items"][0] = F.make_item(published=DATA_DAY)
        self.assertTrue(any("深度元数据" in p for p in run(raw)))


class TestTiers(unittest.TestCase):
    def test_tier_below_minimum(self):
        problems = run(passing_brief(), target_counts={"total_min": 2, "noise": [3, 6]})
        self.assertIn("items: noise 只有 1 条，低于下限 3", problems)

    def test_above_maximum_is_left_to_the_grader(self):
        self.assertEqual(run(passing_brief(), target_counts={"total_min": 2, "noise": [0, 0]}), [])

    def test_old_must_read_blocked_even_within_overall_limit(self):
        raw = passing_brief()
        raw["items"][0]["published"] = "2026-09-05"  # 3 天前：整体上限内，必读上限外
        problems = run(raw)
        self.assertTrue(any("items[rank=1].published" in p for p in problems))


class TestSources(unittest.TestCase):
    def test_item_without_sources(self):
        raw = passing_brief()
        raw["items"][1]["sources"] = []
        self.assertIn("items[rank=2].sources: 没有任何来源", run(raw))


class TestMarket(unittest.TestCase):
    def test_missing_market(self):
        raw = passing_brief()
        del raw["market"]
        self.assertTrue(any(p.startswith("market:") for p in run(raw)))

    def test_intraday_snapshot_rejected(self):
        """实际发生过：09-18 到 09-23 的简报存的都是前一天盘中 13 点的快照。"""
        raw = passing_brief()
        raw["market"] = F.make_market(asof="13:26 ET", session="intraday")
        problems = run(raw)
        self.assertTrue(any(p.startswith("market.session") for p in problems))
        self.assertTrue(any(p.startswith("market.asof") for p in problems))

    def test_wrong_close_day(self):
        raw = passing_brief()
        raw["market"]["asof"] = DATE
        self.assertTrue(any(p.startswith("market.asof") for p in run(raw)))


class TestMomentum(unittest.TestCase):
    def test_momentum_may_be_omitted(self):
        raw = passing_brief()
        del raw["momentum"]
        self.assertEqual(run(raw), [])

    def test_stale_candidate_rejected(self):
        """实际发生过：GRAL 的数据停在 09-21，却出现在 09-24 的名单里。"""
        raw = passing_brief()
        raw["momentum"]["candidates"].append(candidate(ticker="GRAL", date="2026-09-03"))
        problems = run(raw)
        self.assertTrue(any("GRAL 的数据停在 2026-09-03" in p for p in problems))

    def test_candidate_without_date_rejected(self):
        raw = passing_brief()
        del raw["momentum"]["candidates"][0]["date"]
        self.assertTrue(any("缺数据日期" in p for p in run(raw)))

    def test_candidate_without_note_rejected(self):
        raw = passing_brief()
        raw["momentum"]["candidates"][0]["note"] = " "
        self.assertIn("momentum.candidates[0].note: ABC 还没写 note", run(raw))

    def test_old_scan_rejected(self):
        raw = passing_brief()
        raw["momentum"]["asof"] = "2026-09-03"
        for c in raw["momentum"]["candidates"]:
            c["date"] = "2026-09-03"
        self.assertTrue(any(p.startswith("momentum.asof") for p in run(raw)))


class TestAdvice(unittest.TestCase):
    def test_every_phrase_is_caught_in_every_field(self):
        fields = (
            lambda raw, t: raw.__setitem__("thesis", t),
            lambda raw, t: raw["items"][0].__setitem__("why", t),
            lambda raw, t: raw["items"][1].__setitem__("body", t),
            lambda raw, t: raw["items"][0]["assets"][0].__setitem__("note", t),
            lambda raw, t: raw["momentum"]["candidates"][0].__setitem__("note", t),
        )
        for phrase in ADVICE_PHRASES:
            for put in fields:
                raw = copy.deepcopy(passing_brief())
                put(raw, f"前文，{phrase}，后文。")
                with self.subTest(phrase=phrase):
                    self.assertTrue(any("买卖倾向" in p for p in run(raw)))

    def test_describing_market_behaviour_is_not_advice(self):
        """「资金在加仓」「不是单纯的抄底」是描述盘面，历史简报里都有，不能误报。"""
        raw = passing_brief()
        raw["items"][0]["why"] = "市场开始区分继续加仓 AI 硬件和获利了结的资金，不是单纯的抄底。"
        raw["items"][1]["body"] = "高盛给予买入评级，并上调目标价。"
        self.assertEqual(run(raw), [])


if __name__ == "__main__":
    unittest.main()
