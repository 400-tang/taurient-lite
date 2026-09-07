"""页脚。

日历相关的渲染搬到了 :mod:`taurient_lite.components.calendar`——那边是
网格视图，跟这里的表格是完全不同的形态，放在一起徒增混淆。
"""

from __future__ import annotations

#: 页脚。写清楚这份东西是什么、覆盖什么、以及它明确不是什么。
#: 最后一行不是免责套话，是这个工具的实际边界：它只做信息压缩。
COLOPHON_LINES = (
    "Taurient Lite · 由 Claude Code 每个交易日早晨自动生成",
    "覆盖范围：美股与宏观、科技与 AI 行业、影响能源与通胀的地缘事件",
    "涨跌色经过色觉障碍可辨度校验，方向箭头与带符号数值是颜色之外的编码",
    "这是新闻摘要，不是投资建议。数字以原始来源为准。",
)


def colophon() -> str:
    return f'<footer class="colophon">{"<br>".join(COLOPHON_LINES)}</footer>'
