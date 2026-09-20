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

from . import assets
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


def _stat(key: str, value: str) -> str:
    return f'<div class="stat"><div class="k">{esc(key)}</div><div class="v">{value}</div></div>'


def _block(title: str, body: str, sub: str = "") -> str:
    """一个信息块。``body`` 为空时整块返回空串——缺数据就不出标题，
    版面上一个写着「暂无」的空标题传达的信息量是零。"""
    if not body:
        return ""
    head = f'<h2>{esc(title)}</h2>'
    if sub:
        head += f'<span class="co-sub">{esc(sub)}</span>'
    return f'<section class="co"><div class="co-head">{head}</div>{body}</section>'


def render_profile(profile) -> str:
    """公司简介。"""
    if profile.empty:
        return ""
    bits = []
    if profile.description:
        bits.append(f'<p class="co-desc">{esc(profile.description)}</p>')
    tags = []
    for value in (profile.sector, profile.industry, profile.region):
        if value:
            tags.append(f'<span class="co-tag">{esc(value)}</span>')
    if profile.url:
        tags.append(
            f'<a class="co-tag" href="{esc(profile.url)}" target="_blank" '
            f'rel="noopener">官网 &#8599;</a>'
        )
    if tags:
        bits.append(f'<div class="co-tags">{"".join(tags)}</div>')
    return _block("简介", "".join(bits), profile.name)


def render_stats(stats) -> str:
    """关键统计。"""
    if not stats:
        return ""
    cells = "".join(
        f'<div class="co-stat"><div class="k">{esc(k)}</div>'
        f'<div class="v">{esc(v)}</div></div>'
        for k, v in stats
    )
    return _block("关键统计", f'<div class="co-stats">{cells}</div>')


def render_ratings(ratings) -> str:
    """分析师评级。

    **只摆能拿到的。** 数据源给的是一个平均评级和参与券商名单，给不了
    买/持有/卖出的百分比分布；按券商数量编一个比例出来会显得更像那么
    回事，但那是编的。
    """
    if ratings.empty:
        return ""
    tone = {"buy": "buy", "sell": "sell"}.get(ratings.mean.strip().lower(), "hold")
    line = (
        f'<div class="rating-line">'
        f'<span class="rating-badge {tone}">{esc(ratings.mean or "—")}</span>'
        f'<span class="co-sub">{ratings.count} 家券商的平均评级</span>'
        f"</div>"
    )
    note = (
        '<p class="rating-note">这是参与评级的券商给出的平均意见，'
        "不含买/持有/卖出的具体分布——数据源只给到这一层。"
        "评级是别人的判断，不是事实。</p>"
    )
    brokers = ""
    if ratings.brokers:
        brokers = (
            f'<p class="broker-list">{esc(" · ".join(ratings.brokers))}</p>'
        )
    return _block("分析师评级", line + note + brokers)


def render_earnings(quarters) -> str:
    """财报超预期。"""
    if not quarters:
        return ""
    rows = []
    for q in quarters[:6]:
        if q.eps is None:
            continue
        pair = f'{q.eps:.2f}'
        if q.consensus is not None:
            pair += f' <span class="est">预期 {q.consensus:.2f}</span>'
        sur = ""
        if q.surprise_pct is not None:
            tone = "up" if q.surprise_pct >= 0 else "down"
            sur = f'<span class="eps-sur {tone}">{q.surprise_pct:+.1f}%</span>'
        rows.append(
            f'<div class="eps-row">'
            f'<span class="eps-q">{esc(q.fiscal_end)}</span>'
            f'<span class="eps-pair">{pair}</span>'
            f"{sur or '<span></span>'}"
            f"</div>"
        )
    if not rows:
        return ""
    return _block("财报", "".join(rows), "每股收益：实际 vs 预期")


def render_mentions(mentions) -> str:
    """这只票在历史简报里出现过的条目。"""
    if not mentions:
        return ""
    tier_cls = {"must-read": "t1", "worth-knowing": "t2"}
    rows = []
    for m in mentions:
        others = [t for t in m.tickers if t]
        rows.append(
            f'<article class="mention">'
            f'<div class="mention-top">'
            f'<span>{esc(m.date)}</span>'
            f'<span class="mention-tier {tier_cls.get(m.tier, "t3")}">'
            f"{esc(m.tier_label)}</span>"
            f'<span>{esc(" · ".join(others))}</span>'
            f"</div>"
            f"<h3>{esc(m.title)}</h3>"
            + (f"<p>{esc(m.why)}</p>" if m.why else "")
            + "</article>"
        )
    return _block("相关新闻", "".join(rows), "来自历史简报")


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
    company=None,
    mentions=(),
) -> str:
    """整页个股视图的 body 部分。

    ``company`` 与 ``mentions`` 都可以缺席：取不到就少几块，页面照常出。
    个股页的主体是 K 线，公司资料是补充——补充拿不到不该让主体一起陪葬。
    """
    chart = "\n".join([
        f'<script src="{esc(CHART_LIB)}"></script>',
        assets.script(
            "stock_chart.js",
            symbol=esc(symbol),
            chart_lib=esc(CHART_LIB),
            candles=json.dumps([b.as_candle() for b in bars]),
            volumes=json.dumps(
                [b.as_volume(up_color=up_color, down_color=down_color) for b in bars]
            ),
        ),
    ])

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

    # 顺序即阅读顺序：先知道这家公司是干什么的，再看数字，再看别人的判断，
    # 再看它兑现得怎么样，最后是最近发生了什么。
    blocks = ""
    if company is not None and not company.empty:
        blocks += render_profile(company.profile)
        blocks += render_stats(company.stats)
        blocks += render_ratings(company.ratings)
        blocks += render_earnings(company.quarters)
    blocks += render_mentions(mentions)

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
{blocks}
<p class="stock-note">日线来自 Yahoo Finance，{esc(stats.get("from", ""))} 至
{esc(stats.get("to", ""))}。区间涨跌按首尾收盘价算，不含分红与拆股调整之外的任何处理。
图表可以滚轮缩放、拖动平移，移到哪根看哪根。</p>
</div>
{chart}
"""
