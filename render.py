#!/usr/bin/env python3
"""Render a daily brief JSON into the dashboard HTML and a Markdown archive.

Usage:  python3 render.py 2026-09-06
        python3 render.py            # newest brief in briefs/
"""

import datetime as dt
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRIEFS = ROOT / "briefs"
SITE = ROOT / "site"
CONFIG = ROOT / "config.json"

TIER_LABEL = {
    "must-read": "必读",
    "worth-knowing": "值得知道",
    "noise": "背景噪音",
}
TIER_ORDER = ["must-read", "worth-knowing", "noise"]
WEIGHT_LABEL = {"high": "关键", "mid": "留意", "low": "常规"}


def e(s):
    return html.escape(str(s), quote=True)


def age_days(published, today):
    """新闻距离简报日期几天。解析失败时返回 None，调用方不显示徽章。"""
    try:
        p = dt.date.fromisoformat(published)
        t = dt.date.fromisoformat(today)
        return (t - p).days
    except (ValueError, TypeError):
        return None


def age_badge(published, today):
    n = age_days(published, today)
    if n is None:
        return "", ""
    if n <= 0:
        return "今天", "fresh"
    if n == 1:
        return "昨天", "fresh"
    if n == 2:
        return "2 天前", "aging"
    return f"{n} 天前", "stale"


# --------------------------------------------------------------------------- CSS

CSS = """
:root {
  --paper:        #EDEFF0;
  --paper-sunk:   #E3E6E8;
  --rule:         #C6CCD0;
  --rule-soft:    #D8DDE0;
  --ink:          #131A21;
  --ink-mid:      #4A555E;
  --ink-faint:    #79848C;
  --accent:       #1F3FCB;
  --accent-soft:  #DDE2F7;

  /* 涨跌是语义色，与品牌色分开，且经过色盲可辨度校验（deutan ΔE 8.1）。 */
  --up:           #12916A;
  --down:         #C4342B;
  --up-wash:      #D6EDE4;
  --down-wash:    #F7DEDB;

  --tier-1:       #C4342B;
  --tier-2:       #1F3FCB;
  --tier-3:       #79848C;

  --display: "Newsreader", Georgia, "Songti SC", serif;
  --body: "IBM Plex Sans", "PingFang SC", "Hiragino Sans GB", system-ui, sans-serif;
  --data: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper:       #0E1317;
    --paper-sunk:  #161C21;
    --rule:        #2C353C;
    --rule-soft:   #212930;
    --ink:         #DDE3E7;
    --ink-mid:     #9AA6AE;
    --ink-faint:   #6C7982;
    --accent:      #8AA0FF;
    --accent-soft: #1B2340;
    --up:          #1FAD82;
    --down:        #E4634F;
    --up-wash:     #14312A;
    --down-wash:   #34201D;
    --tier-1:      #E4634F;
    --tier-2:      #8AA0FF;
    --tier-3:      #6C7982;
  }
}

:root[data-theme="dark"] {
  --paper:       #0E1317;
  --paper-sunk:  #161C21;
  --rule:        #2C353C;
  --rule-soft:   #212930;
  --ink:         #DDE3E7;
  --ink-mid:     #9AA6AE;
  --ink-faint:   #6C7982;
  --accent:      #8AA0FF;
  --accent-soft: #1B2340;
  --up:          #1FAD82;
  --down:        #E4634F;
  --up-wash:     #14312A;
  --down-wash:   #34201D;
  --tier-1:      #E4634F;
  --tier-2:      #8AA0FF;
  --tier-3:      #6C7982;
}

* { box-sizing: border-box; }

body {
  background: var(--paper);
  color: var(--ink);
  font-family: var(--body);
  font-size: 16px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

.sheet {
  max-width: 46rem;
  margin: 0 auto;
  padding: 2.5rem 1.5rem 5rem;
}

/* ---------------------------------------------------------------- masthead */

.masthead { border-bottom: 2px solid var(--ink); padding-bottom: 0.75rem; }

.masthead h1 {
  font-family: var(--display);
  font-weight: 500;
  font-size: clamp(2rem, 6vw, 2.9rem);
  line-height: 1.05;
  letter-spacing: -0.015em;
  margin: 0;
  text-wrap: balance;
}

.masthead h1 em { font-style: italic; color: var(--accent); }

.stamp {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1.1rem;
  margin-top: 0.9rem;
  font-family: var(--data);
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-faint);
}

.stamp b { color: var(--ink-mid); font-weight: 500; }

.lede {
  font-family: var(--display);
  font-size: 1.3rem;
  line-height: 1.5;
  margin: 1.6rem 0 0;
  padding-left: 1rem;
  border-left: 3px solid var(--accent);
  text-wrap: pretty;
}

/* ----------------------------------------------------------- section heads */

.sec-head {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  margin: 2.8rem 0 0.2rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--rule);
}

.sec-head h2 {
  font-family: var(--body);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  margin: 0;
}

.sec-head .n { font-family: var(--data); font-size: 0.72rem; color: var(--ink-faint); }
.sec-head .asof {
  margin-left: auto;
  font-family: var(--data);
  font-size: 0.65rem;
  color: var(--ink-faint);
  text-transform: none;
  letter-spacing: 0.02em;
}

.t1 h2 { color: var(--tier-1); }
.t2 h2 { color: var(--tier-2); }
.t3 h2 { color: var(--tier-3); }

/* ------------------------------------------------------------ mag7 diverging bars */

.mag7 { margin-top: 0.9rem; }

.mag7-row {
  display: grid;
  grid-template-columns: 3.6rem 1fr 4.2rem;
  align-items: center;
  gap: 0 0.7rem;
  padding: 0.22rem 0;
  position: relative;
}

.mag7-row:hover .mag7-track { background: var(--paper-sunk); }

.mag7-tick {
  font-family: var(--data);
  font-size: 0.8rem;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.mag7-track {
  position: relative;
  height: 1.35rem;
  border-radius: 2px;
  transition: background 120ms ease;
}

/* 零轴。所有条形都从这条线出发，方向本身就是第二重编码。 */
.mag7-track::before {
  content: "";
  position: absolute;
  left: 50%;
  top: -0.1rem;
  bottom: -0.1rem;
  width: 1px;
  background: var(--rule);
}

.mag7-bar {
  position: absolute;
  top: 0.3rem;
  height: 0.75rem;
}

.mag7-bar.up {
  left: 50%;
  background: var(--up);
  border-radius: 0 3px 3px 0;
}

.mag7-bar.down {
  right: 50%;
  background: var(--down);
  border-radius: 3px 0 0 3px;
}

.mag7-val {
  font-family: var(--data);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.mag7-val.up { color: var(--up); }
.mag7-val.down { color: var(--down); }

.mag7-price {
  position: absolute;
  right: 4.9rem;
  font-family: var(--data);
  font-size: 0.7rem;
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
  opacity: 0;
  transition: opacity 120ms ease;
  pointer-events: none;
  background: var(--paper);
  padding: 0 0.3rem;
}

.mag7-row:hover .mag7-price { opacity: 1; }

.mag7-axis {
  display: grid;
  grid-template-columns: 3.6rem 1fr 4.2rem;
  gap: 0 0.7rem;
  margin-top: 0.3rem;
}

.mag7-axis .lbl {
  grid-column: 2;
  display: flex;
  justify-content: space-between;
  font-family: var(--data);
  font-size: 0.62rem;
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
}

.mag7-foot {
  margin-top: 0.55rem;
  font-size: 0.78rem;
  color: var(--ink-mid);
  text-wrap: pretty;
}

/* -------------------------------------------------------------- watchlist */

.wl { margin-top: 0.9rem; }

.wl-grid { display: flex; flex-wrap: wrap; gap: 0.4rem; }

.wl-chip {
  font-family: var(--data);
  font-size: 0.76rem;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--rule);
  border-radius: 2px;
  color: var(--ink-faint);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.wl-chip.hit {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-soft);
  font-weight: 500;
}

.wl-chip .cnt {
  font-size: 0.62rem;
  background: var(--accent);
  color: var(--paper);
  border-radius: 999px;
  min-width: 1rem;
  height: 1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.wl-foot { margin-top: 0.6rem; font-size: 0.78rem; color: var(--ink-mid); }

/* -------------------------------------------------------------------- tape */

.tape-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
  gap: 0;
  margin-top: 0.5rem;
}

.tape-cell { padding: 0.7rem 0.9rem 0.7rem 0; border-bottom: 1px solid var(--rule-soft); }
.tape-cell .k { font-size: 0.72rem; color: var(--ink-faint); }
.tape-cell .v {
  font-family: var(--data);
  font-size: 1.05rem;
  font-variant-numeric: tabular-nums;
  margin-top: 0.15rem;
}
.tape-cell .d { font-family: var(--data); font-size: 0.72rem; font-variant-numeric: tabular-nums; }

.d.up { color: var(--up); }
.d.down { color: var(--down); }
.d.flat { color: var(--ink-faint); }

/* ------------------------------------------------------------------- items */

.item {
  display: grid;
  grid-template-columns: 2.4rem 1fr;
  gap: 0 0.9rem;
  padding: 1.5rem 0;
  border-bottom: 1px solid var(--rule-soft);
  scroll-margin-top: 1rem;
}

.item .rank {
  font-family: var(--data);
  font-size: 0.95rem;
  font-variant-numeric: tabular-nums;
  color: var(--ink-faint);
  padding-top: 0.28rem;
  border-top: 2px solid currentColor;
  align-self: start;
}

.item.t1 .rank { color: var(--tier-1); }
.item.t2 .rank { color: var(--tier-2); }
.item.t3 .rank { color: var(--tier-3); }

.item h3 {
  font-family: var(--display);
  font-weight: 600;
  font-size: 1.42rem;
  line-height: 1.25;
  letter-spacing: -0.01em;
  margin: 0;
  text-wrap: balance;
}

.item.t3 h3 { font-size: 1.1rem; font-weight: 500; }

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.55rem;
}

.tag {
  font-family: var(--data);
  font-size: 0.65rem;
  letter-spacing: 0.05em;
  color: var(--ink-mid);
  border: 1px solid var(--rule);
  border-radius: 2px;
  padding: 0.08rem 0.4rem;
}

.tag.tk { color: var(--accent); border-color: var(--accent); font-weight: 500; }

.age {
  font-family: var(--data);
  font-size: 0.65rem;
  letter-spacing: 0.05em;
  padding: 0.08rem 0.4rem;
  border-radius: 2px;
}

.age.fresh { color: var(--up); background: var(--up-wash); }
.age.aging { color: var(--ink-mid); background: var(--paper-sunk); }
.age.stale { color: var(--ink-faint); border: 1px dashed var(--rule); }

.item p { margin: 0.7rem 0 0; text-wrap: pretty; }

.why {
  margin-top: 0.85rem;
  padding: 0.7rem 0.9rem;
  background: var(--paper-sunk);
  border-left: 2px solid var(--accent);
}

.why .lbl {
  font-family: var(--data);
  font-size: 0.63rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent);
  display: block;
  margin-bottom: 0.2rem;
}

.why p { margin: 0; font-size: 0.94rem; }

.impact { margin-top: 0.65rem; font-family: var(--data); font-size: 0.73rem; color: var(--ink-mid); }
.impact::before { content: "\\2192\\00a0"; color: var(--ink-faint); }

.srcs { margin-top: 0.7rem; }

.srcs summary {
  font-family: var(--data);
  font-size: 0.68rem;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
  cursor: pointer;
  list-style: none;
}

.srcs summary::-webkit-details-marker { display: none; }
.srcs summary::before { content: "+ "; }
.srcs[open] summary::before { content: "\\2212 "; }
.srcs summary:hover { color: var(--accent); }

.srcs ul {
  margin: 0.4rem 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem 0.9rem;
}

.srcs a {
  font-family: var(--data);
  font-size: 0.72rem;
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid var(--accent-soft);
}

.srcs a:hover { border-bottom-color: var(--accent); }

/* ---------------------------------------------------------------- calendar */

.cal-scroll { overflow-x: auto; margin-top: 0.4rem; }

table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }

td {
  padding: 0.6rem 0.7rem 0.6rem 0;
  border-bottom: 1px solid var(--rule-soft);
  vertical-align: top;
}

td.when { font-family: var(--data); font-size: 0.8rem; white-space: nowrap; color: var(--ink-mid); }
td.time {
  font-family: var(--data);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--ink-faint);
}
td.w { text-align: right; white-space: nowrap; }

.w span { font-family: var(--data); font-size: 0.63rem; letter-spacing: 0.08em; padding: 0.1rem 0.4rem; border-radius: 2px; }
.w-high { background: var(--accent-soft); color: var(--accent); }
.w-mid { color: var(--ink-mid); }
.w-low { color: var(--ink-faint); }

/* ---------------------------------------------------------------- colophon */

.colophon {
  margin-top: 3.5rem;
  padding-top: 1rem;
  border-top: 2px solid var(--ink);
  font-family: var(--data);
  font-size: 0.68rem;
  line-height: 1.7;
  color: var(--ink-faint);
  letter-spacing: 0.02em;
}

a:focus-visible, summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

@media (max-width: 520px) {
  .item { grid-template-columns: 1.8rem 1fr; gap: 0 0.7rem; }
  .item h3 { font-size: 1.22rem; }
  .mag7-row, .mag7-axis { grid-template-columns: 3.1rem 1fr 3.7rem; }
  .mag7-price { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""


# ----------------------------------------------------------------- mag 7 chart

def render_mag7(m7):
    """七只权重股的单日涨跌，横向发散条形图。

    一条零轴，一个对称标度。方向和带符号的数值标签是颜色之外的第二重编码，
    所以红绿对色觉障碍读者不构成唯一信息来源。
    """
    rows = sorted(m7["rows"], key=lambda r: r["change_pct"], reverse=True)
    peak = max(abs(r["change_pct"]) for r in rows)
    # 标度取整到 0.5 的倍数，让轴标签是个整齐的数。
    domain = max(0.5, (int(peak / 0.5) + 1) * 0.5)

    out = ['<section class="mag7">']
    for r in rows:
        v = r["change_pct"]
        d = "up" if v >= 0 else "down"
        width = abs(v) / domain * 50.0          # 半幅占 50%
        sign = "+" if v >= 0 else ""
        out.append('<div class="mag7-row">')
        out.append(f'<div class="mag7-tick">{e(r["ticker"])}</div>')
        out.append('<div class="mag7-track">')
        out.append(f'<div class="mag7-bar {d}" style="width:{width:.2f}%"></div>')
        out.append("</div>")
        out.append(f'<div class="mag7-price">${e(r["price"])}</div>')
        out.append(f'<div class="mag7-val {d}">{sign}{v:.2f}%</div>')
        out.append("</div>")

    out.append('<div class="mag7-axis"><div class="lbl">')
    out.append(f"<span>−{domain:.1f}%</span><span>0</span><span>+{domain:.1f}%</span>")
    out.append("</div></div>")

    if m7.get("note"):
        out.append(f'<p class="mag7-foot">{e(m7["note"])}</p>')
    out.append("</section>")
    return "\n".join(out)


# ------------------------------------------------------------ watchlist panel

def render_watchlist(symbols, items):
    """自选股面板。有新闻的代码点亮并可跳到对应条目。"""
    hits = {}
    for it in items:
        for tk in it.get("tickers", []):
            hits.setdefault(tk, []).append(it["rank"])

    out = ['<section class="wl"><div class="wl-grid">']
    for s in symbols:
        got = hits.get(s)
        if got:
            out.append(
                f'<a class="wl-chip hit" href="#item-{got[0]}">{e(s)}'
                f'<span class="cnt">{len(got)}</span></a>'
            )
        else:
            out.append(f'<span class="wl-chip">{e(s)}</span>')
    out.append("</div>")

    n = len(hits)
    if n:
        out.append(
            f'<p class="wl-foot">你的 {len(symbols)} 只自选股里，'
            f"今天有 {n} 只出现在新闻中，点代码跳到对应条目。</p>"
        )
    else:
        out.append(
            f'<p class="wl-foot">你的 {len(symbols)} 只自选股今天都没有单独的新闻。</p>'
        )
    out.append("</section>")
    return "\n".join(out)


# -------------------------------------------------------------------- HTML

def render_html(d, cfg):
    items = d["items"]
    today = d["date"]
    parts = []

    parts.append("<title>Morning Tape</title>")
    parts.append(
        '<link rel="stylesheet" '
        'href="https://fonts.googleapis.com/css2?'
        "family=Newsreader:ital,wght@0,400;0,500;0,600;1,400&"
        "family=IBM+Plex+Sans:wght@400;500;600&"
        'family=IBM+Plex+Mono:wght@400;500&display=swap">'
    )
    parts.append(f"<style>{CSS}</style>")
    parts.append('<div class="sheet">')

    # masthead
    parts.append('<header class="masthead">')
    parts.append("<h1>Morning <em>Tape</em></h1>")
    parts.append('<div class="stamp">')
    parts.append(f'<span><b>{e(today)}</b> {e(d["weekday"])}</span>')
    parts.append(f'<span>{e(d["edition"])}</span>')
    parts.append(f'<span>扫描 <b>{d["scanned"]}</b> 篇 · 保留 <b>{d["kept"]}</b> 条</span>')
    parts.append(f'<span>生成于 {e(d["generated_at"])}</span>')
    parts.append("</div></header>")

    parts.append(f'<p class="lede">{e(d["thesis"])}</p>')

    # mag 7
    if d.get("mag7"):
        parts.append('<div class="sec-head t2"><h2>七巨头单日涨跌</h2>')
        parts.append(f'<span class="asof">{e(d["mag7"]["asof"])}</span></div>')
        parts.append(render_mag7(d["mag7"]))

    # watchlist
    wl = cfg.get("watchlist", {}).get("symbols", [])
    if wl:
        parts.append('<div class="sec-head t2"><h2>自选股</h2>')
        parts.append(f'<span class="n">{len(wl)}</span></div>')
        parts.append(render_watchlist(wl, items))

    # tape
    tape = d["tape"]
    parts.append('<div class="sec-head t2"><h2>指数与利率</h2>')
    parts.append(f'<span class="asof">{e(tape["asof"])}</span></div>')
    parts.append('<section><div class="tape-grid">')
    for r in tape["rows"]:
        parts.append('<div class="tape-cell">')
        parts.append(f'<div class="k">{e(r["name"])}</div>')
        parts.append(f'<div class="v">{e(r["value"])}</div>')
        parts.append(f'<div class="d {e(r["dir"])}">{e(r["change"])}</div>')
        parts.append("</div>")
    parts.append("</div></section>")

    # items by tier
    for idx, tier in enumerate(TIER_ORDER, start=1):
        group = [i for i in items if i["tier"] == tier]
        if not group:
            continue
        parts.append(f'<div class="sec-head t{idx}"><h2>{e(TIER_LABEL[tier])}</h2>')
        parts.append(f'<span class="n">{len(group)}</span></div>')
        for it in group:
            parts.append(f'<article class="item t{idx}" id="item-{it["rank"]}">')
            parts.append(f'<div class="rank">{it["rank"]:02d}</div>')
            parts.append("<div>")
            parts.append(f'<h3>{e(it["headline"])}</h3>')

            parts.append('<div class="meta">')
            label, cls = age_badge(it.get("published"), today)
            if label:
                parts.append(f'<span class="age {cls}">{e(label)}</span>')
            for tk in it.get("tickers", []):
                parts.append(f'<span class="tag tk">{e(tk)}</span>')
            for s in it.get("sectors", []):
                parts.append(f'<span class="tag">{e(s)}</span>')
            parts.append("</div>")

            parts.append(f'<p>{e(it["body"])}</p>')
            if it.get("why"):
                parts.append('<div class="why"><span class="lbl">为什么重要</span>')
                parts.append(f'<p>{e(it["why"])}</p></div>')
            if it.get("impact"):
                parts.append(f'<div class="impact">{e(it["impact"])}</div>')
            if it.get("sources"):
                n = len(it["sources"])
                parts.append(f'<details class="srcs"><summary>{n} 个来源</summary><ul>')
                for s in it["sources"]:
                    parts.append(
                        f'<li><a href="{e(s["url"])}" target="_blank" '
                        f'rel="noopener">{e(s["name"])}</a></li>'
                    )
                parts.append("</ul></details>")
            parts.append("</div></article>")

    # calendar
    parts.append('<div class="sec-head t2"><h2>接下来要盯的时间点</h2></div>')
    parts.append('<section class="cal-scroll"><table><tbody>')
    for c in d["calendar"]:
        w = c.get("weight", "low")
        parts.append("<tr>")
        parts.append(f'<td class="when">{e(c["when"])}</td>')
        parts.append(f'<td class="time">{e(c["time"])}</td>')
        parts.append(f'<td>{e(c["event"])}</td>')
        parts.append(f'<td class="w"><span class="w-{e(w)}">{e(WEIGHT_LABEL[w])}</span></td>')
        parts.append("</tr>")
    parts.append("</tbody></table></section>")

    parts.append(
        '<footer class="colophon">'
        "Taurient Lite · 由 Claude Code 每个交易日早晨自动生成<br>"
        "覆盖范围：美股与宏观、科技与 AI 行业、影响能源与通胀的地缘事件<br>"
        "涨跌色经过色觉障碍可辨度校验，方向与带符号数值是颜色之外的第二重编码<br>"
        "这是新闻摘要，不是投资建议。数字以原始来源为准。"
        "</footer>"
    )
    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------- Markdown

def render_md(d, cfg):
    today = d["date"]
    L = [f"# Morning Tape — {today} ({d['weekday']})", ""]
    L.append(f"> {d['thesis']}")
    L.append("")
    L.append(
        f"*{d['edition']} · 扫描 {d['scanned']} 篇，保留 {d['kept']} 条 "
        f"· 生成于 {d['generated_at']}*"
    )
    L.append("")

    if d.get("mag7"):
        L.append(f"## 七巨头单日涨跌 — {d['mag7']['asof']}")
        L.append("")
        L.append("| 代码 | 价格 | 涨跌 |")
        L.append("|---|---|---|")
        for r in sorted(d["mag7"]["rows"], key=lambda x: x["change_pct"], reverse=True):
            sign = "+" if r["change_pct"] >= 0 else ""
            L.append(f"| {r['ticker']} | `${r['price']}` | `{sign}{r['change_pct']:.2f}%` |")
        L.append("")
        if d["mag7"].get("note"):
            L.append(d["mag7"]["note"])
            L.append("")

    wl = cfg.get("watchlist", {}).get("symbols", [])
    if wl:
        hits = sorted({t for it in d["items"] for t in it.get("tickers", []) if t in wl})
        L.append("## 自选股")
        L.append("")
        L.append(f"关注中：`{'` `'.join(wl)}`")
        L.append("")
        L.append(f"今天有新闻：{'、'.join(hits) if hits else '无'}")
        L.append("")

    L.append(f"## 指数与利率 — {d['tape']['asof']}")
    L.append("")
    L.append("| | 水平 | 变化 |")
    L.append("|---|---|---|")
    for r in d["tape"]["rows"]:
        L.append(f"| {r['name']} | `{r['value']}` | {r['change']} |")
    L.append("")

    for tier in TIER_ORDER:
        group = [i for i in d["items"] if i["tier"] == tier]
        if not group:
            continue
        L.append(f"## {TIER_LABEL[tier]}")
        L.append("")
        for it in group:
            L.append(f"### {it['rank']:02d}. {it['headline']}")
            bits = []
            label, _ = age_badge(it.get("published"), today)
            if label:
                bits.append(label)
            bits += it.get("tickers", []) + it.get("sectors", [])
            if bits:
                L.append(f"`{'` `'.join(bits)}`")
            L.append("")
            L.append(it["body"])
            L.append("")
            if it.get("why"):
                L.append(f"**为什么重要：** {it['why']}")
                L.append("")
            if it.get("impact"):
                L.append(f"**影响面：** {it['impact']}")
                L.append("")
            if it.get("sources"):
                srcs = " · ".join(f"[{s['name']}]({s['url']})" for s in it["sources"])
                L.append(f"来源：{srcs}")
                L.append("")

    L.append("## 接下来要盯的时间点")
    L.append("")
    L.append("| 时间 | 时刻 | 事件 | 权重 |")
    L.append("|---|---|---|---|")
    for c in d["calendar"]:
        L.append(
            f"| {c['when']} | {c['time']} | {c['event']} "
            f"| {WEIGHT_LABEL[c.get('weight','low')]} |"
        )
    L.append("")
    L.append("---")
    L.append("*Taurient Lite。新闻摘要，不是投资建议。*")
    return "\n".join(L) + "\n"


def main():
    if len(sys.argv) > 1:
        date = sys.argv[1]
    else:
        found = sorted(BRIEFS.glob("*.json"))
        if not found:
            sys.exit("briefs/ 里没有任何 JSON")
        date = found[-1].stem

    src = BRIEFS / f"{date}.json"
    if not src.exists():
        sys.exit(f"找不到 {src}")

    d = json.loads(src.read_text(encoding="utf-8"))
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))

    SITE.mkdir(exist_ok=True)
    out_html = SITE / "index.html"
    out_html.write_text(render_html(d, cfg), encoding="utf-8")

    out_md = BRIEFS / f"{date}.md"
    out_md.write_text(render_md(d, cfg), encoding="utf-8")

    # 周一和周日的前瞻版覆盖的是整个周末乃至上一周，所以允许单期简报
    # 用 max_age_days 覆写默认上限。平日版仍然按 config 里的严格值判。
    limit = d.get("max_age_days", cfg["freshness"]["max_age_days"])
    stale = [
        i["rank"] for i in d["items"]
        if (a := age_days(i.get("published"), date)) is not None and a > limit
    ]

    print(f"HTML  -> {out_html}  ({out_html.stat().st_size:,} bytes)")
    print(f"MD    -> {out_md}  ({out_md.stat().st_size:,} bytes)")
    print(f"条目  -> {len(d['items'])} 条")
    if stale:
        print(f"提醒  -> 第 {stale} 条超过了 {limit} 天的时效上限")


if __name__ == "__main__":
    main()
