"""个股页上的「最新消息」。

这一层刻意不做判断，所以测试守的不是「选得准不准」，而是三件更基础的事：
**查询拼得对不对**（代码是常用词时会捞回整个大盘）、**去重管不管用**
（一件事十家报会占满全部位置）、**时间标注诚不诚实**（解析不了就不显示，
不能编一个）。

网络不在测试范围内：``parse_feed`` 是纯函数，注入一段假 RSS 就能覆盖
全部分支。
"""

from __future__ import annotations

import datetime as dt
import unittest
import urllib.parse

from backend.news_feed import (
    MAX_AGE_DAYS,
    Headline,
    build_query,
    parse_feed,
)

NOW = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc)


def rss(*items: str) -> str:
    return "<rss><channel>" + "".join(items) + "</channel></rss>"


def item(title: str, when: str = "Sun, 20 Sep 2026 10:00:00 GMT",
         link: str = "https://example.com/a") -> str:
    return f"<item><title>{title}</title><link>{link}</link><pubDate>{when}</pubDate></item>"


class TestBuildQuery(unittest.TestCase):
    def test_uses_the_company_name_when_available(self):
        q = urllib.parse.unquote(build_query("NVDA", "NVIDIA Corporation"))
        self.assertEqual(q, '"NVIDIA" stock')

    def test_never_ors_in_a_ticker_that_is_a_common_word(self):
        """实测教训：搜 "Agilent Technologies" OR "A" stock 返回的全是
        「全球股市会不会崩盘」这类大盘新闻，一条 Agilent 都没有。
        代码是常用词时（A / ON / ALL / IT / CAR），OR 进去等于不过滤。
        """
        q = urllib.parse.unquote(build_query("A", "Agilent Technologies Inc."))
        self.assertNotIn('"A"', q)
        self.assertIn("Agilent", q)

    def test_falls_back_to_the_ticker_without_a_name(self):
        """拿不到公司名时代码是唯一线索，再嘈杂也比没有强。"""
        self.assertEqual(urllib.parse.unquote(build_query("ZZQQ")), '"ZZQQ" stock')

    def test_strips_legal_suffixes(self):
        for name, want in (("SK hynix Inc. ADR", "SK hynix"),
                           ("Barclays PLC", "Barclays"),
                           ("Ford Motor Company", "Ford Motor")):
            with self.subTest(name):
                self.assertIn(f'"{want}"', urllib.parse.unquote(build_query("X", name)))


class TestParseFeed(unittest.TestCase):
    def test_reads_title_source_and_time(self):
        out = parse_feed(rss(item("Nvidia hits a record - Barron's")), now=NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Nvidia hits a record")
        self.assertEqual(out[0].source, "Barron's")

    def test_only_splits_the_last_dash(self):
        """标题里本来就可能有连字符，从前面拆会把标题腰斩。"""
        out = parse_feed(rss(item("AI - the next step - Reuters")), now=NOW)
        self.assertEqual(out[0].title, "AI - the next step")
        self.assertEqual(out[0].source, "Reuters")

    def test_deduplicates_the_same_story(self):
        """一件事十家报，不去重的话八个位置会被一个事件占满。"""
        out = parse_feed(rss(
            item("Nvidia beats earnings expectations again - CNBC"),
            item("Nvidia beats earnings expectations again - Reuters"),
            item("Something entirely different happened - WSJ"),
        ), now=NOW)
        self.assertEqual(len(out), 2)

    def test_drops_items_older_than_the_window(self):
        old = "Mon, 01 Jun 2026 10:00:00 GMT"
        out = parse_feed(rss(item("Ancient news - WSJ", when=old)), now=NOW)
        self.assertEqual(out, ())

    def test_keeps_items_inside_the_window(self):
        recent = (NOW - dt.timedelta(days=MAX_AGE_DAYS - 1)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT")
        out = parse_feed(rss(item("Still relevant - WSJ", when=recent)), now=NOW)
        self.assertEqual(len(out), 1)

    def test_unparseable_date_keeps_the_item_but_shows_no_time(self):
        """时间读不出来不该丢掉整条，但也绝不能编一个。"""
        out = parse_feed(rss(item("No date here - WSJ", when="昨天下午")), now=NOW)
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0].published)
        self.assertEqual(out[0].age_label(NOW), "")

    def test_respects_the_limit(self):
        items = [item(f"Story number {i} - WSJ") for i in range(30)]
        self.assertEqual(len(parse_feed(rss(*items), limit=5, now=NOW)), 5)

    def test_unescapes_html_entities(self):
        out = parse_feed(rss(item("Apple&#x2019;s quarter - WSJ")), now=NOW)
        self.assertIn("’", out[0].title)

    def test_empty_feed_is_empty(self):
        self.assertEqual(parse_feed(rss(), now=NOW), ())
        self.assertEqual(parse_feed("这不是 XML", now=NOW), ())


class TestAgeLabel(unittest.TestCase):
    def label(self, minutes: int) -> str:
        h = Headline("t", "u", "s", NOW - dt.timedelta(minutes=minutes))
        return h.age_label(NOW)

    def test_scales(self):
        self.assertEqual(self.label(0), "刚刚")
        self.assertEqual(self.label(20), "20 分钟前")
        self.assertEqual(self.label(180), "3 小时前")
        self.assertEqual(self.label(60 * 50), "2 天前")


if __name__ == "__main__":
    unittest.main()
