(function () {
  var client = supabase.createClient(__SUPABASE_URL__, __SUPABASE_KEY__);

  var loggedOutEl = document.getElementById('tl-auth-logged-out');
  var loggedInEl = document.getElementById('tl-auth-logged-in');
  var googleBtn = document.getElementById('tl-google-btn');
  var loginStatus = document.getElementById('tl-login-status');
  var userEmailEl = document.getElementById('tl-user-email');
  var logoutBtn = document.getElementById('tl-logout');
  var chipsEl = document.getElementById('tl-chips');
  var addForm = document.getElementById('tl-add-form');
  var addInput = document.getElementById('tl-add-input');
  var matchStatus = document.getElementById('tl-match-status');

  var TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/;
  var currentSymbols = [];

  // 当天这份简报总共涉及哪些代码。用来在「一条都没匹配上」时告诉用户
  // 今天可选的范围是什么，而不是让他对着空页面猜是不是坏了。
  function showLoggedOut() {
    loggedOutEl.hidden = false;
    loggedInEl.hidden = true;
  }

  function showLoggedIn(user) {
    loggedOutEl.hidden = true;
    loggedInEl.hidden = false;
    userEmailEl.textContent = user.email;
  }

  function renderChips() {
    chipsEl.innerHTML = '';
    currentSymbols.forEach(function (symbol) {
      var chip = document.createElement('span');
      chip.className = 'tl-chip';
      chip.appendChild(document.createTextNode(symbol));
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'tl-chip-remove';
      remove.textContent = '×';
      remove.setAttribute('aria-label', '移除 ' + symbol);
      remove.addEventListener('click', function () { removeSymbol(symbol); });
      chip.appendChild(remove);
      chipsEl.appendChild(chip);
    });
  }

  function persist(userId) {
    // onConflict 显式指到 user_id（这张表的主键）：不留给默认行为猜，
    // 免得哪天客户端库的默认冲突列判定方式变了，写操作在这里悄悄改行为。
    client.from('watchlists').upsert({
      user_id: userId,
      symbols: currentSymbols,
      updated_at: new Date().toISOString()
    }, { onConflict: 'user_id' }).then(function (result) {
      if (result.error) console.error('存自选股失败', result.error);
    });
  }

  function withUser(fn) {
    client.auth.getUser().then(function (result) {
      var user = result.data && result.data.user;
      if (user) fn(user.id);
    });
  }

  function removeSymbol(symbol) {
    currentSymbols = currentSymbols.filter(function (s) { return s !== symbol; });
    renderChips();
    withUser(persist);
  }

  var suggestBox = document.getElementById('tl-suggest');
  var suggestRows = [];
  var suggestIndex = -1;
  var searchTimer = null;
  var searchSeq = 0;

  function say(text) {
    matchStatus.hidden = false;
    matchStatus.textContent = text;
  }

  function hideSuggest() {
    suggestBox.hidden = true;
    suggestBox.innerHTML = '';
    suggestRows = [];
    suggestIndex = -1;
    addInput.setAttribute('aria-expanded', 'false');
  }

  function highlight(i) {
    suggestIndex = i;
    var items = suggestBox.children;
    for (var k = 0; k < items.length; k++) {
      items[k].setAttribute('aria-selected', k === i ? 'true' : 'false');
    }
    if (i >= 0 && items[i]) { items[i].scrollIntoView({ block: 'nearest' }); }
  }

  function showSuggest(rows) {
    suggestRows = rows;
    suggestBox.innerHTML = '';
    rows.forEach(function (row, i) {
      var li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      var sym = document.createElement('span');
      sym.className = 'tl-sym';
      sym.textContent = row.symbol;
      var name = document.createElement('span');
      name.className = 'tl-name';
      name.textContent = row.name;
      li.appendChild(sym);
      li.appendChild(name);
      if (row.exchange) {
        var ex = document.createElement('span');
        ex.className = 'tl-exch';
        ex.textContent = row.exchange;
        li.appendChild(ex);
      }
      // 用 mousedown 而不是 click：click 发生在 blur 之后，
      // 那时下拉已经被收起来了，点击会落空。
      li.addEventListener('mousedown', function (event) {
        event.preventDefault();
        pick(i);
      });
      li.addEventListener('mouseenter', function () { highlight(i); });
      suggestBox.appendChild(li);
    });
    suggestBox.hidden = rows.length === 0;
    addInput.setAttribute('aria-expanded', rows.length ? 'true' : 'false');
    highlight(-1);
  }

  function pick(i) {
    var row = suggestRows[i];
    if (!row) { return; }
    addInput.value = '';
    hideSuggest();
    commitSymbol(row.symbol);
  }

  function lookup(term) {
    // 每次请求带一个序号，只有最新那次的结果才允许改动界面——
    // 否则打字快的时候先发的慢请求会后到，把界面覆盖成旧结果。
    var seq = ++searchSeq;
    return fetch('/api/search?q=' + encodeURIComponent(term)).then(function (res) {
      if (!res.ok) { throw new Error('search failed'); }
      return res.json();
    }).then(function (rows) {
      return seq === searchSeq ? rows : [];
    });
  }

  function commitSymbol(symbol) {
    if (currentSymbols.indexOf(symbol) !== -1) {
      say(symbol + ' 已经在列表里了');
      return;
    }
    currentSymbols.push(symbol);
    renderChips();
    withUser(persist);
  }

  // 直接提交（没从下拉里选）时，必须先确认这个代码真实存在。
  // 改造前这里只做格式校验，于是 APPLE、GOOGLE、ZZZZZ 全都能存进去，
  // 页面上出现一个看着正常、却永远匹配不到任何新闻的芯片——静默失败。
  function addSymbol(raw) {
    var text = (raw || '').trim();
    if (!text) { return; }
    var symbol = text.toUpperCase();
    if (currentSymbols.indexOf(symbol) !== -1) {
      say(symbol + ' 已经在列表里了');
      return;
    }
    say('正在查证 ' + text + ' …');
    lookup(text).then(function (rows) {
      var exact = null;
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].symbol === symbol) { exact = rows[i]; break; }
      }
      if (exact) { hideSuggest(); commitSymbol(exact.symbol); return; }
      if (rows.length) {
        // 找不到完全一致的，但有候选——让人挑，而不是替他猜。
        showSuggest(rows);
        say('没有找到代码 ' + symbol + '，你是不是想找下面这些？');
        return;
      }
      say('找不到 ' + text + '，也没有相近的代码。试试公司英文名，比如 apple。');
    }).catch(function () {
      // 搜索服务挂了就退回老行为：格式过得去就先存，别把人卡死。
      if (TICKER_RE.test(symbol)) { hideSuggest(); commitSymbol(symbol); }
      else { say('搜索暂时不可用，请直接输入股票代码。'); }
    });
  }

  function loadWatchlist(userId) {
    client.from('watchlists').select('symbols').eq('user_id', userId).maybeSingle()
      .then(function (result) {
        if (result.error) {
          console.error('读自选股失败', result.error);
          currentSymbols = [];
        } else {
          currentSymbols = (result.data && result.data.symbols) || [];
        }
        renderChips();
      });
  }

  googleBtn.addEventListener('click', function () {
    loginStatus.hidden = false;
    loginStatus.textContent = '跳转中…';
    client.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.href }
    }).then(function (result) {
      // 成功的话浏览器此刻已经在跳去 Google 的登录页了，这里只处理
      // 「跳转请求本身」失败的情况（比如 Google 登录方式还没在
      // Supabase 后台启用），不是「用户在 Google 那边输错密码」
      // 那种——那种错误发生在 Google 自己的页面上，回不到这里。
      if (result.error) {
        loginStatus.textContent = '出错了：' + result.error.message;
      }
    });
  });

  logoutBtn.addEventListener('click', function () {
    client.auth.signOut().then(function () {
      currentSymbols = [];
      showLoggedOut();
    });
  });

  addInput.addEventListener('input', function () {
    var term = addInput.value.trim();
    if (searchTimer) { clearTimeout(searchTimer); }
    if (term.length < 1) { hideSuggest(); return; }
    // 200ms 防抖：逐字符打到后端既浪费也会触发上游限流。
    searchTimer = setTimeout(function () {
      lookup(term).then(showSuggest).catch(function () { hideSuggest(); });
    }, 200);
  });

  addInput.addEventListener('keydown', function (event) {
    if (suggestBox.hidden) { return; }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      highlight((suggestIndex + 1) % suggestRows.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      highlight(suggestIndex <= 0 ? suggestRows.length - 1 : suggestIndex - 1);
    } else if (event.key === 'Enter' && suggestIndex >= 0) {
      event.preventDefault();
      pick(suggestIndex);
    } else if (event.key === 'Escape') {
      hideSuggest();
    }
  });

  addInput.addEventListener('blur', function () {
    // 延后一拍，让下拉项的 mousedown 先跑完。
    setTimeout(hideSuggest, 120);
  });

  addForm.addEventListener('submit', function (event) {
    event.preventDefault();
    if (suggestIndex >= 0) { pick(suggestIndex); return; }
    if (searchTimer) { clearTimeout(searchTimer); }
    addSymbol(addInput.value);
    addInput.value = '';
  });


  // 只挂这一个监听器，不再额外调用一次 getSession()——supabase-js v2
  // 在挂上监听器的那一刻就会用当前会话触发一次 INITIAL_SESSION 事件，
  // 两边都调用等于页面一加载就把自选股读两遍。TOKEN_REFRESHED 每小时
  // 左右会自动触发一次（同一个用户、同一份数据），特意跳过，不然会
  // 定期无声地把用户正在编辑的自选股面板重新渲染一遍。
  client.auth.onAuthStateChange(function (event, session) {
    if (event === 'SIGNED_OUT' || !session) {
      currentSymbols = [];
      showLoggedOut();
      return;
    }
    if (event === 'TOKEN_REFRESHED') return;
    showLoggedIn(session.user);
    loadWatchlist(session.user.id);
  });
})();
