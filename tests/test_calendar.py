"""日历标签页测试：窗口分配、网格渲染、更远列表。

:func:`~taurient_lite.components.calendar.build_window` 是纯函数，
所以窗口大小、事件分组这些逻辑在这里直接断言，不用解析 HTML。
"""

from __future__ import annotations

import datetime as dt
import re
import unittest

from taurient_lite.components.calendar import (
    MAX_WEEKS,
    MIN_WEEKS,
    build_window,
    calendar_grid,
    calendar_tab,
    later_list,
)
from taurient_lite.schema import Brief, CalendarEntry

from . import fixtures as F

TODAY = dt.date(2026, 9, 6)  # Sunday


def entry(when="x", time="", event="e", weight="low", date=None) -> CalendarEntry:
    return CalendarEntry.from_dict(
        {
            "when": when,
            "time": time,
            "event": event,
            "weight": weight,
            **({"date": date} if date else {}),
        },
        "c",
    )


class TestBuildWindow(unittest.TestCase):
    def test_window_starts_on_monday_of_todays_week(self):
        window = build_window(TODAY, ())
        self.assertEqual(window.start.weekday(), 0)
        self.assertLessEqual(window.start, TODAY)
        self.assertGreater(window.start + dt.timedelta(days=7), TODAY)

    def test_empty_entries_still_gets_minimum_window(self):
        window = build_window(TODAY, ())
        self.assertEqual(window.weeks, MIN_WEEKS)
        self.assertTrue(window.is_empty)

    def test_near_event_does_not_shrink_below_minimum(self):
        window = build_window(TODAY, (entry(date="2026-09-08"),))
        self.assertEqual(window.weeks, MIN_WEEKS)

    def test_window_grows_to_fit_a_farther_dated_event(self):
        # 9/6 到 10/2 跨了将近 4 周，加上起点前的几天，需要 5 周才装得下。
        window = build_window(TODAY, (entry(date="2026-10-02"),))
        self.assertGreaterEqual(window.weeks, 5)
        self.assertIn(dt.date(2026, 10, 2), window.by_date)

    def test_window_never_exceeds_max_weeks(self):
        window = build_window(TODAY, (entry(date="2027-01-01"),))
        self.assertEqual(window.weeks, MAX_WEEKS)

    def test_event_beyond_window_falls_into_later(self):
        window = build_window(TODAY, (entry(event="遥远的事", date="2027-01-01"),))
        self.assertEqual(window.by_date, {})
        self.assertEqual(len(window.later), 1)
        self.assertEqual(window.later[0].event, "遥远的事")

    def test_undated_entry_never_touches_the_grid(self):
        window = build_window(TODAY, (entry(event="FOMC", when="本月晚些"),))
        self.assertEqual(window.by_date, {})
        self.assertEqual(window.undated[0].event, "FOMC")

    def test_multiple_events_same_day_grouped_together(self):
        window = build_window(
            TODAY,
            (entry(event="A", date="2026-09-09"), entry(event="B", date="2026-09-09")),
        )
        self.assertEqual(len(window.by_date[dt.date(2026, 9, 9)]), 2)

    def test_days_property_length_matches_weeks(self):
        window = build_window(TODAY, ())
        self.assertEqual(len(window.days), MIN_WEEKS * 7)

    def test_end_is_inclusive_last_day(self):
        window = build_window(TODAY, ())
        self.assertEqual(window.end, window.days[-1])


class TestCalendarGrid(unittest.TestCase):
    def test_seven_columns_per_week(self):
        window = build_window(TODAY, ())
        html = calendar_grid(window, TODAY)
        self.assertEqual(html.count('class="cal-wd"'), 7)

    def test_cell_count_matches_window(self):
        window = build_window(TODAY, ())
        html = calendar_grid(window, TODAY)
        # 用 lookahead 卡住 "cal-day" 后面必须是空格或引号，否则 "cal-daynum"
        # 的 <div> 也会被数进去（它是每个格子里都有的子元素），数字会翻倍。
        cells = re.findall(r'class="cal-day(?=[\s"])', html)
        self.assertEqual(len(cells), MIN_WEEKS * 7)

    def test_today_cell_is_marked(self):
        window = build_window(TODAY, ())
        html = calendar_grid(window, TODAY)
        # 今天这一格还可能同时带 weekend/empty，只断言 "today" 紧跟在 "cal-day" 后面。
        self.assertIn('class="cal-day today', html)

    def test_event_chip_carries_weight_class(self):
        window = build_window(TODAY, (entry(event="CPI", weight="high", date="2026-09-11"),))
        html = calendar_grid(window, TODAY)
        self.assertIn("cal-chip w-high", html)
        self.assertIn("CPI", html)

    def test_month_start_shows_month_slash_day(self):
        window = build_window(dt.date(2026, 8, 28), ())
        html = calendar_grid(window, dt.date(2026, 8, 28))
        self.assertIn(">9/1<", html)

    def test_non_month_start_shows_bare_day_number(self):
        window = build_window(TODAY, ())
        html = calendar_grid(window, TODAY)
        self.assertIn(">6<", html)  # 9/6 本身

    def test_empty_day_gets_empty_class(self):
        window = build_window(TODAY, ())
        html = calendar_grid(window, TODAY)
        self.assertIn("cal-day empty", html)

    def test_time_shown_when_present(self):
        window = build_window(
            TODAY, (entry(event="CPI", time="08:30 ET", date="2026-09-11"),)
        )
        html = calendar_grid(window, TODAY)
        self.assertIn("08:30 ET", html)

    def test_headline_is_escaped(self):
        window = build_window(
            TODAY, (entry(event="<script>evil()</script>", date="2026-09-09"),)
        )
        html = calendar_grid(window, TODAY)
        self.assertNotIn("<script>evil", html)


class TestLaterList(unittest.TestCase):
    def test_empty_when_nothing_left_over(self):
        window = build_window(TODAY, (entry(date="2026-09-08"),))
        self.assertEqual(later_list(window), "")

    def test_undated_entry_shows_original_when_text(self):
        window = build_window(TODAY, (entry(event="FOMC", when="本月晚些"),))
        html = later_list(window)
        self.assertIn("本月晚些", html)
        self.assertIn("FOMC", html)

    def test_far_dated_entry_shows_formatted_date_not_raw_when(self):
        window = build_window(
            TODAY, (entry(event="上市", when="随便写的原文", date="2027-03-01"),)
        )
        html = later_list(window)
        self.assertIn("3/1", html)
        self.assertNotIn("随便写的原文", html)

    def test_far_and_undated_both_appear(self):
        window = build_window(
            TODAY,
            (
                entry(event="远期事件", date="2027-03-01"),
                entry(event="日期不明", when="以后"),
            ),
        )
        html = later_list(window)
        self.assertIn("远期事件", html)
        self.assertIn("日期不明", html)


class TestCalendarTab(unittest.TestCase):
    def test_omitted_when_brief_has_no_calendar_at_all(self):
        brief = Brief.from_dict(F.make_brief(calendar=[]))
        self.assertEqual(calendar_tab(brief), "")

    def test_present_when_brief_has_calendar(self):
        brief = Brief.from_dict(F.make_brief())
        html = calendar_tab(brief)
        self.assertIn("cal-grid", html)
        self.assertIn("8 月 CPI", html)

    def test_undated_fomc_entry_reaches_later_list(self):
        brief = Brief.from_dict(F.make_brief())
        html = calendar_tab(brief)
        self.assertIn("9 月 FOMC 决议", html)
        self.assertIn("日期待定", html)


if __name__ == "__main__":
    unittest.main()
