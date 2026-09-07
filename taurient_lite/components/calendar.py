"""日历标签页：一个滚动的周网格，事件标注在它实际发生的那一天。

替换掉原来那张「接下来要盯的时间点」列表——列表把日期埋在文字里，
读者得逐行读才知道哪天扎堆。网格把日期摆在轴上，扎堆与空档一眼可见。

**为什么是滚动窗口而不是严格的自然月。** 简报的日历事件通常横跨
一到两周，偶尔跨月（比如月底的会议、下月的上市）。严格按自然月画，
要么留一堆空白格，要么在月初漏看下月第一周的事。所以窗口从简报当天
所在周的周一开始，按周对齐，长度按最远的已知日期动态撑到 4 到 6 周，
超过 6 周的事件不硬塞进网格，落进「日期待定」列表里显示。

**为什么日期不明的事件不摆上网格。** 「本月晚些」「10 月」这类条目
没有确切日期，摆在网格的哪一格都是编的。诚实的做法是单独列出来，
标签保留原文，而不是伪造一个日期换取视觉上的整齐。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ..schema import Brief, CalendarEntry
from .base import esc, join, section_head

#: 网格最少撑 4 周，即使所有事件都在本周内，也给读者看到未来的空档。
MIN_WEEKS = 4
#: 超过 6 周还够不着的已知日期，不再撑大网格，转入「日期待定」列表。
MAX_WEEKS = 6

WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")


@dataclass(frozen=True, slots=True)
class CalendarWindow:
    """网格覆盖的日期范围，以及落在窗口内外的事件分组。"""

    start: dt.date
    weeks: int
    by_date: dict[dt.date, tuple[CalendarEntry, ...]]
    #: 有确切日期、但超出窗口的事件，与真正日期不明的事件一起进「更远」列表，
    #: 只是前者的 label 用日期而非原始 when 文本。
    later: tuple[CalendarEntry, ...]
    undated: tuple[CalendarEntry, ...]

    @property
    def end(self) -> dt.date:
        return self.start + dt.timedelta(days=self.weeks * 7 - 1)

    @property
    def days(self) -> list[dt.date]:
        return [self.start + dt.timedelta(days=i) for i in range(self.weeks * 7)]

    @property
    def is_empty(self) -> bool:
        return not self.by_date and not self.later and not self.undated


def build_window(today: dt.date, entries: tuple[CalendarEntry, ...]) -> CalendarWindow:
    """把日历事件分配进网格窗口，纯函数，不碰 HTML。"""
    start = today - dt.timedelta(days=today.weekday())  # 本周周一

    dated = sorted((e for e in entries if e.date is not None), key=lambda e: e.date)
    undated = tuple(e for e in entries if e.date is None)

    if dated:
        span_days = (dated[-1].date - start).days + 1
        weeks = max(MIN_WEEKS, -(-span_days // 7))  # 向上取整到整周
        weeks = min(weeks, MAX_WEEKS)
    else:
        weeks = MIN_WEEKS

    end = start + dt.timedelta(days=weeks * 7 - 1)

    by_date: dict[dt.date, list[CalendarEntry]] = {}
    later: list[CalendarEntry] = []
    for entry in dated:
        if entry.date <= end:
            by_date.setdefault(entry.date, []).append(entry)
        else:
            later.append(entry)

    return CalendarWindow(
        start=start,
        weeks=weeks,
        by_date={d: tuple(v) for d, v in by_date.items()},
        later=tuple(later),
        undated=undated,
    )


def _day_cell(day: dt.date, today: dt.date, entries: tuple[CalendarEntry, ...]) -> str:
    is_today = day == today
    is_weekend = day.weekday() >= 5
    is_month_start = day.day == 1

    classes = ["cal-day"]
    if is_today:
        classes.append("today")
    if is_weekend:
        classes.append("weekend")
    if not entries:
        classes.append("empty")

    # 平常只显示日号；每月第一天连月份一起显示，标出网格跨月的位置。
    date_text = f"{day.month}/{day.day}" if is_month_start else str(day.day)

    chips = "".join(
        f'<div class="cal-chip w-{e.weight}">'
        + (f'<span class="cal-chip-time">{esc(e.time)}</span>' if e.time else "")
        + f"<span>{esc(e.event)}</span></div>"
        for e in entries
    )

    return (
        f'<div class="{" ".join(classes)}">'
        f'<div class="cal-daynum">{esc(date_text)}</div>'
        f"{chips}"
        "</div>"
    )


def calendar_grid(window: CalendarWindow, today: dt.date) -> str:
    """周网格本身：表头加若干行，每行 7 天。"""
    header = "".join(f'<div class="cal-wd">{esc(w)}</div>' for w in WEEKDAY_LABELS)
    cells = "".join(
        _day_cell(day, today, window.by_date.get(day, ())) for day in window.days
    )
    return f'<div class="cal-grid">{header}{cells}</div>'


def _later_label(entry: CalendarEntry) -> str:
    """更远列表里的日期标签：有确切日期就用日期，没有就用原始的 when 文本。"""
    return f"{entry.date.month}/{entry.date.day}" if entry.date else entry.when


def later_list(window: CalendarWindow) -> str:
    """网格容不下的和日期不明的事件，合并成一张表。"""
    entries = tuple(window.later) + tuple(window.undated)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        rows += [
            "<tr>",
            f'<td class="when">{esc(_later_label(entry))}</td>',
            f'<td class="time">{esc(entry.time)}</td>',
            f"<td>{esc(entry.event)}</td>",
            f'<td class="w"><span class="w-{entry.weight}">{esc(entry.label)}</span></td>',
            "</tr>",
        ]
    return join(
        [
            '<div class="cal-later-head">日期待定 · 更远的事件</div>',
            '<div class="cal-scroll"><table><tbody>',
            join(rows),
            "</tbody></table></div>",
        ]
    )


def calendar_tab(brief: Brief) -> str:
    """日历标签页的完整内容。没有任何日历数据时返回空串。"""
    if not brief.calendar:
        return ""
    window = build_window(brief.date, brief.calendar)
    if window.is_empty:
        return ""
    return join(
        [
            section_head("接下来的日历", asof=f"{window.weeks} 周窗口"),
            calendar_grid(window, brief.date),
            later_list(window),
        ]
    )
