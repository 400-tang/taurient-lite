# Taurient Lite — 每日运行手册

这个文件是给 Claude 读的。定时任务每天早上把这份指令交给一个 Claude Code
会话，它照着做完四步，Eddie 打开同一个链接就能看到当天的简报。

工作目录：`/Users/eddie/Desktop/DSO429/taurient-lite`
配置：`config.json`（覆盖范围、条数目标、Artifact 链接）

---

## 第 1 步 · 扫描

用 `WebSearch` 跑至少 8 组查询，覆盖 `config.json` 里的 scope。查询里带上当天日期，
让搜索引擎优先返回新内容。建议的查询骨架，每天按当下情况调整：

1. `stock market today <日期> recap S&P 500 Nasdaq`
2. `Federal Reserve interest rate news <月份 年份>`
3. `US economic data release <日期> CPI jobs PMI`
4. `earnings report <日期> stock reaction`
5. `Nvidia AI semiconductor news <日期>`
6. `AI company funding announcement <日期>`
7. `oil prices treasury yields <日期>`
8. `premarket movers <日期>`

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
| `tape.rows` | 主要指数、收益率、油价的最新收盘，`dir` 只能是 `up`/`down`/`flat` |
| `tape.asof` | 明确标注这些数字的时点，跨时区容易搞错 |
| `items[].rank` | 全局排名，从 1 开始，跨 tier 连续 |
| `calendar` | 未来几天的已知事件，`weight` 为 `high`/`mid`/`low` |

**准确性规则。** 每个数字都要能追到 `sources` 里的某一条。不确定的数字宁可不写，
也不要估。日期和时区一律写清楚（ET / PT）。不写任何形式的买卖建议或价格预测。

## 第 4 步 · 渲染并发布

```bash
cd /Users/eddie/Desktop/DSO429/taurient-lite
python3 render.py            # 不带参数就渲染最新的那份
```

生成 `site/index.html` 和 `briefs/<日期>.md`。然后用 Artifact 工具发布，
**必须**把 `config.json` 里的 `artifact_url` 作为 `url` 参数传进去，
这样链接保持不变。发布前先 `action: "read"` 读一次线上版本。

发布完成后给 Eddie 一句话：今天的主线是什么，加上链接。

---

## 手动跑

```bash
cd /Users/eddie/Desktop/DSO429/taurient-lite
claude "照着 RUNBOOK.md 生成今天的简报"
```

## 改覆盖范围

编辑 `config.json` 的 `scope`，第 1 步的查询会跟着变。改条数目标就动
`target_counts`。改版式和配色去 `render.py` 里的 `CSS`，JSON 数据不用动。
