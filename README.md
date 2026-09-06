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

云端 routine `trig_01TCdAaPJVRePAdQvQRffedk`，周一到周五自动执行：克隆仓库、
扫描新闻、渲染、发布到固定的 Artifact 链接、再把当天的 JSON 和 Markdown 提交回来。
本地想同步归档就 `git pull`。管理页面在
https://claude.ai/code/routines/trig_01TCdAaPJVRePAdQvQRffedk

**夏令时不用管。** cron 只认 UTC，单点触发会在时区切换时漂一小时。所以排成
每天两次 `0 13,14 * * 1-5`，由运行提示里的时间闸门决定哪一次真正执行：
只有加州本地时间已过 6:00、且当天简报尚未生成时才动手。夏令时命中 13:00 UTC 那次，
冬令时命中 14:00 UTC 那次，另一次空跑退出。

**本地定时已停用。** `com.eddie.taurient-lite.plist.disabled` 和 `run_daily.sh`
留在仓库里备查。云端已经覆盖了所有情况，再跑一份本地的只会重复消耗额度。
真要恢复就把 plist 拷回 `~/Library/LaunchAgents/` 再 `launchctl bootstrap`。

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
