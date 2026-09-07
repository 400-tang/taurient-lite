"""渲染流水线的编排层。

一次渲染就是四步：定位简报 → 解析并校验 → 渲染两种格式 → 写盘。
每一步都能单独测试，:func:`run` 只负责把它们串起来并收集结果。

流水线不做任何网络请求。取行情是 :mod:`taurient_lite.quotes` 的事，
且发生在渲染之前，写进简报 JSON。这样渲染永远是纯函数式的、可重放的：
同样的 JSON 一定得到同样的页面。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .html_renderer import render_html
from .markdown_renderer import render_markdown
from .schema import Brief, SchemaError


class PipelineError(RuntimeError):
    """流水线无法继续。消息面向命令行用户，直接打出来就能看懂。"""


@dataclass(frozen=True, slots=True)
class Paths:
    """一次运行涉及的所有路径。集中在这里，测试时整个换成临时目录。"""

    root: Path

    @property
    def briefs(self) -> Path:
        return self.root / "briefs"

    @property
    def site(self) -> Path:
        return self.root / "site"

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    def brief_json(self, date: str) -> Path:
        return self.briefs / f"{date}.json"

    def brief_md(self, date: str) -> Path:
        return self.briefs / f"{date}.md"

    @property
    def index_html(self) -> Path:
        return self.site / "index.html"


@dataclass(frozen=True, slots=True)
class Result:
    """一次渲染的产出，供 CLI 打印，也供集成测试断言。"""

    date: str
    html_path: Path
    markdown_path: Path
    html_bytes: int
    markdown_bytes: int
    item_count: int
    warnings: tuple[str, ...]


def latest_date(paths: Paths) -> str:
    """briefs 目录里最新的一份简报日期。

    文件名本身就是 ISO 日期，所以字典序等于时间序，直接排序即可。
    """
    found = sorted(p.stem for p in paths.briefs.glob("*.json"))
    if not found:
        raise PipelineError(f"{paths.briefs} 里没有任何简报 JSON")
    return found[-1]


def load_brief(paths: Paths, date: str) -> Brief:
    """读取并校验一份简报。

    这里把两类失败分开报：JSON 语法错和结构校验错，前者是文件坏了，
    后者是字段写错了，排查方向完全不同。
    """
    path = paths.brief_json(date)
    if not path.exists():
        raise PipelineError(f"找不到 {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineError(f"{path} 不是合法的 JSON：{exc}") from exc

    try:
        return Brief.from_dict(raw)
    except SchemaError as exc:
        raise PipelineError(f"{path} 结构校验没过：{exc}") from exc


def run(root: Path, date: str | None = None) -> Result:
    """跑完整条流水线。

    :param root: 项目根目录。
    :param date: ``YYYY-MM-DD``；省略则取最新的一份。
    """
    paths = Paths(root)
    config = Config.load(paths.config)

    target_date = date or latest_date(paths)
    brief = load_brief(paths, target_date)

    html = render_html(brief, config)
    markdown = render_markdown(brief, config)

    paths.site.mkdir(parents=True, exist_ok=True)
    paths.briefs.mkdir(parents=True, exist_ok=True)
    paths.index_html.write_text(html, encoding="utf-8")
    paths.brief_md(target_date).write_text(markdown, encoding="utf-8")

    warnings = brief.warnings(
        max_age_days=config.freshness.max_age_days,
        min_items=config.min_items,
    )

    return Result(
        date=target_date,
        html_path=paths.index_html,
        markdown_path=paths.brief_md(target_date),
        html_bytes=len(html.encode("utf-8")),
        markdown_bytes=len(markdown.encode("utf-8")),
        item_count=len(brief.items),
        warnings=tuple(warnings),
    )
