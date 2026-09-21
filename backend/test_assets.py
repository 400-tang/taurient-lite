"""资源加载器：CSS 与 JS 从文件读，占位符必须替换干净。

这一层存在的理由是 f-string 与 JavaScript 打架——JS 的每个花括号在
f-string 里都要写两遍。搬进 .js 文件之后花括号可以原样写，代价是插值
不再由语言保证，所以这里守的就是那个代价：**漏替换必须炸，不能静默
把一个 ``__CANDLES__`` 字面量送进浏览器。**
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from backend import assets

JS_FILES = ("stock_chart.js", "account.js", "auth_bar.js")
CSS_FILES = ("stock_page.css", "account.css", "auth_bar.css", "account_shell.css")


class TestLoad(unittest.TestCase):
    def test_reads_a_real_file(self):
        self.assertIn(".stock", assets.load("stock_page.css"))

    def test_missing_file_raises(self):
        with self.assertRaises(assets.AssetError):
            assets.load("没有这个文件.css")

    def test_substitutes_placeholders(self):
        out = assets.load(
            "auth_bar.js", supabase_url='"u"', supabase_key='"k"'
        )
        self.assertIn('createClient("u", "k")', out)

    def test_unreplaced_placeholder_raises(self):
        """少传一个参数的表现会是浏览器里出现字面的 __SUPABASE_KEY__，
        图表画不出来而控制台报一个跟真实原因毫不相干的语法错。"""
        with self.assertRaises(assets.AssetError) as ctx:
            assets.load("auth_bar.js", supabase_url='"u"')
        self.assertIn("__SUPABASE_KEY__", str(ctx.exception))

    def test_error_names_what_was_passed(self):
        """报错要说清楚「这次传了什么」，否则得回去翻调用点才知道漏了哪个。"""
        with self.assertRaises(assets.AssetError) as ctx:
            assets.load("auth_bar.js")
        self.assertIn("空", str(ctx.exception))


class TestAssetFiles(unittest.TestCase):
    """文件本身的健康检查。"""

    def test_every_js_file_parses(self):
        """语法错误在服务端是看不见的——HTML 照样返回 200，只是脚本不跑。

        这正是把 JS 搬出 Python 字符串的目的：现在它能被真正的解析器检查。
        """
        node = subprocess.run(["node", "--version"], capture_output=True)
        if node.returncode != 0:
            self.skipTest("没有 node，跳过语法检查")
        for name in JS_FILES:
            with self.subTest(name):
                path = assets.ASSETS / name
                r = subprocess.run(["node", "--check", str(path)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[:400])

    def test_no_doubled_braces_left_over(self):
        """``{{`` 是 f-string 的遗留物。留在 .js 文件里是语法错误，
        而且说明搬家没搬干净。"""
        for name in JS_FILES:
            with self.subTest(name):
                self.assertNotIn("{{", (assets.ASSETS / name).read_text())

    def test_placeholders_are_all_known(self):
        """文件里出现的占位符必须都有人传值，否则永远加载不了。"""
        known = {"__SYMBOL__", "__CHART_LIB__", "__CANDLES__", "__VOLUMES__",
                 "__SUPABASE_URL__", "__SUPABASE_KEY__"}
        for name in JS_FILES + CSS_FILES:
            with self.subTest(name):
                found = set(assets.PLACEHOLDER.findall(
                    (assets.ASSETS / name).read_text()))
                self.assertLessEqual(found, known, f"{name} 里有未登记的占位符")

    def test_css_files_have_balanced_braces(self):
        for name in CSS_FILES:
            with self.subTest(name):
                text = (assets.ASSETS / name).read_text()
                self.assertEqual(text.count("{"), text.count("}"))

    def test_chart_height_does_not_depend_on_leftover_space(self):
        """图表高度必须是显式的，不能靠「吃掉剩余空间」算出来。

        **这条守的是一个已经发生过的静默退化。** ``.chart-wrap`` 原来写的是
        ``flex: 1 1 auto``——页面上只有图表和几个统计数字时，它确实撑满了
        一屏。后来加了简介、关键统计、分析师评级、财报、两块新闻，内容一
        超过一屏，「剩余空间」就变成 0，图表被压回 ``min-height`` 的底线，
        从 26rem 缩到 16rem。没有任何报错，页面照常渲染，只是越加内容图表
        越小，而谁都不会想到去怪那行 flex。

        所以判据是：``.chart-wrap`` 里必须出现一个显式的 ``height``。
        """
        css = (assets.ASSETS / "stock_page.css").read_text()
        block = re.search(r"\.chart-wrap\s*\{([^}]*)\}", css)
        self.assertIsNotNone(block, "找不到 .chart-wrap 规则")
        body = block.group(1)
        self.assertRegex(
            body, r"(?<!min-)(?<!max-)height:\s*\S",
            ".chart-wrap 没有显式高度，又会被下面的内容挤没",
        )


if __name__ == "__main__":
    unittest.main()
