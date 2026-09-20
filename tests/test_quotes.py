"""行情层测试。

一次网络都不发：``fetcher`` 和 ``sleep`` 都是注入的。这样重试路径、
限流、结构变更这些分支全部可测，而且测试永远不会因为对方服务抖动而变红。
"""

from __future__ import annotations

import unittest
import urllib.error

from taurient_lite.quotes import (
    Quote,
    QuoteError,
    fetch_many,
    fetch_quote,
    parse_quote,
)

from . import fixtures as F


class TestParseQuote(unittest.TestCase):
    def test_parses_valid_payload(self):
        quote = parse_quote("NVDA", F.yahoo_payload())
        self.assertEqual(quote.ticker, "NVDA")
        self.assertAlmostEqual(quote.price, 230.36)
        self.assertAlmostEqual(quote.change_pct, 0.836)

    def test_missing_chart_key(self):
        with self.assertRaises(QuoteError) as ctx:
            parse_quote("NVDA", {"error": "rate limited"})
        self.assertIn("NVDA", str(ctx.exception))

    def test_empty_result_list(self):
        with self.assertRaises(QuoteError):
            parse_quote("NVDA", {"chart": {"result": []}})

    def test_missing_price_field(self):
        payload = F.yahoo_payload()
        del payload["chart"]["result"][0]["meta"]["regularMarketPrice"]
        with self.assertRaises(QuoteError) as ctx:
            parse_quote("NVDA", payload)
        self.assertIn("字段缺失", str(ctx.exception))

    def test_non_numeric_price(self):
        payload = F.yahoo_payload()
        payload["chart"]["result"][0]["meta"]["regularMarketPrice"] = "n/a"
        with self.assertRaises(QuoteError):
            parse_quote("NVDA", payload)

    def test_payload_of_wrong_type(self):
        with self.assertRaises(QuoteError):
            parse_quote("NVDA", "just a string")


class TestFetchQuote(unittest.TestCase):
    def test_succeeds_first_try(self):
        calls = []

        def fetcher(url):
            calls.append(url)
            return F.yahoo_payload()

        quote = fetch_quote("NVDA", fetcher=fetcher, sleep=lambda _: None)
        self.assertEqual(len(calls), 1)
        self.assertIn("NVDA", calls[0])
        self.assertEqual(quote.ticker, "NVDA")

    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        def flaky(url):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise urllib.error.URLError("connection reset")
            return F.yahoo_payload()

        quote = fetch_quote("NVDA", fetcher=flaky, sleep=lambda _: None)
        self.assertEqual(attempts["n"], 3)
        self.assertAlmostEqual(quote.price, 230.36)

    def test_gives_up_after_retries(self):
        def always_fails(url):
            raise urllib.error.URLError("429")

        with self.assertRaises(QuoteError) as ctx:
            fetch_quote("NVDA", retries=2, fetcher=always_fails, sleep=lambda _: None)
        self.assertIn("取价失败", str(ctx.exception))

    def test_backoff_grows(self):
        waits = []

        def always_fails(url):
            raise urllib.error.URLError("boom")

        with self.assertRaises(QuoteError):
            fetch_quote("X", retries=3, fetcher=always_fails, sleep=waits.append)
        # 最后一次失败后不再等待，所以是 retries-1 次退避
        self.assertEqual(waits, [1.5, 3.0])


class TestFetchMany(unittest.TestCase):
    def test_partial_failure_is_tolerated(self):
        def fetcher(url):
            if "BAD" in url:
                raise urllib.error.URLError("nope")
            return F.yahoo_payload()

        quotes, failures = fetch_many(
            ["NVDA", "BAD", "TSLA"], fetcher=fetcher, sleep=lambda _: None
        )
        self.assertEqual([q.ticker for q in quotes], ["NVDA", "TSLA"])
        self.assertEqual(len(failures), 1)
        self.assertIn("BAD", failures[0])

    def test_total_failure_returns_empty(self):
        def fetcher(url):
            raise urllib.error.URLError("down")

        quotes, failures = fetch_many(["A", "B"], fetcher=fetcher, sleep=lambda _: None)
        self.assertEqual(quotes, [])
        self.assertEqual(len(failures), 2)


class TestBuildBlock(unittest.TestCase):
    def setUp(self):
        self.quotes = [
            Quote("NVDA", 230.36, 0.836, 1788552000),
            Quote("TSLA", 354.08, -5.92, 1788551000),
        ]

class TestBackendFallback(unittest.TestCase):
    """直连被沙箱网关拒绝时，改从 Render 后端取数的回退路径。

    云端定时任务的出站流量被限制成「仅包管理器」，直连 Yahoo 在
    CONNECT 阶段就被 403；后端跑在普通云主机上外网不受限。这条
    路径存在的意义就是让有网的那一端负责取数。
    """

    def sample(self):
        return [
            {"ticker": "NVDA", "price": 227.139, "change_pct": -1.398, "market_time": 1788880001},
            {"ticker": "TSLA", "price": 350.5, "change_pct": 2.0, "market_time": 1788880001},
        ]

