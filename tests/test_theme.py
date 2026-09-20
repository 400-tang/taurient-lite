"""主题层测试。

这里守的是 Artifact 页面最经典的一个崩法：**某个颜色只在媒体查询里定义**。
读者用「跟随系统」且系统是亮色时，那个变量根本不存在，页面会拿一个主题的
文字画在另一个主题的底色上。所以这套测试逐个 token 断言三个块都完整。
"""

from __future__ import annotations

import re
import unittest

from taurient_lite.theme import (
    TOKENS,
    TYPE_SCALE,
    build_css,
    build_palette_css,
)


class TestPalette(unittest.TestCase):
    def setUp(self):
        self.css = build_palette_css()

    def test_every_token_declared_in_bare_root(self):
        """裸 :root 必须声明全部 token，一个都不能少。"""
        bare = self.css.split("@media", 1)[0]
        for name in TOKENS:
            self.assertIn(f"--{name}:", bare, f"--{name} 没有在裸 :root 里声明")

    def test_every_token_redefined_in_dark_media(self):
        media = self.css.split("@media", 1)[1].split(':root[data-theme="dark"]', 1)[0]
        for name in TOKENS:
            self.assertIn(f"--{name}:", media, f"--{name} 在暗色媒体查询里缺失")

    def test_every_token_redefined_in_dark_stamp(self):
        stamp = self.css.split(':root[data-theme="dark"]', 1)[1]
        for name in TOKENS:
            self.assertIn(f"--{name}:", stamp, f"--{name} 在 data-theme=dark 块里缺失")

    def test_dark_media_guarded_against_explicit_light(self):
        """显式选亮色的读者不该被系统的暗色设置盖掉。"""
        self.assertIn(':root:not([data-theme="light"])', self.css)

    def test_dark_stamp_comes_after_media_query(self):
        """顺序即优先级：显式选择必须写在媒体查询之后才能赢。"""
        self.assertLess(
            self.css.index("@media (prefers-color-scheme: dark)"),
            self.css.index(':root[data-theme="dark"]'),
        )

    def test_all_colors_are_valid_hex(self):
        for name, (light, dark) in TOKENS.items():
            for value in (light, dark):
                self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$", f"--{name} 的 {value} 不是合法色值")

    def test_light_and_dark_differ_for_every_token(self):
        """两套主题完全相同的 token 说明漏改了。

        热力色阶一度是这条规则的例外（当时它是一块不跟随主题的深色行情板），
        现在它也跟着主题走，例外随之取消——整份 TOKENS 重新没有一个豁免。
        """
        for name, (light, dark) in TOKENS.items():
            self.assertNotEqual(light.lower(), dark.lower(), f"--{name} 两套主题取值相同")

    def test_semantic_colors_separate_from_accent(self):
        """涨跌语义色绝不能与品牌色重合，否则语义就被污染了。"""
        accent = {v.lower() for v in TOKENS["accent"]}
        for name in ("up", "down"):
            self.assertFalse(accent & {v.lower() for v in TOKENS[name]})


class TestFullStylesheet(unittest.TestCase):
    def setUp(self):
        self.css = build_css()

    def test_body_paints_its_own_background(self):
        """透明的 body 会借用宿主的底色，两套主题就串了。"""
        self.assertRegex(self.css, r"body\s*\{[^}]*background:\s*var\(--paper\)")

    def test_braces_balanced(self):
        self.assertEqual(self.css.count("{"), self.css.count("}"))

    def test_every_var_reference_has_a_definition(self):
        """引用了却没定义的变量会静默失效，这是最难查的一类样式 bug。"""
        referenced = set(re.findall(r"var\(--([a-z0-9-]+)\)", self.css))
        defined = set(re.findall(r"--([a-z0-9-]+):", self.css))
        self.assertEqual(referenced - defined, set())

    def test_reduced_motion_honoured(self):
        self.assertIn("prefers-reduced-motion: reduce", self.css)

    def test_type_scale_tokens_all_used_or_declared(self):
        for name in TYPE_SCALE:
            self.assertIn(f"--{name}:", self.css)

    def test_focus_visible_styled(self):
        """键盘用户必须看得见焦点。"""
        self.assertIn("focus-visible", self.css)


if __name__ == "__main__":
    unittest.main()
