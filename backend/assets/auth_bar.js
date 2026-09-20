(function () {
  var client = supabase.createClient(__SUPABASE_URL__, __SUPABASE_KEY__);

  var link = document.getElementById('tl-account-link');
  var filterWrap = document.getElementById('tl-filter-wrap');
  var filterToggle = document.getElementById('tl-filter-toggle');
  var matchStatus = document.getElementById('tl-match-status');
  var currentSymbols = [];

  function availableTickers() {
    var seen = {};
    document.querySelectorAll('.item[data-tickers]').forEach(function (el) {
      (el.getAttribute('data-tickers') || '').split(' ').filter(Boolean)
        .forEach(function (t) { seen[t] = true; });
    });
    return Object.keys(seen).sort();
  }

  function setMatchStatus(matched) {
    if (!currentSymbols.length) {
      matchStatus.hidden = true;
      return;
    }
    matchStatus.hidden = false;
    if (matched > 0) {
      matchStatus.textContent =
        '今天有 ' + matched + ' 条跟你的自选股相关，已高亮。';
      return;
    }
    var available = availableTickers();
    matchStatus.textContent = available.length
      ? '今天没有跟你自选股相关的新闻。今日简报涉及：' + available.join('、')
      : '今天的简报里没有任何个股新闻。';
  }

  function applyFilter() {
    var mine = {};
    currentSymbols.forEach(function (s) { mine[s] = true; });
    var matched = 0;
    document.querySelectorAll('.item').forEach(function (el) {
      var raw = el.getAttribute('data-tickers') || '';
      var tickers = raw.split(' ').filter(Boolean);
      var isMine = tickers.some(function (t) { return mine[t]; });
      if (isMine) matched++;
      el.classList.toggle('tl-mine', isMine);
    });
    document.body.classList.toggle('tl-filtering', filterToggle.checked);
    setMatchStatus(matched);
  }

  function showLoggedOut() {
    link.textContent = '登录 / 注册';
    link.classList.remove('on');
    filterWrap.classList.remove('show');
    filterToggle.checked = false;
    currentSymbols = [];
    document.body.classList.remove('tl-filtering');
    applyFilter();
  }

  function showLoggedIn(user) {
    // 邮箱可能很长，按钮上只留 @ 之前那一段；完整地址在账号页上。
    link.textContent = (user.email || '已登录').split('@')[0];
    link.classList.add('on');
    filterWrap.classList.add('show');
  }

  function loadWatchlist(userId) {
    client.from('watchlists').select('symbols').eq('user_id', userId).maybeSingle()
      .then(function (res) {
        currentSymbols = (res.data && res.data.symbols) || [];
        applyFilter();
      });
  }

  filterToggle.addEventListener('change', applyFilter);

  // 只挂这一个监听器：supabase-js v2 在挂上的那一刻就会用当前会话触发
  // 一次 INITIAL_SESSION，再额外调一次 getSession() 等于把自选股读两遍。
  // TOKEN_REFRESHED 每小时左右自动触发一次（同一个用户、同一份数据），
  // 特意跳过，不然会定期无声地重算一遍高亮。
  client.auth.onAuthStateChange(function (event, session) {
    if (event === 'SIGNED_OUT' || !session) {
      showLoggedOut();
      return;
    }
    if (event === 'TOKEN_REFRESHED') return;
    showLoggedIn(session.user);
    loadWatchlist(session.user.id);
  });
})();
