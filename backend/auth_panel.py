"""登录与个人自选股面板：backend 独有的功能，故意不进 `taurient_lite/`。

**为什么不放进共享的渲染层。** `taurient_lite/html_renderer.py` 生成的片段
同时供 Artifact 发布和这个后端使用。账号系统只对后端有意义——Artifact
链接是给人快速扫一眼的静态快照，不适合也不需要登录状态。把这个面板
做成 backend 自己拼接的一段 HTML+JS，只注入到后端渲染的页面里，
Artifact 那份完全不受影响，`taurient_lite/` 包继续保持零依赖、
跟账号系统这种「有第三方服务、有真实用户数据」的东西彻底解耦。

**登录方式是 Google 一键登录，不是密码，也不是邮箱魔法链接。** 最早用的是
魔法链接，但 Supabase 免费版自带的邮件服务每小时只能发 2 封认证邮件，
调试阶段随手点两次就把额度用光，对日常使用也是多一道「去邮箱翻邮件」的
麻烦。改成 Google 登录之后这两个问题都不存在：跳转到 Google 自己的
登录页，用谁的 Google 账号登、密码对不对，全部由 Google 处理，
没有邮件发送这个环节，也不用存密码。

**权限边界完全在 Supabase 那边用行级安全策略定义，不靠这段 JS。**
这里传给浏览器的 anon key 本来就设计成可以公开——谁都能拿着它发请求，
但 Supabase 数据库那边的 RLS 策略保证一个用户的请求只能读写
`auth.uid() = user_id` 的那一行。前端代码写错、被人改、被绕过，
最坏结果也只是那个人自己的数据出问题，不可能碰到别人的一行。

**个性化怎么生效。** 每条新闻在渲染时已经带了 `data-tickers="NVDA TSLA"`
属性（见 `taurient_lite/components/items.py`），这里的 JS 只是拿用户
存的自选股跟这些属性做交集，命中的条目加一个高亮样式，配合一个开关
可以直接把不相关的条目隐藏——不需要重新请求新闻数据，当天已经生成好的
那批内容原地复用。
"""

from __future__ import annotations

import json

from taurient_lite.config import Supabase

from . import assets

SUPABASE_JS_CDN = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js"

HTML = """
<div class="tl-auth">
  <div id="tl-auth-logged-out" hidden>
    <p class="tl-auth-lede">登录后可以保存自己的自选股。回到简报页时，跟你相关的新闻会自动高亮，也可以只看这些。</p>
    <button id="tl-google-btn" type="button">
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.9c1.7-1.57 2.7-3.88 2.7-6.62z"/>
        <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.9-2.26c-.8.54-1.84.86-3.06.86-2.35 0-4.34-1.59-5.05-3.72H.96v2.33A9 9 0 0 0 9 18z"/>
        <path fill="#FBBC05" d="M3.95 10.7A5.4 5.4 0 0 1 3.67 9c0-.59.1-1.17.28-1.7V4.97H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.03l2.99-2.33z"/>
        <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.46 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.97l2.99 2.33C4.66 5.17 6.65 3.58 9 3.58z"/>
      </svg>
      用 Google 登录
    </button>
    <p id="tl-login-status" class="tl-auth-status" hidden></p>
  </div>
  <div id="tl-auth-logged-in" hidden>
    <div class="tl-auth-row">
      <span id="tl-user-email"></span>
      <button id="tl-logout" type="button">退出</button>
    </div>
    <div id="tl-chips" class="tl-chips"></div>
    <!-- 提示语必须在输入框**上方**：下拉候选是绝对定位的浮层，放在下方
         会被它整个盖住，而「没有找到代码 X，你是不是想找」这句恰恰要和
         候选列表同时可见才有意义。 -->
    <p id="tl-match-status" class="tl-auth-status" hidden></p>
    <form id="tl-add-form" autocomplete="off">
      <div id="tl-search-wrap">
        <input type="text" id="tl-add-input" placeholder="输入公司名或代码，比如 apple 或 AAPL"
               maxlength="64" role="combobox" aria-expanded="false"
               aria-controls="tl-suggest" aria-autocomplete="list">
        <ul id="tl-suggest" role="listbox" hidden></ul>
      </div>
      <button type="submit">添加</button>
    </form>
  </div>
</div>
"""


def _js_string(value: str) -> str:
    """把一个 Python 字符串变成安全嵌进 ``<script>`` 标签的 JS 字符串字面量。

    ``json.dumps`` 保证了引号不会提前把字符串截断，但它不管 ``</script``
    这种子串——HTML 解析器认标签是在 JS 语法之前，字符串里字面出现
    ``</script`` 照样会把外层的 `<script>` 标签在这里截断，JS 语法
    正不正确都救不了。这两个值目前只来自 `config.json`，是网站主自己
    维护的，不是任何人能远程注入的东西，但没必要让这段代码的安全性
    依赖「配置文件里凑巧没人写这几个字符」这个假设。
    """
    return json.dumps(value).replace("</script", "<\\/script")


def render_page(supabase: Supabase) -> str:
    """整个面板：样式 + 标记 + 脚本。没配置 Supabase 时返回空串。"""
    if not supabase.configured:
        return ""
    return "\n".join([
        assets.style("account.css"),
        f'<script src="{SUPABASE_JS_CDN}"></script>',
        HTML,
        assets.script(
            "account.js",
            supabase_url=_js_string(supabase.url),
            supabase_key=_js_string(supabase.anon_key),
        ),
    ])
