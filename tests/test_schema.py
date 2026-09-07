"""schema 层的反序列化与校验测试。

重点覆盖两件事：合法输入解析成什么，以及**非法输入是否在正确的位置报错**。
后者更重要——错误消息里的字段路径是排查时唯一的线索。
"""

from __future__ import annotations

import datetime as dt
import unittest

from taurient_lite.schema import (
    AssetImpact,
    Brief,
    CrossSource,
    HistoricalContext,
    Item,
    Mag7,
    SchemaError,
    Source,
    Tape,
)

from . import fixtures as F


class TestSource(unittest.TestCase):
    def test_parses_minimal(self):
        source = Source.from_dict(F.make_source(), "sources[0]")
        self.assertEqual(source.name, "CNBC")
        self.assertEqual(source.angle, "")

    def test_angle_is_optional_and_may_be_empty(self):
        source = Source.from_dict(F.make_source(angle=""), "s")
        self.assertEqual(source.angle, "")

    def test_missing_url_reports_path(self):
        with self.assertRaises(SchemaError) as ctx:
            Source.from_dict({"name": "CNBC"}, "items[2].sources[0]")
        self.assertIn("items[2].sources[0].url", str(ctx.exception))


class TestAssetImpact(unittest.TestCase):
    def test_conviction_maps_to_steps(self):
        for conviction, expected in (("high", 3), ("medium", 2), ("low", 1)):
            impact = AssetImpact.from_dict(F.make_asset(conviction=conviction), "a")
            self.assertEqual(impact.steps, expected)

    def test_conviction_defaults_to_medium(self):
        data = F.make_asset()
        del data["conviction"]
        self.assertEqual(AssetImpact.from_dict(data, "a").conviction, "medium")

    def test_direction_label(self):
        self.assertEqual(AssetImpact.from_dict(F.make_asset(direction="mixed"), "a").label, "分化")

    def test_rejects_unknown_asset_class(self):
        with self.assertRaises(SchemaError) as ctx:
            AssetImpact.from_dict(F.make_asset(asset_class="日本茶叶"), "items[0].assets[1]")
        self.assertIn("items[0].assets[1].asset_class", str(ctx.exception))

    def test_rejects_unknown_direction(self):
        with self.assertRaises(SchemaError):
            AssetImpact.from_dict(F.make_asset(direction="sideways"), "a")


class TestCrossSource(unittest.TestCase):
    def test_label(self):
        cross = CrossSource.from_dict(F.make_cross_source(agreement="split"), "c")
        self.assertEqual(cross.label, "存在分歧")

    def test_summary_is_required(self):
        with self.assertRaises(SchemaError) as ctx:
            CrossSource.from_dict({"agreement": "aligned"}, "items[0].cross_source")
        self.assertIn("items[0].cross_source.summary", str(ctx.exception))


class TestHistoricalContext(unittest.TestCase):
    def test_timeline_parsed_in_order(self):
        history = HistoricalContext.from_dict(F.make_history(), "h")
        self.assertEqual(len(history.timeline), 2)
        self.assertEqual(history.timeline[0].when, "2026-07")

    def test_timeline_optional(self):
        history = HistoricalContext.from_dict({"summary": "只有一句"}, "h")
        self.assertEqual(history.timeline, ())

    def test_bad_timeline_entry_reports_index(self):
        data = F.make_history(timeline=[{"when": "2026-07"}])
        with self.assertRaises(SchemaError) as ctx:
            HistoricalContext.from_dict(data, "items[3].history")
        self.assertIn("items[3].history.timeline[0].event", str(ctx.exception))


class TestItem(unittest.TestCase):
    def test_parses_deep_item(self):
        item = Item.from_dict(F.make_deep_item(), "items[0]")
        self.assertTrue(item.has_depth)
        self.assertEqual(len(item.assets), 2)
        self.assertIsNotNone(item.cross_source)
        self.assertIsNotNone(item.history)

    def test_plain_item_has_no_depth(self):
        self.assertFalse(Item.from_dict(F.make_item(), "items[0]").has_depth)

    def test_published_optional(self):
        data = F.make_item()
        del data["published"]
        item = Item.from_dict(data, "items[0]")
        self.assertIsNone(item.published)
        self.assertIsNone(item.age_days(dt.date(2026, 9, 6)))

    def test_age_days(self):
        item = Item.from_dict(F.make_item(published="2026-09-04"), "i")
        self.assertEqual(item.age_days(dt.date(2026, 9, 6)), 2)

    def test_age_can_be_negative_for_future_dates(self):
        # 时区导致的「明天」偶尔会出现，不该崩，交给展示层处理成「今天」。
        item = Item.from_dict(F.make_item(published="2026-09-07"), "i")
        self.assertEqual(item.age_days(dt.date(2026, 9, 6)), -1)

    def test_bad_date_format_rejected(self):
        with self.assertRaises(SchemaError) as ctx:
            Item.from_dict(F.make_item(published="9/4/2026"), "items[0]")
        self.assertIn("items[0].published", str(ctx.exception))

    def test_duplicate_asset_class_rejected(self):
        data = F.make_item(assets=[F.make_asset(), F.make_asset()])
        with self.assertRaises(SchemaError) as ctx:
            Item.from_dict(data, "items[0]")
        self.assertIn("出现了不止一次", str(ctx.exception))

    def test_rank_must_be_int_not_string(self):
        with self.assertRaises(SchemaError) as ctx:
            Item.from_dict(F.make_item(rank="1"), "items[0]")
        self.assertIn("items[0].rank", str(ctx.exception))

    def test_bool_is_not_accepted_as_int(self):
        # True 会被 int() 悄悄吃成 1，那样只会掩盖数据错误。
        with self.assertRaises(SchemaError):
            Item.from_dict(F.make_item(rank=True), "items[0]")

    def test_unknown_tier_rejected(self):
        with self.assertRaises(SchemaError) as ctx:
            Item.from_dict(F.make_item(tier="urgent"), "items[0]")
        self.assertIn("items[0].tier", str(ctx.exception))

    def test_empty_headline_rejected(self):
        with self.assertRaises(SchemaError):
            Item.from_dict(F.make_item(headline="   "), "items[0]")

    def test_item_must_be_object(self):
        with self.assertRaises(SchemaError) as ctx:
            Item.from_dict(["not", "an", "object"], "items[4]")
        self.assertIn("items[4]", str(ctx.exception))


class TestMag7(unittest.TestCase):
    def test_direction_derived_from_sign(self):
        mag7 = Mag7.from_dict(F.make_mag7(), "mag7")
        self.assertEqual(mag7.rows[0].direction, "up")
        self.assertEqual(mag7.rows[1].direction, "down")

    def test_zero_change_counts_as_up(self):
        # 平盘归到涨侧只是为了让条形有个确定的方向，宽度是 0，视觉上没有区别。
        mag7 = Mag7.from_dict(
            F.make_mag7(rows=[{"ticker": "X", "price": "1.00", "change_pct": 0}]), "mag7"
        )
        self.assertEqual(mag7.rows[0].direction, "up")

    def test_empty_rows_rejected(self):
        with self.assertRaises(SchemaError) as ctx:
            Mag7.from_dict(F.make_mag7(rows=[]), "mag7")
        self.assertIn("mag7.rows", str(ctx.exception))

    def test_change_pct_must_be_number(self):
        with self.assertRaises(SchemaError) as ctx:
            Mag7.from_dict(
                F.make_mag7(rows=[{"ticker": "X", "price": "1", "change_pct": "0.84"}]),
                "mag7",
            )
        self.assertIn("mag7.rows[0].change_pct", str(ctx.exception))


class TestTape(unittest.TestCase):
    def test_direction_enum_enforced(self):
        bad = F.make_tape(rows=[{"name": "X", "value": "1", "change": "", "dir": "sideways"}])
        with self.assertRaises(SchemaError) as ctx:
            Tape.from_dict(bad, "tape")
        self.assertIn("tape.rows[0].dir", str(ctx.exception))

    def test_change_may_be_empty(self):
        tape = Tape.from_dict(
            F.make_tape(rows=[{"name": "X", "value": "1", "change": "", "dir": "flat"}]), "tape"
        )
        self.assertEqual(tape.rows[0].change, "")


class TestBrief(unittest.TestCase):
    def test_parses_full_brief(self):
        brief = Brief.from_dict(F.make_brief())
        self.assertEqual(brief.date, dt.date(2026, 9, 6))
        self.assertEqual(len(brief.items), 2)
        self.assertIsNotNone(brief.mag7)

    def test_mag7_optional(self):
        data = F.make_brief()
        del data["mag7"]
        self.assertIsNone(Brief.from_dict(data).mag7)

    def test_empty_items_rejected(self):
        with self.assertRaises(SchemaError):
            Brief.from_dict(F.make_brief(items=[]))

    def test_by_tier_preserves_order(self):
        brief = Brief.from_dict(F.make_brief())
        self.assertEqual([i.rank for i in brief.by_tier("must-read")], [1])
        self.assertEqual(brief.by_tier("worth-knowing"), ())

    def test_ticker_hits(self):
        brief = Brief.from_dict(F.make_brief())
        self.assertEqual(brief.ticker_hits(), {"SPY": [1]})

    def test_stale_ranks(self):
        brief = Brief.from_dict(F.make_brief())
        self.assertEqual(brief.stale_ranks(1), [1, 2])
        self.assertEqual(brief.stale_ranks(5), [])

    def test_root_must_be_object(self):
        with self.assertRaises(SchemaError):
            Brief.from_dict([1, 2, 3])


class TestBriefWarnings(unittest.TestCase):
    """质量警告不阻断发布，但必须报得准。"""

    def test_clean_brief_warns_only_about_freshness(self):
        brief = Brief.from_dict(F.make_brief())
        notes = brief.warnings(max_age_days=5, min_items=2)
        self.assertEqual(notes, [])

    def test_stale_items_warned(self):
        brief = Brief.from_dict(F.make_brief())
        notes = brief.warnings(max_age_days=1, min_items=2)
        self.assertTrue(any("时效上限" in n for n in notes))

    def test_max_age_override_wins(self):
        brief = Brief.from_dict(F.make_brief(max_age_days=9))
        notes = brief.warnings(max_age_days=1, min_items=2)
        self.assertFalse(any("时效上限" in n for n in notes))

    def test_too_few_items_warned(self):
        brief = Brief.from_dict(F.make_brief())
        notes = brief.warnings(max_age_days=5, min_items=15)
        self.assertTrue(any("低于 15 条" in n for n in notes))

    def test_duplicate_rank_warned(self):
        data = F.make_brief(
            items=[F.make_deep_item(rank=1), F.make_item(rank=1, tier="noise")]
        )
        notes = Brief.from_dict(data).warnings(max_age_days=5, min_items=1)
        self.assertTrue(any("rank 有重复" in n for n in notes))

    def test_non_contiguous_rank_warned(self):
        data = F.make_brief(
            items=[F.make_deep_item(rank=1), F.make_item(rank=7, tier="noise")]
        )
        notes = Brief.from_dict(data).warnings(max_age_days=5, min_items=1)
        self.assertTrue(any("连续整数" in n for n in notes))

    def test_missing_published_warned(self):
        item = F.make_item(rank=2, tier="noise")
        del item["published"]
        data = F.make_brief(items=[F.make_deep_item(), item])
        notes = Brief.from_dict(data).warnings(max_age_days=5, min_items=1)
        self.assertTrue(any("缺 published" in n for n in notes))

    def test_must_read_without_depth_warned(self):
        data = F.make_brief(items=[F.make_item(rank=1, tier="must-read")])
        notes = Brief.from_dict(data).warnings(max_age_days=5, min_items=1)
        self.assertTrue(any("深度元数据" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
