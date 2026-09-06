# Taurient Lite

一个盘前新闻简报工具。每个交易日早上 6:00 PT 自动扫描全球财经与科技新闻，
去重、按重要性分层、写清楚每条为什么重要，生成一个网页仪表盘和一份 Markdown 存档。

灵感来自澳洲对冲基金 Minotaur Capital 的内部工具 Taurient，那套系统每周用多个
大模型扫描约 3.5 万篇新闻来定位投资标的。这个是它的简化版，只做信息压缩这一层：
不选股，不给建议，只负责让你在开盘前用几分钟知道该知道的事。

**线上简报：** https://claude.ai/code/artifact/65328183-42d9-4ead-93c5-d2d3dc41b97a

## 覆盖范围

美股与宏观（联储、利率、通胀就业数据、财报公告、板块轮动），
科技与 AI 行业（半导体、云、AI 公司动态与融资，不限于上市公司）。

## 结构

```
taurient-lite/
├── RUNBOOK.md              每日流程，定时任务读这个
├── config.json             覆盖范围、条数目标、Artifact 链接
├── render.py               JSON → HTML + Markdown
├── briefs/
│   ├── 2026-09-06.json     当天的结构化数据，唯一的真实来源
│   └── 2026-09-06.md       可检索的历史存档
└── site/
    └── index.html          渲染产物，发布成 Artifact
```

数据和呈现是分开的。JSON 是唯一的真实来源，Markdown 存档和网页都从它生成。
想换配色或版式只改 `render.py` 里的 CSS，历史数据不受影响；想改覆盖范围只改
`config.json`，渲染逻辑不受影响。

## 每天发生什么

1. 扫描：至少 8 组 `WebSearch` 查询，重要条目用 `WebFetch` 回原文核对数字
2. 筛选：同一事件跨媒体合并，来源数量作为重要性信号，分成三层
3. 排序：影响的资产范围 > 意外程度 > 时效性 > 报道密度
4. 渲染：`python3 render.py`，然后发布到同一个 Artifact 链接

## 定时运行

**本地。** launchd 任务 `com.eddie.taurient-lite`，每周一到周五 5:45 PT
调用 `run_daily.sh`。脚本先检查当天的 JSON 是否已存在，存在就跳过，
所以合盖休眠后唤醒补跑不会重复生成。生成成功后立刻 commit 并 push 到 GitHub，
这一步是云端去重的前提。日志在 `logs/`。

```bash
launchctl print gui/$(id -u)/com.eddie.taurient-lite   # 看状态
launchctl kickstart -k gui/$(id -u)/com.eddie.taurient-lite   # 立刻跑一次
launchctl bootout gui/$(id -u)/com.eddie.taurient-lite        # 停掉
```

**云端。** routine `trig_01TCdAaPJVRePAdQvQRffedk`，笔记本关机时兜底。
两边发布到同一个 Artifact 链接。

**为什么本地早 15 分钟。** 两边同时启动的话谁也看不到谁的成果，会重复生成一遍，
白白消耗一倍用量。所以本地排在 5:45，跑完把当天的 JSON 推到 GitHub；
云端 6:00 克隆下来时看到文件已存在，直接退出。机器关着的那天本地不跑，
云端拿不到文件，正常执行。

**夏令时。** 本地 launchd 认系统本地时间，夏令时切换时自动跟随，不用管。
云端 cron 只认 UTC，所以排成每天两次 `0 13,14 * * 1-5`，再由运行提示里的
时间闸门决定哪一次真正执行：只有加州本地时间已过 6:00、且当天简报尚未生成时才动手。
夏令时是 13:00 UTC 那次命中，冬令时是 14:00 UTC 那次，另一次空跑退出。
这样两年一次的时区切换不需要任何人工调整。

## 手动跑一次

```bash
cd /Users/eddie/Desktop/DSO429/taurient-lite
claude "照着 RUNBOOK.md 生成今天的简报"
```

只想重新渲染已有数据，不重新抓新闻：

```bash
python3 render.py 2026-09-06
```

## 设计说明

版面参考晨间通讯稿而不是交易终端：单栏阅读宽度，左侧数字轨标出排名，
Newsreader 做标题、IBM Plex Sans 做正文、IBM Plex Mono 做所有数字。
钴蓝是品牌色，只用在结构上；红绿严格保留给市场方向，不参与装饰。
明暗两套主题都通过 CSS 变量定义，跟随系统或读者的显式选择。

## 边界

这是新闻摘要工具，不是投顾。不产生买卖建议，不做价格预测。
所有数字都必须能追溯到 `sources` 里的原始报道，拿不准的数字不写。
