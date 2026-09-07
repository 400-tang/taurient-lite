"""FINRA 空头持仓模块测试。

跟 :mod:`taurient_lite.quotes` 一样的策略：``fetcher`` 和 ``sleep`` 都是
注入的，一次网络都不发。真实端点的联通性已经在开发时用 curl 手动核实过
（``consolidatedShortInterest`` 这个数据集名字不在 FINRA 公开文档里，
是逐字段试出来的），这里测的是解析逻辑本身，不重复验证网络连通性。
"""

from __future__ import annotations

import datetime as dt
import unittest
import urllib.error

from taurient_lite.short_interest import (
    ShortInterestError,
    fetch_latest,
    fetch_many,
    parse_records,
)


def row(
    symbol="AI",
    settlement="2026-08-14",
    current=48144524,
    previous=46307686,
    change_pct=3.97,
    days_to_cover=11.46,
    volume=4200138,
    name="C3.ai, Inc.",
) -> dict:
    return {
        "symbolCode": symbol,
        "issueName": name,
        "settlementDate": settlement,
        "currentShortPositionQuantity": current,
        "previousShortPositionQuantity": previous,
        "changePercent": change_pct,
        "daysToCoverQuantity": days_to_cover,
        "averageDailyVolumeQuantity": volume,
        # 响应里还有这些字段，解析用不上，但真实数据都带着，
        # 混进去确保解析器不会因为多余字段就炸。
        "marketClassCode": "NYSE",
        "issuerServicesGroupExchangeCode": "A",
        "accountingYearMonthNumber": 20260814,
        "changePreviousNumber": 1836838,
        "stockSplitFlag": None,
        "revisionFlag": None,
    }


class TestParseRecords(unittest.TestCase):
    def test_parses_normal_array(self):
        records = parse_records("AI", [row()])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].settlement_date, dt.date(2026, 8, 14))
        self.assertEqual(records[0].current_shares, 48144524)

    def test_empty_array_returns_empty_list(self):
        self.assertEqual(parse_records("AI", []), [])

    def test_error_object_raises_with_message(self):
        payload = {"statusCode": 400, "message": "The following fields are not available"}
        with self.assertRaises(ShortInterestError) as ctx:
            parse_records("AI", payload)
        self.assertIn("not available", str(ctx.exception))

    def test_non_list_non_error_payload_rejected(self):
        with self.assertRaises(ShortInterestError):
            parse_records("AI", "just a string")

    def test_missing_field_reports_symbol(self):
        bad = row()
        del bad["currentShortPositionQuantity"]
        with self.assertRaises(ShortInterestError) as ctx:
            parse_records("AI", [bad])
        self.assertIn("AI", str(ctx.exception))

    def test_change_shares_computed(self):
        records = parse_records("AI", [row(current=100, previous=80)])
        self.assertEqual(records[0].change_shares, 20)

    def test_citation_includes_settlement_date_and_direction(self):
        [record] = parse_records("AI", [row(change_pct=-5.0)])
        citation = record.as_citation()
        self.assertIn("2026-08-14", citation)
        self.assertIn("-5.00%", citation)
        self.assertNotIn("+-5.00%", citation)  # 负数不该被再加一个正号


class TestFetchLatest(unittest.TestCase):
    def test_picks_max_settlement_date_among_multiple_periods(self):
        def fetcher(url, body):
            return [row(settlement="2026-07-31", current=100), row(settlement="2026-08-14", current=200)]

        record = fetch_latest("AI", fetcher=fetcher, sleep=lambda _: None)
        self.assertEqual(record.settlement_date, dt.date(2026, 8, 14))
        self.assertEqual(record.current_shares, 200)

    def test_empty_result_raises(self):
        with self.assertRaises(ShortInterestError):
            fetch_latest("ZZZZ", fetcher=lambda url, body: [], sleep=lambda _: None)

    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        def flaky(url, body):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise urllib.error.URLError("timeout")
            return [row()]

        record = fetch_latest("AI", fetcher=flaky, sleep=lambda _: None)
        self.assertEqual(attempts["n"], 2)
        self.assertEqual(record.symbol, "AI")

    def test_gives_up_after_retries(self):
        def always_fails(url, body):
            raise urllib.error.URLError("down")

        with self.assertRaises(ShortInterestError):
            fetch_latest("AI", retries=2, fetcher=always_fails, sleep=lambda _: None)

    def test_finra_rejection_is_not_silently_swallowed(self):
        """字段名要是哪天变了，FINRA 会用一个 400 错误对象回应，
        这必须冒泡成异常，不能被解析成一条看起来正常的空记录。
        """

        def rejecting(url, body):
            return {"statusCode": 400, "message": "The following fields are not available"}

        with self.assertRaises(ShortInterestError):
            fetch_latest("AI", retries=1, fetcher=rejecting, sleep=lambda _: None)


class TestFetchMany(unittest.TestCase):
    def test_partial_failure_tolerated(self):
        def fetcher(url, body):
            symbol = body["compareFilters"][0]["fieldValue"]
            if symbol == "BAD":
                raise urllib.error.URLError("nope")
            return [row(symbol=symbol)]

        records, failures = fetch_many(["AI", "BAD", "TSLA"], fetcher=fetcher, sleep=lambda _: None)
        self.assertEqual({r.symbol for r in records}, {"AI", "TSLA"})
        self.assertEqual(len(failures), 1)

    def test_total_failure_returns_empty_records(self):
        def always_fails(url, body):
            raise urllib.error.URLError("down")

        records, failures = fetch_many(["AI", "TSLA"], fetcher=always_fails, sleep=lambda _: None)
        self.assertEqual(records, [])
        self.assertEqual(len(failures), 2)


if __name__ == "__main__":
    unittest.main()
