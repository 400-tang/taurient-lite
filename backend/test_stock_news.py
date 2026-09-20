"""个股页上的「相关新闻」：从历史简报里按代码反查。

这一块的数据来自项目自己的简报，不是第三方新闻源——简报里每条都已经
筛过、去过重、写过「为什么重要」。所以这里要守的是检索本身的正确性：
不漏、不串、不因为某一天的简报坏掉就整块失败。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.stock_news import MAX_ITEMS, mentions_for


def write(dirpath: Path, date: str, items: list[dict]) -> None:
    (dirpath / f"{date}.json").write_text(
        json.dumps({"date": date, "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )


def item(rank: int, tickers: list[str], headline: str = "标题", tier: str = "must-read"):
    return {"rank": rank, "tier": tier, "headline": headline,
            "why": "为什么重要", "tickers": tickers}


class TestMentions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_finds_items_that_mention_the_ticker(self):
        write(self.dir, "2026-09-18", [item(1, ["NVDA"]), item(2, ["AAPL"])])
        found = mentions_for(self.dir, "NVDA")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].date, "2026-09-18")

    def test_newest_first(self):
        write(self.dir, "2026-09-16", [item(1, ["NVDA"], "旧的")])
        write(self.dir, "2026-09-18", [item(1, ["NVDA"], "新的")])
        self.assertEqual([m.title for m in mentions_for(self.dir, "NVDA")],
                         ["新的", "旧的"])

    def test_matching_is_case_insensitive(self):
        write(self.dir, "2026-09-18", [item(1, ["nvda"])])
        self.assertEqual(len(mentions_for(self.dir, "NVDA")), 1)

    def test_does_not_match_a_different_ticker(self):
        """NVDA 不能把 NVDAX 的新闻也捞进来。"""
        write(self.dir, "2026-09-18", [item(1, ["NVDAX"])])
        self.assertEqual(mentions_for(self.dir, "NVDA"), ())

    def test_respects_the_limit(self):
        write(self.dir, "2026-09-18",
              [item(i, ["NVDA"]) for i in range(MAX_ITEMS + 5)])
        self.assertEqual(len(mentions_for(self.dir, "NVDA")), MAX_ITEMS)

    def test_a_broken_brief_does_not_kill_the_whole_lookup(self):
        """少几条旧新闻是小事，因此拖垮整页不是。"""
        (self.dir / "2026-09-17.json").write_text("{ 这不是 JSON", encoding="utf-8")
        write(self.dir, "2026-09-18", [item(1, ["NVDA"])])
        self.assertEqual(len(mentions_for(self.dir, "NVDA")), 1)

    def test_items_not_a_list_is_skipped(self):
        (self.dir / "2026-09-18.json").write_text('{"items": "oops"}', encoding="utf-8")
        self.assertEqual(mentions_for(self.dir, "NVDA"), ())

    def test_unknown_ticker_returns_nothing(self):
        write(self.dir, "2026-09-18", [item(1, ["NVDA"])])
        self.assertEqual(mentions_for(self.dir, "ZZZZ"), ())

    def test_tier_labels_are_chinese(self):
        write(self.dir, "2026-09-18", [item(1, ["NVDA"], tier="worth-knowing")])
        self.assertEqual(mentions_for(self.dir, "NVDA")[0].tier_label, "值得知道")

    def test_unknown_tier_falls_back(self):
        write(self.dir, "2026-09-18", [item(1, ["NVDA"], tier="奇怪的层")])
        self.assertEqual(mentions_for(self.dir, "NVDA")[0].tier_label, "背景噪音")


if __name__ == "__main__":
    unittest.main()
