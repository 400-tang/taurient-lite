"""日历表格与页脚。"""

from __future__ import annotations

from ..schema import CalendarEntry
from .base import esc, join, section_head

#: 页脚。写清楚这份东西是什么、覆盖什么、以及它明确不是什么。
#: 最后一行不是免责套话，是这个工具的实际边界：它只做信息压缩。
COLOPHON_LINES = (
    "Taurient Lite · 由 Claude Code 每个交易日早晨自动生成",
    "覆盖范围：美股与宏观、科技与 AI 行业、影响能源与通胀的地缘事件",
    "涨跌色经过色觉障碍可辨度校验，方向箭头与带符号数值是颜色之外的编码",
    "这是新闻摘要，不是投资建议。数字以原始来源为准。",
)


def calendar_panel(entries: tuple[CalendarEntry, ...]) -> str:
    """接下来要盯的时间点。没有条目就整块省掉。"""
    if not entries:
        return ""
    rows = []
    for entry in entries:
        rows += [
            "<tr>",
            f'<td class="when">{esc(entry.when)}</td>',
            f'<td class="time">{esc(entry.time)}</td>',
            f"<td>{esc(entry.event)}</td>",
            f'<td class="w"><span class="w-{entry.weight}">{esc(entry.label)}</span></td>',
            "</tr>",
        ]
    return join(
        [
            section_head("接下来要盯的时间点", count=len(entries)),
            '<section class="cal-scroll"><table><tbody>',
            join(rows),
            "</tbody></table></section>",
        ]
    )


def colophon() -> str:
    return f'<footer class="colophon">{"<br>".join(COLOPHON_LINES)}</footer>'
