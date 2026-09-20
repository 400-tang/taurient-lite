"""矩形树图布局（squarified treemap）。纯几何计算，不碰 HTML 也不碰数据。

把一组权重铺满一个矩形，每块面积正比于权重，且尽量接近正方形。
算法是 Bruls / Huizing / van Wijk 1999 的 squarified 版本：贪心地往当前
行里加块，一旦「最差长宽比」开始变坏就收行，换到剩余矩形的另一条边继续。

**为什么不用简单的横条或网格。** 横条布局在权重差距大时会产出极扁的
长条——一个市值 4 万亿的块和一个 200 亿的块并排，后者会细到放不下代码。
squarified 的全部意义就是让每块都接近正方形，文字才放得进去。

**为什么自己写而不是用图表库。** 整个包零第三方依赖，而这个算法
连同注释不到 100 行。引入 plotly/d3 要付出的是整条流水线的运行环境。

坐标系：调用方给一个 ``box_w`` × ``box_h`` 的虚拟画布（用容器的真实
长宽比，比如 100×62），返回的矩形已经换算成**百分比**，可以直接写进
``style="left:..%"``。不换算的话，在一个 16:9 的容器里按正方形算出来的
「正方形」会被拉成横的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class Rect:
    """一块矩形，四个值都是相对容器的百分比。"""

    left: float
    top: float
    width: float
    height: float

    def style(self, *, gap: float = 0.0) -> str:
        """拼成 CSS 内联样式。

        ``gap`` 是块与块之间留的缝（百分比），从宽高里扣掉而不是用
        margin——绝对定位下 margin 会把块推出原位，缝就不均匀了。
        """
        w = max(self.width - gap, 0.0)
        h = max(self.height - gap, 0.0)
        return (
            f"left:{self.left:.4f}%;top:{self.top:.4f}%;"
            f"width:{w:.4f}%;height:{h:.4f}%"
        )


def _worst(row: Sequence[float], side: float) -> float:
    """一行里最差的长宽比。越小说明这一行越接近一排正方形。

    公式来自原论文：行内面积和为 s、最大块 rmax、最小块 rmin、行宽 side，
    则最差比例是 ``max(side²·rmax/s², s²/(side²·rmin))``。
    """
    if not row or side <= 0:
        return float("inf")
    s = sum(row)
    if s <= 0:
        return float("inf")
    rmax, rmin = max(row), min(row)
    if rmin <= 0:
        return float("inf")
    return max(side * side * rmax / (s * s), s * s / (side * side * rmin))


def squarify(
    weights: Sequence[float],
    *,
    box_w: float = 100.0,
    box_h: float = 100.0,
) -> list[Rect]:
    """把 ``weights`` 铺满画布，返回与输入一一对应的矩形列表。

    **输入必须按权重从大到小排好序**，这是算法本身的前提：从最大的块
    开始铺，长宽比才收敛。调用方排序而不是这里排，是因为调用方还要按
    同样的顺序拿回矩形去配数据，在这里排会把对应关系弄丢。

    权重里的 0 和负数会被跳过（返回零面积矩形占位），保证返回长度等于
    输入长度——少返回一个，调用方 zip 的时候就会静默错位。
    """
    n = len(weights)
    out: list[Rect | None] = [None] * n

    live = [(i, float(w)) for i, w in enumerate(weights) if w and w > 0]
    for i, _ in ((i, w) for i, w in enumerate(weights) if not (w and w > 0)):
        out[i] = Rect(0.0, 0.0, 0.0, 0.0)

    if not live or box_w <= 0 or box_h <= 0:
        return [r or Rect(0.0, 0.0, 0.0, 0.0) for r in out]

    total = sum(w for _, w in live)
    scale = (box_w * box_h) / total
    areas = [(i, w * scale) for i, w in live]

    x, y, dx, dy = 0.0, 0.0, box_w, box_h
    cursor = 0

    while cursor < len(areas):
        side = min(dx, dy)
        row: list[tuple[int, float]] = [areas[cursor]]
        cursor += 1
        # 贪心：能让长宽比继续变好就继续加，一变坏立刻收行。
        while cursor < len(areas):
            trial = [a for _, a in row] + [areas[cursor][1]]
            if _worst(trial, side) > _worst([a for _, a in row], side):
                break
            row.append(areas[cursor])
            cursor += 1

        row_sum = sum(a for _, a in row)
        if dx >= dy:
            # 剩余空间偏横，这一行竖着贴在左边。
            w = row_sum / dy if dy > 0 else 0.0
            oy = y
            for idx, a in row:
                h = a / w if w > 0 else 0.0
                out[idx] = Rect(x / box_w * 100, oy / box_h * 100,
                                w / box_w * 100, h / box_h * 100)
                oy += h
            x += w
            dx -= w
        else:
            # 剩余空间偏竖，这一行横着贴在顶上。
            h = row_sum / dx if dx > 0 else 0.0
            ox = x
            for idx, a in row:
                w = a / h if h > 0 else 0.0
                out[idx] = Rect(ox / box_w * 100, y / box_h * 100,
                                w / box_w * 100, h / box_h * 100)
                ox += w
            y += h
            dy -= h

    return [r or Rect(0.0, 0.0, 0.0, 0.0) for r in out]
