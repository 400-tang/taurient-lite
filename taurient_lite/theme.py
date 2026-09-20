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

from functools import lru_cache
from pathlib import Path
from typing import Sequence

#: 样式表所在目录。**CSS 写在 .css 文件里，不写在 Python 字符串里。**
#:
#: 搬出来之前，这个文件有一千三百多行 CSS 挤在三引号字符串里：没有语法
#: 高亮、没有补全、没有格式化，也没法用 stylelint。改一处配色要靠肉眼
#: 确认括号配对。搬出来之后编辑器把它当 CSS 对待，而 Python 这边只多了
#: 一个读文件的函数。
#:
#: **颜色仍然由 Python 生成**（见 :func:`build_palette_css`）——「每个 token
#: 都必须在裸 :root 里声明」这条规则由构造保证，这是 CSS 文件做不到的。
STYLES = Path(__file__).resolve().parent / "styles"

#: 拼进整页的样式表，顺序即层叠顺序。
#:
#: 显式列出来而不是扫目录：扫目录的话，新加一个文件会静默生效、顺序由
#: 文件名决定，而层叠顺序是有意义的。漏在这份名单外的文件由
#: ``tests.test_theme`` 抓出来。
STYLE_FILES: tuple[str, ...] = (
    "layout.css",
    "panels.css",
    "items.css",
    "depth.css",
    "tabs.css",
    "calendar.css",
    "momentum.css",
    "fundamentals.css",
    "heatmap.css",
    "tail.css",
)


@lru_cache(maxsize=None)
def load_style(name: str) -> str:
    """读一份样式表。缓存住——同一份 CSS 在一次进程里会被拼很多次。"""
    path = STYLES / name
    if not path.is_file():
        raise FileNotFoundError(f"样式表不存在：{path}")
    return path.read_text(encoding="utf-8")

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



# ------------------------------------------------------------------ 七巨头图表



# ---------------------------------------------------------------------- 条目



# ------------------------------------------------------------- 深度元数据微卡片



# -------------------------------------------------------------------------- 标签页
#
# 隐藏的 radio + label 实现切换，零 JavaScript。选择器耦合具体的两个 slug
# （brief / calendar）——这个组件在代码层面是通用的，但这个页面只用到这
# 两个标签页，per-slug 选择器比引入 JS 或数据属性联动划算得多。



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



# -------------------------------------------------------------------- 日历与页脚

# -------------------------------------------------------------------------- 价量异动



# -------------------------------------------------------------------------- 基本面
#
# 分数格子用品牌色的浅洗做「进度条」底色，不用涨跌绿红——分数不是涨跌，借用
# 语义色会让读者把「现金 90 分」读成「涨了」。低分改用必读层那支「需要注意」
# 的红，只染数字不染底色：它提示的是「去看这一步」，不是「利空」。



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







def build_css() -> str:
    """拼出完整样式表。

    生成的部分（调色板、标签页选择器、热力色阶）在前，静态样式表在后——
    后者引用前者定义的 CSS 变量。
    """
    parts = [
        build_palette_css(),
        build_tabs_css(),
        build_heat_levels_css(),
    ]
    parts.extend(load_style(name) for name in STYLE_FILES)
    return "\n".join(parts)
