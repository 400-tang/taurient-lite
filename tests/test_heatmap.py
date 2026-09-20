"""树图布局、色阶分档与热力图组件。

这里有两条测试值得单独说明，因为它们盯的是**不会报错的错误**：

* :meth:`TestBox.test_css_box_matches_layout_box` —— CSS 的
  ``aspect-ratio`` 和 ``squarify`` 的画布比例一旦对不上，页面照样渲染，
  只是所有块都被拉成长条，而这种「看起来只是有点丑」的问题最容易蒙混
  过关。
* :meth:`TestContrast.test_invert_lists_are_exactly_the_failing_levels` ——
  两套主题需要反转文字色的档位**不一样**，很容易想当然地对齐。判据直接
  按 WCAG 公式算，不是照抄代码注释里的结论；注释写错了，测试也会红。
"""

from __future__ import annotations

import datetime as dt
import unittest

from taurient_lite.components.heatmap import (
    COMPACT_W,
    LARGE_W,
    MAX_TILES,
    _fit,
    legend,
    market_tab,
    sector_card,
)
from taurient_lite.schema import (
    HEAT_CLAMP_PCT,
    HEAT_FLAT_PCT,
    Market,
    SectorBlock,
    SectorTile,
    heat_level,
)
from taurient_lite.theme import (
    HEAT_BOX,
    HEAT_INK,
    HEAT_INVERT_DARK,
    HEAT_INVERT_LIGHT,
    HEAT_LEVEL_NAMES,
    TOKENS,
    build_css,
    build_heat_levels_css,
)
from taurient_lite.treemap import Rect, squarify


def tile(ticker: str, chg: float, cap: float) -> SectorTile:
    return SectorTile(ticker=ticker, change_pct=chg, market_cap=cap, name=f"{ticker} Inc.")


def block(name: str = "科技", chg: float = 1.0, n: int = 6) -> SectorBlock:
    tiles = tuple(tile(f"T{i}", chg, 1000.0 / (i + 1)) for i in range(n))
    return SectorBlock(name=name, change_pct=chg, market_cap=5000.0, tiles=tiles)


# ------------------------------------------------------------------ 树图几何


class TestSquarify(unittest.TestCase):
    def test_returns_one_rect_per_input(self):
        rects = squarify([5, 3, 2])
        self.assertEqual(len(rects), 3)

    def test_areas_are_proportional_to_weights(self):
        weights = [50, 30, 12, 8]
        rects = squarify(weights, box_w=100, box_h=100)
        total = sum(weights)
        for w, r in zip(weights, rects):
            self.assertAlmostEqual(r.width * r.height / 100, w / total * 100, places=4)

    def test_rects_fill_the_whole_canvas(self):
        rects = squarify([9, 7, 5, 3, 1])
        covered = sum(r.width * r.height for r in rects) / 100
        self.assertAlmostEqual(covered, 100.0, places=4)

    def test_no_rect_escapes_the_canvas(self):
        for r in squarify([40, 25, 15, 10, 6, 4], box_w=100, box_h=62):
            self.assertGreaterEqual(r.left, -1e-9)
            self.assertGreaterEqual(r.top, -1e-9)
            self.assertLessEqual(r.left + r.width, 100 + 1e-6)
            self.assertLessEqual(r.top + r.height, 100 + 1e-6)

    def test_aspect_ratios_stay_reasonable(self):
        """squarified 的全部意义就是别产出细长条，这里定个上限盯着它。"""
        bw, bh = HEAT_BOX
        rects = squarify([4500, 3800, 3100, 2400, 1800, 900, 600, 420, 300, 210],
                         box_w=bw, box_h=bh)
        for r in rects:
            # 换算回真实像素比例：画布本身不是正方形。
            w = r.width * bw
            h = r.height * bh
            self.assertLess(max(w / h, h / w), 4.0, f"{r} 太细长了")

    def test_zero_and_negative_weights_get_empty_rects(self):
        """跳过的块也要占位，否则调用方 zip 会静默错位。"""
        rects = squarify([10, 0, 5, -3])
        self.assertEqual(len(rects), 4)
        self.assertEqual(rects[1], Rect(0.0, 0.0, 0.0, 0.0))
        self.assertEqual(rects[3], Rect(0.0, 0.0, 0.0, 0.0))

    def test_empty_input(self):
        self.assertEqual(squarify([]), [])

    def test_all_zero_weights_does_not_crash(self):
        self.assertEqual(len(squarify([0, 0, 0])), 3)

    def test_style_subtracts_gap(self):
        style = Rect(10.0, 20.0, 30.0, 40.0).style(gap=2.0)
        self.assertIn("left:10.0000%", style)
        self.assertIn("width:28.0000%", style)
        self.assertIn("height:38.0000%", style)

    def test_style_never_goes_negative(self):
        """缝隙比块还宽时宽度必须钳到 0，负宽度会让浏览器忽略整条规则。"""
        self.assertIn("width:0.0000%", Rect(0, 0, 0.5, 0.5).style(gap=2.0))


# ------------------------------------------------------------------ 色阶分档


class TestHeatLevel(unittest.TestCase):
    def test_flat_band_covers_both_signs(self):
        self.assertEqual(heat_level(0.0), "flat")
        self.assertEqual(heat_level(HEAT_FLAT_PCT / 2), "flat")
        self.assertEqual(heat_level(-HEAT_FLAT_PCT / 2), "flat")

    def test_direction_picks_the_prefix(self):
        self.assertTrue(heat_level(1.0).startswith("u"))
        self.assertTrue(heat_level(-1.0).startswith("d"))

    def test_clamped_at_the_top_level(self):
        self.assertEqual(heat_level(HEAT_CLAMP_PCT), "u5")
        self.assertEqual(heat_level(HEAT_CLAMP_PCT * 10), "u5")
        self.assertEqual(heat_level(-HEAT_CLAMP_PCT * 10), "d5")

    def test_monotonic(self):
        """涨得越多颜色只能越深，不能回头。"""
        levels = [int(heat_level(x / 10)[1:]) for x in range(1, 40)]
        self.assertEqual(levels, sorted(levels))

    def test_every_level_is_reachable(self):
        """有一档永远取不到，就等于色阶少了一档还没人发现。"""
        seen = {heat_level(x / 100) for x in range(6, 400)}
        self.assertEqual(seen, {f"u{i}" for i in range(1, 6)})

    def test_common_moves_are_not_saturated(self):
        """常态波动必须落在中间档。

        这是当初把曲线从 0.5 调到 0.75 的原因：平方根刻度下 +1.3% 就顶到
        最亮一档，满屏亮绿，「今天有没有异常」反而看不出来了。
        """
        self.assertLessEqual(int(heat_level(1.0)[1:]), 3)
        self.assertLessEqual(int(heat_level(1.3)[1:]), 3)
        self.assertGreaterEqual(int(heat_level(2.8)[1:]), 4)

    def test_nan_is_flat(self):
        self.assertEqual(heat_level(float("nan")), "flat")

    def test_all_level_names_are_covered_by_tokens(self):
        for name in HEAT_LEVEL_NAMES:
            self.assertIn(f"heat-{name}", TOKENS, f"色阶 {name} 没有对应的颜色 token")


# ------------------------------------------------------------------ 对比度


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class TestContrast(unittest.TestCase):
    """色块上的文字必须读得出来。判据按 WCAG 现算，不照抄注释里的结论。

    两套主题各校验一遍。``MODES`` 里的 0/1 就是 TOKENS 每个条目的两栏。
    """

    MODES = ((0, "亮色", HEAT_INVERT_LIGHT), (1, "暗色", HEAT_INVERT_DARK))

    def test_every_level_reaches_4_5_with_its_chosen_ink(self):
        """每一档的底色配上它自己那个 heat-on-* 文字色都要达标。

        直接读 ``heat-on-<档位>`` 而不是自己按名单推一遍文字色：推一遍就是
        把生成逻辑在测试里抄第二份，两边一起错的时候测试照样绿。
        """
        for idx, label, _ in self.MODES:
            for name in HEAT_LEVEL_NAMES:
                bg = TOKENS[f"heat-{name}"][idx]
                ink = TOKENS[f"heat-on-{name}"][idx]
                self.assertGreaterEqual(
                    _contrast(bg, ink), 4.5,
                    f"{label}模式 {name} 档（{bg} 配 {ink}）对比度不足 4.5:1",
                )

    def test_invert_lists_are_exactly_the_failing_levels(self):
        """反转名单不是拍脑袋列的，而且必须**恰好**是不达标的那几档。

        两个方向都查：名单里的档位默认色确实不合格，名单外的档位确实合格。
        只查前者的话，多写一档进名单不会被发现。
        """
        for idx, label, invert in self.MODES:
            default_ink = HEAT_INK[idx]
            for name in HEAT_LEVEL_NAMES:
                bg = TOKENS[f"heat-{name}"][idx]
                ok = _contrast(bg, default_ink) >= 4.5
                if name in invert:
                    self.assertFalse(
                        ok, f"{label}模式 {name} 档默认文字色其实合格，不该进反转名单")
                else:
                    self.assertTrue(
                        ok, f"{label}模式 {name} 档默认文字色不合格，应该进反转名单")

    def test_ramp_moves_away_from_the_background_monotonically(self):
        """幅度越大，色块必须离底色越远。

        **两套主题的方向是相反的**：亮色模式下色阶越深（亮度递减），暗色
        模式下越亮（亮度递增）。所以这里断言的不是「递增」或「递减」，
        而是「和底色的亮度差单调变大」——这才是两套色阶共同遵守的那条规则。
        """
        for idx, label, _ in self.MODES:
            base = _luminance(TOKENS["heat-card"][idx])
            for prefix in ("u", "d"):
                gaps = [
                    abs(_luminance(TOKENS[f"heat-{prefix}{i}"][idx]) - base)
                    for i in range(1, 6)
                ]
                self.assertEqual(
                    gaps, sorted(gaps),
                    f"{label}模式 {prefix} 色阶与底色的距离不是单调变大的：{gaps}",
                )

    def test_light_ramp_starts_near_the_paper(self):
        """亮色模式最低档必须贴近卡片底色，否则「小幅度」看起来就不小了。"""
        base = _luminance(TOKENS["heat-card"][0])
        for name in ("u1", "d1"):
            self.assertLess(
                abs(_luminance(TOKENS[f"heat-{name}"][0]) - base), 0.25,
                f"亮色 {name} 档离纸张底色太远",
            )

    def test_faint_tiles_have_an_edge_to_stand_on(self):
        """最低档和卡片底色的差距小到需要边框来勾边界。

        这条测试存在的理由是记录一个设计决定：``heat-edge`` 不是装饰。
        亮色模式下 +0.21% 的色块和卡片底色几乎分不开，靠边框才看得出这里
        有一块。哪天有人觉得边框多余想删掉，这条断言会解释它为什么在。
        """
        base = _luminance(TOKENS["heat-card"][0])
        faint = _luminance(TOKENS["heat-u1"][0])
        self.assertLess(_contrast(TOKENS["heat-card"][0], TOKENS["heat-u1"][0]), 1.3)
        self.assertLess(abs(faint - base), 0.12)
        # 边框本身要比底色深，才勾得出来。
        self.assertLess(_luminance(TOKENS["heat-edge"][0]), base)


# ------------------------------------------------------------------ 画布一致


class TestBox(unittest.TestCase):
    def test_css_box_matches_layout_box(self):
        """CSS 的 aspect-ratio 必须和 squarify 的画布比例一致。

        对不上不会报错，只会让所有块被容器拉成长条——最难靠肉眼发现的
        那类问题，所以钉在这里。
        """
        w, h = HEAT_BOX
        self.assertIn(f"aspect-ratio: {w} / {h}", build_css())


# ------------------------------------------------------------------ 组件渲染


class TestLevelsCss(unittest.TestCase):
    def test_every_level_has_background_and_color(self):
        css = build_heat_levels_css()
        for name in HEAT_LEVEL_NAMES:
            self.assertIn(f".tile.{name} {{ background: var(--heat-{name});", css)
            self.assertIn(f".swatch.sw-{name}", css)

    def test_every_level_points_at_its_own_ink_token(self):
        """文字色必须走 heat-on-*，不能在 CSS 里按主题分支写两遍。"""
        css = build_heat_levels_css()
        for name in HEAT_LEVEL_NAMES:
            line = next(l for l in css.splitlines() if l.startswith(f".tile.{name} "))
            self.assertIn(f"var(--heat-on-{name})", line)


class TestFit(unittest.TestCase):
    def test_large_blocks_get_bigger_type(self):
        self.assertEqual(_fit(LARGE_W + 1, 40.0), "lg")

    def test_mid_blocks_show_both_lines(self):
        self.assertEqual(_fit(20.0, 20.0), "")

    def test_narrow_blocks_drop_the_number(self):
        self.assertEqual(_fit(COMPACT_W + 0.5, 10.0), "compact")

    def test_tiny_blocks_show_nothing(self):
        self.assertEqual(_fit(2.0, 2.0), "bare")


class TestSectorCard(unittest.TestCase):
    def test_renders_one_tile_per_member(self):
        html = sector_card(block(n=5))
        # 末尾的空格是必要的：不加会把 tile-tk / tile-ch 两个子元素也数进来。
        self.assertEqual(html.count('class="tile '), 5)

    def test_caps_the_tile_count(self):
        html = sector_card(block(n=MAX_TILES + 9))
        self.assertEqual(html.count('class="tile '), MAX_TILES)

    def test_biggest_company_comes_first(self):
        """树图算法要求输入按权重降序，顺序错了长宽比就崩。"""
        small = tile("SMALL", 1.0, 10.0)
        big = tile("BIG", 1.0, 9000.0)
        html = sector_card(SectorBlock(name="X", change_pct=1.0, market_cap=9010.0,
                                       tiles=(small, big)))
        self.assertLess(html.index("BIG"), html.index("SMALL"))

    def test_signed_number_is_always_present(self):
        """颜色之外必须有第二重编码，否则对红绿色盲读者等于没有信息。"""
        html = sector_card(SectorBlock(name="X", change_pct=1.0, market_cap=100.0,
                                       tiles=(tile("AAA", -2.5, 100.0),)))
        self.assertIn("-2.50%", html)

    def test_sector_change_text_is_not_level_shaded(self):
        """行业涨跌幅的文字不能用色阶上色。

        踩过的坑：``.sec-chg`` 曾经直接套色阶类名，于是 -0.07% 拿到的是
        最低档的暗棕 #3A201C，压在同样暗的卡片底上几乎看不见。色阶是给
        **背景**设计的，当文字色用必然在低档失效。
        """
        faint = SectorBlock(name="金融", change_pct=-0.07, market_cap=100.0,
                            tiles=(tile("JPM", -0.07, 100.0),))
        html = sector_card(faint)
        self.assertIn('class="sec-chg down"', html)
        for level in HEAT_LEVEL_NAMES:
            self.assertNotIn(f'class="sec-chg {level}"', html)

    def test_flat_sector_gets_neutral_text(self):
        flat = SectorBlock(name="持平", change_pct=0.0, market_cap=100.0,
                           tiles=(tile("AAA", 0.0, 100.0),))
        self.assertIn('class="sec-chg flat"', sector_card(flat))

    def test_empty_block_renders_nothing(self):
        self.assertEqual(sector_card(SectorBlock(name="空", change_pct=0.0,
                                                 market_cap=0.0, tiles=())), "")

    def test_escapes_hostile_text(self):
        evil = SectorTile(ticker='<img src=x>', change_pct=1.0, market_cap=10.0,
                          name='"onload="alert(1)')
        html = sector_card(SectorBlock(name="<b>", change_pct=1.0, market_cap=10.0,
                                       tiles=(evil,)))
        self.assertNotIn("<img", html)
        self.assertNotIn('"onload=', html)


class TestLastTradingDay(unittest.TestCase):
    """``asof`` 标的是数据所属的交易日，不是抓取日期。

    踩过的坑：直接用 ``date.today()``，周六抓一次，页面上就印出
    「截至 2026-09-19 收盘」——那天是周六，根本没有这个收盘。
    """

    def setUp(self):
        import fetch_sectors
        self.fn = fetch_sectors.last_trading_day

    def test_weekday_points_at_yesterday(self):
        # 周五抓 → 周四收盘
        self.assertEqual(self.fn(dt.datetime(2026, 9, 18, 8, 30)), dt.date(2026, 9, 17))

    def test_saturday_points_at_friday(self):
        self.assertEqual(self.fn(dt.datetime(2026, 9, 19, 8, 30)), dt.date(2026, 9, 18))

    def test_sunday_points_at_friday(self):
        self.assertEqual(self.fn(dt.datetime(2026, 9, 20, 8, 30)), dt.date(2026, 9, 18))

    def test_monday_skips_back_over_the_weekend(self):
        """周一盘前抓到的是上周五的收盘，不是周日。"""
        self.assertEqual(self.fn(dt.datetime(2026, 9, 21, 8, 30)), dt.date(2026, 9, 18))

    def test_never_returns_a_weekend(self):
        day = dt.datetime(2026, 1, 1)
        for _ in range(400):
            self.assertLess(self.fn(day).weekday(), 5)
            day += dt.timedelta(days=1)


class TestMarketTab(unittest.TestCase):
    def test_none_renders_nothing(self):
        self.assertEqual(market_tab(None), "")

    def test_empty_sectors_render_nothing(self):
        self.assertEqual(market_tab(Market(asof="2026-09-10")), "")

    def test_sectors_ranked_by_strength(self):
        weak = SectorBlock(name="弱", change_pct=-1.5, market_cap=10.0,
                           tiles=(tile("A", -1.5, 10.0),))
        strong = SectorBlock(name="强", change_pct=2.0, market_cap=10.0,
                             tiles=(tile("B", 2.0, 10.0),))
        html = market_tab(Market(asof="2026-09-10", sectors=(weak, strong)))
        self.assertLess(html.index("强"), html.index("弱"))

    def test_shows_the_data_date(self):
        """盘前页面上的涨跌幅必须标明是哪一天的，否则会被读成「今天」。"""
        html = market_tab(Market(asof="2026-09-10", sectors=(block(),)))
        self.assertIn("截至 2026-09-10 收盘", html)

    def test_legend_is_present(self):
        html = market_tab(Market(asof="2026-09-10", sectors=(block(),)))
        self.assertIn("heat-legend", html)
        self.assertIn("±3%", html)

    def test_legend_swatches_are_not_absolutely_positioned_tiles(self):
        """图例复用 .tile 会让所有色块叠在一起——真踩过这个坑。"""
        self.assertNotIn('class="tile', legend())


if __name__ == "__main__":
    unittest.main()
