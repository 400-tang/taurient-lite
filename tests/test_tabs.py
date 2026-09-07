"""标签页脚手架测试。

机制是隐藏的 radio + label，零 JavaScript，所以这里验证的是标记本身
是否具备这个机制要求的性质：id 与 for 对应、第一个默认选中、
以及退化成单标签页时不出现多余的标签栏。
"""

from __future__ import annotations

import unittest

from taurient_lite.components.tabs import tabs


class TestTabs(unittest.TestCase):
    def test_empty_panels_returns_empty_string(self):
        self.assertEqual(tabs([]), "")

    def test_single_panel_skips_the_tab_bar(self):
        html = tabs([("only", "唯一", "<p>内容</p>")])
        self.assertEqual(html, "<p>内容</p>")
        self.assertNotIn("tab-nav", html)

    def test_two_panels_render_both_bodies(self):
        html = tabs([("a", "A", "<p>甲</p>"), ("b", "B", "<p>乙</p>")])
        self.assertIn("<p>甲</p>", html)
        self.assertIn("<p>乙</p>", html)

    def test_first_panel_checked_by_default(self):
        """静止状态下必须完整可读：第一个标签页在没有任何交互时就是可见的。"""
        html = tabs([("a", "A", "x"), ("b", "B", "y")])
        self.assertIn('id="tab-a" class="tab-input" checked', html)
        self.assertNotIn('id="tab-b" class="tab-input" checked', html)

    def test_label_for_matches_input_id(self):
        html = tabs([("brief", "简报", "x"), ("calendar", "日历", "y")])
        self.assertIn('for="tab-brief"', html)
        self.assertIn('for="tab-calendar"', html)
        self.assertIn('id="tab-brief"', html)
        self.assertIn('id="tab-calendar"', html)

    def test_panel_data_attribute_matches_slug(self):
        html = tabs([("brief", "简报", "x"), ("calendar", "日历", "y")])
        self.assertIn('data-tab="brief"', html)
        self.assertIn('data-tab="calendar"', html)

    def test_labels_are_escaped(self):
        html = tabs([("a", "<script>", "x"), ("b", "B", "y")])
        self.assertNotIn("<script>", html)


if __name__ == "__main__":
    unittest.main()
