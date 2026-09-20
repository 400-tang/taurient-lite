"""设计 token 与样式表生成。

把颜色做成数据而不是写死在 CSS 字符串里，是为了让「每个 token 都必须在裸
``:root`` 里声明」这条规则**由构造保证**，而不是靠人眼检查。
:func:`build_css` 会遍历 :data:`TOKENS` 生成三个块：

* 裸 ``:root``：完整的亮色调色板。任何 token 只在媒体查询里定义，
  就会在「跟随系统」且系统为亮色时整个失效，这是暗色简报最常见的崩法。
* ``@media (prefers-color-scheme: dark)`` 且 ``:root:not([data-theme="light"])``：
  读者没有显式选择时跟随系统，但显式选了亮色就不生效。
* ``:root[data-theme="dark"]``：读者显式选了暗色，压过系统设置。

涨跌色是**语义色**，与钴蓝品牌色严格分开，且跑过色觉障碍可辨度校验
（亮色模式 deutan ΔE 8.1，全项通过；暗色模式 ΔE 7.5，落在需要二次编码的
区间，页面上用方向箭头、带符号数值和强度格子三重补足）。
"""

from __future__ import annotations

from typing import Sequence

# --------------------------------------------------------------------------- 颜色
#
# 每个条目是 (亮色, 暗色)。暗色不是亮色的机械反转：中性色带一点冷调偏向
# 品牌蓝，暗色下的强调色要提亮才能在深色底上保住对比度。

TOKENS: dict[str, tuple[str, str]] = {
    # 底色。paper-raised 是微卡片的抬升面，比正文底略亮（暗色下略亮一档）。
    "paper": ("#EDEFF0", "#0E1317"),
    "paper-raised": ("#F6F7F8", "#151C22"),
    "paper-sunk": ("#E3E6E8", "#161C21"),
    # 分隔线三档：主分隔、次分隔、发丝线。
    "rule": ("#C6CCD0", "#2C353C"),
    "rule-soft": ("#D8DDE0", "#212930"),
    "rule-hair": ("#E5E8EA", "#1B2228"),
    # 文字三档。
    "ink": ("#131A21", "#DDE3E7"),
    "ink-mid": ("#4A555E", "#9AA6AE"),
    "ink-faint": ("#79848C", "#6C7982"),
    # 品牌钴蓝，只用在结构与交互上，绝不参与涨跌语义。
    "accent": ("#1F3FCB", "#8AA0FF"),
    "accent-soft": ("#DDE2F7", "#1B2340"),
    "accent-strong": ("#16309E", "#AEBEFF"),
    # 涨跌语义色。
    "up": ("#12916A", "#1FAD82"),
    "down": ("#C4342B", "#E4634F"),
    "flat": ("#79848C", "#6C7982"),
    "up-wash": ("#D6EDE4", "#14312A"),
    "down-wash": ("#F7DEDB", "#34201D"),
    "flat-wash": ("#E3E6E8", "#1B2228"),
    # 分层标识色。必读借用跌色的红，是「需要注意」而非「利空」的语义，
    # 但两者在页面上从不相邻出现，不会混淆。
    "tier-1": ("#C4342B", "#E4634F"),
    "tier-2": ("#1F3FCB", "#8AA0FF"),
    "tier-3": ("#79848C", "#6C7982"),
    # ---------------------------------------------------------------- 热力色阶
    #
    # 热力图跟随主题，两套色阶**方向相反**：亮色模式下低幅度接近纸张底色、
    # 高幅度压深；暗色模式下低幅度暗而浊、高幅度亮而饱和。两边都是「幅度
    # 越大、离底色越远」，只是底色一个亮一个暗。
    #
    # 这里曾经做成一块不跟随主题的深色「行情板」，理由是白底上的浅绿浅红
    # 在小色块上难分辨。做出来一看，它在纸张版面里像一块异物，整页最抢眼
    # 的东西变成了一个次要板块。分辨率的问题另有解法（每块加一条发丝边框
    # 把边界勾出来，见 ``heat-edge``），而版面不协调没有解法。
    #
    # 低档的红两边都刻意偏棕/偏粉而不是正红：小幅下跌如果用正红，版面上会
    # 出现一片和大跌同样刺眼的红，而它们的意义相差一个数量级。
    #
    # **每一档的色值都跑过 WCAG 对比度校验**，配套的文字色见下面的
    # ``heat-on-*``，``tests.test_heatmap.TestContrast`` 会按公式重算一遍。
    "heat-board": ("#E9ECEE", "#0B0F13"),
    "heat-card": ("#F6F7F8", "#141A20"),
    "heat-flat": ("#DCE0E3", "#1F262D"),
    # 色块之间的发丝边框。亮色模式下把小幅度的浅色块勾出边界——不加的话
    # +0.21% 这种块淡得和卡片底色分不开，看起来像空格子。暗色模式下取卡片
    # 底色，等于不画。
    "heat-edge": ("#D7DCDF", "#141A20"),
    "heat-u1": ("#DDEFE6", "#0F3325"),
    "heat-u2": ("#B4E0CD", "#165639"),
    "heat-u3": ("#78C5A6", "#1C7A4D"),
    "heat-u4": ("#2E9C74", "#24A162"),
    "heat-u5": ("#0B6F4E", "#3AC776"),
    "heat-d1": ("#FAE0DB", "#3A201C"),
    "heat-d2": ("#F4C3B9", "#5C2723"),
    "heat-d3": ("#E79683", "#87332A"),
    "heat-d4": ("#C24E36", "#B24232"),
    "heat-d5": ("#A32E20", "#D95833"),
    "heat-ink": ("#10231C", "#F2F6F8"),
    "heat-ink-dim": ("#6B757D", "#8C9AA5"),
}

#: 色块上文字的默认色与反转色。亮色模式默认深字、反转成白字；
#: 暗色模式正好倒过来。
HEAT_INK: tuple[str, str] = ("#10231C", "#F2F6F8")
HEAT_INK_FLIP: tuple[str, str] = ("#FFFFFF", "#06110B")

#: 需要反转文字色的档位，两套主题各一份。
#:
#: **两份名单不一样，这不是笔误。** 亮色色阶到 u5 才压得够深，而暗色色阶
#: 从 u4 就亮到白字压不住了。判据是同一条：默认文字色在该底色上的对比度
#: 掉到 4.5:1 以下就翻。``tests.test_heatmap`` 按 WCAG 公式重算这两份名单，
#: 所以名单写错了测试会红，不会靠人眼把关。
HEAT_INVERT_LIGHT: tuple[str, ...] = ("u5", "d4", "d5")
HEAT_INVERT_DARK: tuple[str, ...] = ("u4", "u5", "d5")

#: 所有色阶档名。定义在这里而不是靠近 CSS，是因为下面要用它生成
#: ``heat-on-*`` 这一批 token，而 token 必须在 :data:`TOKENS` 里就位。
HEAT_LEVEL_NAMES: tuple[str, ...] = tuple(
    [f"u{i}" for i in range(1, 6)] + [f"d{i}" for i in range(1, 6)] + ["flat"]
)

# 每一档配一个文字色 token。生成而不是手写十一行，是因为「哪些档要反转」
# 已经由上面两份名单表达了，手写等于把同一个事实抄第二遍。
for _level in HEAT_LEVEL_NAMES:
    TOKENS[f"heat-on-{_level}"] = (
        HEAT_INK_FLIP[0] if _level in HEAT_INVERT_LIGHT else HEAT_INK[0],
        HEAT_INK_FLIP[1] if _level in HEAT_INVERT_DARK else HEAT_INK[1],
    )
del _level

#: 字体族。Newsreader 是为新闻正文优化的衬线体，不是常见的展示型衬线；
#: IBM Plex 两支给正文和数据，中文回退到系统黑体与宋体。
FONT_STACKS = {
    "display": '"Newsreader", Georgia, "Songti SC", "Noto Serif CJK SC", serif',
    "body": '"IBM Plex Sans", "PingFang SC", "Hiragino Sans GB", '
    '"Microsoft YaHei", system-ui, sans-serif',
    "data": '"IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace',
}

#: 字号阶梯，小三度（1.2）。写成 token 而不是散落在各处的魔数，
#: 保证整页只有这几个尺寸。
TYPE_SCALE = {
    "t-2xs": "0.625rem",
    "t-xs": "0.6875rem",
    "t-sm": "0.8125rem",
    "t-base": "0.9375rem",
    "t-md": "1.0625rem",
    "t-lg": "1.3125rem",
    "t-xl": "1.5rem",
    "t-2xl": "clamp(2rem, 5.5vw, 2.75rem)",
}

#: 字间距。全大写的小标签必须放宽，衬线大标题必须收紧。
TRACKING = {
    "track-label": "0.14em",
    "track-mono": "0.04em",
    "track-display": "-0.015em",
}

GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;"
    "1,6..72,400&"
    "family=IBM+Plex+Sans:wght@400;450;500;600&"
    "family=IBM+Plex+Mono:wght@400;500&display=swap"
)


def _palette_block(index: int, indent: str = "  ") -> str:
    """生成一套调色板的变量声明。``index`` 0 是亮色，1 是暗色。"""
    return "\n".join(
        f"{indent}--{name}: {values[index]};" for name, values in TOKENS.items()
    )


def build_palette_css() -> str:
    """三个主题块。顺序即优先级，不能调换。"""
    light = _palette_block(0)
    dark_media = _palette_block(1, indent="    ")
    dark_stamp = _palette_block(1)

    fonts = "\n".join(f"  --font-{k}: {v};" for k, v in FONT_STACKS.items())
    sizes = "\n".join(f"  --{k}: {v};" for k, v in TYPE_SCALE.items())
    tracks = "\n".join(f"  --{k}: {v};" for k, v in TRACKING.items())

    return f""":root {{
{light}

{fonts}

{sizes}

{tracks}

  --measure: 34rem;          /* 正文单行约 65 个西文字符 */
  --gutter: 1.5rem;
  --rail: 2.6rem;            /* 左侧序号轨的宽度 */
}}

/* 读者没有显式选主题时跟随系统；显式选了亮色则这里不生效。 */
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{dark_media}
  }}
}}

/* 读者显式选了暗色，压过系统设置。 */
:root[data-theme="dark"] {{
{dark_stamp}
}}"""


# --------------------------------------------------------------------------- 版式

LAYOUT_CSS = """
*, *::before, *::after { box-sizing: border-box; }

body {
  background: var(--paper);
  color: var(--ink);
  font-family: var(--font-body);
  font-size: var(--t-base);
  font-weight: 400;
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.sheet {
  max-width: 48rem;
  margin: 0 auto;
  padding: 2.75rem var(--gutter) 5rem;
}

/* 全大写小标签的通用形态。整页所有 eyebrow 都走这一个类。 */
.label {
  font-family: var(--font-body);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}

.mono {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  letter-spacing: var(--track-mono);
}

/* ---------------------------------------------------------------- masthead */

.masthead {
  border-bottom: 2px solid var(--ink);
  padding-bottom: 0.8rem;
}

.masthead h1 {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: var(--t-2xl);
  line-height: 1.02;
  letter-spacing: var(--track-display);
  margin: 0;
  text-wrap: balance;
}

.masthead h1 em {
  font-style: italic;
  font-weight: 400;
  color: var(--accent);
}

.stamp {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem 1.15rem;
  margin-top: 0.95rem;
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--ink-faint);
}

.stamp b { color: var(--ink-mid); font-weight: 500; }

.lede {
  font-family: var(--font-display);
  font-size: var(--t-lg);
  font-weight: 400;
  line-height: 1.5;
  margin: 1.7rem 0 0;
  padding-left: 1.05rem;
  border-left: 3px solid var(--accent);
  text-wrap: pretty;
  max-width: var(--measure);
}

/* ----------------------------------------------------------- section heads */

.sec-head {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  margin: 3rem 0 0.2rem;
  padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--rule);
}

.sec-head h2 { margin: 0; }
.sec-head .n { font-family: var(--font-data); font-size: var(--t-xs); color: var(--ink-faint); }

.sec-head .asof {
  margin-left: auto;
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  color: var(--ink-faint);
  letter-spacing: var(--track-mono);
}

.t1 h2 { color: var(--tier-1); }
.t2 h2 { color: var(--tier-2); }
.t3 h2 { color: var(--tier-3); }
"""

# ------------------------------------------------------------------ 七巨头图表

MAG7_CSS = """
.mag7 { margin-top: 1rem; }

.mag7-row {
  display: grid;
  grid-template-columns: 3.7rem 1fr 4.4rem;
  align-items: center;
  gap: 0 0.7rem;
  padding: 0.24rem 0;
  position: relative;
}

.mag7-row:hover .mag7-track { background: var(--paper-sunk); }
.mag7-row:hover .mag7-price { opacity: 1; }

.mag7-tick {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-weight: 500;
  letter-spacing: var(--track-mono);
}

.mag7-track {
  position: relative;
  height: 1.4rem;
  border-radius: 2px;
  transition: background 140ms ease;
}

/* 零轴。条形从这里出发，方向本身就是颜色之外的第二重编码。 */
.mag7-track::before {
  content: "";
  position: absolute;
  left: 50%;
  top: -0.12rem;
  bottom: -0.12rem;
  width: 1px;
  background: var(--rule);
}

.mag7-bar { position: absolute; top: 0.32rem; height: 0.76rem; }
.mag7-bar.up { left: 50%; background: var(--up); border-radius: 0 3px 3px 0; }
.mag7-bar.down { right: 50%; background: var(--down); border-radius: 3px 0 0 3px; }

.mag7-val {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.mag7-val.up { color: var(--up); }
.mag7-val.down { color: var(--down); }

.mag7-price {
  position: absolute;
  right: 5.1rem;
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
  opacity: 0;
  transition: opacity 140ms ease;
  pointer-events: none;
  background: var(--paper);
  padding: 0 0.3rem;
}

.mag7-axis {
  display: grid;
  grid-template-columns: 3.7rem 1fr 4.4rem;
  gap: 0 0.7rem;
  margin-top: 0.35rem;
}

.mag7-axis .lbl {
  grid-column: 2;
  display: flex;
  justify-content: space-between;
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
}

.mag7-foot {
  margin-top: 0.7rem;
  font-size: var(--t-sm);
  color: var(--ink-mid);
  max-width: var(--measure);
  text-wrap: pretty;
}
"""

# ------------------------------------------------------------------ 自选股与行情

PANELS_CSS = """
.wl { margin-top: 1rem; }
.wl-grid { display: flex; flex-wrap: wrap; gap: 0.4rem; }

.wl-chip {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  letter-spacing: var(--track-mono);
  padding: 0.22rem 0.55rem;
  border: 1px solid var(--rule);
  border-radius: 2px;
  color: var(--ink-faint);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  transition: border-color 140ms ease, color 140ms ease;
}

.wl-chip.hit {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-soft);
  font-weight: 500;
}

.wl-chip.hit:hover { border-color: var(--accent-strong); color: var(--accent-strong); }

.wl-chip .cnt {
  font-size: var(--t-2xs);
  background: var(--accent);
  color: var(--paper);
  border-radius: 999px;
  min-width: 1.05rem;
  height: 1.05rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.wl-foot, .tape-foot {
  margin-top: 0.7rem;
  font-size: var(--t-sm);
  color: var(--ink-mid);
}

.tape-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
  margin-top: 0.55rem;
}

.tape-cell { padding: 0.72rem 0.9rem 0.72rem 0; border-bottom: 1px solid var(--rule-soft); }
.tape-cell .k { font-size: var(--t-sm); color: var(--ink-faint); }

.tape-cell .v {
  font-family: var(--font-data);
  font-size: var(--t-md);
  font-variant-numeric: tabular-nums;
  margin-top: 0.15rem;
}

.tape-cell .d {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  font-variant-numeric: tabular-nums;
}

.d.up { color: var(--up); }
.d.down { color: var(--down); }
.d.flat { color: var(--ink-faint); }
"""

# ---------------------------------------------------------------------- 条目

ITEMS_CSS = """
.item {
  display: grid;
  grid-template-columns: var(--rail) 1fr;
  gap: 0 0.95rem;
  padding: 1.7rem 0;
  border-bottom: 1px solid var(--rule-soft);
  scroll-margin-top: 1rem;
}

.item .rank {
  font-family: var(--font-data);
  font-size: var(--t-base);
  font-variant-numeric: tabular-nums;
  color: var(--ink-faint);
  padding-top: 0.3rem;
  border-top: 2px solid currentColor;
  align-self: start;
  transition: color 140ms ease;
}

.item.t1 .rank { color: var(--tier-1); }
.item.t2 .rank { color: var(--tier-2); }
.item.t3 .rank { color: var(--tier-3); }

.item h3 {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--t-xl);
  line-height: 1.22;
  letter-spacing: var(--track-display);
  margin: 0;
  text-wrap: balance;
  max-width: var(--measure);
  transition: color 140ms ease;
}

.item.t3 h3 { font-size: var(--t-md); font-weight: 500; }
.item:hover h3 { color: var(--accent-strong); }

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.38rem;
  margin-top: 0.6rem;
}

.tag {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-mono);
  color: var(--ink-mid);
  border: 1px solid var(--rule);
  border-radius: 2px;
  padding: 0.1rem 0.42rem;
}

.tag.tk { color: var(--accent); border-color: var(--accent); font-weight: 500; }

.age {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-mono);
  padding: 0.1rem 0.42rem;
  border-radius: 2px;
}

.age.fresh { color: var(--up); background: var(--up-wash); }
.age.aging { color: var(--ink-mid); background: var(--paper-sunk); }
.age.stale { color: var(--ink-faint); border: 1px dashed var(--rule); }

.item p { margin: 0.75rem 0 0; max-width: var(--measure); text-wrap: pretty; }

.why {
  margin-top: 0.9rem;
  padding: 0.75rem 0.95rem;
  background: var(--paper-sunk);
  border-left: 2px solid var(--accent);
  max-width: var(--measure);
}

.why .lbl {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--accent);
  display: block;
  margin-bottom: 0.22rem;
}

.why p { margin: 0; font-size: var(--t-base); max-width: none; }

.impact {
  margin-top: 0.7rem;
  font-family: var(--font-data);
  font-size: var(--t-sm);
  color: var(--ink-mid);
}

.impact::before { content: "\\2192\\00a0"; color: var(--ink-faint); }

.srcs { margin-top: 0.75rem; }

.srcs summary {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: 0.06em;
  color: var(--ink-faint);
  cursor: pointer;
  list-style: none;
  display: inline-block;
}

.srcs summary::-webkit-details-marker { display: none; }
.srcs summary::before { content: "+ "; }
.srcs[open] summary::before { content: "\\2212 "; }
.srcs summary:hover { color: var(--accent); }

.srcs ul { margin: 0.45rem 0 0; padding: 0; list-style: none; }
.srcs li { margin-top: 0.3rem; font-size: var(--t-sm); color: var(--ink-mid); }

.srcs a {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid var(--accent-soft);
  transition: border-color 140ms ease;
}

.srcs a:hover { border-bottom-color: var(--accent); }
"""

# ------------------------------------------------------------- 深度元数据微卡片

DEPTH_CSS = """
/* 三块深度元数据：资产波及矩阵占满宽度，交叉信源与历史脉络并排成微卡片。 */

.depth { margin-top: 1.1rem; }

.depth-head {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-faint);
  padding-bottom: 0.3rem;
  border-bottom: 1px solid var(--rule-hair);
  margin-bottom: 0.55rem;
}

/* --- 资产波及矩阵 --- */

.assets {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
  gap: 0.4rem;
}

.asset {
  border: 1px solid var(--rule-hair);
  border-radius: 3px;
  padding: 0.5rem 0.6rem;
  background: var(--paper-raised);
  transition: border-color 140ms ease;
}

.asset:hover { border-color: var(--rule); }

.asset-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.4rem;
}

.asset-name {
  font-size: var(--t-sm);
  font-weight: 500;
  color: var(--ink);
}

/* 方向：箭头字形 + 文字 + 颜色，三重编码，色觉障碍读者不依赖颜色。 */
.asset-dir {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-mono);
  white-space: nowrap;
}

.asset-dir.up { color: var(--up); }
.asset-dir.down { color: var(--down); }
.asset-dir.mixed, .asset-dir.none { color: var(--flat); }

/* 判断强度：三格，填几格就是几档。同样是颜色之外的编码。 */
.conv { display: flex; gap: 2px; margin-top: 0.4rem; }

.conv i {
  display: block;
  width: 0.85rem;
  height: 3px;
  border-radius: 1px;
  background: var(--rule);
}

.conv.up i.on { background: var(--up); }
.conv.down i.on { background: var(--down); }
.conv.mixed i.on, .conv.none i.on { background: var(--flat); }

.asset-note {
  margin-top: 0.42rem;
  font-size: var(--t-2xs);
  line-height: 1.5;
  color: var(--ink-mid);
  text-wrap: pretty;
}

/* --- 交叉信源与历史脉络 --- */

.cards {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.6rem;
  margin-top: 0.9rem;
}

@media (min-width: 46rem) {
  .cards.two { grid-template-columns: 1fr 1fr; }
}

.card {
  border: 1px solid var(--rule-hair);
  border-radius: 3px;
  padding: 0.7rem 0.8rem;
  background: var(--paper-raised);
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.45rem;
}

.card-head .t {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-faint);
}

.agree {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-mono);
  padding: 0.08rem 0.4rem;
  border-radius: 2px;
  white-space: nowrap;
}

.agree.aligned { color: var(--up); background: var(--up-wash); }
.agree.split { color: var(--down); background: var(--down-wash); }
.agree.single { color: var(--ink-faint); background: var(--flat-wash); }

.card p { margin: 0; font-size: var(--t-sm); line-height: 1.6; max-width: none; }

/* 时间轴。是真正的时间序列，所以竖轴加节点这个结构是有信息含量的。 */
.tl { margin: 0; padding: 0 0 0 0.85rem; list-style: none; position: relative; }

.tl::before {
  content: "";
  position: absolute;
  left: 2px;
  top: 0.42rem;
  bottom: 0.42rem;
  width: 1px;
  background: var(--rule);
}

.tl li { position: relative; padding: 0.22rem 0; font-size: var(--t-sm); line-height: 1.55; }

.tl li::before {
  content: "";
  position: absolute;
  left: -0.85rem;
  top: 0.62rem;
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: var(--ink-faint);
}

/* 最后一个节点是「当下」，用品牌色点亮，读者一眼看到脉络走到哪了。 */
.tl li:last-child::before { background: var(--accent); }

.tl .w {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-mono);
  color: var(--ink-faint);
  margin-right: 0.4rem;
}
"""

# -------------------------------------------------------------------------- 标签页
#
# 隐藏的 radio + label 实现切换，零 JavaScript。选择器耦合具体的两个 slug
# （brief / calendar）——这个组件在代码层面是通用的，但这个页面只用到这
# 两个标签页，per-slug 选择器比引入 JS 或数据属性联动划算得多。

TABS_CSS = """
.tab-input {
  position: absolute;
  opacity: 0;
  width: 1px;
  height: 1px;
  overflow: hidden;
}

.tab-nav {
  display: flex;
  gap: 0.3rem;
  margin: 2.6rem 0 0;
  border-bottom: 1px solid var(--rule);
}

.tab-label {
  font-family: var(--font-body);
  font-size: var(--t-sm);
  font-weight: 500;
  color: var(--ink-faint);
  padding: 0.55rem 0.15rem;
  margin-bottom: -1px;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color 140ms ease, border-color 140ms ease;
}

.tab-label + .tab-label { margin-left: 1.3rem; }

.tab-label:hover { color: var(--ink); }

.tab-panel { display: none; }
"""

#: 页面上所有标签页的 slug。**必须和 :mod:`taurient_lite.html_renderer`
#: 里传给 tabs() 的 slug 一致。**
#:
#: 这份名单存在的原因是一次真实的故障：标签页的选择器原先是手写的两条，
#: 加第三个标签页时只改了渲染层，CSS 没跟上——结果标签栏里有「异动」
#: 这个标签，点开却是一片空白。这种失败不报错、不告警，只是内容消失。
#: 现在选择器由这份名单生成，:mod:`tests.test_theme` 再断言渲染层用到的
#: 每个 slug 都在名单里，同样的漏改会在测试阶段就炸出来。
TAB_SLUGS: tuple[str, ...] = (
    "brief", "calendar", "momentum", "fundamentals", "market",
)


def build_tabs_css(slugs: Sequence[str] = TAB_SLUGS) -> str:
    """按 slug 生成标签页的选中态选择器。"""

    def group(selector: str, body: str) -> str:
        joined = ",\n".join(selector.format(s=s) for s in slugs)
        return f"{joined} {{\n{body}\n}}"

    return "\n\n".join(
        [
            group(
                '#tab-{s}:focus-visible ~ .tab-nav label[for="tab-{s}"]',
                "  outline: 2px solid var(--accent);\n  outline-offset: 2px;",
            ),
            group(
                '#tab-{s}:checked ~ .tab-panel[data-tab="{s}"]',
                "  display: block;",
            ),
            group(
                '#tab-{s}:checked ~ .tab-nav label[for="tab-{s}"]',
                "  color: var(--accent);\n  border-bottom-color: var(--accent);",
            ),
        ]
    )

# -------------------------------------------------------------------------- 日历网格

CALENDAR_CSS = """
.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 1px;
  margin-top: 0.9rem;
  background: var(--rule-soft);
  border: 1px solid var(--rule-soft);
}

.cal-wd {
  background: var(--paper);
  padding: 0.55rem 0;
  text-align: center;
  font-family: var(--font-data);
  font-size: var(--t-xs);
  letter-spacing: var(--track-mono);
  color: var(--ink-faint);
}

.cal-day {
  background: var(--paper);
  min-height: 5rem;
  padding: 0.5rem 0.55rem 0.6rem;
  display: flex;
  flex-direction: column;
  gap: 0.36rem;
}

.cal-day.weekend .cal-daynum { color: var(--ink-faint); }
.cal-day.empty { background: var(--paper-raised); }

.cal-day.today {
  background: var(--accent-soft);
  box-shadow: inset 0 0 0 1.5px var(--accent);
}

.cal-daynum {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-variant-numeric: tabular-nums;
  color: var(--ink-mid);
}

.cal-day.today .cal-daynum { color: var(--accent-strong); font-weight: 600; }

.cal-chip {
  font-size: var(--t-xs);
  line-height: 1.4;
  padding: 0.22rem 0.4rem;
  border-radius: 3px;
  text-wrap: pretty;
}

.cal-chip.w-high { background: var(--accent-soft); color: var(--accent-strong); }
.cal-chip.w-mid { background: var(--paper-sunk); color: var(--ink-mid); }
.cal-chip.w-low {
  background: var(--paper-raised);
  color: var(--ink-faint);
  border-left: 2px solid var(--rule);
  padding-left: 0.34rem;
}

.cal-chip-time {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  margin-right: 0.3rem;
  opacity: 0.85;
}

/* 网格格子空间紧张，来源只留一个小箭头：一个排定的日期本身就是一条
   需要出处的事实，这个入口比完全不留任何验证途径要好，完整来源名
   展开在下方的表格里。 */
.cal-src {
  margin-left: 0.3rem;
  color: var(--accent);
  text-decoration: none;
  font-size: 0.85em;
}

.cal-src:hover { color: var(--accent-strong); }

.cal-later-head {
  margin-top: 1.6rem;
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-faint);
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--rule);
}

.cal-later-src { font-size: var(--t-sm); }

.cal-later-src a {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid var(--accent-soft);
  transition: border-color 140ms ease;
}

.cal-later-src a:hover { border-bottom-color: var(--accent); }

@media (max-width: 34rem) {
  .cal-grid { grid-template-columns: repeat(7, minmax(2.6rem, 1fr)); }
  .cal-day { min-height: 3.6rem; padding: 0.35rem 0.32rem 0.42rem; gap: 0.26rem; }
  .cal-chip { font-size: 0.62rem; padding: 0.16rem 0.3rem; }
  .cal-wd { font-size: 0.62rem; padding: 0.45rem 0; }
}
"""

# -------------------------------------------------------------------- 日历与页脚

# -------------------------------------------------------------------------- 价量异动

MOMENTUM_CSS = """
/* 首页上的初动摘要条。视觉上刻意贴近自选股面板——两者回答的是同一类
   问题（哪些代码今天值得多看一眼），长得像才不会让读者以为是新东西。 */
.mo-strip { margin-top: 1rem; }

.mo-strip-grid { display: flex; flex-wrap: wrap; gap: 0.4rem; }

.mo-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.26rem 0.5rem;
  border: 1px solid var(--rule);
  border-radius: 3px;
  font-family: var(--font-data);
  font-size: var(--t-sm);
  letter-spacing: var(--track-mono);
  color: var(--ink-mid);
  text-decoration: none;
  transition: border-color 140ms ease, color 140ms ease;
}

.mo-chip:hover { border-color: var(--accent-strong); color: var(--accent-strong); }

.mo-chip-n {
  font-size: var(--t-2xs);
  font-variant-numeric: tabular-nums;
  opacity: 0.75;
}

.mo-strip-foot {
  margin: 0.55rem 0 0;
  font-size: var(--t-sm);
  color: var(--ink-faint);
  max-width: var(--measure);
  text-wrap: pretty;
}

.mo-lede {
  margin: 0.9rem 0 0;
  max-width: var(--measure);
  font-size: var(--t-base);
  line-height: 1.7;
  text-wrap: pretty;
}

/* 免责声明用边框而不是底色：它必须一眼看见，但不该抢走候选名单的注意力。 */
.mo-disclaimer {
  margin-top: 0.9rem;
  padding: 0.6rem 0.75rem;
  border-left: 2px solid var(--rule);
  font-size: var(--t-sm);
  line-height: 1.6;
  color: var(--ink-mid);
  max-width: var(--measure);
  text-wrap: pretty;
}

.mo-groups { margin-top: 1.5rem; }
.mo-group + .mo-group { margin-top: 1.75rem; }

.mo-group-head {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--rule);
}

.mo-group-name {
  font-family: var(--font-data);
  font-size: var(--t-xs);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}

.mo-group-n {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  color: var(--ink-faint);
}

.mo-group-blurb {
  font-size: var(--t-sm);
  color: var(--ink-faint);
  text-wrap: pretty;
}

/* 初动是整个板块存在的理由，用品牌色标出来；已延伸整组压暗，
   读者不必逐张卡片去读指标就知道这一组已经错过了。 */
.g-ignition .mo-group-name { color: var(--accent-strong); }
.g-ignition .mo-group-head { border-bottom-color: var(--accent); }
.g-extended { opacity: 0.62; }

.mo-card {
  padding: 0.7rem 0 0.75rem;
  border-bottom: 1px solid var(--rule-hair);
}

.mo-card:last-child { border-bottom: 0; }

.mo-head {
  display: flex;
  align-items: baseline;
  gap: 0.55rem;
  flex-wrap: wrap;
}

.mo-tk {
  font-family: var(--font-data);
  font-size: var(--t-md);
  font-weight: 500;
  letter-spacing: var(--track-mono);
}

.s-ignition .mo-tk { color: var(--accent-strong); }

.mo-px {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-variant-numeric: tabular-nums;
  color: var(--ink-mid);
}

.mo-chg {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-variant-numeric: tabular-nums;
}

.mo-chg-day {
  font-size: var(--t-2xs);
  color: var(--ink-faint);
  margin-right: 0.15rem;
}

.mo-chg.up { color: var(--up); }
.mo-chg.down { color: var(--down); }

.mo-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1.1rem;
  margin-top: 0.5rem;
}

.mo-metric { display: flex; align-items: baseline; gap: 0.3rem; }

.mo-metric-k {
  font-size: var(--t-2xs);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-faint);
}

.mo-metric-v {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.mo-note {
  margin: 0.5rem 0 0;
  font-size: var(--t-sm);
  line-height: 1.65;
  color: var(--ink-mid);
  max-width: var(--measure);
  text-wrap: pretty;
}

.mo-src { margin-top: 0.4rem; }

.mo-src a {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid var(--accent-soft);
}

.mo-src a:hover { border-bottom-color: var(--accent); }

@media (max-width: 34rem) {
  .mo-group-blurb { flex-basis: 100%; }
  .mo-metrics { gap: 0.3rem 0.8rem; }
}
"""

# -------------------------------------------------------------------------- 基本面
#
# 分数格子用品牌色的浅洗做「进度条」底色，不用涨跌绿红——分数不是涨跌，借用
# 语义色会让读者把「现金 90 分」读成「涨了」。低分改用必读层那支「需要注意」
# 的红，只染数字不染底色：它提示的是「去看这一步」，不是「利空」。

FUNDAMENTALS_CSS = """
.fu-lede {
  margin: 0.9rem 0 0;
  max-width: var(--measure);
  font-size: var(--t-base);
  line-height: 1.7;
  text-wrap: pretty;
}

.fu-disclaimer {
  margin-top: 0.9rem;
  padding: 0.6rem 0.75rem;
  border-left: 2px solid var(--rule);
  font-size: var(--t-sm);
  line-height: 1.6;
  color: var(--ink-mid);
  max-width: var(--measure);
  text-wrap: pretty;
}

/* 矩阵在窄屏上自己横向滚动，整页不出现横向滚动条。 */
.fu-matrix-wrap { overflow-x: auto; margin-top: 1.4rem; }

.fu-matrix {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-variant-numeric: tabular-nums;
}

.fu-matrix th, .fu-matrix td {
  padding: 0.42rem 0.45rem;
  border-bottom: 1px solid var(--rule-hair);
  text-align: right;
  white-space: nowrap;
}

.fu-matrix thead th {
  font-family: var(--font-body);
  font-size: var(--t-2xs);
  font-weight: 500;
  letter-spacing: var(--track-label);
  color: var(--ink-faint);
  border-bottom: 1px solid var(--rule);
}

.fu-matrix thead th:first-child,
.fu-matrix tbody th { text-align: left; }

.fu-matrix tbody th { font-weight: 400; }

.fu-tk {
  color: var(--ink);
  font-weight: 500;
  letter-spacing: var(--track-mono);
  text-decoration: none;
  border-bottom: 1px solid var(--rule);
}

.fu-tk:hover { color: var(--accent-strong); border-bottom-color: var(--accent); }

.fu-prof {
  margin-left: 0.45rem;
  font-family: var(--font-body);
  font-size: var(--t-2xs);
  color: var(--ink-faint);
}

.fu-total { color: var(--ink); font-weight: 500; }

.fu-grade {
  margin-left: 0.3rem;
  font-size: var(--t-2xs);
  color: var(--ink-faint);
}

.fu-cell {
  min-width: 2.6rem;
  color: var(--ink-mid);
  background: linear-gradient(
    to right, var(--accent-soft) var(--fill, 0%), transparent var(--fill, 0%)
  );
}

.fu-cell.fu-weak { color: var(--tier-1); font-weight: 500; }
.fu-cell.fu-nodata { color: var(--ink-faint); background: none; }

.fu-flags { color: var(--tier-1); }

.fu-flagn::before { content: "\\25B2 "; font-size: 0.7em; }

.fu-legend {
  margin: 0.55rem 0 0;
  font-size: var(--t-xs);
  color: var(--ink-faint);
  max-width: var(--measure);
  text-wrap: pretty;
}

.fu-cards { margin-top: 1.8rem; }

.fu-card {
  padding: 1rem 0 1.05rem;
  border-top: 1px solid var(--rule);
  scroll-margin-top: 1rem;
}

.fu-head {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.fu-card-tk {
  font-family: var(--font-data);
  font-size: var(--t-md);
  font-weight: 500;
  letter-spacing: var(--track-mono);
}

.fu-name { font-size: var(--t-sm); color: var(--ink-mid); }

.fu-score {
  margin-left: auto;
  font-family: var(--font-data);
  font-size: var(--t-md);
  font-variant-numeric: tabular-nums;
}

.fu-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.2rem 0.9rem;
  margin-top: 0.3rem;
  font-size: var(--t-xs);
  color: var(--ink-faint);
}

.fu-meta .fu-prof { margin-left: 0; }
.fu-pen { color: var(--tier-1); }

.fu-verdict, .fu-note {
  margin: 0.55rem 0 0;
  max-width: var(--measure);
  font-size: var(--t-sm);
  line-height: 1.65;
  text-wrap: pretty;
}

.fu-note { color: var(--ink-mid); font-style: italic; }

.fu-gate, .fu-redflags {
  margin: 0.55rem 0 0;
  padding: 0;
  list-style: none;
  max-width: var(--measure);
  font-size: var(--t-sm);
  line-height: 1.55;
}

.fu-gate li {
  padding-left: 0.6rem;
  border-left: 2px solid var(--tier-1);
  color: var(--ink);
}

.fu-redflags li { position: relative; padding-left: 1rem; color: var(--ink-mid); }

.fu-redflags li::before {
  content: "\\25B2";
  position: absolute;
  left: 0;
  top: 0.18em;
  font-size: 0.65em;
  color: var(--tier-1);
}

.fu-gate li + li, .fu-redflags li + li { margin-top: 0.25rem; }

.fu-val {
  display: flex;
  flex-wrap: wrap;
  gap: 0.15rem 0.6rem;
  align-items: baseline;
  margin-top: 0.7rem;
  padding: 0.45rem 0.6rem;
  background: var(--paper-sunk);
  border-radius: 3px;
  font-size: var(--t-sm);
  max-width: var(--measure);
}

.fu-val-k {
  font-size: var(--t-2xs);
  letter-spacing: var(--track-label);
  color: var(--ink-faint);
}

.fu-val-v { font-family: var(--font-data); font-variant-numeric: tabular-nums; }
.fu-val-t { color: var(--ink-mid); }
.fu-val-void .fu-val-v { text-decoration: line-through; color: var(--ink-faint); }

.fu-more { margin-top: 0.7rem; }

.fu-more summary {
  cursor: pointer;
  list-style: none;
  font-size: var(--t-xs);
  color: var(--accent);
}

.fu-more summary::-webkit-details-marker { display: none; }
.fu-more summary::before { content: "+ "; }
.fu-more[open] summary::before { content: "\\2212 "; }

.fu-stages { margin-top: 0.4rem; }

.fu-stage { padding: 0.55rem 0; border-bottom: 1px solid var(--rule-hair); }
.fu-stage:last-child { border-bottom: 0; }

.fu-stage-head { display: flex; align-items: baseline; gap: 0.5rem; }

.fu-step {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  color: var(--ink-faint);
  min-width: 0.9rem;
}

.fu-stage-t { font-size: var(--t-sm); font-weight: 500; }

.fu-stage-s {
  margin-left: auto;
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-variant-numeric: tabular-nums;
  color: var(--ink-mid);
}

.fu-stage-s.fu-weak { color: var(--tier-1); font-weight: 500; }

.fu-find {
  margin: 0.3rem 0 0 1.4rem;
  padding: 0;
  font-size: var(--t-sm);
  line-height: 1.6;
  color: var(--ink-mid);
  max-width: var(--measure);
}

.fu-find li + li { margin-top: 0.15rem; }

.fu-source {
  margin: 1.4rem 0 0;
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  color: var(--ink-faint);
}

@media (max-width: 34rem) {
  .fu-score { margin-left: 0; }
  .fu-find { margin-left: 0.9rem; }
}
"""

# -------------------------------------------------------------------- 市场热力

#: 树图画布的长宽比。**这个值同时被两处使用**：CSS 的 ``aspect-ratio``
#: 和 :func:`~taurient_lite.treemap.squarify` 的 ``box_w``/``box_h``。
#: 两边不一致，算出来的正方形就会被容器拉成长条——``tests.test_heatmap``
#: 里有一条断言专门盯这个。
HEAT_BOX: tuple[int, int] = (100, 62)

def build_heat_levels_css() -> str:
    """按档位生成色块规则。

    十一条规则手写一遍不是不行，但那样「新增一档」就要改两个地方，
    而漏改的那一档会静默退化成透明色块——生成出来，档位表就是唯一真相。

    文字色走 ``--heat-on-<档位>``，而不是在这里按主题分支：那批 token 本身
    就是成对的（亮色一套、暗色一套），所以这里一条规则同时管两套主题，
    不需要为亮暗各写一遍选择器。
    """
    rules = []
    for name in HEAT_LEVEL_NAMES:
        rules.append(
            f".tile.{name} {{ background: var(--heat-{name}); "
            f"color: var(--heat-on-{name}); }}"
        )
    for name in HEAT_LEVEL_NAMES:
        rules.append(f".swatch.sw-{name} {{ background: var(--heat-{name}); }}")
    return "\n".join(rules)


HEATMAP_CSS = """
/* 行情板。跟随亮暗主题——理由见 TOKENS 里的注释。 */
.board {
  margin: 0.4rem 0 1.6rem;
  padding: 1rem 0.9rem 1.1rem;
  background: var(--heat-board);
  border: 1px solid var(--rule-soft);
  border-radius: 10px;
  color: var(--heat-ink);
}

.board-head {
  display: flex;
  align-items: baseline;
  gap: 0.55rem;
  padding: 0 0.15rem;
  margin-bottom: 0.7rem;
}

.board-title {
  margin: 0;
  font-family: var(--font-body);
  font-size: var(--t-md);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--heat-ink);
}

.board-asof {
  font-size: var(--t-xs);
  color: var(--heat-ink-dim);
}

.board-note {
  margin: 0.8rem 0.15rem 0;
  font-size: var(--t-xs);
  line-height: 1.5;
  color: var(--heat-ink-dim);
  max-width: var(--measure);
  text-wrap: pretty;
}

/* 横向轨道。手机上一屏放不下 12 个行业，竖着堆会把下面的内容推到
   三屏之外；横向滑动配 scroll-snap 是这种场景的原生解法。 */
.sec-rail {
  display: flex;
  gap: 0.7rem;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  padding-bottom: 0.4rem;
  scrollbar-width: thin;
  scrollbar-color: var(--heat-flat) transparent;
}

.sec-card {
  flex: 0 0 min(82%, 20rem);
  scroll-snap-align: start;
  padding: 0.7rem 0.7rem 0.75rem;
  background: var(--heat-card);
  border: 1px solid var(--rule-hair);
  border-radius: 8px;
}

.sec-card-head {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  margin-bottom: 0.55rem;
}

.sec-name {
  font-size: var(--t-base);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--heat-ink);
}

.sec-n {
  font-size: var(--t-2xs);
  color: var(--heat-ink-dim);
}

/* 行业涨跌幅。**刻意不按色阶上色。**
   色阶是给「色块背景」设计的：低档 #3A201C 这种暗棕压在同样暗的卡片上，
   一个 -0.07% 会直接消失。文字只取方向，用色阶最亮的一档保证读得出来，
   幅度由数字本身表达——数字已经写在那里了，不需要颜色再说一遍。 */
.sec-chg {
  margin-left: auto;
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--heat-ink-dim);
}

.sec-chg.up { color: var(--heat-u5); }
.sec-chg.down { color: var(--heat-d5); }

/* 树图画布。aspect-ratio 必须和 treemap.squarify 的 box_w/box_h 一致，
   否则算出来的「正方形」会被容器拉成长条。两边都引用 HEAT_BOX。 */
.heat {
  position: relative;
  width: 100%;
  aspect-ratio: 100 / 62;
}

.tile {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.05rem;
  border: 1px solid var(--heat-edge);
  border-radius: 3px;
  overflow: hidden;
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
  text-align: center;
}

.tile-tk {
  font-size: var(--t-2xs);
  font-weight: 500;
  letter-spacing: var(--track-mono);
}

.tile-ch { font-size: var(--t-2xs); opacity: 0.85; }

/* 小块降级：放不下两行就只留代码，再小就只剩色块。
   不降级的话文字会溢出成一团糊，比没有文字更糟。 */
.tile.compact .tile-ch { display: none; }
.tile.bare .tile-tk,
.tile.bare .tile-ch { display: none; }

/* 大块放大字号：块的大小已经在说「这块更重要」，字号跟上才不矛盾。 */
.tile.lg { gap: 0.15rem; }
.tile.lg .tile-tk { font-size: var(--t-sm); font-weight: 600; }
.tile.lg .tile-ch { font-size: var(--t-xs); opacity: 0.92; }

.heat-legend {
  display: flex;
  align-items: center;
  gap: 0.22rem;
  margin: 0.8rem 0.15rem 0;
  font-size: var(--t-2xs);
  font-family: var(--font-data);
  color: var(--heat-ink-dim);
}

.swatch {
  width: 1.15rem;
  height: 0.45rem;
  border: 1px solid var(--heat-edge);
  border-radius: 2px;
  display: inline-block;
  flex: none;
}

.heat-legend .lg-label { margin: 0 0.2rem; }

@media (max-width: 34rem) {
  .board { padding: 0.85rem 0.7rem 0.9rem; border-radius: 14px; }
  .sec-card { flex-basis: 88%; }
}
"""

TAIL_CSS = """
.cal-scroll { overflow-x: auto; margin-top: 0.5rem; }

table { border-collapse: collapse; width: 100%; font-size: var(--t-base); }

td {
  padding: 0.62rem 0.7rem 0.62rem 0;
  border-bottom: 1px solid var(--rule-soft);
  vertical-align: top;
}

td.when {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  white-space: nowrap;
  color: var(--ink-mid);
}

td.time {
  font-family: var(--font-data);
  font-size: var(--t-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--ink-faint);
}

td.w { text-align: right; white-space: nowrap; }

.w span {
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  letter-spacing: 0.08em;
  padding: 0.1rem 0.42rem;
  border-radius: 2px;
}

.w-high { background: var(--accent-soft); color: var(--accent); }
.w-mid { color: var(--ink-mid); }
.w-low { color: var(--ink-faint); }

.colophon {
  margin-top: 3.5rem;
  padding-top: 1.05rem;
  border-top: 2px solid var(--ink);
  font-family: var(--font-data);
  font-size: var(--t-2xs);
  line-height: 1.8;
  color: var(--ink-faint);
  letter-spacing: 0.02em;
}

a:focus-visible, summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 2px;
}

@media (max-width: 34rem) {
  .item { grid-template-columns: 1.9rem 1fr; gap: 0 0.7rem; }
  .item h3 { font-size: var(--t-lg); }
  .mag7-row, .mag7-axis { grid-template-columns: 3.1rem 1fr 3.8rem; }
  .mag7-price { display: none; }
  .assets { grid-template-columns: 1fr 1fr; }
}

/* 页面在静止状态下就是完整可读的，动效只发生在悬停与聚焦上，
   所以这里整个关掉不会藏起任何内容。 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
"""


def build_css() -> str:
    """拼出完整样式表。"""
    return "\n".join(
        [
            build_palette_css(),
            LAYOUT_CSS,
            MAG7_CSS,
            PANELS_CSS,
            ITEMS_CSS,
            DEPTH_CSS,
            TABS_CSS,
            build_tabs_css(),
            CALENDAR_CSS,
            MOMENTUM_CSS,
            FUNDAMENTALS_CSS,
            HEATMAP_CSS,
            build_heat_levels_css(),
            TAIL_CSS,
        ]
    )
