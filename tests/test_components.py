"""组件层测试：每个板块单独渲染，断言产出的 HTML。

跨组件的共同约定有两条，值得反复验证：
1. 没有数据的板块返回**空串**，而不是一个空壳骨架；
2. 所有来自 JSON 的文本都经过转义。
"""

from __future__ import annotations

import datetime as dt
import unittest

from taurient_lite.components import base, depth, items, panels, tail
from taurient_lite.components.panels import _axis_domain
from taurient_lite.schema import (
    AssetImpact,
    Brief,
    CrossSource,
    HistoricalContext,
    Item,
    Mag7,
)

from . import fixtures as F

TODAY = dt.date(2026, 9, 6)


class TestBase(unittest.TestCase):
    def test_esc_neutralises_markup(self):
        self.assertEqual(base.esc("<script>"), "&lt;script&gt;")

    def test_esc_handles_quotes_for_attributes(self):
        self.assertNotIn('"', base.esc('a"b'))

    def test_attr_omitted_when_empty(self):
        self.assertEqual(base.attr("id", ""), "")
        self.assertEqual(base.attr("id", None), "")
        self.assertEqual(base.attr("id", "x"), ' id="x"')

    def test_classes_skips_blanks(self):
        self.assertEqual(base.classes("a", None, "", "b"), ' class="a b"')
        self.assertEqual(base.classes(None, ""), "")

    def test_join_drops_empty_fragments(self):
        self.assertEqual(base.join(["a", "", "b"]), "a\nb")

    def test_section_head_optional_parts(self):
        bare = base.section_head("标题")
        self.assertNotIn('class="n"', bare)
        self.assertNotIn("asof", bare)
        full = base.section_head("标题", count=3, asof="收盘")
        self.assertIn(">3<", full)
        self.assertIn("收盘", full)


class TestMag7Chart(unittest.TestCase):
    def setUp(self):
        self.mag7 = Mag7.from_dict(F.make_mag7(), "mag7")

    def test_axis_domain_rounds_up_to_half_steps(self):
        self.assertEqual(_axis_domain(5.92), 6.0)
        self.assertEqual(_axis_domain(0.84), 1.0)
        self.assertEqual(_axis_domain(2.0), 2.5)

    def test_axis_domain_has_a_floor(self):
        """全员平盘时不能出现零标度，否则宽度计算会除以零。"""
        self.assertEqual(_axis_domain(0.0), 0.5)

    def test_rows_sorted_descending(self):
        html = panels.mag7_chart(self.mag7)
        self.assertLess(html.index("NVDA"), html.index("TSLA"))

    def test_bar_width_proportional_to_domain(self):
        html = panels.mag7_chart(self.mag7)
        # TSLA -5.92 在 6.0 的标度上占半幅的 98.67%，即整轨的 49.33%
        self.assertIn("width:49.33%", html)

    def test_signed_labels_present(self):
        """带符号数值是颜色之外的编码，必须出现。"""
        html = panels.mag7_chart(self.mag7)
        self.assertIn("+0.84%", html)
        self.assertIn("-5.92%", html)

    def test_zero_axis_labels(self):
        html = panels.mag7_chart(self.mag7)
        self.assertIn("<span>0</span>", html)

    def test_panel_omitted_without_data(self):
        self.assertEqual(panels.mag7_panel(None), "")

    def test_single_row_does_not_crash(self):
        one = Mag7.from_dict(
            F.make_mag7(rows=[{"ticker": "X", "price": "1.00", "change_pct": 0.0}]), "m"
        )
        self.assertIn("X", panels.mag7_chart(one))


class TestWatchlist(unittest.TestCase):
    def setUp(self):
        self.brief = Brief.from_dict(F.make_brief())

    def test_omitted_when_no_symbols(self):
        self.assertEqual(panels.watchlist_panel((), self.brief), "")

    def test_matched_symbol_becomes_anchor(self):
        html = panels.watchlist_panel(("SPY",), self.brief)
        self.assertIn('href="#item-1"', html)
        self.assertIn("wl-chip hit", html)

    def test_unmatched_symbol_is_inert_span(self):
        html = panels.watchlist_panel(("ZZZZ",), self.brief)
        self.assertIn("wl-chip", html)
        self.assertNotIn("href", html)

    def test_footer_counts_only_matches(self):
        html = panels.watchlist_panel(("SPY", "ZZZZ"), self.brief)
        self.assertIn("有 1 只出现在新闻中", html)

    def test_footer_when_nothing_matches(self):
        html = panels.watchlist_panel(("ZZZZ",), self.brief)
        self.assertIn("都没有单独的新闻", html)


class TestAssetMatrix(unittest.TestCase):
    def test_empty_matrix_omitted(self):
        self.assertEqual(depth.asset_matrix(()), "")

    def test_direction_glyph_accompanies_colour(self):
        """颜色之外必须有字形，色觉障碍读者靠它区分方向。"""
        cell = depth.asset_cell(AssetImpact.from_dict(F.make_asset(direction="up"), "a"))
        self.assertIn("&#8593;", cell)
        self.assertIn("利好", cell)

    def test_conviction_renders_as_filled_steps(self):
        high = depth.asset_cell(AssetImpact.from_dict(F.make_asset(conviction="high"), "a"))
        low = depth.asset_cell(AssetImpact.from_dict(F.make_asset(conviction="low"), "a"))
        self.assertEqual(high.count('class="on"'), 3)
        self.assertEqual(low.count('class="on"'), 1)

    def test_note_rendered_when_present(self):
        cell = depth.asset_cell(AssetImpact.from_dict(F.make_asset(note="传导路径"), "a"))
        self.assertIn("传导路径", cell)

    def test_note_omitted_when_blank(self):
        cell = depth.asset_cell(AssetImpact.from_dict(F.make_asset(note=""), "a"))
        self.assertNotIn("asset-note", cell)


class TestDepthCards(unittest.TestCase):
    def setUp(self):
        self.item = Item.from_dict(F.make_deep_item(), "items[0]")

    def test_depth_block_omitted_for_plain_item(self):
        plain = Item.from_dict(F.make_item(), "items[0]")
        self.assertEqual(depth.depth_block(plain), "")

    def test_two_cards_get_two_column_class(self):
        html = depth.depth_block(self.item)
        self.assertIn('class="cards two"', html)

    def test_single_card_stays_full_width(self):
        data = F.make_item(assets=[F.make_asset()], history=F.make_history())
        one = Item.from_dict(data, "items[0]")
        html = depth.depth_block(one)
        self.assertIn('class="cards"', html)
        self.assertNotIn("cards two", html)

    def test_agreement_badge_reflects_state(self):
        cross = CrossSource.from_dict(F.make_cross_source(agreement="split"), "c")
        html = depth.cross_source_card(cross, self.item)
        self.assertIn('class="agree split"', html)
        self.assertIn("存在分歧", html)

    def test_source_angles_listed_when_present(self):
        data = F.make_deep_item(
            sources=[F.make_source(name="FT", angle="强调债务而非能源")]
        )
        item = Item.from_dict(data, "items[0]")
        html = depth.cross_source_card(item.cross_source, item)
        self.assertIn("强调债务而非能源", html)

    def test_history_timeline_rendered(self):
        history = HistoricalContext.from_dict(F.make_history(), "h")
        html = depth.history_card(history)
        self.assertIn("2026-07", html)
        self.assertEqual(html.count("<li>"), 2)

    def test_history_without_timeline_has_no_list(self):
        history = HistoricalContext.from_dict({"summary": "一句话"}, "h")
        self.assertNotIn("<li>", depth.history_card(history))


class TestItems(unittest.TestCase):
    def test_age_badge_buckets(self):
        cases = {
            "2026-09-06": ("今天", "fresh"),
            "2026-09-05": ("昨天", "fresh"),
            "2026-09-04": ("2 天前", "aging"),
            "2026-09-01": ("5 天前", "stale"),
        }
        for published, expected in cases.items():
            item = Item.from_dict(F.make_item(published=published), "i")
            self.assertEqual(items.age_badge(item, TODAY), expected)

    def test_age_badge_absent_without_published(self):
        data = F.make_item()
        del data["published"]
        item = Item.from_dict(data, "i")
        self.assertEqual(items.age_badge(item, TODAY), ("", ""))

    def test_future_date_shows_as_today(self):
        item = Item.from_dict(F.make_item(published="2026-09-08"), "i")
        self.assertEqual(items.age_badge(item, TODAY)[0], "今天")

    def test_meta_row_omitted_when_nothing_to_show(self):
        data = F.make_item(sectors=[], tickers=[])
        del data["published"]
        item = Item.from_dict(data, "i")
        self.assertEqual(items.item_meta(item, TODAY), "")

    def test_item_anchor_matches_rank(self):
        item = Item.from_dict(F.make_item(rank=7), "i")
        self.assertIn('id="item-7"', items.render_item(item, TODAY))

    def test_data_tickers_attribute_present_when_tickers_exist(self):
        item = Item.from_dict(F.make_item(tickers=["NVDA", "TSLA"]), "i")
        html = items.render_item(item, TODAY)
        self.assertIn('data-tickers="NVDA TSLA"', html)

    def test_data_tickers_attribute_omitted_when_no_tickers(self):
        item = Item.from_dict(F.make_item(tickers=[]), "i")
        self.assertNotIn("data-tickers", items.render_item(item, TODAY))

    def test_rank_zero_padded(self):
        item = Item.from_dict(F.make_item(rank=3), "i")
        self.assertIn(">03<", items.render_item(item, TODAY))

    def test_headline_is_escaped(self):
        item = Item.from_dict(F.make_item(headline='<img src=x onerror="alert(1)">'), "i")
        html = items.render_item(item, TODAY)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)

    def test_source_url_is_escaped(self):
        item = Item.from_dict(
            F.make_item(sources=[F.make_source(url='https://x/"onmouseover="evil()')]), "i"
        )
        html = items.render_item(item, TODAY)
        self.assertNotIn('"onmouseover="', html)

    def test_optional_blocks_omitted(self):
        data = F.make_item(sources=[])
        del data["why"]
        del data["impact"]
        item = Item.from_dict(data, "i")
        html = items.render_item(item, TODAY)
        for marker in ("why", "impact", "srcs"):
            self.assertNotIn(f'class="{marker}"', html)

    def test_empty_tier_section_omitted(self):
        brief = Brief.from_dict(F.make_brief())
        self.assertEqual(items.tier_section(brief, "worth-knowing"), "")

    def test_all_tiers_ordered(self):
        brief = Brief.from_dict(F.make_brief())
        html = items.all_tiers(brief)
        self.assertLess(html.index("必读"), html.index("背景噪音"))


class TestTail(unittest.TestCase):
    def test_colophon_states_the_boundary(self):
        """页脚必须写明这不是投资建议，这是工具的实际边界。"""
        self.assertIn("不是投资建议", tail.colophon())


if __name__ == "__main__":
    unittest.main()
