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
.stock {
  max-width: 62rem;
  margin: 0 auto;
  padding: 2rem var(--gutter) 4rem;
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

/* 图表容器必须有确定的高度：图表库按容器尺寸初始化，高度为 0 时
   它会画出一张看不见的图，而且不报错。 */
#chart {
  width: 100%;
  height: 26rem;
  border: 1px solid var(--rule-soft);
  border-radius: 3px;
}

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

@media (max-width: 34rem) {
  #chart { height: 18rem; }
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
<div class="stock-bar">{ranges}</div>
<div id="chart"></div>
<div class="stock-stats">{stats_html}</div>
<p class="stock-note">日线来自 Yahoo Finance，{esc(stats.get("from", ""))} 至
{esc(stats.get("to", ""))}。区间涨跌按首尾收盘价算，不含分红与拆股调整之外的任何处理。
图表可以滚轮缩放、拖动平移，移到哪根看哪根。</p>
</div>
{_script(symbol, span, candles, volumes)}
"""
