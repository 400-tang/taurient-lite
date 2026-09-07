"""Taurient Lite —— 盘前新闻简报的生成流水线。

分层是刻意的，依赖方向永远向下，没有环：

    schema      数据定义与校验，不依赖任何其他模块
    config      配置读取
    theme       设计 token 与样式表生成
    components  组件层，只依赖 schema 与 theme
    *_renderer  组装层，只依赖 components
    pipeline    编排层，读文件、调渲染、写文件
    quotes      行情抓取，独立于渲染，跑在渲染之前
    short_interest  FINRA 空头持仓抓取，研究/核实工具，不进渲染流程

这样任何一层都能单独测试：schema 不需要文件，components 不需要磁盘，
pipeline 换个临时目录就能端到端跑一遍。
"""

from .config import Config, ConfigError
from .pipeline import PipelineError, Paths, Result, run
from .schema import Brief, Item, SchemaError

__version__ = "2.0.0"

__all__ = [
    "Brief",
    "Config",
    "ConfigError",
    "Item",
    "Paths",
    "PipelineError",
    "Result",
    "SchemaError",
    "run",
    "__version__",
]
