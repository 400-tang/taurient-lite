"""端到端集成测试。

每个用例在临时目录里搭一个完整的项目（config.json + briefs/），
跑真实的 :func:`taurient_lite.pipeline.run`，然后检查落盘的文件。
不打桩、不 mock 文件系统，跑的就是生产路径。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from taurient_lite.pipeline import Paths, PipelineError, latest_date, load_brief, run

from . import fixtures as F


class ProjectCase(unittest.TestCase):
    """在临时目录里搭一个可运行的项目。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "briefs").mkdir()
        self.write_config()

    def tearDown(self):
        self._tmp.cleanup()

    def write_config(self, **over):
        (self.root / "config.json").write_text(
            json.dumps(F.make_config(**over), ensure_ascii=False), encoding="utf-8"
        )

    def write_brief(self, date="2026-09-06", raw=None, **over):
        payload = raw if raw is not None else F.make_brief(date=date, **over)
        path = self.root / "briefs" / f"{date}.json"
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


class TestHappyPath(ProjectCase):
    def test_produces_both_outputs(self):
        self.write_brief()
        result = run(self.root)

        self.assertEqual(result.date, "2026-09-06")
        self.assertTrue(result.html_path.exists())
        self.assertTrue(result.markdown_path.exists())
        self.assertEqual(result.item_count, 2)
        self.assertGreater(result.html_bytes, 5000)

    def test_html_contains_every_section(self):
        self.write_brief()
        run(self.root)
        html = (self.root / "site" / "index.html").read_text(encoding="utf-8")
        for marker in (
            "<title>Morning Tape</title>",
            "七巨头单日涨跌",
            "自选股",
            "指数与利率",
            "必读",
            "资产波及矩阵",
            "接下来的日历",
            "cal-grid",
        ):
            self.assertIn(marker, html)

    def test_markdown_written_next_to_source(self):
        self.write_brief()
        run(self.root)
        md = (self.root / "briefs" / "2026-09-06.md").read_text(encoding="utf-8")
        self.assertIn("# Morning Tape — 2026-09-06", md)

    def test_site_directory_created_if_missing(self):
        self.write_brief()
        self.assertFalse((self.root / "site").exists())
        run(self.root)
        self.assertTrue((self.root / "site").is_dir())

    def test_explicit_date_argument(self):
        self.write_brief("2026-09-04")
        self.write_brief("2026-09-06")
        self.assertEqual(run(self.root, "2026-09-04").date, "2026-09-04")

    def test_defaults_to_latest(self):
        self.write_brief("2026-09-04")
        self.write_brief("2026-09-06")
        self.assertEqual(run(self.root).date, "2026-09-06")

    def test_rendering_is_deterministic(self):
        """同样的输入必须得到逐字节相同的输出，否则每天的 diff 全是噪音。"""
        self.write_brief()
        run(self.root)
        first = (self.root / "site" / "index.html").read_bytes()
        run(self.root)
        self.assertEqual(first, (self.root / "site" / "index.html").read_bytes())


class TestWarnings(ProjectCase):
    def test_clean_brief_has_no_warnings(self):
        self.write_brief(max_age_days=9)
        self.assertEqual(run(self.root).warnings, ())

    def test_stale_items_warned_but_still_rendered(self):
        self.write_config(freshness={"max_age_days": 1})
        self.write_brief()
        result = run(self.root)
        self.assertTrue(any("时效上限" in w for w in result.warnings))
        self.assertTrue(result.html_path.exists())

    def test_min_items_warning_from_config(self):
        self.write_config(target_counts={"total_min": 15})
        self.write_brief(max_age_days=9)
        result = run(self.root)
        self.assertTrue(any("低于 15 条" in w for w in result.warnings))


class TestFailureModes(ProjectCase):
    def test_missing_brief_file(self):
        self.write_brief("2026-09-06")
        with self.assertRaises(PipelineError) as ctx:
            run(self.root, "2026-01-01")
        self.assertIn("找不到", str(ctx.exception))

    def test_no_briefs_at_all(self):
        with self.assertRaises(PipelineError) as ctx:
            run(self.root)
        self.assertIn("没有任何简报", str(ctx.exception))

    def test_malformed_json(self):
        self.write_brief(raw="{ this is not json")
        with self.assertRaises(PipelineError) as ctx:
            run(self.root)
        self.assertIn("不是合法的 JSON", str(ctx.exception))

    def test_schema_violation_reports_field_path(self):
        bad = F.make_brief()
        bad["items"][0]["tier"] = "urgent"
        self.write_brief(raw=bad)
        with self.assertRaises(PipelineError) as ctx:
            run(self.root)
        message = str(ctx.exception)
        self.assertIn("结构校验没过", message)
        self.assertIn("items[0].tier", message)

    def test_nothing_written_when_validation_fails(self):
        """校验失败时不能留下半张页面覆盖掉昨天的成果。"""
        bad = F.make_brief()
        del bad["thesis"]
        self.write_brief(raw=bad)
        with self.assertRaises(PipelineError):
            run(self.root)
        self.assertFalse((self.root / "site" / "index.html").exists())

    def test_missing_config_falls_back_to_defaults(self):
        (self.root / "config.json").unlink()
        self.write_brief()
        result = run(self.root)
        self.assertTrue(result.html_path.exists())
        # 没有自选股配置，面板整块省掉。注意不能断言整页不含 "wl-chip"：
        # 样式表里本来就有这个类的定义，要看的是板块标题有没有渲染出来。
        html = result.html_path.read_text(encoding="utf-8")
        self.assertNotIn('<h2 class="label">自选股</h2>', html)


class TestPathsAndHelpers(ProjectCase):
    def test_paths_are_derived_from_root(self):
        paths = Paths(self.root)
        self.assertEqual(paths.brief_json("2026-09-06").name, "2026-09-06.json")
        self.assertEqual(paths.brief_md("2026-09-06").name, "2026-09-06.md")
        self.assertEqual(paths.index_html.parent.name, "site")

    def test_latest_date_uses_iso_ordering(self):
        for date in ("2026-09-04", "2026-10-01", "2026-09-30"):
            self.write_brief(date)
        self.assertEqual(latest_date(Paths(self.root)), "2026-10-01")

    def test_load_brief_returns_parsed_object(self):
        self.write_brief()
        brief = load_brief(Paths(self.root), "2026-09-06")
        self.assertEqual(len(brief.items), 2)


class TestUnicodeAndEdgeContent(ProjectCase):
    def test_cjk_and_emoji_survive_round_trip(self):
        data = F.make_brief()
        data["items"][0]["headline"] = "联储转向：加息定价升到 68% 📈"
        self.write_brief(raw=data)
        run(self.root)
        html = (self.root / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn("加息定价升到 68% 📈", html)

    def test_very_long_headline_is_not_truncated(self):
        long_headline = "非常长的标题" * 40
        data = F.make_brief()
        data["items"][0]["headline"] = long_headline
        self.write_brief(raw=data)
        run(self.root)
        html = (self.root / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn(long_headline, html)

    def test_single_item_brief_renders(self):
        data = F.make_brief(items=[F.make_item()])
        self.write_brief(raw=data)
        result = run(self.root)
        self.assertEqual(result.item_count, 1)

    def test_all_items_in_one_tier(self):
        data = F.make_brief(
            items=[
                F.make_item(rank=1, tier="noise"),
                F.make_item(rank=2, tier="noise", headline="第二条"),
            ]
        )
        self.write_brief(raw=data)
        run(self.root)
        html = (self.root / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn("背景噪音", html)
        self.assertNotIn(">必读<", html)


if __name__ == "__main__":
    unittest.main()
