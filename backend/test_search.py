"""股票搜索测试。

:func:`~backend.search.parse_results` 是纯函数，所以过滤逻辑在这里用假响应
直接断言，一次网络请求都不发——真实的 Yahoo 会限流，也会随时改结构，
让测试依赖它等于给自己造一个随机失败的测试。

    python3 -m unittest backend.test_search -v
"""

from __future__ import annotations

import unittest

from .search import (
    MAX_RESULTS,
    clean_name,
    fuzzy_symbols,
    head_word,
    Match,
    SearchError,
    is_us_equity,
    normalise,
    parse_results,
    resolve,
    search,
)


def quote(symbol: str, name: str = "Some Company", **over) -> dict:
    base = {
        "symbol": symbol,
        "shortname": name,
        "quoteType": "EQUITY",
        "exchDisp": "NasdaqGS",
    }
    base.update(over)
    return base


def payload(*rows: dict) -> dict:
    return {"quotes": list(rows)}


class NormaliseTest(unittest.TestCase):
    def test_non_ascii_is_dropped(self):
        """Yahoo 对非 ASCII 查询返回 HTTP 400。原样上送会把「没有结果」
        变成「上游故障」，前端进而显示成「搜索暂时不可用」——误报。
        """
        self.assertEqual(normalise("苹果"), "")

    def test_unknown_text_passes_through(self):
        self.assertEqual(normalise("Rivian"), "Rivian")

    def test_whitespace_trimmed(self):
        self.assertEqual(normalise("  tesla  "), "tesla")

    def test_empty_stays_empty(self):
        self.assertEqual(normalise(""), "")
        self.assertEqual(normalise(None), "")


class FilterTest(unittest.TestCase):
    def test_keeps_plain_us_equity(self):
        self.assertTrue(is_us_equity(quote("AAPL")))

    def test_drops_foreign_listing(self):
        """``AAPL.VI``、``NVD.DE`` 是同一家公司在别国的挂牌：
        既匹配不到美股新闻，价格口径也不同。"""
        self.assertFalse(is_us_equity(quote("AAPL.VI")))
        self.assertFalse(is_us_equity(quote("NVD.DE")))

    def test_drops_non_equity(self):
        self.assertFalse(is_us_equity(quote("AAPW", quoteType="ETF")))
        self.assertFalse(is_us_equity(quote("BTC", quoteType="CRYPTOCURRENCY")))

    def test_drops_row_without_name(self):
        row = quote("XYZ")
        row.pop("shortname")
        self.assertFalse(is_us_equity(row))

    def test_accepts_longname_only(self):
        row = quote("XYZ")
        row.pop("shortname")
        row["longname"] = "XYZ Holdings"
        self.assertTrue(is_us_equity(row))


class ParseTest(unittest.TestCase):
    def test_parses_and_uppercases(self):
        rows = parse_results(payload(quote("aapl", "Apple Inc.")))
        self.assertEqual(rows[0], Match("AAPL", "Apple Inc.", "NasdaqGS"))

    def test_filters_noise(self):
        rows = parse_results(
            payload(
                quote("AAPL", "Apple Inc."),
                quote("AAPL.VI", "APPLE INC"),
                quote("AAPW", "Weekly ETF", quoteType="ETF"),
            )
        )
        self.assertEqual([r.symbol for r in rows], ["AAPL"])

    def test_dedupes(self):
        rows = parse_results(payload(quote("AAPL"), quote("aapl")))
        self.assertEqual(len(rows), 1)

    def test_respects_limit(self):
        rows = parse_results(payload(*[quote(f"S{i}") for i in range(20)]), limit=3)
        self.assertEqual(len(rows), 3)

    def test_missing_quotes_key_returns_empty(self):
        self.assertEqual(parse_results({}), [])

    def test_bad_payload_raises(self):
        with self.assertRaises(SearchError):
            parse_results("not an object")

    def test_skips_non_dict_rows(self):
        """上游偶尔会在数组里混进字符串之类的东西，跳过就好，不该整个失败。"""
        rows = parse_results({"quotes": ["junk", None, quote("AAPL")]})
        self.assertEqual([r.symbol for r in rows], ["AAPL"])


class SearchTest(unittest.TestCase):
    def fetcher(self, captured: list):
        def fake(url, *a, **kw):
            captured.append(url)
            return payload(quote("AAPL", "Apple Inc."))

        return fake

    def test_empty_query_skips_network(self):
        """还没输入就不该去打扰上游。"""
        calls: list = []
        self.assertEqual(search("", fetcher=self.fetcher(calls)), [])
        self.assertEqual(calls, [])

    def test_non_ascii_query_skips_network(self):
        """送不出去的查询就别送，省一次必然失败的往返。"""
        calls: list = []
        self.assertEqual(search("苹果", fetcher=self.fetcher(calls)), [])
        self.assertEqual(calls, [])

    def test_query_is_url_encoded(self):
        calls: list = []
        search("johnson & johnson", fetcher=self.fetcher(calls))
        self.assertNotIn(" ", calls[0])
        self.assertIn("%26", calls[0])  # & 被编码，不会截断查询串


class ResolveTest(unittest.TestCase):
    """``resolve`` 是「APPLE 也能存进自选股」那个静默失败的补丁。"""

    def fake(self, *rows):
        def fetcher(url, *a, **kw):
            return payload(*rows)

        return fetcher

    def test_exact_match_resolves(self):
        match = resolve("AAPL", fetcher=self.fake(quote("AAPL", "Apple Inc.")))
        self.assertIsNotNone(match)
        self.assertEqual(match.symbol, "AAPL")

    def test_lowercase_input_resolves(self):
        self.assertIsNotNone(resolve("aapl", fetcher=self.fake(quote("AAPL"))))

    def test_company_name_is_not_a_symbol(self):
        """输入 APPLE 时上游会返回 AAPL，但两者不相等——不能替用户猜。"""
        self.assertIsNone(resolve("APPLE", fetcher=self.fake(quote("AAPL", "Apple Inc."))))

    def test_nonexistent_returns_none(self):
        self.assertIsNone(resolve("ZZZZZ", fetcher=self.fake()))

    def test_empty_returns_none(self):
        self.assertIsNone(resolve("", fetcher=self.fake(quote("AAPL"))))


class FuzzyTest(unittest.TestCase):
    """容错匹配。存在的理由是 Yahoo 只做前缀/子串匹配，一个字母打错就废：
    ``gogle``、``nvdia``、``microsft`` 全部返回空，而 ``gool`` 更糟——
    它返回 GOOLF，一个真实存在但完全不相干的 OTC 票。
    """

    INDEX = {
        "GOOGL": "Alphabet Inc. - Class A Common Stock",
        "GOOG": "Alphabet Inc. - Class C Capital Stock",
        "MSFT": "Microsoft Corporation - Common Stock",
        "TSLA": "Tesla, Inc. - Common Stock",
        "TLSA": "Tiziana Life Sciences Ltd - Common Stock",
        "NVDA": "NVIDIA Corporation - Common Stock",
        "AMZN": "Amazon.com, Inc. - Common Stock",
        "ZZZQ": "Obscure Holdings Ltd - Common Stock",
    }

    def find(self, term, limit=3):
        return fuzzy_symbols(term, limit=limit, index=self.INDEX)

    def test_typo_in_symbol(self):
        self.assertIn("GOOGL", self.find("gool"))
        self.assertIn("GOOGL", self.find("gogle"))

    def test_typo_matched_via_company_name(self):
        """``microsft`` 跟代码 MSFT 一点都不像，只有比公司名才找得到。"""
        self.assertEqual(self.find("microsft")[0], "MSFT")

    def test_transposition(self):
        self.assertIn("TSLA", self.find("telsa", limit=5))

    def test_missing_letter(self):
        self.assertEqual(self.find("nvdia")[0], "NVDA")
        self.assertEqual(self.find("amazn")[0], "AMZN")

    def test_nonsense_matches_nothing(self):
        self.assertEqual(self.find("qqqqqqqq"), [])

    def test_exclude_is_honoured(self):
        """Yahoo 已经返回过的代码不该在容错结果里再出现一次。"""
        self.assertIn("GOOGL", self.find("gool"))
        again = fuzzy_symbols("gool", limit=3, index=self.INDEX, exclude={"GOOGL"})
        self.assertNotIn("GOOGL", again)

    def test_limit_is_honoured(self):
        self.assertLessEqual(len(self.find("goog", limit=2)), 2)

    def test_zero_limit_short_circuits(self):
        self.assertEqual(fuzzy_symbols("goog", limit=0, index=self.INDEX), [])

    def test_empty_index_returns_nothing(self):
        """索引文件缺失时容错静默失效，搜索退化成纯 Yahoo，仍然可用。"""
        self.assertEqual(fuzzy_symbols("goog", limit=3, index={}), [])


class NameTest(unittest.TestCase):
    def test_clean_name_drops_security_type(self):
        self.assertEqual(clean_name("Apple Inc. - Common Stock"), "Apple Inc.")

    def test_head_word_skips_stopwords(self):
        self.assertEqual(head_word("Microsoft Corporation - Common Stock"), "MICROSOFT")
        self.assertEqual(head_word("The Walt Disney Company"), "WALT")

    def test_head_word_survives_all_stopwords(self):
        self.assertTrue(head_word("Inc Corp - Common Stock"))


if __name__ == "__main__":
    unittest.main()
