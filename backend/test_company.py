"""公司信息的解析与降级。

网络不在测试范围内：``parse_*`` 全是纯函数，注入一段假响应就能覆盖全部
分支，不联网也不受对方限流影响——和 ``test_search`` 同一个路数。

这里最要紧的一组是**缺数据时的行为**。上游给的字段经常是 ``"N/A"``、
空串或者干脆没有，而这几块信息会被读者当成事实看。补 0、补占位、
照单全收，三种做法都会在版面上造出一个不存在的事实。
"""

from __future__ import annotations

import unittest

from backend.company import (
    STAT_FIELDS,
    Company,
    Profile,
    Quarter,
    Ratings,
    compact_number,
    parse_earnings,
    parse_profile,
    parse_ratings,
    parse_stats,
)


def summary(**fields):
    return {"data": {"summaryData": {k: {"value": v} for k, v in fields.items()}}}


class TestParseProfile(unittest.TestCase):
    def test_reads_the_fields_it_needs(self):
        p = parse_profile({"data": {
            "CompanyName": {"value": "NVIDIA Corporation"},
            "CompanyDescription": {"value": "世界 AI 计算的领导者。"},
            "Industry": {"value": "Semiconductors"},
            "Sector": {"value": "Technology"},
            "Region": {"value": "North America"},
            "CompanyUrl": {"value": "https://www.nvidia.com"},
        }})
        self.assertEqual(p.name, "NVIDIA Corporation")
        self.assertEqual(p.industry, "Semiconductors")
        self.assertFalse(p.empty)

    def test_placeholders_count_as_missing(self):
        p = parse_profile({"data": {
            "CompanyDescription": {"value": "N/A"},
            "Industry": {"value": ""},
            "Sector": {"value": "--"},
        }})
        self.assertTrue(p.empty)

    def test_broken_payload_yields_an_empty_profile(self):
        for bad in ({}, {"data": None}, {"data": []}, None):
            self.assertTrue(parse_profile(bad).empty)


class TestParseStats(unittest.TestCase):
    def test_keeps_only_whitelisted_fields_in_order(self):
        """顺序就是版面顺序，而且不该被上游的字段顺序左右。"""
        payload = summary(MarketCap="1,000,000,000", PreviousClose="$10.00",
                          Exchange="NASDAQ-GS")
        labels = [k for k, _ in parse_stats(payload)]
        self.assertEqual(labels, ["前收盘", "市值"])
        self.assertNotIn("NASDAQ-GS", [v for _, v in parse_stats(payload)])

    def test_missing_fields_are_dropped_not_filled(self):
        """缺字段就少一格。写着 N/A 的格子信息量是零，注意力成本却一样。"""
        out = parse_stats(summary(PreviousClose="$10.00", MarketCap="N/A"))
        self.assertEqual(out, (("前收盘", "$10.00"),))

    def test_market_cap_is_compacted(self):
        """实测 NVDA 的市值原样摆进格子会盖住隔壁的一年目标价。"""
        out = dict(parse_stats(summary(MarketCap="5,356,707,000,000")))
        self.assertEqual(out["市值"], "5.36 万亿")

    def test_whitelist_labels_are_unique(self):
        labels = [label for _, label in STAT_FIELDS]
        self.assertEqual(len(labels), len(set(labels)))


class TestCompactNumber(unittest.TestCase):
    def test_scales(self):
        self.assertEqual(compact_number("5,356,707,000,000"), "5.36 万亿")
        self.assertEqual(compact_number("250,000,000"), "2.50 亿")

    def test_unparseable_input_is_returned_untouched(self):
        """看不懂就别改：这一格写的是事实，不是装饰。"""
        self.assertEqual(compact_number("abc"), "abc")
        self.assertEqual(compact_number("999"), "999")


class TestParseRatings(unittest.TestCase):
    def test_counts_brokers(self):
        r = parse_ratings({"data": {
            "meanRatingType": "Buy",
            "ratingsSummary": "Based on 3 analysts",
            "brokerNames": ["A", "B", "C"],
            "upgradesDowngrades": [{"x": 1}],
        }})
        self.assertEqual(r.mean, "Buy")
        self.assertEqual(r.count, 3)
        self.assertEqual(len(r.changes), 1)
        self.assertFalse(r.empty)

    def test_empty_when_there_is_nothing_to_say(self):
        self.assertTrue(parse_ratings({"data": {}}).empty)
        self.assertTrue(parse_ratings(None).empty)


class TestParseEarnings(unittest.TestCase):
    ROWS = {"data": {"earningsSurpriseTable": {"rows": [
        {"fiscalQtrEnd": "Jul 2026", "dateReported": "8/26/2026",
         "eps": 2.22, "consensusForecast": "2.09", "percentageSurprise": "6.22"},
        {"fiscalQtrEnd": "Apr 2026", "dateReported": "5/20/2026",
         "eps": 1.87, "consensusForecast": "1.7", "percentageSurprise": "10"},
    ]}}}

    def test_parses_rows(self):
        qs = parse_earnings(self.ROWS)
        self.assertEqual(len(qs), 2)
        self.assertAlmostEqual(qs[0].eps, 2.22)
        self.assertAlmostEqual(qs[0].consensus, 2.09)
        self.assertTrue(qs[0].beat)

    def test_missing_numbers_stay_none(self):
        """缺一个数就不下结论，而不是拿 0 顶替再算出一个假的超预期。"""
        qs = parse_earnings({"data": {"earningsSurpriseTable": {"rows": [
            {"fiscalQtrEnd": "Jul 2026", "eps": "N/A", "consensusForecast": "2.09"}
        ]}}})
        self.assertIsNone(qs[0].eps)
        self.assertIsNone(qs[0].beat)

    def test_rows_without_a_quarter_are_skipped(self):
        qs = parse_earnings({"data": {"earningsSurpriseTable": {"rows": [
            {"eps": 1.0}, {"fiscalQtrEnd": "Jul 2026", "eps": 1.0}
        ]}}})
        self.assertEqual(len(qs), 1)

    def test_broken_payload_is_empty(self):
        for bad in ({}, {"data": {}}, {"data": {"earningsSurpriseTable": {}}}, None):
            self.assertEqual(parse_earnings(bad), ())


class TestCompany(unittest.TestCase):
    def test_empty_when_every_block_is_missing(self):
        """四块全缺时整段省掉，而不是渲染一排空标题。"""
        self.assertTrue(Company(symbol="X").empty)

    def test_not_empty_if_any_block_has_content(self):
        self.assertFalse(
            Company(symbol="X", quarters=(Quarter("Jul 2026", "", 1.0, 0.9, 11.1),)).empty
        )
        self.assertFalse(Company(symbol="X", stats=(("市值", "1 亿"),)).empty)
        self.assertFalse(Company(symbol="X", ratings=Ratings(mean="Buy")).empty)
        self.assertFalse(
            Company(symbol="X", profile=Profile(description="做芯片的")).empty
        )


if __name__ == "__main__":
    unittest.main()
