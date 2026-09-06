#!/usr/bin/env python3
"""Render a daily brief JSON into the dashboard HTML and a Markdown archive.

Usage:  python3 render.py 2026-09-06
        python3 render.py            # newest brief in briefs/
"""

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRIEFS = ROOT / "briefs"
SITE = ROOT / "site"

TIER_LABEL = {
    "must-read": "必读",
    "worth-knowing": "值得知道",
    "noise": "背景噪音",
}
TIER_ORDER = ["must-read", "worth-knowing", "noise"]
WEIGHT_LABEL = {"high": "关键", "mid": "留意", "low": "常规"}


def e(s):
    return html.escape(str(s), quote=True)


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
  --up:           #0B6E4F;
  --down:         #A82C24;
  --tier-1:       #A82C24;
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
    --up:          #3FBF8F;
    --down:        #E8756A;
    --tier-1:      #E8756A;
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
  --up:          #3FBF8F;
  --down:        #E8756A;
  --tier-1:      #E8756A;
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
  max-width: 44rem;
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

.masthead h1 em {
  font-style: italic;
  color: var(--accent);
}

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

/* -------------------------------------------------------------------- lede */

.lede {
  font-family: var(--display);
  font-size: 1.3rem;
  line-height: 1.5;
  margin: 1.6rem 0 0;
  padding-left: 1rem;
  border-left: 3px solid var(--accent);
  text-wrap: pretty;
}

/* -------------------------------------------------------------------- tape */

.tape { margin-top: 2rem; }

.tape-head {
  font-family: var(--data);
  font-size: 0.65rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
  padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--rule);
}

.tape-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
  gap: 0;
}

.tape-cell {
  padding: 0.7rem 0.9rem 0.7rem 0;
  border-bottom: 1px solid var(--rule-soft);
}

.tape-cell .k {
  font-size: 0.72rem;
  color: var(--ink-faint);
  letter-spacing: 0.02em;
}

.tape-cell .v {
  font-family: var(--data);
  font-size: 1.05rem;
  font-variant-numeric: tabular-nums;
  margin-top: 0.15rem;
}

.tape-cell .d {
  font-family: var(--data);
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
}

.d.up { color: var(--up); }
.d.down { color: var(--down); }

/* ------------------------------------------------------------------- tiers */

.tier-head {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  margin: 2.8rem 0 0.2rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--rule);
}

.tier-head h2 {
  font-family: var(--body);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  margin: 0;
}

.tier-head .n {
  font-family: var(--data);
  font-size: 0.72rem;
  color: var(--ink-faint);
}

.t1 h2 { color: var(--tier-1); }
.t2 h2 { color: var(--tier-2); }
.t3 h2 { color: var(--tier-3); }

/* ------------------------------------------------------------------- items */

.item {
  display: grid;
  grid-template-columns: 2.4rem 1fr;
  gap: 0 0.9rem;
  padding: 1.5rem 0;
  border-bottom: 1px solid var(--rule-soft);
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

.tags {
  display: flex;
  flex-wrap: wrap;
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

.impact {
  margin-top: 0.65rem;
  font-family: var(--data);
  font-size: 0.73rem;
  color: var(--ink-mid);
}

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

.cal { margin-top: 3rem; }

.cal h2 {
  font-family: var(--body);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  margin: 0 0 0.35rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--rule);
}

.cal-scroll { overflow-x: auto; }

table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }

td {
  padding: 0.6rem 0.7rem 0.6rem 0;
  border-bottom: 1px solid var(--rule-soft);
  vertical-align: top;
}

td.when {
  font-family: var(--data);
  font-size: 0.8rem;
  white-space: nowrap;
  color: var(--ink-mid);
}

td.time {
  font-family: var(--data);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--ink-faint);
}

td.w { text-align: right; white-space: nowrap; }

.w span {
  font-family: var(--data);
  font-size: 0.63rem;
  letter-spacing: 0.08em;
  padding: 0.1rem 0.4rem;
  border-radius: 2px;
}

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

@media (max-width: 480px) {
  .item { grid-template-columns: 1.8rem 1fr; gap: 0 0.7rem; }
  .item h3 { font-size: 1.22rem; }
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""


# -------------------------------------------------------------------- HTML

def render_html(d):
    items = d["items"]
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
    parts.append(f'<h1>Morning <em>Tape</em></h1>')
    parts.append('<div class="stamp">')
    parts.append(f'<span><b>{e(d["date"])}</b> {e(d["weekday"])}</span>')
    parts.append(f'<span>{e(d["edition"])}</span>')
    parts.append(f'<span>扫描 <b>{d["scanned"]}</b> 篇 · 保留 <b>{d["kept"]}</b> 条</span>')
    parts.append(f'<span>生成于 {e(d["generated_at"])}</span>')
    parts.append("</div></header>")

    parts.append(f'<p class="lede">{e(d["thesis"])}</p>')

    # tape
    tape = d["tape"]
    parts.append('<section class="tape">')
    parts.append(f'<div class="tape-head">{e(tape["asof"])}</div>')
    parts.append('<div class="tape-grid">')
    for r in tape["rows"]:
        parts.append('<div class="tape-cell">')
        parts.append(f'<div class="k">{e(r["name"])}</div>')
        parts.append(f'<div class="v">{e(r["value"])}</div>')
        parts.append(f'<div class="d {e(r["dir"])}">{e(r["change"])}</div>')
        parts.append("</div>")
    parts.append("</div></section>")

    # items grouped by tier
    for idx, tier in enumerate(TIER_ORDER, start=1):
        group = [i for i in items if i["tier"] == tier]
        if not group:
            continue
        parts.append(f'<div class="tier-head t{idx}">')
        parts.append(f'<h2>{e(TIER_LABEL[tier])}</h2>')
        parts.append(f'<span class="n">{len(group)}</span>')
        parts.append("</div>")
        for it in group:
            parts.append(f'<article class="item t{idx}">')
            parts.append(f'<div class="rank">{it["rank"]:02d}</div>')
            parts.append("<div>")
            parts.append(f'<h3>{e(it["headline"])}</h3>')
            if it.get("sectors"):
                parts.append('<div class="tags">')
                for s in it["sectors"]:
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
    parts.append('<section class="cal"><h2>接下来要盯的时间点</h2>')
    parts.append('<div class="cal-scroll"><table><tbody>')
    for c in d["calendar"]:
        w = c.get("weight", "low")
        parts.append("<tr>")
        parts.append(f'<td class="when">{e(c["when"])}</td>')
        parts.append(f'<td class="time">{e(c["time"])}</td>')
        parts.append(f"<td>{e(c['event'])}</td>")
        parts.append(f'<td class="w"><span class="w-{e(w)}">{e(WEIGHT_LABEL[w])}</span></td>')
        parts.append("</tr>")
    parts.append("</tbody></table></div></section>")

    parts.append(
        '<footer class="colophon">'
        "Taurient Lite · 由 Claude Code 每个交易日早晨自动生成<br>"
        "覆盖范围：美股与宏观、科技与 AI 行业<br>"
        "这是新闻摘要，不是投资建议。数字以原始来源为准。"
        "</footer>"
    )
    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------- Markdown

def render_md(d):
    L = [f"# Morning Tape — {d['date']} ({d['weekday']})", ""]
    L.append(f"> {d['thesis']}")
    L.append("")
    L.append(f"*{d['edition']} · 扫描 {d['scanned']} 篇，保留 {d['kept']} 条 · 生成于 {d['generated_at']}*")
    L.append("")
    L.append(f"## 行情快照 — {d['tape']['asof']}")
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
            if it.get("sectors"):
                L.append(f"`{'` `'.join(it['sectors'])}`")
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
        L.append(f"| {c['when']} | {c['time']} | {c['event']} | {WEIGHT_LABEL[c.get('weight','low')]} |")
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

    SITE.mkdir(exist_ok=True)
    out_html = SITE / "index.html"
    out_html.write_text(render_html(d), encoding="utf-8")

    out_md = BRIEFS / f"{date}.md"
    out_md.write_text(render_md(d), encoding="utf-8")

    print(f"HTML  -> {out_html}  ({out_html.stat().st_size:,} bytes)")
    print(f"MD    -> {out_md}  ({out_md.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
