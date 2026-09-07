"""组件层共用的 HTML 拼装原语。

所有组件都返回字符串片段，由 :mod:`taurient_lite.html_renderer` 拼成整页。
选择字符串拼装而不是模板引擎，是为了零依赖：这套东西每天要在一个干净的
云端容器里跑，少一个 pip install 就少一处可能失败的地方。

安全性上只有一条铁律：**任何来自 JSON 的文本都必须经过 :func:`esc`**。
简报内容来自网页搜索结果，属于不可信输入，未转义直接拼进 HTML 就是注入。
组件里凡是拼接变量的地方都走 :func:`esc` 或 :func:`attr`。
"""

from __future__ import annotations

import html
from typing import Iterable


def esc(value: object) -> str:
    """转义成可安全放进 HTML 文本节点或属性值的字符串。

    ``quote=True`` 会一并转义单双引号，所以同一个函数既能用于文本也能用于属性。
    """
    return html.escape(str(value), quote=True)


def attr(name: str, value: object | None) -> str:
    """渲染一个 HTML 属性，值为 ``None`` 或空串时整个属性省略。

    这样调用方不用为「有没有这个属性」写分支。
    """
    if value is None or value == "":
        return ""
    return f' {name}="{esc(value)}"'


def classes(*names: str | None) -> str:
    """把若干可选类名拼成 ``class="..."``，全为空时返回空串。"""
    kept = [n for n in names if n]
    return f' class="{esc(" ".join(kept))}"' if kept else ""


def join(parts: Iterable[str]) -> str:
    """拼接片段，自动丢掉空串，避免产出成片的空行。"""
    return "\n".join(p for p in parts if p)


def section_head(
    title: str,
    *,
    tier_class: str = "t2",
    count: int | None = None,
    asof: str = "",
) -> str:
    """统一的板块标题。整页所有分节都走这一个函数，保证形态一致。"""
    bits = [f'<div class="sec-head {esc(tier_class)}">', f'<h2 class="label">{esc(title)}</h2>']
    if count is not None:
        bits.append(f'<span class="n">{count}</span>')
    if asof:
        bits.append(f'<span class="asof">{esc(asof)}</span>')
    bits.append("</div>")
    return "".join(bits)
