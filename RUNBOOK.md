# Taurient Lite — 每日运行手册

这个文件是给 Claude 读的。定时任务每天早上把这份指令交给一个 Claude Code
会话，它照着做完四步，Eddie 打开同一个链接就能看到当天的简报。

工作目录：`/Users/eddie/Desktop/DSO429/taurient-lite`
配置：`config.json`（覆盖范围、条数目标、Artifact 链接）

---

## 第 1 步 · 扫描

用 `WebSearch` 跑至少 12 组查询，覆盖 `config.json` 里的 scope。查询里带上当天日期，
让搜索引擎优先返回新内容。目标是扫过 60 篇以上，最终留下 15 条以上。

固定要跑的：

1. `stock market today <日期> recap S&P 500 Nasdaq`
2. `Federal Reserve interest rate news <日期>`
3. `US economic data release <日期> CPI jobs PMI`
4. `earnings report <日期> stock reaction`
5. `biggest stock movers <日期> why`
6. `Nvidia AI semiconductor news <日期>`
7. `AI company funding acquisition <日期>`
8. `oil prices treasury yields <日期>`
9. `premarket movers <日期>`
10. `tech layoffs guidance cut <日期>`

再加：`config.json` 的 `watchlist.symbols` 里每个代码至少一组
`<代码> stock news <日期>`，把命中的条目在 `tickers` 字段里标上代码。

**时效是硬要求。** `config.json` 的 `freshness` 定死了上限：正文超过
`max_age_days` 天的新闻不收，`must-read` 层不得超过 `must_read_max_age_days` 天。
已经发酵了几天的事件只能进 `noise` 层，而且正文第一句必须说清楚它是旧闻，
以及今天有什么新进展。周日或周一的前瞻版可以在简报 JSON 里写
`"max_age_days": 5` 覆写上限。

对最重要的三到五条，用 `WebFetch` 打开原文确认数字，不要只依赖搜索摘要。

## 第 2 步 · 筛选与排序

**去重合并。** 同一个事件被多家媒体报道时合成一条，把所有媒体放进 `sources`。
来源数量本身就是重要性信号。

**分三层。**
- `must-read` — 会改变资产定价的事：政策转向、宏观数据超预期、大市值公司的重大公告。
- `worth-knowing` — 影响单个板块，或者是接下来事件的前置背景。
- `noise` — 值得知道但不影响任何决策，一句话带过。

**排序标准**，从重到轻：影响的资产范围 > 意外程度（实际 vs 预期的差距）>
时效性 > 报道密度。

**每条要写清楚三件事：** 发生了什么（`body`）、为什么重要（`why`）、
影响到谁（`impact`）。`noise` 层只要 `body`。

`why` 是这份简报的价值所在。不要复述新闻，要说出这条新闻改变了什么判断。

## 第 3 步 · 写 JSON

写到 `briefs/<YYYY-MM-DD>.json`，结构照抄 `briefs/2026-09-06.json`。字段说明：

| 字段 | 说明 |
|---|---|
| `thesis` | 一句话把当天所有新闻串成一条主线，两三句以内 |
| `scanned` / `kept` | 实际扫描与保留的条数，如实填 |
| `max_age_days` | 可选。只在周日或周一的前瞻版上写，覆写时效上限 |
| `mag7` | 别手写，第 4 步用 `fetch_quotes.py` 自动填。只需要写 `note` 那一句解读 |
| `tape.rows` | 指数、收益率、油价，`dir` 只能是 `up`/`down`/`flat` |
| `tape.asof` | 明确标注数字的时点，跨时区容易搞错 |
| `items[].published` | **必填**，新闻本身的发布日期，`YYYY-MM-DD`。页面靠它显示时效徽章 |
| `items[].tickers` | 这条新闻涉及的股票代码，自选股面板靠它点亮 |
| `items[].rank` | 全局排名，从 1 开始，跨 tier 连续 |
| `calendar` | 未来几天的已知事件，`weight` 为 `high`/`mid`/`low` |

条数目标见 `config.json` 的 `target_counts`：必读 3-5 条，值得知道 7-10 条，
背景噪音 4-6 条，总数不少于 15 条。少于这个数说明扫描不够，回第 1 步补查询。

**准确性规则。** 每个数字都要能追到 `sources` 里的某一条。不确定的数字宁可不写，
也不要估。日期和时区一律写清楚（ET / PT）。不写任何形式的买卖建议或价格预测。

## 第 4 步 · 取行情，渲染，发布

```bash
cd /Users/eddie/Desktop/DSO429/taurient-lite
python3 fetch_quotes.py <日期>     # 抓七巨头收盘价，写进 mag7 字段
python3 render.py                  # 不带参数就渲染最新的那份
```

`fetch_quotes.py` 走 Yahoo Finance 的 chart 端点，不需要 API key，
返回里带 `regularMarketTime`，所以 `asof` 是数据自己报的时点，不是推断的。
这个端点未受官方支持，可能被限流或改动；真取不到就跳过 `mag7` 板块，
不要手填数字。

`render.py` 生成 `site/index.html` 和 `briefs/<日期>.md`，并在最后提醒
哪些条目超出了时效上限。有提醒就回去把那些条目降级到 `noise` 或者删掉。

然后用 Artifact 工具发布，**必须**把 `config.json` 里的 `artifact_url`
作为 `url` 参数传进去，这样链接保持不变。发布前先 `action: "read"` 读一次线上版本。

发布完成后给 Eddie 一句话：今天的主线是什么，加上链接。

---

## 手动跑

```bash
cd /Users/eddie/Desktop/DSO429/taurient-lite
claude "照着 RUNBOOK.md 生成今天的简报"
```

## 改自选股

`config.json` 的 `watchlist.symbols` 是手工维护的。TradingView 可以导出：
打开自选列表 → Advanced view → Download list as TXT，然后

```bash
python3 import_watchlist.py ~/Downloads/watchlist.txt
python3 import_watchlist.py ~/Downloads/watchlist.txt --replace   # 整个覆盖
```

Robinhood 接不了。到 2026 年它仍然没有公开的股票 API，唯一开放的是加密货币
交易 API，股票端点从未文档化且服务条款禁止自动化访问。

## 改覆盖范围

编辑 `config.json` 的 `scope`，第 1 步的查询会跟着变。改条数目标就动
`target_counts`。改版式和配色去 `render.py` 里的 `CSS`，JSON 数据不用动。
