# Taurient Lite

一个盘前新闻简报工具。每个交易日早上 6:00 PT 自动扫描全球财经与科技新闻，
去重、按重要性分层、写清楚每条为什么重要，生成一个网页仪表盘和一份 Markdown 存档。

灵感来自澳洲对冲基金 Minotaur Capital 的内部工具 Taurient，那套系统每周用多个
大模型扫描约 3.5 万篇新闻来定位投资标的。这个是它的简化版，只做信息压缩这一层：
不选股，不给建议，只负责让你在开盘前用几分钟知道该知道的事。

**线上简报：** https://claude.ai/code/artifact/65328183-42d9-4ead-93c5-d2d3dc41b97a

## 每天的产出

- **七巨头单日涨跌**，横向发散条形图，行情来自带时间戳的接口
- **自选股面板**，有新闻的代码点亮并可跳转
- **指数与利率**快照
- **三层新闻**，必读、值得知道、背景噪音，每条带发布日期与时效徽章
- **重点条目的深度元数据**：资产波及矩阵、多方信源交叉对比、历史演进脉络
- **接下来要盯的时间点**

## 覆盖范围

美股与宏观（联储、利率、通胀就业数据、财报公告、板块轮动），
科技与 AI 行业（半导体、云、AI 公司动态与融资，不限于上市公司），
以及直接影响能源价格与通胀路径的地缘事件。

## 结构

```
taurient-lite/
├── RUNBOOK.md              每日流程，定时任务读这个
├── config.json             覆盖范围、条数目标、时效上限、自选股
├── render.py               命令行入口：渲染
├── fetch_quotes.py         命令行入口：取行情
├── import_watchlist.py     导入 TradingView 的自选股导出
├── taurient_lite/          渲染流水线
│   ├── schema.py           数据定义与校验
│   ├── config.py           配置读取
│   ├── theme.py            设计 token 与样式表
│   ├── components/         组件层
│   ├── html_renderer.py    组装整页
│   ├── markdown_renderer.py 组装存档
│   ├── pipeline.py         编排
│   └── quotes.py           行情抓取
├── tests/                  184 个用例，零依赖
├── briefs/                 每日 JSON（真相来源）与 Markdown 存档
└── site/index.html         渲染产物，发布成 Artifact
```

数据和呈现是分开的。JSON 是唯一的真实来源，Markdown 存档和网页都从它生成。
想换配色或版式只改 `taurient_lite/theme.py`，历史数据不动；想改覆盖范围只改
`config.json`，渲染逻辑不动。

依赖方向严格向下，没有环：`schema` 不依赖任何模块，`components` 只依赖
`schema` 和 `theme`，`pipeline` 只依赖渲染器。所以每一层都能单独测试。

## 每天发生什么

1. 扫描：至少 12 组查询加逐个自选股，重要条目用原文核对数字
2. 筛选：同一事件跨媒体合并，来源数量当重要性信号，分成三层
3. 写 JSON：必读层补齐资产矩阵、交叉信源、历史脉络
4. 取行情并渲染：`fetch_quotes.py` 然后 `render.py`
5. 发布到同一个 Artifact 链接，归档提交回 GitHub

## 定时运行

云端 routine `trig_01TCdAaPJVRePAdQvQRffedk`，周一到周五自动执行。
管理页面 https://claude.ai/code/routines/trig_01TCdAaPJVRePAdQvQRffedk

**夏令时不用管。** cron 只认 UTC，单点触发会在时区切换时漂一小时。所以排成
每天两次 `0 13,14 * * 1-5`，由运行提示里的时间闸门决定哪一次真正执行：
只有加州本地时间已过 6:00、且当天简报尚未生成时才动手。夏令时命中 13:00 UTC
那次，冬令时命中 14:00 UTC 那次，另一次空跑退出。

**本地定时已停用。** `com.eddie.taurient-lite.plist.disabled` 和 `run_daily.sh`
留在仓库里备查。云端已经覆盖所有情况，再跑一份本地的只会重复消耗额度。

## 手动跑一次

```bash
cd /Users/eddie/Desktop/DSO429/taurient-lite
claude "照着 RUNBOOK.md 生成今天的简报"
```

只想重新渲染已有数据，不重新抓新闻：

```bash
python3 render.py 2026-09-06
```

## 测试

```bash
python3 -m unittest discover -s tests -t .
```

184 个用例，只用标准库。改完 `taurient_lite/` 下的任何文件都要跑一遍。
覆盖反序列化的每条校验规则、组件的空数据分支、主题三个块的完整性、
HTML 转义、行情解析与重试路径、以及临时目录里的端到端渲染。

## 设计说明

版面参考晨间通讯稿而不是交易终端：单栏阅读宽度约 65 个西文字符，左侧数字轨
标出排名，Newsreader 做标题、IBM Plex Sans 做正文、IBM Plex Mono 管所有数字。
字号走小三度阶梯，全大写标签加宽字距，衬线标题收紧字距。

钴蓝是品牌色，只用在结构和交互上；红绿严格保留给市场方向，不参与装饰。
涨跌色跑过色觉障碍可辨度校验，亮色模式全项通过，暗色模式靠方向箭头、
带符号数值和三格强度条做二次编码。

明暗两套主题由 `theme.py` 里的 token 表生成三个块：裸 `:root` 定义完整亮色
调色板，媒体查询跟随系统但让位于显式的亮色选择，`[data-theme="dark"]` 让
显式的暗色选择压过系统。测试逐个 token 断言三个块都完整，这是 Artifact
页面最经典的一类崩法。

## 边界

这是新闻摘要工具，不是投顾。不产生买卖建议，不做价格预测。
所有数字都必须能追溯到 `sources` 里的原始报道，拿不准的数字不写。
