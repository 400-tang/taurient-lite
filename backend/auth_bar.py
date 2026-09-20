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

from .auth_panel import SUPABASE_JS_CDN, _js_string

CSS = """
.tl-topbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.5rem;
  max-width: 48rem;
  margin: 0 auto;
  padding: 0.7rem var(--gutter) 0;
}

.tl-account-link {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-family: var(--font-data);
  font-size: var(--t-xs);
  letter-spacing: var(--track-mono);
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--rule);
  border-radius: 2px;
  color: var(--ink-mid);
  text-decoration: none;
  transition: border-color 140ms ease, color 140ms ease;
}

.tl-account-link:hover { border-color: var(--accent); color: var(--accent); }

/* 已登录时按钮变成品牌色的实心点加邮箱，一眼能区分状态。 */
.tl-account-link.on { border-color: var(--accent); color: var(--accent); }

.tl-account-link.on::before {
  content: "";
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 999px;
  background: var(--accent);
}

/* 过滤开关只在登录后出现：没有自选股时它切不出任何区别。 */
.tl-filter {
  display: none;
  align-items: center;
  gap: 0.35rem;
  font-size: var(--t-xs);
  color: var(--ink-mid);
  cursor: pointer;
}

.tl-filter.show { display: inline-flex; }

.tl-hint {
  max-width: 48rem;
  margin: 0.35rem auto 0;
  padding: 0 var(--gutter);
  font-size: var(--t-xs);
  color: var(--ink-faint);
  text-align: right;
}

@media (max-width: 34rem) {
  .tl-topbar { padding-top: 0.5rem; flex-wrap: wrap; }
  .tl-hint { text-align: left; }
}

/* 命中自选股的条目：跟日历标签页「今天」那格同一套视觉语言
   （柔和底色 + 内嵌强调色描边），不用负 margin 那种容易在网格
   布局里出岔子的技巧。 */
.item.tl-mine {
  background: var(--accent-soft);
  box-shadow: inset 3px 0 0 var(--accent);
}

/* 打开筛选开关时，只隐藏「带了股票代码、但都不在你自选股里」的条目。
   完全没有 data-tickers 的条目是宏观新闻（联储、地缘、油价这类），
   它们不属于任何个股，却往往是当天最重要的几条——第一版把它们也
   一并隐藏了，结果 18 条里有 10 条属于这一类，一开筛选整页就空了，
   还没有任何提示，看起来像页面坏了。 */
body.tl-filtering .item[data-tickers]:not(.tl-mine) { display: none; }
"""

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


def _script(supabase: Supabase) -> str:
    """读会话、读自选股、然后操作这一页的新闻列表。"""
    url_literal = _js_string(supabase.url)
    key_literal = _js_string(supabase.anon_key)

    return f"""
<script src="{SUPABASE_JS_CDN}"></script>
<script>
(function () {{
  var client = supabase.createClient({url_literal}, {key_literal});

  var link = document.getElementById('tl-account-link');
  var filterWrap = document.getElementById('tl-filter-wrap');
  var filterToggle = document.getElementById('tl-filter-toggle');
  var matchStatus = document.getElementById('tl-match-status');
  var currentSymbols = [];

  function availableTickers() {{
    var seen = {{}};
    document.querySelectorAll('.item[data-tickers]').forEach(function (el) {{
      (el.getAttribute('data-tickers') || '').split(' ').filter(Boolean)
        .forEach(function (t) {{ seen[t] = true; }});
    }});
    return Object.keys(seen).sort();
  }}

  function setMatchStatus(matched) {{
    if (!currentSymbols.length) {{
      matchStatus.hidden = true;
      return;
    }}
    matchStatus.hidden = false;
    if (matched > 0) {{
      matchStatus.textContent =
        '\\u4eca\\u5929\\u6709 ' + matched + ' \\u6761\\u8ddf\\u4f60\\u7684\\u81ea\\u9009\\u80a1\\u76f8\\u5173\\uff0c\\u5df2\\u9ad8\\u4eae\\u3002';
      return;
    }}
    var available = availableTickers();
    matchStatus.textContent = available.length
      ? '\\u4eca\\u5929\\u6ca1\\u6709\\u8ddf\\u4f60\\u81ea\\u9009\\u80a1\\u76f8\\u5173\\u7684\\u65b0\\u95fb\\u3002\\u4eca\\u65e5\\u7b80\\u62a5\\u6d89\\u53ca\\uff1a' + available.join('\\u3001')
      : '\\u4eca\\u5929\\u7684\\u7b80\\u62a5\\u91cc\\u6ca1\\u6709\\u4efb\\u4f55\\u4e2a\\u80a1\\u65b0\\u95fb\\u3002';
  }}

  function applyFilter() {{
    var mine = {{}};
    currentSymbols.forEach(function (s) {{ mine[s] = true; }});
    var matched = 0;
    document.querySelectorAll('.item').forEach(function (el) {{
      var raw = el.getAttribute('data-tickers') || '';
      var tickers = raw.split(' ').filter(Boolean);
      var isMine = tickers.some(function (t) {{ return mine[t]; }});
      if (isMine) matched++;
      el.classList.toggle('tl-mine', isMine);
    }});
    document.body.classList.toggle('tl-filtering', filterToggle.checked);
    setMatchStatus(matched);
  }}

  function showLoggedOut() {{
    link.textContent = '\\u767b\\u5f55 / \\u6ce8\\u518c';
    link.classList.remove('on');
    filterWrap.classList.remove('show');
    filterToggle.checked = false;
    currentSymbols = [];
    document.body.classList.remove('tl-filtering');
    applyFilter();
  }}

  function showLoggedIn(user) {{
    // 邮箱可能很长，按钮上只留 @ 之前那一段；完整地址在账号页上。
    link.textContent = (user.email || '\\u5df2\\u767b\\u5f55').split('@')[0];
    link.classList.add('on');
    filterWrap.classList.add('show');
  }}

  function loadWatchlist(userId) {{
    client.from('watchlists').select('symbols').eq('user_id', userId).maybeSingle()
      .then(function (res) {{
        currentSymbols = (res.data && res.data.symbols) || [];
        applyFilter();
      }});
  }}

  filterToggle.addEventListener('change', applyFilter);

  // 只挂这一个监听器：supabase-js v2 在挂上的那一刻就会用当前会话触发
  // 一次 INITIAL_SESSION，再额外调一次 getSession() 等于把自选股读两遍。
  // TOKEN_REFRESHED 每小时左右自动触发一次（同一个用户、同一份数据），
  // 特意跳过，不然会定期无声地重算一遍高亮。
  client.auth.onAuthStateChange(function (event, session) {{
    if (event === 'SIGNED_OUT' || !session) {{
      showLoggedOut();
      return;
    }}
    if (event === 'TOKEN_REFRESHED') return;
    showLoggedIn(session.user);
    loadWatchlist(session.user.id);
  }});
}})();
</script>
"""


def render(supabase: Supabase) -> str:
    """右上角账号条。没配 Supabase 时返回空串。"""
    if not supabase.configured:
        return ""
    return f"<style>{CSS}</style>\n{HTML}\n{_script(supabase)}"
