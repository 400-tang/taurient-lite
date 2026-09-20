"""把 CSS 与 JavaScript 从 Python 字符串里搬出来，放进真正的 .css / .js 文件。

**搬家的理由是 f-string 与 JavaScript 打架。** 之前这些脚本写在 f-string
里，于是 JS 的每一个花括号都要写成两个：

    function renderTrends() {{
      trends.forEach(function (t, i) {{

代价不只是难看。没有语法高亮、没有补全、没有类型检查，写的时候编辑器
帮不上忙，只能等跑到浏览器里才发现问题——今天三个 bug 都是这么抓到的。
现在 .js 文件就是 .js 文件，``node --check`` 和编辑器都认。

**插值改用命名占位符，不用 f-string。** ``__SYMBOL__`` 这种形式不会和
JS 语法冲突，所以花括号可以原样写。代价是替换不再由语言保证——所以
:func:`load` 在替换完成后会检查有没有漏网的占位符，漏了直接抛异常，
而不是把一个 ``__CANDLES__`` 字面量送进浏览器。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"

#: 占位符长这样：两条下划线夹住全大写的名字。
PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")


class AssetError(RuntimeError):
    """资源文件缺失，或者占位符没替换干净。"""


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    path = ASSETS / name
    if not path.is_file():
        raise AssetError(f"资源文件不存在：{path}")
    return path.read_text(encoding="utf-8")


def load(name: str, **subs: str) -> str:
    """读一份资源，把 ``__NAME__`` 占位符换成给定的值。

    **替换完还留着占位符就抛异常。** 少传一个参数、或者把名字拼错，
    表现会是浏览器里出现一个字面的 ``__CANDLES__``——图表画不出来，
    控制台报一个跟真实原因毫不相干的语法错。宁可在服务端就炸掉。
    """
    text = _read(name)
    for key, value in subs.items():
        text = text.replace(f"__{key.upper()}__", value)

    missing = sorted(set(PLACEHOLDER.findall(text)))
    if missing:
        raise AssetError(
            f"{name} 里还有没替换的占位符：{'、'.join(missing)}"
            f"（这次传进来的是：{'、'.join(sorted(subs)) or '（空）'}）"
        )
    return text


def style(name: str, **subs: str) -> str:
    """样式表，包进 ``<style>``。"""
    return f"<style>{load(name, **subs)}</style>"


def script(name: str, **subs: str) -> str:
    """脚本，包进 ``<script>``。"""
    return f"<script>{load(name, **subs)}</script>"
