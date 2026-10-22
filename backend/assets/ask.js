(function () {
  // 划词问答：选中简报里的文字 → 旁边出现「问一问」 → 点开右侧抽屉，
  // 把选中的文字和它所在的整条新闻发给 /api/ask，回答逐字流回来。
  var chip = document.getElementById('ask-chip');
  var drawer = document.getElementById('ask-drawer');
  var quote = document.getElementById('ask-quote');
  var log = document.getElementById('ask-log');
  var left = document.getElementById('ask-left');
  var suggest = document.getElementById('ask-suggest');
  var form = document.getElementById('ask-compose');
  var input = document.getElementById('ask-input');
  var send = document.getElementById('ask-send');
  var sheet = document.querySelector('.sheet');
  if (!chip || !drawer || !sheet) return;

  var MAX_SELECTION = 500;
  var MAX_CONTEXT = 4000;
  var FOLLOW_UPS = ['用更简单的话再说一遍', '这对市场意味着什么？', '举个例子'];

  // 当前这段对话。换一段文字就整个重来。
  var state = { selection: '', context: '', messages: [], busy: false, abort: null };
  var pending = { selection: '', context: '' };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // 选中的文字所在的那条新闻：优先整条 .item（标题、正文、为什么重要都在里面），
  // 不在新闻条目里（比如主线、日历）就退回最近的段落或区块。
  function contextOf(node) {
    var start = node && node.nodeType === 1 ? node : node && node.parentElement;
    if (!start) return '';
    var box = start.closest('.item') || start.closest('section, li, p, tr') || start;
    return (box.innerText || '').trim().slice(0, MAX_CONTEXT);
  }

  // ---------------------------------------------------------- 「问一问」按钮

  function hideChip() { chip.hidden = true; }

  function placeChip() {
    var sel = window.getSelection();
    var text = sel && sel.rangeCount ? sel.toString().trim() : '';
    if (!text || !sheet.contains(sel.anchorNode) || drawer.contains(sel.anchorNode)) {
      hideChip();
      return;
    }
    var range = sel.getRangeAt(0);
    var rects = range.getClientRects();
    var r = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
    pending.selection = text.slice(0, MAX_SELECTION);
    pending.context = contextOf(range.commonAncestorContainer);
    chip.hidden = false;
    var w = chip.offsetWidth || 90;
    chip.style.left = Math.max(8, Math.min(r.right + 6, window.innerWidth - w - 8)) + 'px';
    chip.style.top = Math.max(8, r.bottom + 6) + 'px';
  }

  // mouseup / keyup 覆盖鼠标拖选和 Shift+方向键；touchend 之后选区还在变，
  // 所以统一延后一拍再读。
  ['mouseup', 'keyup', 'touchend'].forEach(function (type) {
    document.addEventListener(type, function (e) {
      if (chip.contains(e.target)) return;
      setTimeout(placeChip, 10);
    });
  });
  window.addEventListener('scroll', hideChip, { passive: true });

  chip.addEventListener('mousedown', function (e) { e.preventDefault(); }); // 别让点击把选区清掉
  chip.addEventListener('click', function () {
    hideChip();
    start(pending.selection, pending.context);
    var sel = window.getSelection();
    if (sel) sel.removeAllRanges();
  });

  // ---------------------------------------------------------- 抽屉

  function openDrawer() {
    drawer.hidden = false;
    document.body.classList.add('ask-open');
  }

  function closeDrawer() {
    if (state.abort) state.abort.abort();
    drawer.hidden = true;
    document.body.classList.remove('ask-open');
  }

  document.getElementById('ask-close').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !drawer.hidden) closeDrawer();
  });

  function setBusy(busy) {
    state.busy = busy;
    send.disabled = busy;
    suggest.hidden = busy;
  }

  function showSuggestions() {
    suggest.innerHTML = '';
    FOLLOW_UPS.forEach(function (q) {
      var b = el('button', null, q);
      b.type = 'button';
      b.addEventListener('click', function () { ask(q); });
      suggest.appendChild(b);
    });
  }

  function showError(message, withLogin) {
    var box = el('div', 'ask-msg error', message);
    if (withLogin) {
      box.appendChild(document.createTextNode(' '));
      var a = el('a', null, '去登录');
      a.href = '/account';
      box.appendChild(a);
    }
    log.appendChild(box);
    log.scrollTop = log.scrollHeight;
  }

  // ---------------------------------------------------------- 提问

  function start(selection, context) {
    if (!selection) return;
    if (state.abort) state.abort.abort();
    state = { selection: selection, context: context, messages: [], busy: false, abort: null };
    quote.textContent = selection.length > 160 ? selection.slice(0, 160) + '…' : selection;
    log.innerHTML = '';
    suggest.innerHTML = '';
    left.textContent = '';
    openDrawer();
    ask('请解释一下「' + selection + '」是什么意思，以及它在这条新闻里的作用。', true);
  }

  function token() {
    var client = window.tlSupabase;
    if (!client) return Promise.resolve('');
    return client.auth.getSession().then(function (res) {
      return (res.data && res.data.session && res.data.session.access_token) || '';
    }, function () { return ''; });
  }

  function ask(question, hidden) {
    if (state.busy || !question) return;
    // 第一问是替用户拼的，不在对话里显示成一条用户消息——引用框已经说明了在问什么。
    if (!hidden) log.appendChild(el('div', 'ask-msg user', question));
    state.messages.push({ role: 'user', content: question });

    var answer = el('div', 'ask-msg bot pending');
    log.appendChild(answer);
    log.scrollTop = log.scrollHeight;
    setBusy(true);

    var controller = new AbortController();
    state.abort = controller;
    var mine = state;

    token().then(function (t) {
      if (!t) {
        answer.remove();
        mine.messages.pop();
        showError('登录之后才能提问。', true);
        return null;
      }
      return fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + t },
        body: JSON.stringify({ selection: mine.selection, context: mine.context, messages: mine.messages }),
        signal: controller.signal
      });
    }).then(function (res) {
      if (!res) return;
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          answer.remove();
          mine.messages.pop();
          showError(body.detail || ('出错了（' + res.status + '）'), res.status === 401);
        });
      }
      var remaining = res.headers.get('X-Ask-Remaining');
      if (remaining !== null) left.textContent = '今天还能问 ' + remaining + ' 次';
      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var text = '';
      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) return;
          text += decoder.decode(chunk.value, { stream: true });
          answer.textContent = text;
          log.scrollTop = log.scrollHeight;
          return pump();
        });
      }
      return pump().then(function () {
        text += decoder.decode();
        answer.textContent = text || '（没有收到回答）';
        mine.messages.push({ role: 'assistant', content: text || '（没有回答）' });
      });
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      answer.remove();
      mine.messages.pop();
      showError('网络出错了，稍后再试。');
    }).then(function () {
      if (state !== mine) return; // 期间已经换了一段文字，别去动新对话的界面
      answer.classList.remove('pending');
      setBusy(false);
      if (mine.messages.length && mine.messages[mine.messages.length - 1].role === 'assistant') {
        showSuggestions();
      }
    });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q || state.busy) return;
    input.value = '';
    ask(q);
  });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
})();
