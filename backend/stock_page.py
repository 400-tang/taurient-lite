"""个股页面：一张可缩放、可拖动、带十字光标的 K 线图。

**这是整个项目里第一个真正依赖前端库的页面，这个例外是想清楚了的。**
其余所有页面都是服务端拼好 HTML、零 JavaScript——因为那些页面本质上是
「排好版的文档」，静止状态下就完整可读。K 线不是：缩放、拖动、十字光标
读数这三件事发生在读者的手上，服务端渲染的 SVG 给不了，硬做就是在用
错工具。

**所以它只存在于后端渲染的页面里**，跟 ``auth_panel`` 的处境一样：
``taurient_lite/`` 核心包对它一无所知，保持零依赖。

用 TradingView 的 lightweight-charts，从 CDN 直接引，不引入构建链——
这个项目至今没有 npm、没有打包工具，为了一张图表把整套前端工具链搬进来
不划算。

**主题跟着页面走。** 图表库不认 CSS 变量，得把颜色读出来传进去；
读者切换亮暗时再传一次。不做这件事的话，暗色模式下会出现一张白底图。
"""

from __future__ import annotations

import json

from taurient_lite.components.base import esc
from taurient_lite.history import DEFAULT_RANGE, RANGES

#: 图表库的 CDN 地址。锁到小版本：CDN 上的 ``@5`` 会跟着上游升级，
#: 而这个页面对 API 形状有依赖，静默升级出问题时很难联想到是它。
CHART_LIB = (
    "https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.1/"
    "dist/lightweight-charts.standalone.production.js"
)

#: 区间选择器上的中文标签。
RANGE_LABELS: dict[str, str] = {
    "1mo": "1 月",
    "3mo": "3 月",
    "6mo": "6 月",
    "1y": "1 年",
    "5y": "5 年",
}

CSS = """
/* 整页撑满视口：图表是这一页的主体，让它吃掉剩下的全部高度。
   固定高度（原来是 26rem）在高屏幕上会留出大半屏空白，而 K 线恰恰是
   越高越好读——纵向空间直接决定价格轴的分辨率。 */
.stock {
  max-width: 96rem;
  margin: 0 auto;
  padding: 1.4rem var(--gutter) 1.6rem;
  min-height: 100vh;
  min-height: 100dvh;   /* 手机上地址栏会伸缩，dvh 才是真正可见的高度 */
  display: flex;
  flex-direction: column;
}

.stock-head {
  display: flex;
  align-items: baseline;
  gap: 0.7rem;
  flex-wrap: wrap;
  border-bottom: 2px solid var(--ink);
  padding-bottom: 0.7rem;
}

.stock-tk {
  font-family: var(--font-data);
  font-size: var(--t-xl);
  font-weight: 500;
  letter-spacing: var(--track-mono);
}

.stock-name { font-size: var(--t-base); color: var(--ink-mid); }

.stock-last {
  margin-left: auto;
  font-family: var(--font-data);
  font-size: var(--t-lg);
  font-variant-numeric: tabular-nums;
}

.stock-chg {
  font-family: var(--font-data);
  font-size: var(--t-base);
  font-variant-numeric: tabular-nums;
}

.stock-chg.up { color: var(--up); }
.stock-chg.down { color: var(--down); }

.stock-bar {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0.9rem 0 0.7rem;
  flex-wrap: wrap;
}

.range-btn {
  font-family: var(--font-data);
  font-size: var(--t-xs);
  letter-spacing: var(--track-mono);
  padding: 0.28rem 0.6rem;
  border: 1px solid var(--rule);
  border-radius: 2px;
  background: transparent;
  color: var(--ink-mid);
  cursor: pointer;
  text-decoration: none;
}

.range-btn:hover { border-color: var(--accent); color: var(--accent); }

.range-btn.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-weight: 500;
}

/* 图表吃掉纵向的剩余空间。min-height 是底线：图表库按容器尺寸初始化，
   高度为 0 时它会画出一张看不见的图，而且不报错。 */
.chart-wrap {
  position: relative;
  flex: 1 1 auto;
  min-height: 16rem;
  display: flex;
}

#chart {
  width: 100%;
  flex: 1 1 auto;
  border: 1px solid var(--rule-soft);
  border-radius: 3px;
}

/* 趋势线画在图表上方的一层 SVG 里。
   **默认 pointer-events: none**，否则它会吃掉所有鼠标事件，图表就拖不动、
   缩放不了了。只有线本身和端点手柄打开事件，空白处的点击照常穿透给图表；
   进入绘制模式时才整层接管。 */
#draw {
  position: absolute;
  pointer-events: none;
  overflow: visible;
  /* 必须压过图表自己的画布。图表库内部元素带 z-index，光靠 DOM 顺序
     赢不了——不加这一行，覆盖层会沉到 canvas 底下，点击全被画布吃掉，
     而处理器看上去完全正常，只是永远收不到事件。 */
  z-index: 5;
}

#draw.drawing { pointer-events: auto; cursor: crosshair; }
#draw .trend { pointer-events: stroke; cursor: pointer; }
#draw .grab { pointer-events: all; cursor: grab; }
#draw .grab:active { cursor: grabbing; }

.stock-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(7.5rem, 1fr));
  gap: 0.5rem;
  margin-top: 0.9rem;
}

.stat { border-top: 1px solid var(--rule-soft); padding-top: 0.45rem; }

.stat .k {
  font-size: var(--t-2xs);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-faint);
}

.stat .v {
  font-family: var(--font-data);
  font-size: var(--t-md);
  font-variant-numeric: tabular-nums;
  margin-top: 0.1rem;
}

.stock-note {
  margin-top: 1.4rem;
  font-size: var(--t-sm);
  line-height: 1.7;
  color: var(--ink-mid);
  max-width: var(--measure);
  text-wrap: pretty;
}

.stock-back {
  display: inline-block;
  margin-bottom: 1.2rem;
  font-family: var(--font-data);
  font-size: var(--t-xs);
  color: var(--accent);
  text-decoration: none;
}

.stock-back:hover { color: var(--accent-strong); }

.chart-fallback {
  padding: 1.2rem;
  font-size: var(--t-sm);
  color: var(--ink-mid);
  text-wrap: pretty;
}

/* 横线工具条与已画横线列表。 */
.line-tools {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-left: auto;
}

.line-btn {
  font-family: var(--font-data);
  font-size: var(--t-xs);
  letter-spacing: var(--track-mono);
  padding: 0.28rem 0.6rem;
  border: 1px solid var(--rule);
  border-radius: 2px;
  background: transparent;
  color: var(--ink-mid);
  cursor: pointer;
}

.line-btn:hover { border-color: var(--accent); color: var(--accent); }

/* 待放置状态要一眼可见：此刻点图表就会落一条线，不告诉用户就是个惊吓。 */
.line-btn.arming {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-weight: 500;
}

.line-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin: 0.5rem 0 0;
  padding: 0;
  list-style: none;
}

.line-list li {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: var(--font-data);
  font-size: var(--t-xs);
  font-variant-numeric: tabular-nums;
  padding: 0.18rem 0.3rem 0.18rem 0.5rem;
  border: 1px solid var(--rule-soft);
  border-radius: 2px;
  color: var(--ink-mid);
}

.line-list button {
  border: 0;
  background: none;
  color: var(--ink-faint);
  cursor: pointer;
  font-size: var(--t-sm);
  line-height: 1;
  padding: 0 0.15rem;
}

.line-list button:hover { color: var(--down); }

.line-hint { font-size: var(--t-xs); color: var(--ink-faint); }

/* 底部这两块是固定高度的附属信息，不参与抢高度。 */
.stock-stats { flex: none; }
.stock-note { flex: none; margin-top: 0.9rem; }

@media (max-width: 34rem) {
  .stock { padding: 1rem var(--gutter) 1.2rem; }
  #chart { min-height: 14rem; }
  .stock-note { font-size: var(--t-xs); }
}
"""


def _stat(key: str, value: str) -> str:
    return f'<div class="stat"><div class="k">{esc(key)}</div><div class="v">{value}</div></div>'


def _script(symbol: str, span: str, candles: list, volumes: list) -> str:
    """初始化图表。颜色从 CSS 变量里读，跟着页面主题走。

    数据直接内联进页面，不让浏览器再发一次请求：一张 6 个月的日线也就
    几十 KB，多一次往返只会让图表晚出来一拍。区间切换才走 ``/api/history``。
    """
    return f"""
<script src="{esc(CHART_LIB)}"></script>
<script>
(function () {{
  var box = document.getElementById('chart');
  if (!window.LightweightCharts) {{
    // CDN 挂了就说清楚，而不是留一块空白让人以为页面坏了。
    box.innerHTML = '<p class="chart-fallback">图表库没有加载成功，'
      + '刷新一次通常就好。数据本身没问题，可以从 /api/history/{esc(symbol)} 取。</p>';
    return;
  }}

  // 图表库不认 CSS 变量，得把当前主题的颜色读出来传进去。
  function tone(name, fallback) {{
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v || '').trim() || fallback;
  }}

  function palette() {{
    return {{
      up: tone('--up', '#12916A'),
      down: tone('--down', '#C4342B'),
      ink: tone('--ink', '#131A21'),
      faint: tone('--ink-faint', '#79848C'),
      rule: tone('--rule-hair', '#E5E8EA'),
      paper: tone('--paper', '#EDEFF0')
    }};
  }}

  var p = palette();
  var chart = LightweightCharts.createChart(box, {{
    layout: {{ background: {{ color: p.paper }}, textColor: p.faint, attributionLogo: false }},
    grid: {{ vertLines: {{ color: p.rule }}, horzLines: {{ color: p.rule }} }},
    rightPriceScale: {{ borderColor: p.rule }},
    timeScale: {{ borderColor: p.rule }},
    // 十字光标：读者要的「移到哪根看哪根」。
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    // 缩放与拖动，鼠标滚轮和触摸都走这套默认行为。
    handleScroll: true,
    handleScale: true
  }});

  var candles = chart.addSeries(LightweightCharts.CandlestickSeries, {{
    upColor: p.up, downColor: p.down,
    borderUpColor: p.up, borderDownColor: p.down,
    wickUpColor: p.up, wickDownColor: p.down,
    // 最新价那条横线取中性色。默认会用涨跌色，于是一只区间涨 35% 的票
    // 可能因为最后一根是阴线就挂一个红标签，暗示一个不存在的方向。
    priceLineColor: p.faint
  }});
  candles.setData({json.dumps(candles)});

  // 成交量压在底部两成高度里：它是辅助信息，不该跟价格抢地方。
  var volume = chart.addSeries(LightweightCharts.HistogramSeries, {{
    priceFormat: {{ type: 'volume' }},
    priceScaleId: 'vol',
    // 成交量不需要最新值标签和价格线：它是辅助信息，挂标签只是噪音。
    lastValueVisible: false,
    priceLineVisible: false
  }});
  chart.priceScale('vol').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
  volume.setData({json.dumps(volumes)});

  chart.timeScale().fitContent();

  // 容器宽度变了要跟着重画，否则旋转手机后图会错位。
  if (window.ResizeObserver) {{
    new ResizeObserver(function () {{
      chart.applyOptions({{ width: box.clientWidth, height: box.clientHeight }});
    }}).observe(box);
  }}

  // 读者切换系统主题时把颜色重新传一遍，不然暗色模式下是一张白底图。
  var media = window.matchMedia('(prefers-color-scheme: dark)');
  var onTheme = function () {{
    var q = palette();
    chart.applyOptions({{
      layout: {{ background: {{ color: q.paper }}, textColor: q.faint }},
      grid: {{ vertLines: {{ color: q.rule }}, horzLines: {{ color: q.rule }} }}
    }});
    candles.applyOptions({{
      upColor: q.up, downColor: q.down,
      borderUpColor: q.up, borderDownColor: q.down,
      wickUpColor: q.up, wickDownColor: q.down
    }});
  }};
  if (media.addEventListener) {{ media.addEventListener('change', onTheme); }}

  // ---------------------------------------------------------------- 横线
  //
  // 存在浏览器本地，不上服务器：一条「跌破这个价位再看」的线是读者自己的
  // 草稿，不是需要被别人看到的数据。代价是换个浏览器就没了——这个取舍
  // 写在界面提示里，不让人以为它会跟着账号走。
  //
  // 趋势线没有做。图表库不含任何内置绘图工具，斜线要自己实现命中测试和
  // 拖拽，几百行；横线是 createPriceLine 一个调用的事。先把便宜的做了，
  // 等确认真的每天在用，再决定值不值得写那几百行。

  var KEY = 'tl:lines:{esc(symbol)}';
  var lines = [];          // {{ price: number, handle: IPriceLine }}
  var arming = false;

  var addBtn = document.getElementById('add-line');
  var clearBtn = document.getElementById('clear-lines');
  var listBox = document.getElementById('line-list');
  var hint = document.getElementById('line-hint');

  function load() {{
    // 隐私模式下 localStorage 会直接抛异常，不能让它带崩整张图。
    try {{ return JSON.parse(localStorage.getItem(KEY) || '[]'); }}
    catch (e) {{ return []; }}
  }}

  function save() {{
    try {{ localStorage.setItem(KEY, JSON.stringify(lines.map(function (l) {{ return l.price; }}))); }}
    catch (e) {{ /* 存不了就只在本次会话里有效，不打扰用户 */ }}
  }}

  function draw() {{
    listBox.innerHTML = '';

    // trends 在下面的趋势线小节才赋值，而这里在加载横线时就会被调用一次。
    // var 提升让它此刻是 undefined，不兜住就是一个启动即崩的空指针。
    var ts = (typeof trends !== 'undefined' && trends) || [];
    ts.forEach(function (t, i) {{
      var li = document.createElement('li');
      if (selected === i) {{ li.style.borderColor = tone('--accent', '#1F3FCB'); }}
      var label = document.createElement('span');
      label.textContent = '\u2571 ' + t.a.p.toFixed(2) + ' \u2192 ' + t.b.p.toFixed(2);
      var del = document.createElement('button');
      del.type = 'button';
      del.textContent = '\u00d7';
      del.setAttribute('aria-label', '删除这条趋势线');
      del.addEventListener('click', function () {{ removeTrend(i); }});
      li.appendChild(label);
      li.appendChild(del);
      listBox.appendChild(li);
    }});

    lines.forEach(function (line, i) {{
      var li = document.createElement('li');
      var label = document.createElement('span');
      label.textContent = line.price.toFixed(2);
      var del = document.createElement('button');
      del.type = 'button';
      del.textContent = '\u00d7';
      del.setAttribute('aria-label', '删除 ' + line.price.toFixed(2) + ' 这条横线');
      del.addEventListener('click', function () {{ remove(i); }});
      li.appendChild(label);
      li.appendChild(del);
      listBox.appendChild(li);
    }});
    clearBtn.hidden = lines.length === 0 && ts.length === 0;
  }}

  // 趋势线那边按这个名字调用，指向同一个函数——列表只有一个。
  var drawList = draw;

  function add(price) {{
    if (!isFinite(price)) {{ return; }}
    var handle = candles.createPriceLine({{
      price: price,
      color: tone('--accent', '#1F3FCB'),
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true,
      title: ''
    }});
    lines.push({{ price: price, handle: handle }});
    save();
    draw();
  }}

  function remove(i) {{
    var line = lines[i];
    if (!line) {{ return; }}
    candles.removePriceLine(line.handle);
    lines.splice(i, 1);
    save();
    draw();
  }}

  function disarm() {{
    arming = false;
    addBtn.classList.remove('arming');
    hint.textContent = '';
  }}

  addBtn.addEventListener('click', function () {{
    if (arming) {{ disarm(); return; }}
    arming = true;
    addBtn.classList.add('arming');
    hint.textContent = '点图表上任意高度放一条线（Esc 取消）';
  }});

  clearBtn.addEventListener('click', function () {{
    while (lines.length) {{ remove(lines.length - 1); }}
    if (typeof trends !== 'undefined') {{
      while (trends.length) {{ removeTrend(trends.length - 1); }}
    }}
  }});

  document.addEventListener('keydown', function (e) {{
    if (e.key === 'Escape') {{
      if (arming) {{ disarm(); }}
      if (svg && svg.classList.contains('drawing')) {{ disarmTrend(); }}
    }}
    if ((e.key === 'Delete' || e.key === 'Backspace') && selected >= 0) {{
      // 输入框里按退格不该删线。
      var tag = (document.activeElement || {{}}).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') {{ return; }}
      e.preventDefault();
      removeTrend(selected);
    }}
  }});

  // 只在「待放置」时才接管点击：平时点图表是选中/取消十字光标的正常行为，
  // 随手一点就落一条线会让人不敢碰图。
  chart.subscribeClick(function (param) {{
    if (!arming || !param.point) {{ return; }}
    var price = candles.coordinateToPrice(param.point.y);
    if (price !== null) {{ add(price); }}
    disarm();
  }});

  load().forEach(function (price) {{ add(Number(price)); }});

  // -------------------------------------------------------------- 趋势线
  //
  // **锚点存的是「逻辑序号 + 价格」，不是「时间 + 价格」。** 趋势线的用处
  // 恰恰在于延伸到右侧的空白区去预判，而按时间换算的坐标一旦越过最后一根
  // K 线就返回 null，线会在图表边缘断掉。逻辑序号没有这个限制。
  //
  // **画在一层 SVG 上，没有用图表库的 primitive 插件接口。** 插件接口要自己
  // 实现渲染器和命中测试；用 SVG 的话，每条线就是一个真实 DOM 元素，
  // 命中测试和拖拽由浏览器代劳。代价是每次平移缩放都要重画一遍——
  // 范围变化的回调是同步触发的，肉眼看不出延迟。

  var TKEY = 'tl:trends:{esc(symbol)}';
  var NS = 'http://www.w3.org/2000/svg';
  var trends = [];        // {{ a: {{l, p}}, b: {{l, p}} }}
  var svg = document.getElementById('draw');
  var trendBtn = document.getElementById('add-trend');
  var pending = null;     // 画到一半的那条
  var selected = -1;
  var dragging = null;    // {{ i, end }}

  // 覆盖层必须和图表的绘图区严格对齐，否则线会整体偏移。不去问图表库要
  // 尺寸（压缩后的 API 名不可靠），直接量它自己那块 canvas 的位置。
  function fitOverlay() {{
    var canvas = box.querySelector('canvas');
    if (!canvas) {{ return; }}
    var wrap = svg.parentNode.getBoundingClientRect();
    var c = canvas.getBoundingClientRect();
    svg.style.left = (c.left - wrap.left) + 'px';
    svg.style.top = (c.top - wrap.top) + 'px';
    svg.style.width = c.width + 'px';
    svg.style.height = c.height + 'px';
  }}

  function toXY(anchor) {{
    var x = chart.timeScale().logicalToCoordinate(anchor.l);
    var y = candles.priceToCoordinate(anchor.p);
    return (x === null || y === null) ? null : {{ x: x, y: y }};
  }}

  function fromXY(x, y) {{
    var l = chart.timeScale().coordinateToLogical(x);
    var p = candles.coordinateToPrice(y);
    return (l === null || p === null) ? null : {{ l: l, p: p }};
  }}

  function localPoint(e) {{
    var r = svg.getBoundingClientRect();
    return {{ x: e.clientX - r.left, y: e.clientY - r.top }};
  }}

  function saveTrends() {{
    try {{ localStorage.setItem(TKEY, JSON.stringify(trends)); }} catch (err) {{}}
  }}

  function line(x1, y1, x2, y2, cls, width) {{
    var el = document.createElementNS(NS, 'line');
    el.setAttribute('x1', x1); el.setAttribute('y1', y1);
    el.setAttribute('x2', x2); el.setAttribute('y2', y2);
    el.setAttribute('stroke-width', width);
    el.setAttribute('class', cls);
    return el;
  }}

  function handle(x, y, i, end) {{
    var el = document.createElementNS(NS, 'circle');
    el.setAttribute('cx', x); el.setAttribute('cy', y); el.setAttribute('r', 5);
    el.setAttribute('class', 'grab');
    el.setAttribute('fill', tone('--paper', '#fff'));
    el.setAttribute('stroke', tone('--accent', '#1F3FCB'));
    el.setAttribute('stroke-width', 2);
    el.addEventListener('pointerdown', function (e) {{
      e.preventDefault();
      e.stopPropagation();
      dragging = {{ i: i, end: end }};
    }});
    return el;
  }}

  function renderTrends() {{
    fitOverlay();
    while (svg.firstChild) {{ svg.removeChild(svg.firstChild); }}
    var stroke = tone('--accent', '#1F3FCB');

    trends.forEach(function (t, i) {{
      var a = toXY(t.a), b = toXY(t.b);
      if (!a || !b) {{ return; }}
      // 先铺一条透明的粗线做命中区：2px 的线用鼠标几乎点不中。
      var hit = line(a.x, a.y, b.x, b.y, 'trend', 12);
      hit.setAttribute('stroke', 'transparent');
      hit.addEventListener('click', function (e) {{
        e.stopPropagation();
        selected = (selected === i) ? -1 : i;
        renderTrends();
        drawList();
      }});
      svg.appendChild(hit);

      var vis = line(a.x, a.y, b.x, b.y, '', selected === i ? 2.5 : 1.5);
      vis.setAttribute('stroke', stroke);
      vis.setAttribute('pointer-events', 'none');
      svg.appendChild(vis);

      if (selected === i) {{
        svg.appendChild(handle(a.x, a.y, i, 'a'));
        svg.appendChild(handle(b.x, b.y, i, 'b'));
      }}
    }});

    if (pending) {{
      var s0 = toXY(pending.a);
      if (s0 && pending.cursor) {{
        var prev = line(s0.x, s0.y, pending.cursor.x, pending.cursor.y, '', 1.5);
        prev.setAttribute('stroke', stroke);
        prev.setAttribute('stroke-dasharray', '4 3');
        prev.setAttribute('pointer-events', 'none');
        svg.appendChild(prev);
      }}
    }}
  }}

  function disarmTrend() {{
    pending = null;
    svg.classList.remove('drawing');
    trendBtn.classList.remove('arming');
    hint.textContent = '';
    renderTrends();
  }}

  trendBtn.addEventListener('click', function () {{
    if (svg.classList.contains('drawing')) {{ disarmTrend(); return; }}
    disarm();                       // 横线那边的待放置状态互斥
    selected = -1;
    svg.classList.add('drawing');
    trendBtn.classList.add('arming');
    hint.textContent = '点起点，再点终点（Esc 取消）';
    renderTrends();
    drawList();
  }});

  svg.addEventListener('click', function (e) {{
    if (!svg.classList.contains('drawing')) {{ return; }}
    var pt = localPoint(e);
    var anchor = fromXY(pt.x, pt.y);
    if (!anchor) {{ return; }}
    if (!pending) {{
      pending = {{ a: anchor, cursor: pt }};
      hint.textContent = '再点一下定终点（Esc 取消）';
      return;
    }}
    trends.push({{ a: pending.a, b: anchor }});
    saveTrends();
    disarmTrend();
    drawList();
  }});

  // **移动与抬起挂在 window 上，不挂 svg。** svg 平时是 pointer-events: none，
  // 拖拽途中鼠标移到线以外就收不到事件了，手柄会在半路脱手。window 不受
  // 命中测试影响，按下之后无论指针飘到哪都跟得住。
  window.addEventListener('pointermove', function (e) {{
    if (!dragging && !pending) {{ return; }}
    var pt = localPoint(e);
    if (dragging) {{
      var anchor = fromXY(pt.x, pt.y);
      if (anchor) {{
        trends[dragging.i][dragging.end] = anchor;
        renderTrends();
      }}
      return;
    }}
    if (pending) {{ pending.cursor = pt; renderTrends(); }}
  }});

  window.addEventListener('pointerup', function (e) {{
    if (dragging) {{
      saveTrends();
      dragging = null;
      drawList();
    }}
  }});

  function removeTrend(i) {{
    trends.splice(i, 1);
    if (selected === i) {{ selected = -1; }}
    else if (selected > i) {{ selected -= 1; }}
    saveTrends();
    renderTrends();
    drawList();
  }}

  try {{
    var raw = JSON.parse(localStorage.getItem(TKEY) || '[]');
    if (Array.isArray(raw)) {{
      trends = raw.filter(function (t) {{
        return t && t.a && t.b && isFinite(t.a.l) && isFinite(t.a.p)
          && isFinite(t.b.l) && isFinite(t.b.p);
      }});
    }}
  }} catch (err) {{}}

  // 平移、缩放、容器尺寸变化都要重画：锚点是逻辑坐标，屏幕位置每次都不同。
  chart.timeScale().subscribeVisibleLogicalRangeChange(renderTrends);
  if (window.ResizeObserver) {{
    new ResizeObserver(renderTrends).observe(box);
  }}
  renderTrends();

  draw();
}})();
</script>
"""


def render(
    symbol: str,
    *,
    name: str,
    span: str,
    bars: list,
    stats: dict,
    backend_url: str = "",
    up_color: str = "#12916A",
    down_color: str = "#C4342B",
) -> str:
    """整页个股视图的 body 部分。"""
    candles = [b.as_candle() for b in bars]
    volumes = [b.as_volume(up_color=up_color, down_color=down_color) for b in bars]

    change = stats.get("change_pct", 0.0)
    tone = "up" if change > 0 else "down" if change < 0 else "flat"
    ranges = "".join(
        f'<a class="range-btn{" on" if key == span else ""}" '
        f'href="?range={esc(key)}">{esc(RANGE_LABELS.get(key, key))}</a>'
        for key in RANGES
    )

    stats_html = "".join(
        [
            _stat("最新", f'{stats.get("last", 0):,.2f}'),
            _stat("区间涨跌", f'<span class="stock-chg {tone}">{change:+.2f}%</span>'),
            _stat("区间最高", f'{stats.get("high", 0):,.2f}'),
            _stat("区间最低", f'{stats.get("low", 0):,.2f}'),
            _stat("K 线根数", str(stats.get("bars", 0))),
        ]
    )

    back = f'<a class="stock-back" href="{esc(backend_url)}/">&larr; 回简报</a>'

    return f"""<div class="stock">
{back}
<div class="stock-head">
<span class="stock-tk">{esc(symbol)}</span>
<span class="stock-name">{esc(name)}</span>
<span class="stock-last">{stats.get("last", 0):,.2f}</span>
<span class="stock-chg {tone}">{change:+.2f}%</span>
</div>
<div class="stock-bar">{ranges}
<div class="line-tools">
<button type="button" id="add-trend" class="line-btn">＋ 趋势线</button>
<button type="button" id="add-line" class="line-btn">＋ 横线</button>
<button type="button" id="clear-lines" class="line-btn" hidden>清空</button>
<span class="line-hint" id="line-hint"></span>
</div>
</div>
<ul class="line-list" id="line-list"></ul>
<div class="chart-wrap">
<div id="chart"></div>
<svg id="draw" aria-hidden="true"></svg>
</div>
<div class="stock-stats">{stats_html}</div>
<p class="stock-note">日线来自 Yahoo Finance，{esc(stats.get("from", ""))} 至
{esc(stats.get("to", ""))}。区间涨跌按首尾收盘价算，不含分红与拆股调整之外的任何处理。
图表可以滚轮缩放、拖动平移，移到哪根看哪根。</p>
</div>
{_script(symbol, span, candles, volumes)}
"""
