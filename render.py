#!/usr/bin/env python3
"""命令行入口：把简报 JSON 渲染成网页与 Markdown 存档。

    python3 render.py 2026-09-06     # 指定日期
    python3 render.py                # 最新的一份

真正的逻辑全在 ``taurient_lite`` 包里，这里只负责解析参数、打印结果、
把异常翻译成人能看懂的退出信息。业务逻辑不写在 CLI 里，是为了让整条
流水线可以被测试直接调用，不必去解析命令行输出。

退出码：0 成功；1 失败（找不到文件、JSON 坏了、结构校验没过）。
质量警告不影响退出码——简报成色不够不是渲染失败。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从任意工作目录调用：把脚本所在目录加进搜索路径。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from taurient_lite import PipelineError, run  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    date = argv[1] if len(argv) > 1 else None

    try:
        result = run(ROOT, date)
    except PipelineError as exc:
        print(f"渲染失败：{exc}", file=sys.stderr)
        return 1

    print(f"HTML  -> {result.html_path}  ({result.html_bytes:,} bytes)")
    print(f"MD    -> {result.markdown_path}  ({result.markdown_bytes:,} bytes)")
    print(f"条目  -> {result.item_count} 条")

    for warning in result.warnings:
        print(f"提醒  -> {warning}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
