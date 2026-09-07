"""``config.json`` 的读取与校验。

配置和简报数据分开：简报是每天变的内容，配置是跨天稳定的策略参数
（覆盖范围、条数目标、时效上限、自选股、Artifact 链接）。

这里对缺失字段一律给可用的默认值而不是抛异常——配置文件被人手工编辑的
概率远高于简报 JSON，少一个字段就整条流水线跑不动是不划算的。真正非法的
值（比如 ``max_age_days`` 是负数）才会抛 :class:`ConfigError`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """``config.json`` 的内容非法。"""


@dataclass(frozen=True, slots=True)
class Freshness:
    """时效策略。"""

    max_age_days: int = 3
    must_read_max_age_days: int = 2
    week_ahead_max_age_days: int = 5

    @classmethod
    def from_dict(cls, data: Any) -> Freshness:
        data = data or {}
        if not isinstance(data, dict):
            raise ConfigError("freshness 应该是一个对象")

        def positive(key: str, default: int) -> int:
            value = data.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigError(f"freshness.{key} 应该是不小于 1 的整数，实际是 {value!r}")
            return value

        return cls(
            max_age_days=positive("max_age_days", 3),
            must_read_max_age_days=positive("must_read_max_age_days", 2),
            week_ahead_max_age_days=positive("week_ahead_max_age_days", 5),
        )


@dataclass(frozen=True, slots=True)
class Config:
    """整个工具的配置。"""

    artifact_url: str = ""
    timezone: str = "America/Los_Angeles"
    freshness: Freshness = field(default_factory=Freshness)
    mag7: tuple[str, ...] = ()
    watchlist: tuple[str, ...] = ()
    min_items: int = 15
    scope: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Any) -> Config:
        if not isinstance(data, dict):
            raise ConfigError("config.json 的根节点应该是一个对象")

        def symbols(raw: Any, where: str) -> tuple[str, ...]:
            if raw is None:
                return ()
            if not isinstance(raw, list):
                raise ConfigError(f"{where} 应该是数组")
            out = []
            for i, v in enumerate(raw):
                if not isinstance(v, str) or not v.strip():
                    raise ConfigError(f"{where}[{i}] 应该是非空字符串，实际是 {v!r}")
                out.append(v.strip().upper())
            return tuple(out)

        watchlist_raw = data.get("watchlist") or {}
        if not isinstance(watchlist_raw, dict):
            raise ConfigError("watchlist 应该是一个对象")

        targets = data.get("target_counts") or {}
        min_items = targets.get("total_min", 15) if isinstance(targets, dict) else 15
        if isinstance(min_items, bool) or not isinstance(min_items, int) or min_items < 1:
            raise ConfigError(
                f"target_counts.total_min 应该是不小于 1 的整数，实际是 {min_items!r}"
            )

        scope_raw = data.get("scope") or []
        if not isinstance(scope_raw, list):
            raise ConfigError("scope 应该是数组")

        return cls(
            artifact_url=str(data.get("artifact_url", "") or ""),
            timezone=str(data.get("timezone", "America/Los_Angeles") or "America/Los_Angeles"),
            freshness=Freshness.from_dict(data.get("freshness")),
            mag7=symbols(data.get("mag7"), "mag7"),
            watchlist=symbols(watchlist_raw.get("symbols"), "watchlist.symbols"),
            min_items=min_items,
            scope=tuple(str(s) for s in scope_raw),
        )

    @classmethod
    def load(cls, path: Path) -> Config:
        """从磁盘读取。文件不存在时退回全默认值，不抛异常。"""
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} 不是合法的 JSON：{exc}") from exc
        return cls.from_dict(raw)
