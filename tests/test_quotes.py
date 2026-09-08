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
    fetch_from_backend,
    parse_backend_quotes,
    asof_label,
    build_mag7_block,
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

    def test_rows_formatted_for_schema(self):
        block = build_mag7_block(self.quotes)
        self.assertEqual(block["rows"][0], {"ticker": "NVDA", "price": "230.36", "change_pct": 0.84})

    def test_asof_uses_latest_timestamp(self):
        block = build_mag7_block(self.quotes)
        self.assertEqual(block["asof"], asof_label(1788552000))

    def test_human_note_is_preserved(self):
        """人写的那句解读不该被自动抓取覆盖掉。"""
        block = build_mag7_block(self.quotes, {"note": "五跌两涨", "rows": [], "asof": "旧"})
        self.assertEqual(block["note"], "五跌两涨")
        self.assertNotEqual(block["asof"], "旧")

    def test_empty_quotes_rejected(self):
        with self.assertRaises(QuoteError):
            build_mag7_block([])

    def test_price_thousands_separator(self):
        block = build_mag7_block([Quote("BRK", 712345.6, 1.0, 1788552000)])
        self.assertEqual(block["rows"][0]["price"], "712,345.60")

    def test_asof_label_shape(self):
        self.assertRegex(asof_label(1788552000), r"^收盘 · \w+ \d+/\d+ \d{2}:\d{2} ET$")



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

    def test_parses_backend_payload(self):
        quotes, failures = parse_backend_quotes(self.sample())
        self.assertEqual([q.ticker for q in quotes], ["NVDA", "TSLA"])
        self.assertAlmostEqual(quotes[0].price, 227.139)
        self.assertEqual(failures, [])

    def test_per_ticker_error_becomes_failure_not_exception(self):
        """后端对单只失败返回 error 字段而不是整体报错，这里同样要
        允许部分成功，形状跟 fetch_many 保持一致。"""
        payload = self.sample() + [{"ticker": "BAD", "error": "上游 403"}]
        quotes, failures = parse_backend_quotes(payload)
        self.assertEqual(len(quotes), 2)
        self.assertEqual(len(failures), 1)
        self.assertIn("BAD", failures[0])

    def test_non_list_payload_rejected(self):
        with self.assertRaises(QuoteError):
            parse_backend_quotes({"detail": "500 Internal Server Error"})

    def test_malformed_row_does_not_kill_the_batch(self):
        payload = self.sample() + [{"ticker": "X", "price": "n/a", "change_pct": 1, "market_time": 1}]
        quotes, failures = parse_backend_quotes(payload)
        self.assertEqual(len(quotes), 2)
        self.assertEqual(len(failures), 1)

    def test_builds_correct_url(self):
        seen = {}

        def fetcher(url, timeout=None):
            seen["url"] = url
            seen["timeout"] = timeout
            return self.sample()

        fetch_from_backend("https://x.onrender.com/", fetcher=fetcher)
        self.assertEqual(seen["url"], "https://x.onrender.com/api/quotes/live")

    def test_generous_timeout_for_cold_start(self):
        """Render 免费版闲置会休眠，唤醒要半分钟到一分钟，
        默认的 15 秒超时会稳定死在冷启动上。"""
        seen = {}

        def fetcher(url, timeout=None):
            seen["timeout"] = timeout
            return self.sample()

        fetch_from_backend("https://x.onrender.com", fetcher=fetcher)
        self.assertGreaterEqual(seen["timeout"], 60)

if __name__ == "__main__":
    unittest.main()
