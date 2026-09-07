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

SUPABASE_JS_CDN = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js"

CSS = """
/* 跟 taurient_lite/theme.py 里 .sheet 的宽度和左右留白对齐，这样这个
   面板跟下面的正文在同一条竖线上对齐，不会显得是另一个不相关的模块。
   只是不套 .sheet 本身的大段上下 padding——那是给正文用的，这里
   只是页顶的一条工具条，贴着往下走就行。 */
.tl-bar {
  max-width: 48rem;
  margin: 1.75rem auto 0;
  padding: 0 var(--gutter);
}

.tl-auth {
  margin: 0;
  padding: 1rem 1.2rem;
  background: var(--paper-raised);
  border: 1px solid var(--rule-hair);
  border-radius: 4px;
}

.tl-auth-lede { margin: 0 0 0.7rem; font-size: var(--t-sm); color: var(--ink-mid); }

#tl-google-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.5rem 1rem 0.5rem 0.7rem;
  border: 1px solid var(--rule);
  border-radius: 4px;
  background: var(--paper);
  color: var(--ink);
  font-size: var(--t-sm);
  font-weight: 500;
  font-family: var(--font-body);
  cursor: pointer;
  transition: border-color 140ms ease, background 140ms ease;
}

#tl-google-btn:hover { border-color: var(--ink-mid); background: var(--paper-sunk); }
#tl-google-btn svg { flex: none; }

#tl-add-form button {
  padding: 0.45rem 0.9rem;
  border: 1px solid var(--accent);
  border-radius: 3px;
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: var(--t-sm);
  font-weight: 500;
  font-family: var(--font-body);
  cursor: pointer;
  transition: background 140ms ease, color 140ms ease;
}

#tl-add-form button:hover {
  background: var(--accent);
  color: var(--paper);
}

.tl-auth-status { margin: 0.6rem 0 0; font-size: var(--t-sm); color: var(--ink-mid); }

.tl-auth-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  margin-bottom: 0.8rem;
}

#tl-user-email {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  color: var(--ink-mid);
}

#tl-logout {
  padding: 0.35rem 0.75rem;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: transparent;
  color: var(--ink-mid);
  font-size: var(--t-sm);
  font-family: var(--font-body);
  cursor: pointer;
}

#tl-logout:hover { border-color: var(--ink-mid); background: var(--paper-sunk); color: var(--ink); }

.tl-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.7rem; }

.tl-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-family: var(--font-data);
  font-size: var(--t-sm);
  padding: 0.2rem 0.3rem 0.2rem 0.55rem;
  border: 1px solid var(--accent);
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.tl-chip-remove {
  border: none;
  background: none;
  cursor: pointer;
  color: inherit;
  font-size: 1rem;
  line-height: 1;
  padding: 0 0.15rem;
}

.tl-chip-remove:hover { color: var(--down); }

#tl-add-form { display: flex; gap: 0.5rem; margin-bottom: 0.8rem; }

#tl-add-input {
  flex: 1 1 10rem;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--font-data);
  text-transform: uppercase;
  font-size: var(--t-sm);
}

.tl-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--t-sm);
  color: var(--ink-mid);
  cursor: pointer;
}

/* 命中自选股的条目：跟日历标签页「今天」那格同一套视觉语言
   （柔和底色 + 内嵌强调色描边），不用负 margin 那种容易在网格
   布局里出岔子的技巧。 */
.item.tl-mine {
  background: var(--accent-soft);
  box-shadow: inset 3px 0 0 var(--accent);
}

/* 打开筛选开关时，不相关的条目整个隐藏。 */
body.tl-filtering .item:not(.tl-mine) { display: none; }
"""

HTML = """
<div class="tl-bar">
<div class="tl-auth">
  <div id="tl-auth-logged-out" hidden>
    <p class="tl-auth-lede">登录后可以保存自己的自选股，跟你相关的新闻会自动高亮。</p>
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
    <form id="tl-add-form">
      <input type="text" id="tl-add-input" placeholder="加一个股票代码，比如 NVDA" maxlength="10">
      <button type="submit">添加</button>
    </form>
    <label class="tl-toggle">
      <input type="checkbox" id="tl-filter-toggle">
      只看跟我相关的新闻
    </label>
  </div>
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


def _script(supabase: Supabase) -> str:
    """登录、读写自选股、按 ``data-tickers`` 做个性化的全部客户端逻辑。"""
    url_literal = _js_string(supabase.url)
    key_literal = _js_string(supabase.anon_key)

    return f"""
<script src="{SUPABASE_JS_CDN}"></script>
<script>
(function () {{
  var client = supabase.createClient({url_literal}, {key_literal});

  var loggedOutEl = document.getElementById('tl-auth-logged-out');
  var loggedInEl = document.getElementById('tl-auth-logged-in');
  var googleBtn = document.getElementById('tl-google-btn');
  var loginStatus = document.getElementById('tl-login-status');
  var userEmailEl = document.getElementById('tl-user-email');
  var logoutBtn = document.getElementById('tl-logout');
  var chipsEl = document.getElementById('tl-chips');
  var addForm = document.getElementById('tl-add-form');
  var addInput = document.getElementById('tl-add-input');
  var filterToggle = document.getElementById('tl-filter-toggle');

  var TICKER_RE = /^[A-Z][A-Z0-9.\\-]{{0,9}}$/;
  var currentSymbols = [];

  function showLoggedOut() {{
    loggedOutEl.hidden = false;
    loggedInEl.hidden = true;
    document.body.classList.remove('tl-filtering');
  }}

  function showLoggedIn(user) {{
    loggedOutEl.hidden = true;
    loggedInEl.hidden = false;
    userEmailEl.textContent = user.email;
  }}

  function renderChips() {{
    chipsEl.innerHTML = '';
    currentSymbols.forEach(function (symbol) {{
      var chip = document.createElement('span');
      chip.className = 'tl-chip';
      chip.appendChild(document.createTextNode(symbol));
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'tl-chip-remove';
      remove.textContent = '\\u00d7';
      remove.setAttribute('aria-label', '\\u79fb\\u9664 ' + symbol);
      remove.addEventListener('click', function () {{ removeSymbol(symbol); }});
      chip.appendChild(remove);
      chipsEl.appendChild(chip);
    }});
  }}

  function applyFilter() {{
    var mine = {{}};
    currentSymbols.forEach(function (s) {{ mine[s] = true; }});
    document.querySelectorAll('.item').forEach(function (el) {{
      var raw = el.getAttribute('data-tickers') || '';
      var tickers = raw.split(' ').filter(Boolean);
      var isMine = tickers.some(function (t) {{ return mine[t]; }});
      el.classList.toggle('tl-mine', isMine);
    }});
    document.body.classList.toggle('tl-filtering', filterToggle.checked);
  }}

  function persist(userId) {{
    // onConflict 显式指到 user_id（这张表的主键）：不留给默认行为猜，
    // 免得哪天客户端库的默认冲突列判定方式变了，写操作在这里悄悄改行为。
    client.from('watchlists').upsert({{
      user_id: userId,
      symbols: currentSymbols,
      updated_at: new Date().toISOString()
    }}, {{ onConflict: 'user_id' }}).then(function (result) {{
      if (result.error) console.error('\\u5b58\\u81ea\\u9009\\u80a1\\u5931\\u8d25', result.error);
    }});
  }}

  function withUser(fn) {{
    client.auth.getUser().then(function (result) {{
      var user = result.data && result.data.user;
      if (user) fn(user.id);
    }});
  }}

  function removeSymbol(symbol) {{
    currentSymbols = currentSymbols.filter(function (s) {{ return s !== symbol; }});
    renderChips();
    applyFilter();
    withUser(persist);
  }}

  function addSymbol(raw) {{
    var symbol = (raw || '').trim().toUpperCase();
    if (!TICKER_RE.test(symbol) || currentSymbols.indexOf(symbol) !== -1) return;
    currentSymbols.push(symbol);
    renderChips();
    applyFilter();
    withUser(persist);
  }}

  function loadWatchlist(userId) {{
    client.from('watchlists').select('symbols').eq('user_id', userId).maybeSingle()
      .then(function (result) {{
        if (result.error) {{
          console.error('\\u8bfb\\u81ea\\u9009\\u80a1\\u5931\\u8d25', result.error);
          currentSymbols = [];
        }} else {{
          currentSymbols = (result.data && result.data.symbols) || [];
        }}
        renderChips();
        applyFilter();
      }});
  }}

  googleBtn.addEventListener('click', function () {{
    loginStatus.hidden = false;
    loginStatus.textContent = '\\u8df3\\u8f6c\\u4e2d\\u2026';
    client.auth.signInWithOAuth({{
      provider: 'google',
      options: {{ redirectTo: window.location.href }}
    }}).then(function (result) {{
      // 成功的话浏览器此刻已经在跳去 Google 的登录页了，这里只处理
      // 「跳转请求本身」失败的情况（比如 Google 登录方式还没在
      // Supabase 后台启用），不是「用户在 Google 那边输错密码」
      // 那种——那种错误发生在 Google 自己的页面上，回不到这里。
      if (result.error) {{
        loginStatus.textContent = '\\u51fa\\u9519\\u4e86\\uff1a' + result.error.message;
      }}
    }});
  }});

  logoutBtn.addEventListener('click', function () {{
    client.auth.signOut().then(function () {{
      currentSymbols = [];
      applyFilter();
      showLoggedOut();
    }});
  }});

  addForm.addEventListener('submit', function (event) {{
    event.preventDefault();
    addSymbol(addInput.value);
    addInput.value = '';
  }});

  filterToggle.addEventListener('change', applyFilter);

  // 只挂这一个监听器，不再额外调用一次 getSession()——supabase-js v2
  // 在挂上监听器的那一刻就会用当前会话触发一次 INITIAL_SESSION 事件，
  // 两边都调用等于页面一加载就把自选股读两遍。TOKEN_REFRESHED 每小时
  // 左右会自动触发一次（同一个用户、同一份数据），特意跳过，不然会
  // 定期无声地把用户正在编辑的自选股面板重新渲染一遍。
  client.auth.onAuthStateChange(function (event, session) {{
    if (event === 'SIGNED_OUT' || !session) {{
      currentSymbols = [];
      applyFilter();
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
    """整个面板：样式 + 标记 + 脚本。没配置 Supabase 时返回空串。"""
    if not supabase.configured:
        return ""
    return f"<style>{CSS}</style>\n{HTML}\n{_script(supabase)}"
