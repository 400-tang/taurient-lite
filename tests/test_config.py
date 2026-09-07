"""config 层测试。

配置文件被人手工编辑的概率远高于简报 JSON，所以策略是：**缺字段给默认值，
错值才抛异常**。少一个字段就整条流水线跑不动是不划算的。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from taurient_lite.config import Config, ConfigError, Freshness, Supabase

from . import fixtures as F


class TestFreshness(unittest.TestCase):
    def test_defaults(self):
        f = Freshness.from_dict(None)
        self.assertEqual(f.max_age_days, 3)
        self.assertEqual(f.must_read_max_age_days, 2)
        self.assertEqual(f.week_ahead_max_age_days, 5)

    def test_partial_override(self):
        f = Freshness.from_dict({"max_age_days": 7})
        self.assertEqual(f.max_age_days, 7)
        self.assertEqual(f.must_read_max_age_days, 2)

    def test_zero_rejected(self):
        with self.assertRaises(ConfigError):
            Freshness.from_dict({"max_age_days": 0})

    def test_negative_rejected(self):
        with self.assertRaises(ConfigError):
            Freshness.from_dict({"max_age_days": -1})

    def test_bool_rejected(self):
        with self.assertRaises(ConfigError):
            Freshness.from_dict({"max_age_days": True})

    def test_non_object_rejected(self):
        with self.assertRaises(ConfigError):
            Freshness.from_dict(["nope"])


class TestSupabase(unittest.TestCase):
    def test_defaults_to_unconfigured(self):
        cfg = Supabase.from_dict(None)
        self.assertEqual(cfg.url, "")
        self.assertFalse(cfg.configured)

    def test_configured_when_both_present(self):
        cfg = Supabase.from_dict({"url": "https://x.supabase.co", "anon_key": "eyJ..."})
        self.assertTrue(cfg.configured)

    def test_not_configured_when_only_one_present(self):
        """半配置状态视为未配置，不该渲染一个必然报错的登录框。"""
        cfg = Supabase.from_dict({"url": "https://x.supabase.co"})
        self.assertFalse(cfg.configured)

    def test_non_object_rejected(self):
        with self.assertRaises(ConfigError):
            Supabase.from_dict(["nope"])


class TestConfig(unittest.TestCase):
    def test_parses_full_config(self):
        cfg = Config.from_dict(F.make_config())
        self.assertEqual(cfg.mag7, ("NVDA", "TSLA"))
        self.assertEqual(cfg.watchlist, ("SPY", "NVDA"))
        self.assertEqual(cfg.min_items, 2)

    def test_symbols_normalised_to_upper(self):
        cfg = Config.from_dict(F.make_config(watchlist={"symbols": [" nvda ", "tsla"]}))
        self.assertEqual(cfg.watchlist, ("NVDA", "TSLA"))

    def test_empty_config_uses_defaults(self):
        cfg = Config.from_dict({})
        self.assertEqual(cfg.watchlist, ())
        self.assertEqual(cfg.min_items, 15)
        self.assertEqual(cfg.freshness.max_age_days, 3)
        self.assertFalse(cfg.supabase.configured)

    def test_supabase_block_wired_through(self):
        cfg = Config.from_dict(
            F.make_config(supabase={"url": "https://x.supabase.co", "anon_key": "eyJ..."})
        )
        self.assertTrue(cfg.supabase.configured)
        self.assertEqual(cfg.supabase.url, "https://x.supabase.co")

    def test_blank_symbol_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            Config.from_dict(F.make_config(watchlist={"symbols": ["NVDA", "  "]}))
        self.assertIn("watchlist.symbols[1]", str(ctx.exception))

    def test_symbols_must_be_list(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(F.make_config(mag7="NVDA"))

    def test_watchlist_must_be_object(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(F.make_config(watchlist=["NVDA"]))

    def test_bad_total_min_rejected(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(F.make_config(target_counts={"total_min": 0}))

    def test_root_must_be_object(self):
        with self.assertRaises(ConfigError):
            Config.from_dict([1, 2])


class TestConfigLoad(unittest.TestCase):
    def test_missing_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config.load(Path(tmp) / "nope.json")
            self.assertEqual(cfg.min_items, 15)

    def test_reads_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(F.make_config()), encoding="utf-8")
            self.assertEqual(Config.load(path).mag7, ("NVDA", "TSLA"))

    def test_malformed_json_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                Config.load(path)
            self.assertIn("config.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
