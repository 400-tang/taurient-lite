"""两个标签页之间切换的通用脚手架。

用隐藏的 radio input 加 label 实现，不引入任何 JavaScript：Artifact 的 CSP
不允许内联事件处理器之外的随意脚本来源，而这个交互本质上就是「选一个」，
原生表单控件正好胜任。好处还有键盘可达性是免费的——方向键在同组
radio 间切换是浏览器原生行为，不需要额外写 ARIA 或事件监听。

用法：``tabs([("brief", "简报", brief_html), ("calendar", "日历", calendar_html)])``。
第一个标签页默认选中，对应静止状态下页面必须完整可读的要求。
"""

from __future__ import annotations

from .base import esc, join


def tabs(panels: list[tuple[str, str, str]]) -> str:
    """渲染一组标签页。

    :param panels: ``(slug, label, html)`` 三元组的列表。``slug`` 参与
        radio 的 id，必须在页面内唯一（目前只有两个标签页，天然满足）。
    """
    if not panels:
        return ""
    if len(panels) == 1:
        # 只有一个标签页时，标签栏本身没有意义，直接出内容。
        return panels[0][2]

    inputs = []
    nav = ['<div class="tab-nav" role="tablist">']
    bodies = []

    for i, (slug, label, html) in enumerate(panels):
        checked = " checked" if i == 0 else ""
        inputs.append(
            f'<input type="radio" name="tab" id="tab-{esc(slug)}" '
            f'class="tab-input"{checked}>'
        )
        nav.append(f'<label class="tab-label" for="tab-{esc(slug)}">{esc(label)}</label>')
        bodies.append(f'<div class="tab-panel" data-tab="{esc(slug)}">{html}</div>')

    nav.append("</div>")

    return join(["".join(inputs), "".join(nav), join(bodies)])
