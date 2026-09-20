"""简报页右上角的账号条。

登录表单搬到 ``/account`` 之后，这一层只剩三件事：右上角按钮的状态、
自选股高亮、以及「只看跟我相关」的过滤。**后两件必须留在简报页**，
因为它们作用的对象就是这一页的新闻列表。

这里的用例有一半是从 ``test_auth_panel`` 搬过来的——逻辑搬了家，
守着它的断言也得跟着搬，不能因为原地跑不过就删掉。
"""

from __future__ import annotations

import unittest

from backend.auth_bar import render
from taurient_lite.config import Supabase

CONFIGURED = Supabase(url="https://demo.supabase.co", anon_key="anon-key-123")
UNCONFIGURED = Supabase(url="", anon_key="")


class TestGating(unittest.TestCase):
    def test_no_config_renders_nothing(self):
        """没配 Supabase 就不该在页面上出现一个点了没反应的按钮。"""
        self.assertEqual(render(UNCONFIGURED), "")

    def test_half_config_renders_nothing(self):
        self.assertEqual(render(Supabase(url="https://x.supabase.co")), "")

    def test_configured_renders_something(self):
        self.assertTrue(render(CONFIGURED))


class TestMarkup(unittest.TestCase):
    def setUp(self):
        self.html = render(CONFIGURED)

    def test_login_entry_is_a_link_to_the_account_page(self):
        """登录入口是一个跳转链接，不是就地展开的表单——这正是这次改动的全部意义。"""
        self.assertIn('id="tl-account-link"', self.html)
        self.assertIn('href="/account"', self.html)

    def test_no_login_form_on_the_brief_page(self):
        """Google 登录按钮、退出、自选股增删都不该再出现在简报页上。"""
        for gone in ('id="tl-google-btn"', 'id="tl-logout"',
                     'id="tl-add-form"', 'id="tl-suggest"'):
            self.assertNotIn(gone, self.html, gone)

    def test_filter_controls_stay_here(self):
        """过滤开关切的是这一页的条目，搬走就失去了对象。"""
        self.assertIn('id="tl-filter-toggle"', self.html)
        self.assertIn('id="tl-match-status"', self.html)

    def test_credentials_are_embedded_safely(self):
        self.assertIn('"https://demo.supabase.co"', self.html)
        self.assertIn('"anon-key-123"', self.html)


class TestScriptLogic(unittest.TestCase):
    def setUp(self):
        self.html = render(CONFIGURED)

    def test_filter_never_hides_macro_items(self):
        """没有 data-tickers 的条目是宏观新闻（联储、地缘、油价），
        不属于任何个股却往往最重要。第一版把它们也一并隐藏，结果
        18 条里 10 条属于这类，一开筛选整页就空了。选择器必须带上
        [data-tickers]，让没有代码的条目根本不进入隐藏范围。
        """
        self.assertIn(
            "body.tl-filtering .item[data-tickers]:not(.tl-mine)", self.html
        )
        # 不能存在那条不加限定的旧规则
        self.assertNotIn("body.tl-filtering .item:not(.tl-mine)", self.html)

    def test_reports_match_count(self):
        """筛选之后必须说明结果，不能让用户对着空页面猜是不是坏了。"""
        self.assertIn('id="tl-match-status"', self.html)
        self.assertIn("setMatchStatus", self.html)

    def test_lists_available_tickers_when_nothing_matches(self):
        """一条都没匹配上时，告诉用户今天的简报覆盖了哪些代码，
        他才知道该加什么，而不是反复试。"""
        self.assertIn("function availableTickers", self.html)

    def test_highlight_class_is_applied_to_items(self):
        self.assertIn("tl-mine", self.html)
        self.assertIn("data-tickers", self.html)

    def test_single_auth_listener(self):
        """supabase-js 挂上监听器那一刻就会用当前会话触发一次，
        再额外调一次 getSession() 等于把自选股读两遍。"""
        self.assertEqual(self.html.count("onAuthStateChange"), 1)
        # 盯真实调用，不是注释——注释里正好解释了为什么不调它。
        self.assertNotIn("client.auth.getSession()", self.html)

    def test_token_refresh_is_skipped(self):
        """TOKEN_REFRESHED 每小时触发一次、数据没变，重算会无声地闪一下。"""
        self.assertIn("TOKEN_REFRESHED", self.html)

    def test_logged_out_state_clears_the_filter(self):
        """退出之后如果还留着筛选，页面会莫名其妙地少掉一半条目。"""
        self.assertIn("document.body.classList.remove('tl-filtering')", self.html)


if __name__ == "__main__":
    unittest.main()
