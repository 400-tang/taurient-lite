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
class Supabase:
    """账号与个人自选股用的 Supabase 项目凭据。

    ``anon_key`` 是设计成可以公开的那把钥匙——真正挡住别人读写他人数据的
    是 Supabase 那边的行级安全策略，不是这把钥匙保不保密。两个字段留空
    时（默认值）表示没配置账号功能，backend 那边看到空值就不渲染登录面板。
    """

    url: str = ""
    anon_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.url and self.anon_key)

    @classmethod
    def from_dict(cls, data: Any) -> Supabase:
        data = data or {}
        if not isinstance(data, dict):
            raise ConfigError("supabase 应该是一个对象")
        return cls(
            url=str(data.get("url", "") or ""),
            anon_key=str(data.get("anon_key", "") or ""),
        )


@dataclass(frozen=True, slots=True)
class Config:
    """整个工具的配置。"""

    artifact_url: str = ""
    #: 部署在 Render 上的后端地址。云端定时任务所在的沙箱网络出口是
    #: 「仅包管理器」模式，直连 Yahoo、FINRA 这些第三方接口会被网关
    #: 403 拒绝；而 Render 是普通云主机，外网不受限。所以后端在这里
    #: 承担取数代理的角色：直连失败时改从它拿。留空则不启用这个回退。
    backend_url: str = ""
    timezone: str = "America/Los_Angeles"
    freshness: Freshness = field(default_factory=Freshness)
    mag7: tuple[str, ...] = ()
    watchlist: tuple[str, ...] = ()
    #: 基本面标签页扫哪些代码。留空就用自选股——但两者分开设是有理由的：
    #: 自选股决定每天**新闻**额外查谁，基本面要的是你想**比较**的一组，
    #: 常常包括不在自选股里的同业（看 NVDA 就想顺带看 TSM、AMD）。
    fundamentals: tuple[str, ...] = ()
    min_items: int = 15
    scope: tuple[str, ...] = ()
    supabase: Supabase = field(default_factory=Supabase)

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

        fundamentals_raw = data.get("fundamentals") or {}
        if not isinstance(fundamentals_raw, dict):
            raise ConfigError("fundamentals 应该是一个对象")

        return cls(
            artifact_url=str(data.get("artifact_url", "") or ""),
            backend_url=str(data.get("backend_url", "") or ""),
            timezone=str(data.get("timezone", "America/Los_Angeles") or "America/Los_Angeles"),
            freshness=Freshness.from_dict(data.get("freshness")),
            mag7=symbols(data.get("mag7"), "mag7"),
            watchlist=symbols(watchlist_raw.get("symbols"), "watchlist.symbols"),
            fundamentals=symbols(fundamentals_raw.get("symbols"), "fundamentals.symbols"),
            min_items=min_items,
            scope=tuple(str(s) for s in scope_raw),
            supabase=Supabase.from_dict(data.get("supabase")),
        )

    @property
    def fundamentals_symbols(self) -> tuple[str, ...]:
        """基本面扫描名单：显式配置优先，没配就退回自选股。"""
        return self.fundamentals or self.watchlist

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
