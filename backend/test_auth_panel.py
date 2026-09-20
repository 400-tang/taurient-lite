"""登录面板测试。

`auth_panel.py` 是纯字符串拼装，不依赖 FastAPI，所以这些测试不需要
`backend/requirements.txt` 里的任何东西，跑起来比 `test_server.py` 更轻。

**JS 语法检查是自动化的，不再是手动跑一次 ``node --check`` 就完事。**
这段脚本上一次改的时候就出过一个真实的 bug——`options {{ ... }}` 漏了个
冒号，靠肉眼审查漏掉了，是手动跑 Node 检查才抓到的。与其指望下次改动
还记得手动测一遍，不如把这一步做成测试的一部分：环境里有 `node` 就真的
拿 `node --check` 验证生成的脚本，没有就跳过而不是让整个套件失败——
这台机器上有 Node，但 Render 的构建环境不一定有，CI 环境也可能没有。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.auth_panel import render
from taurient_lite.config import Supabase

CONFIGURED = Supabase(url="https://x.supabase.co", anon_key="eyJ.fake.token")
UNCONFIGURED = Supabase()


class TestRenderGating(unittest.TestCase):
    def test_empty_when_not_configured(self):
        self.assertEqual(render(UNCONFIGURED), "")

    def test_empty_when_only_url_present(self):
        self.assertEqual(render(Supabase(url="https://x.supabase.co")), "")

    def test_non_empty_when_configured(self):
        self.assertTrue(render(CONFIGURED))


class TestMarkup(unittest.TestCase):
    def setUp(self):
        self.html = render(CONFIGURED)

    def test_google_button_present(self):
        self.assertIn('id="tl-google-btn"', self.html)
        self.assertIn("用 Google 登录", self.html)

    def test_no_email_form_left_over(self):
        """换成 Google 登录之后，邮箱表单的痕迹不该还留在标记里。"""
        for leftover in ("tl-login-form", 'id="tl-email"', "发送登录链接"):
            self.assertNotIn(leftover, self.html)

    def test_watchlist_controls_present(self):
        self.assertIn('id="tl-chips"', self.html)
        self.assertIn('id="tl-add-form"', self.html)
        self.assertIn('id="tl-filter-toggle"', self.html)

    def test_credentials_embedded(self):
        self.assertIn(CONFIGURED.url, self.html)
        self.assertIn(CONFIGURED.anon_key, self.html)

    def test_embedded_quote_does_not_break_js_string(self):
        """凭据里如果有双引号，json.dumps 会转义成 \\"，不会提前截断字符串。"""
        tricky = Supabase(url='https://x.supabase.co/"weird', anon_key="a")
        html = render(tricky)
        self.assertIn('\\"weird', html)

    def test_embedded_close_script_tag_does_not_break_out(self):
        """光靠 json.dumps 保证不了这个——HTML 解析器认标签在 JS 语法
        之前，字符串里字面出现 </script 照样会把外层标签截断。
        _js_string() 额外把它转成 <\\/script，这条测试验证这一步真的生效。
        """
        tricky = Supabase(url="https://x.supabase.co", anon_key="</script><script>evil()")
        html = render(tricky)
        self.assertNotIn("</script><script>evil()", html)
        self.assertIn("<\\/script><script>evil()", html)

    def test_tags_balanced(self):
        import re

        for tag in ("div", "form", "button", "svg", "script", "style"):
            opened = len(re.findall(rf"<{tag}\b", self.html))
            closed = len(re.findall(rf"</{tag}>", self.html))
            self.assertEqual(opened, closed, f"<{tag}> 开闭不匹配")


class TestScriptLogic(unittest.TestCase):
    def setUp(self):
        self.html = render(CONFIGURED)

    def test_uses_oauth_not_otp(self):
        self.assertIn("signInWithOAuth", self.html)
        self.assertNotIn("signInWithOtp", self.html)

    def test_google_is_the_provider(self):
        self.assertIn("provider: 'google'", self.html)

    def test_redirects_to_current_page(self):
        self.assertIn("window.location.href", self.html)

    def test_single_auth_state_listener_no_redundant_getsession(self):
        """挂 onAuthStateChange 时 supabase-js 会自动补发一次
        INITIAL_SESSION，这里不该再额外单独调用一次 getSession()——
        那样会导致刚登录的人自选股被读两遍。检查的是真正的调用写法
        `client.auth.getSession()`，不是随便一个子串——解释这个设计
        决定的注释里本来就会提到"getSession()"这个词，那不算数。"""
        self.assertEqual(self.html.count("onAuthStateChange"), 1)
        self.assertNotIn("client.auth.getSession()", self.html)

    def test_token_refreshed_does_not_trigger_reload(self):
        self.assertIn("TOKEN_REFRESHED", self.html)

    def test_upsert_has_explicit_conflict_target(self):
        self.assertIn("onConflict: 'user_id'", self.html)

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

    def test_rejected_ticker_input_gives_feedback(self):
        """输入非法代码或重复代码时原来是静默 return，用户分不清
        是输错了还是功能坏了。

        断言的是「有没有反馈」这个意图，不是某一行具体怎么写的——
        反馈现在统一走 ``say()``，早先直接写 ``matchStatus.textContent``。
        """
        self.assertIn("function say(", self.html)
        say_fn = self.html.split("function say(", 1)[1][:200]
        self.assertIn("matchStatus.textContent", say_fn)
        add_fn = self.html.split("function addSymbol", 1)[1][:1200]
        self.assertIn("say(", add_fn)

    def test_symbol_must_resolve_before_being_added(self):
        """代码必须先被查证存在才能加进自选股。

        改造前只有格式校验，于是 APPLE、GOOGLE、ZZZZZ 全都能通过并存进
        数据库，页面上出现一个看着正常、却永远匹配不到任何新闻的芯片。
        """
        add_fn = self.html.split("function addSymbol", 1)[1][:1200]
        self.assertIn("lookup(", add_fn)

    def test_has_autocomplete_dropdown(self):
        """必须能按公司名找代码——不知道 AAPL 的人也要加得了苹果。"""
        self.assertIn('id="tl-suggest"', self.html)
        self.assertIn("/api/search?q=", self.html)
        self.assertIn('role="listbox"', self.html)

    def test_autocomplete_is_keyboard_navigable(self):
        """下拉框必须能用键盘走完，只能点鼠标等于把一部分人挡在外面。"""
        for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
            self.assertIn(key, self.html)

    def test_search_is_debounced(self):
        """逐字符打到后端既浪费也会触发上游限流。"""
        self.assertIn("searchTimer", self.html)
        self.assertIn("clearTimeout", self.html)

    def test_stale_search_results_are_discarded(self):
        """打字快的时候先发的慢请求会后到，不丢弃就会用旧结果覆盖新界面。"""
        self.assertIn("searchSeq", self.html)

    def test_falls_back_when_search_is_down(self):
        """搜索服务挂掉时要退回「只能输精确代码」的老行为，不能把人卡死。"""
        add_fn = self.html.split("function addSymbol", 1)[1][:1600]
        self.assertIn("catch", add_fn)
        self.assertIn("TICKER_RE.test", add_fn)

    def test_ticker_regex_matches_client_side_validation(self):
        """跟 taurient_lite/schema.py 和 backend/server.py 里同一条
        校验规则保持一致，别悄悄出现第二套标准。"""
        self.assertIn("A-Z][A-Z0-9.\\-]{0,9}", self.html)


@unittest.skipUnless(shutil.which("node"), "本机没有装 node，跳过 JS 语法检查")
class TestGeneratedJavaScriptIsValid(unittest.TestCase):
    """真的用 Node 解析一遍生成的脚本，不只是看字符串里有没有某个词。

    上一次改这段代码时，`options {{ emailRedirectTo: ... }}` 漏了个冒号，
    review 时肉眼没看出来，是手动跑 `node --check` 才抓到的——这个测试
    就是把那次手动检查变成以后每次改动都会自动跑的一步。
    """

    def _extract_inline_script(self, html: str) -> str:
        # 第一个 <script> 是外部 CDN 引用，只有第二个是内联逻辑。
        import re

        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        self.assertEqual(len(scripts), 1, "预期只有一段内联 <script>")
        return scripts[0]

    def _check_syntax(self, script: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script.js"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(
            result.returncode, 0, f"生成的 JS 语法有问题：\n{result.stderr}"
        )

    def test_default_config_produces_valid_javascript(self):
        self._check_syntax(self._extract_inline_script(render(CONFIGURED)))

    def test_url_with_special_characters_still_produces_valid_javascript(self):
        tricky = Supabase(url="https://x.supabase.co", anon_key="a'b\"c\\d")
        self._check_syntax(self._extract_inline_script(render(tricky)))


if __name__ == "__main__":
    unittest.main()
