"""板块热力的数据层：时点判定与聚合。

这里最要紧的一组测试是**时点标注**。板块数据有两种时点——走完的收盘、
还在变的盘中——而页面上那行小字会把它当成事实陈述印出来。标错了不会
报错、不会崩，只会让读者把一个还在变的数字当成当天的定论，这正是
``momentum.py`` 里记过代价的那类错误。
"""

from __future__ import annotations

import datetime as dt
import unittest

from taurient_lite.schema import Market, SchemaError
from taurient_lite.sectors import (
    EASTERN,
    MIN_CAP,
    SECTOR_CN,
    TOP_PER_SECTOR,
    SectorError,
    _num,
    build_market_block,
    build_sectors,
    is_market_open,
    last_trading_day,
    session_of,
)


def row(symbol="AAA", sector="Technology", cap="1000000000", chg="1.5%",
        name="Alpha Inc. Common Stock"):
    return {"symbol": symbol, "sector": sector, "marketCap": cap,
            "pctchange": chg, "name": name}


def et(y, m, d, hh=12, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=EASTERN)


# ------------------------------------------------------------------ 时点判定


class TestLastTradingDay(unittest.TestCase):
    def test_weekday_points_at_yesterday(self):
        self.assertEqual(last_trading_day(et(2026, 9, 18, 8, 30)), dt.date(2026, 9, 17))

    def test_saturday_points_at_friday(self):
        self.assertEqual(last_trading_day(et(2026, 9, 19, 8, 30)), dt.date(2026, 9, 18))

    def test_sunday_points_at_friday(self):
        self.assertEqual(last_trading_day(et(2026, 9, 20, 8, 30)), dt.date(2026, 9, 18))

    def test_monday_skips_back_over_the_weekend(self):
        """周一盘前抓到的是上周五的收盘，不是周日。"""
        self.assertEqual(last_trading_day(et(2026, 9, 21, 8, 30)), dt.date(2026, 9, 18))

    def test_never_returns_a_weekend(self):
        day = et(2026, 1, 1)
        for _ in range(400):
            self.assertLess(last_trading_day(day).weekday(), 5)
            day += dt.timedelta(days=1)


class TestIsMarketOpen(unittest.TestCase):
    def test_midday_weekday_is_open(self):
        self.assertTrue(is_market_open(et(2026, 9, 18, 12, 0)))

    def test_just_after_the_bell_is_open(self):
        self.assertTrue(is_market_open(et(2026, 9, 18, 9, 30)))

    def test_premarket_is_closed(self):
        self.assertFalse(is_market_open(et(2026, 9, 18, 8, 30)))

    def test_at_the_close_is_already_closed(self):
        """16:00 整算收盘，不算还开着——区间是左闭右开。"""
        self.assertFalse(is_market_open(et(2026, 9, 18, 16, 0)))

    def test_weekend_is_closed_even_at_midday(self):
        self.assertFalse(is_market_open(et(2026, 9, 19, 12, 0)))


class TestSessionOf(unittest.TestCase):
    def test_intraday_reports_a_clock_time(self):
        session, asof = session_of(et(2026, 9, 18, 14, 32))
        self.assertEqual(session, "intraday")
        self.assertEqual(asof, "14:32 ET")

    def test_outside_hours_reports_the_last_close(self):
        session, asof = session_of(et(2026, 9, 18, 8, 30))
        self.assertEqual(session, "close")
        self.assertEqual(asof, "2026-09-17")

    def test_weekend_reports_fridays_close(self):
        session, asof = session_of(et(2026, 9, 19, 10, 0))
        self.assertEqual(session, "close")
        self.assertEqual(asof, "2026-09-18")

    def test_intraday_never_claims_a_close(self):
        """盘中绝不能标成「截至某日收盘」——那是一个还没发生的事实。"""
        _, asof = session_of(et(2026, 9, 18, 11, 0))
        market = Market(asof=asof, session="intraday")
        self.assertIn("盘中", market.asof_label)
        self.assertNotIn("收盘", market.asof_label)

    def test_close_label_reads_as_a_close(self):
        market = Market(asof="2026-09-18", session="close")
        self.assertEqual(market.asof_label, "截至 2026-09-18 收盘")

    def test_session_defaults_to_close(self):
        """存档进简报 JSON 的永远是收盘数据，缺省值必须是 close。"""
        self.assertEqual(Market(asof="2026-09-18").session, "close")

    def test_schema_rejects_an_unknown_session(self):
        with self.assertRaises(SchemaError):
            Market.from_dict({"asof": "2026-09-18", "session": "盘后"}, "market")


# ------------------------------------------------------------------ 数字解析


class TestNum(unittest.TestCase):
    def test_strips_dollar_and_percent_and_commas(self):
        self.assertAlmostEqual(_num("$1,234.50"), 1234.5)
        self.assertAlmostEqual(_num("0.083%"), 0.083)
        self.assertAlmostEqual(_num("-5.41%"), -5.41)

    def test_placeholders_become_none(self):
        """解析不出来要返回 None，不能当成 0.0。

        当成 0 就是在版面上画一个「平盘」的色块，凭空造一个事实。
        """
        for raw in (None, "", "--", "N/A", "abc"):
            self.assertIsNone(_num(raw), raw)


# ------------------------------------------------------------------ 聚合


class TestBuildSectors(unittest.TestCase):
    def test_groups_by_sector_and_translates_the_name(self):
        out = build_sectors([row(), row(symbol="BBB")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], SECTOR_CN["Technology"])

    def test_change_is_market_cap_weighted(self):
        """大公司说了算：简单平均会让微型股盖过苹果。"""
        rows = [
            row(symbol="BIG", cap="900000000000", chg="1.0%"),
            row(symbol="TINY", cap="100000000000", chg="-9.0%"),
        ]
        # 加权：(1.0*900 + -9.0*100) / 1000 = 0.0
        self.assertAlmostEqual(build_sectors(rows)[0]["change_pct"], 0.0)

    def test_drops_tiny_companies(self):
        self.assertEqual(build_sectors([row(cap=str(int(MIN_CAP / 10)))]), [])

    def test_drops_rows_missing_numbers(self):
        self.assertEqual(build_sectors([row(chg="--")]), [])
        self.assertEqual(build_sectors([row(cap="N/A")]), [])

    def test_skips_the_miscellaneous_bucket(self):
        """杂项筐画成一个板块会让读者以为它是个真实的行业。"""
        self.assertEqual(build_sectors([row(sector="Miscellaneous")]), [])
        self.assertEqual(build_sectors([row(sector="")]), [])

    def test_skips_warrants_and_preferred(self):
        for symbol in ("AAA^B", "BBB/WS", "CCC$D"):
            self.assertEqual(build_sectors([row(symbol=symbol)]), [], symbol)

    def test_trims_the_boilerplate_suffix(self):
        out = build_sectors([row(name="Alpha Inc. Common Stock")])
        self.assertEqual(out[0]["tiles"][0]["name"], "Alpha Inc.")

    def test_caps_tiles_per_sector(self):
        rows = [row(symbol=f"T{i}", cap=str(10_000_000_000 - i)) for i in range(40)]
        self.assertEqual(len(build_sectors(rows)[0]["tiles"]), TOP_PER_SECTOR)

    def test_keeps_the_biggest_companies(self):
        rows = [row(symbol="SMALL", cap="1000000000"),
                row(symbol="HUGE", cap="900000000000")]
        self.assertEqual(build_sectors(rows)[0]["tiles"][0]["ticker"], "HUGE")

    def test_sectors_sorted_by_size(self):
        rows = [row(symbol="A", sector="Energy", cap="1000000000"),
                row(symbol="B", sector="Technology", cap="900000000000")]
        names = [s["name"] for s in build_sectors(rows)]
        self.assertEqual(names[0], SECTOR_CN["Technology"])

    def test_unmapped_sector_keeps_its_english_name(self):
        """没写进对照表的行业照原样显示，不能因为缺翻译就整块消失。"""
        out = build_sectors([row(sector="Something New")])
        self.assertEqual(out[0]["name"], "Something New")


class TestBuildMarketBlock(unittest.TestCase):
    def test_produces_a_block_the_schema_accepts(self):
        block = build_market_block([row()], now=et(2026, 9, 18, 8, 30))
        market = Market.from_dict(block, "market")
        self.assertEqual(market.session, "close")
        self.assertEqual(market.asof, "2026-09-17")
        self.assertEqual(len(market.sectors), 1)

    def test_intraday_block_is_labelled_intraday(self):
        block = build_market_block([row()], now=et(2026, 9, 18, 14, 0))
        self.assertEqual(Market.from_dict(block, "market").session, "intraday")

    def test_empty_result_raises_instead_of_shipping_an_empty_board(self):
        with self.assertRaises(SectorError):
            build_market_block([row(sector="Miscellaneous")], now=et(2026, 9, 18))


if __name__ == "__main__":
    unittest.main()
