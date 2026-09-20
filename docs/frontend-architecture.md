# 这个项目的前端架构

写给想弄清「我的前端到底长什么样、和 React 那套有什么区别」的自己。
本文只讲呈现层，数据抓取和判定逻辑不在范围内。

---

## 一句话概括

**服务端渲染的静态页面（Server-Side Rendering / 静态站点生成）。**
Python 把数据拼成 HTML 字符串，浏览器拿到的是一个已经完整成型的页面，
不需要执行任何 JavaScript 就能看到全部内容。

这不是「用 Python 写前端」。浏览器里跑的仍然是标准的 HTML + CSS，
Python 只是**生成**它们的工具，角色相当于 Hugo、Jekyll 这类静态站点生成器。

---

## 两条发布路径

同一套渲染代码，有两个出口。

### 路径 A：静态文件（主路径）

```
briefs/2026-09-10.json          ← 唯一真相来源
        │
        ├─ render.py            ← 命令行入口
        │     │
        │     └─ taurient_lite/pipeline.py   ← 编排：定位 → 校验 → 渲染 → 写盘
        │            │
        │            ├─ html_renderer.py  → site/index.html   （发布成 Artifact）
        │            └─ markdown_renderer.py → briefs/2026-09-10.md（存档）
```

跑 `python3 render.py` 就得到 `site/index.html`，一个自带样式的文件，
直接发布即可。没有构建步骤，没有服务器，没有依赖。

### 路径 B：FastAPI 后端（部署在 Render）

```
浏览器请求 /  →  backend/server.py
                      │
                      ├─ render_head()  ← 复用同一个 html_renderer
                      ├─ render_body()  ← 复用同一个 html_renderer
                      └─ auth_panel.render()  ← 登录 + 自选股面板（后端独有）
                      │
                      └─ 拼成完整的 <!doctype html> 页面返回
```

关键点：后端**没有重新实现**任何渲染逻辑，它 import 的是同一个
`taurient_lite` 包。差别只有两处：

1. 静态版产出的是「片段」（没有 `<html>`/`<head>`/`<body>`），因为
   Artifact 平台会自己包骨架；后端版在 `_wrap_page()` 里自己补上骨架。
2. 后端版多了一个登录面板。

---

## 呈现层的三层结构

```
taurient_lite/
├── schema.py          数据层：定义 Brief 长什么样，负责校验
│                      不依赖任何其他模块
│
├── theme.py           样式层：所有颜色、字体、CSS
│                      1482 行，是整个呈现层最大的文件
│
├── components/        组件层：把数据变成 HTML 片段
│   ├── base.py        转义、拼接等基础工具
│   ├── panels.py      盘面、自选股、Tape 等面板
│   ├── items.py       新闻条目
│   ├── depth.py       分层内容
│   ├── calendar.py    日历标签页
│   ├── momentum.py    异动标签页
│   ├── fundamentals.py 基本面标签页
│   ├── tabs.py        标签页切换的脚手架
│   └── tail.py        页脚
│
├── html_renderer.py   组装层：把组件按顺序拼成整页
└── markdown_renderer.py 组装层：同一份数据的 Markdown 版本
```

**依赖方向严格向下，没有环。** `schema` 谁都不依赖，`components` 只依赖
`schema` 和 `theme`，`html_renderer` 只依赖 `components`。所以每一层都能
单独测试。

### 和 React 的对应关系

| React 里的概念 | 这个项目里对应什么 |
|---|---|
| 组件（Component） | `components/` 里的函数，比如 `mag7_panel(brief.mag7)` |
| props | 函数参数，就是普通的 Python 对象 |
| JSX | f-string 拼出来的 HTML 字符串 |
| 组件组合 | `C.join([...])` 把一堆片段按顺序接起来 |
| CSS-in-JS / Tailwind | `theme.py` 里的 `TOKENS` 和各个 `*_CSS` 常量 |
| 条件渲染 | 组件在没数据时自己 `return ""` |
| **state（状态）** | **没有。这是最大的区别。** |

思路其实和 React 很像：小函数各自负责一块，往上层层组合。真正的差别
是**渲染发生在什么时候、在哪里**——React 在浏览器里、在用户操作时渲染；
这里在服务端、在生成页面时一次渲染完，之后页面就不再变了。

---

## JavaScript 用在哪里

**静态版页面：一行 JS 都没有。** `site/index.html` 里连 `<script>` 标签
都不存在。

标签页切换（简报 / 日历 / 异动 / 基本面）是用**隐藏的 radio input + label
+ CSS 选择器**实现的，见 [tabs.py](../taurient_lite/components/tabs.py)。
这样做有两个实在的好处：

- Artifact 平台的 CSP（内容安全策略）限制脚本来源，不用 JS 就绕开了这个问题
- 键盘可达性是免费的：方向键在同组 radio 之间切换是浏览器的原生行为，
  不需要额外写 ARIA 或事件监听

**只有后端版的登录面板有 JS**，在
[auth_panel.py](../backend/auth_panel.py) 的 `_script()` 里，约 350 行原生
JavaScript（没有框架），负责：Supabase 登录、读写自选股、代码搜索的自动
补全、按自选股过滤页面内容。

所以准确的描述是：**一个零 JS 的静态页面，加上一块用原生 JS 写的登录面板。**

---

## 样式怎么组织

全部在 [theme.py](../taurient_lite/theme.py) 里。核心设计是**颜色写成
Python 数据，而不是 CSS 字符串**：

```python
TOKENS: dict[str, tuple[str, str]] = {
    "paper": ("#EDEFF0", "#0E1317"),   # (亮色, 暗色)
    "ink":   ("#131A21", "#DDE3E7"),
}
```

然后 `build_css()` 遍历这张表，自动生成三个块：

1. 裸 `:root` —— 完整的亮色调色板
2. `@media (prefers-color-scheme: dark)` —— 跟随系统
3. `:root[data-theme="dark"]` —— 读者显式选了暗色

这样「每个 token 都必须在裸 `:root` 里声明」这条规则由**构造保证**，
不用靠人眼检查。漏掉一个颜色导致亮色模式下页面崩掉的情况不会发生。

改样式的入口：

| 改什么 | 改哪里 |
|---|---|
| 颜色 | `TOKENS` |
| 字体 | `FONT_STACKS` + `GOOGLE_FONTS`（两处都要改） |
| 字号、字间距 | `TYPE_SCALE`、`TRACKING` |
| 版式 | `LAYOUT_CSS` |
| 各区块 | `PANELS_CSS`、`ITEMS_CSS`、`DEPTH_CSS`、`TABS_CSS`、`CALENDAR_CSS`、`MOMENTUM_CSS`、`TAIL_CSS` |

**不要直接改 `site/index.html`**，它是产物，下次跑 `render.py` 就被覆盖了。

---

## 这个架构的取舍

### 现在的好处

- **零依赖**：不用 `npm install`，没有 node_modules，没有打包工具
- **不会有两套逻辑**：数据校验、涨跌判定、渲染规则都只有一份，静态版和
  后端版共用
- **渲染是纯函数**：同一份 JSON 永远得到同样的页面，可重放、好测试
- **产物可以直接发布**：一个 HTML 文件，没有构建和部署步骤
- **首屏没有等待**：不用等 JS 下载和执行，HTML 到了就能读

### 现在的代价

- CSS 写在 Python 字符串里，没有编辑器的高亮和补全
- 改完样式要跑一次 `render.py` 才能看到效果，没有热更新
- 页面渲染完就静止了，做不了实时更新

---

## 什么时候该换成 React + TypeScript

不是「框架更高级所以该换」，而是**当页面从「文档」变成「应用」时才该换**。
具体的信号：

### 1. 需要客户端状态，而且状态之间互相牵连

现在页面只有一个状态——选中哪个标签页，radio 就够了。
如果出现这种需求：拖拽排序自选股、多条件筛选并且筛选结果互相影响、
表单有多步且步骤之间有依赖、撤销/重做——手写 JS 维护这些状态会很快
失控，React 的状态模型就是为这个设计的。

**粗略的判断线**：需要跟踪的独立状态超过 5 个，并且它们之间有依赖关系。

### 2. 数据需要实时更新

盘中每秒刷新行情、WebSocket 推送、图表随数据变化。服务端渲染的页面
做不到这个——它渲染完就定型了。

### 3. 同一块 UI 在多处出现且带交互

现在的组件是「生成一次 HTML 就结束」。如果同一个组件要在不同位置
各自维护自己的状态（比如多个可独立展开收起的卡片、每个都带自己的
数据请求），React 的组件模型会明显更顺手。

### 4. 多人协作开发前端

TypeScript 的类型检查在这时价值最大：别人改了组件参数，编译期就报错，
而不是等页面跑起来才发现。一个人写的项目，这个收益小得多。

### 5. 需要真正的路由

多个页面之间跳转、URL 要能分享和收藏、前进后退要正常工作。
现在只有一个页面，用不上。

### 反过来，这些**不是**换框架的理由

- 「React 更现代」——技术选型要看问题，不看流行度
- 「作品集里有 React 更好看」——如果是这个目的，单独做一个项目更划算，
  不用把一个工作良好的项目推倒
- 「只有登录面板那块 JS 有点乱」——那就只重写那一块

### 如果真要换，不用全盘推倒

可以只把交互最复杂的部分（比如自选股面板）单独做成一个 React 组件，
挂载到页面的某个 `<div>` 上，其余部分继续用 Python 生成。这叫「孤岛
架构」（Islands Architecture），Astro 这类框架就是专门做这个的。

对「每天生成一份阅读型简报」这个需求来说，现在的架构是合适的。
先让需求推着架构走，别反过来。

---

## 快速上手

```bash
python3 render.py               # 用最新一份简报重新生成页面
python3 render.py 2026-09-10    # 指定日期
open site/index.html            # 看效果

python3 -m pytest tests/        # 跑测试
```

改样式 → 跑 `render.py` → 刷新浏览器。这就是完整的开发循环。
