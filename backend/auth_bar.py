"""简报页右上角的账号条：登录入口，以及登录后的高亮与过滤。

**登录表单不在这里。** 它搬到了独立的 ``/account`` 页——一个登录框嵌在
简报正文上方，读者每天打开看新闻时都要先越过它，而登录是一辈子做一两次
的事。这里只留一个按钮。

**但账号相关的逻辑并没有全搬走**，因为有两件事作用的对象就是这一页的
新闻列表，搬到别的页面就失去了对象：

* **高亮**：给涉及自选股的条目加 ``tl-mine``，靠的是渲染时写在每条新闻上的
  ``data-tickers``；
* **过滤**：「只看跟我相关的」这个开关，切的是这一页的条目。

所以这一层要做的是：读会话（supabase-js 从浏览器本地读，不发网络请求）、
读自选股、然后操作页面。登录、退出、增删自选股都在 ``/account``。
"""

from __future__ import annotations

from taurient_lite.config import Supabase

from . import assets
from .auth_panel import SUPABASE_JS_CDN, _js_string

HTML = """
<div class="tl-topbar">
  <label class="tl-filter" id="tl-filter-wrap">
    <input type="checkbox" id="tl-filter-toggle">
    只看跟我相关
  </label>
  <a class="tl-account-link" id="tl-account-link" href="/account">登录 / 注册</a>
</div>
<p class="tl-hint" id="tl-match-status" hidden></p>
"""

HTML = f'<script src="{SUPABASE_JS_CDN}"></script>' + HTML


def render(supabase: Supabase) -> str:
    """右上角账号条。没配 Supabase 时返回空串。"""
    if not supabase.configured:
        return ""
    return "\n".join([
        assets.style("auth_bar.css"),
        HTML,
        assets.script(
            "auth_bar.js",
            supabase_url=_js_string(supabase.url),
            supabase_key=_js_string(supabase.anon_key),
        ),
    ])
