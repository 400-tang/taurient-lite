# Taurient Lite — 每日运行手册

这个文件是给 Claude 读的。定时任务每天早上把这份指令交给一个 Claude Code
会话，它照着做完七步，Eddie 打开同一个链接就能看到当天的简报。

**你是主编。** 搜新闻、查漏报、核对事实交给三个子 agent（定义在 `.claude/agents/`）：

- `news-scanner`：负责一个话题的新闻扫描，一次派四个并行；
- `coverage-checker`：只读，独立找出当天最大的新闻，再对照你的草稿查漏报；
- `fact-checker`：只读，核对数字和日期。

筛选、分层、写稿、发布由你自己做——需要判断的活不外包。

工作目录：`/Users/eddie/Desktop/DSO429/taurient-lite`
配置：`config.json`（覆盖范围、条数目标、时效上限、自选股、Artifact 链接）

---

## 第 1 步 · 并行扫描

先读两份 GitHub Actions 已经提交好的数据（沙箱连不上行情网站，不要自己去抓）：

- `data/momentum_scan.json` 里 `stage` 为 `ignition` 的代码。它们是价量上刚起
  变化、但可能还没进入新闻视野的票。
- `data/market_snapshot.json` 里自选股的 FINRA 空头持仓。写「轧空」「仓位拥挤」
  这类新闻时直接引用这里的数字和结算日期，来源链接用
  `https://www.finra.org/finra-data/browse-catalog/equity-short-interest/data`。
  不同财经网站报的空头占比经常对不上，根源是它们都从同一份 FINRA 数据衍生，
  直接用源头就不用判断「哪家更准」。**不算占流通盘的百分比**——那需要股本
  数据，这里没有。

然后**在同一条消息里**派四个 `news-scanner` 子 agent 并行开工，一个话题一个：

| 话题 | 输出文件 | 任务里带上的固定查询 |
|---|---|---|
| 美股与宏观 | `scratch/scan-macro.json` | `stock market today <日期> recap S&P 500 Nasdaq`、`Federal Reserve interest rate news <日期>`、`US economic data release <日期> CPI jobs PMI`、`earnings report <日期> stock reaction`、`biggest stock movers <日期> why`、`premarket movers <日期>` |
| 科技与 AI | `scratch/scan-tech.json` | `Nvidia AI semiconductor news <日期>`、`AI company funding acquisition <日期>`、`tech layoffs guidance cut <日期>` |
| 地缘与大宗 | `scratch/scan-geo.json` | `oil prices treasury yields <日期>`，以及当天的地缘冲突与供给事件 |
| 自选股 | `scratch/scan-watchlist.json` | `config.json` 的 `watchlist.symbols` 里每个代码一组 `<代码> stock news <日期>` |

子 agent 看不到你的对话，所以每个任务里都要写全：话题和范围（照 `config.json`
的 `scope`）、今天的日期、时效上限、输出文件路径、上表的固定查询，以及上面读到
的初动代码列表。对初动代码要交代清楚：**不要专门去搜**，常规扫描里自然撞上了
再记进 `watch_hits`。专门搜一只票必然搜得到东西，那样就测不出它有没有在常规
新闻流里自然浮现。

**时效是硬要求。** `config.json` 的 `freshness` 定死了上限：超过 `max_age_days` 天的
不收，`must-read` 层不得超过 `must_read_max_age_days` 天。已经发酵几天的事件只能进
`noise` 层，而且正文第一句必须说清楚它是旧闻以及今天有什么新进展。周日或周一的
前瞻版可以在简报 JSON 里写 `"max_age_days": 5` 覆写上限。

四份结果都回来之后，读 `scratch/` 下的四个文件进入第 2 步。某个扫描员失败了，
重派一次；还失败就用剩下的几份继续，在最后给 Eddie 的一句话里提一下。

## 第 2 步 · 筛选与排序

**去重合并。** 同一个事件被多家媒体报道时合成一条，把所有媒体放进 `sources`。
来源数量本身就是重要性信号。

**分三层。**

- `must-read` — 会改变资产定价的事：政策转向、宏观数据超预期、大市值公司的重大公告。
- `worth-knowing` — 影响单个板块，或者是接下来事件的前置背景。
- `noise` — 值得知道但不影响任何决策，一句话带过。

**排序标准**，从重到轻：影响的资产范围 > 意外程度（实际 vs 预期的差距）>
时效性 > 报道密度。

## 第 3 步 · 写 JSON

写到 `briefs/<YYYY-MM-DD>.json`，结构照抄 `briefs/2026-09-06.json`。

### 顶层字段

| 字段 | 说明 |
|---|---|
| `date` / `weekday` / `edition` | 日期、星期、版次 |
| `generated_at` | 生成时刻，带时区 |
| `scanned` / `kept` | 实际扫描与保留的条数，如实填 |
| `thesis` | 一句话把当天所有新闻串成一条主线，两三句以内 |
| `max_age_days` | 可选。只在周日或周一的前瞻版上写，覆写时效上限 |
| `tape` | 指数、收益率、油价。`dir` 只能是 `up`/`down`/`flat` |
| `items` | 新闻条目，见下 |
| `calendar` | 未来的已知事件，见下 |
| `momentum` | 价量异动候选，见下。数字来自 `data/momentum_scan.json`，不要自己算 |

### 日历字段

网页上的「日历」标签页把这些事件摆到一个滚动的周网格上，网格从本周一
开始，长度按最远的已知日期动态撑到 4 到 6 周。

| 字段 | 说明 |
|---|---|
| `when` | 给人看的自由文本，例如 `Fri 9/11`、`本月晚些`、`10 月` |
| `time` | 时刻，例如 `08:30 ET`；没有就写空字符串 |
| `event` | 事件描述 |
| `weight` | `high`/`mid`/`low`，决定网格里方块的样式 |
| `date` | **强烈建议填**，`YYYY-MM-DD`。有这个字段事件才会画在网格的具体那一天上 |
| `sources` | **强烈建议填**，`[{name, url}, ...]`，跟新闻条目的 `sources` 结构完全一样 |

**`date` 只在真正确定的时候才写。** FOMC 决议如果还没有排定具体日期，
就只写 `when: "本月晚些"`，不要编一个日期凑数——没有 `date` 的事件会落进
网格下方的「日期待定」列表，标签就是原文；编一个假日期换来的视觉整齐
是虚假的精确。已经排定的会议、发布会、财报、数据发布日，都应该查到
确切日期再填。

**`sources` 不是可有可无的装饰。** 一个排定的日期本身就是一条事实，跟
新闻条目里任何一个数字没有本质区别——都要能被读者点开验证。日历页面上
网格里的每个事件只留一个指向首个来源的小箭头（空间紧张），完整的来源
列表在「日期待定」表格里展开。写日历条目时，用 `WebFetch` 打开原文确认
这个日期，不要凭经验或惯例推断（比如「苹果一般十点开发布会」这种假设，
哪怕历史上通常如此，也要对当次活动单独核实）。多个信源给出的数字不一致
时（比如空头持仓比例这类会随时间波动的数据），如实写出区间或分别标注，
不要挑一个看起来更整齐的数字了事。


### 异动字段

`data/momentum_scan.json` 是 GitHub Actions 在前一交易日收盘后扫完全市场（约 2500 只
流动性达标的美股）写下的，**里面的数字直接抄，一个都不要自己算**——
判定逻辑在 `taurient_lite/momentum.py` 里，是跑过测试的纯函数。

你要做的只有一件机器做不到的事：**给每只写一句 `note`**。

从扫描结果的 `candidates` 里挑 5 到 10 只写进 `momentum.candidates`，
优先挑 `stage` 是 `ignition` 的（这一档通常只有几只，全都写上），
再从 `continuation` 里补几只，最后可以放一两只 `extended` ——
后者的作用是让读者认出「这个我已经错过了」，不是推荐。

`note` 写一句话：价量上发生了什么，以及如果它恰好出现在你今天读过的
新闻里，那里说了什么。**没出现就不要提新闻**——不要写「今天没有相关
报道」这类话。你只读了当天扫到的几十篇，据此断言「没有报道」是过度
声称；这个字段曾经存在过（叫 `coverage`），正是因为说不准而被删掉。
**也不要为此专门去搜一轮**：专门搜一只票必然搜得到东西，那样得出的
结论和「它有没有在常规新闻流里自然浮现」是两回事。

其余字段（`stage`、`close`、`change_pct`、`rvol`、`breakout_age`、
`ext_ma20`、`run_from_base`）从扫描结果里原样复制。

**不要写任何买卖倾向。** `note` 只陈述「发生了什么」和「已知什么」，
不写「值得关注」「可以考虑」这类措辞。页面上已经印了免责说明：全量回测
（2515 只、两年、5090 次信号）初动档 20 日胜率 51.4%、期望 +1.1%，仅略好过
抛硬币，且收益集中在极少数尾部标的。**同一批数据还证伪了「越早越好」**——
按早期度排序，最早的一批前向收益反而更差。所以名单顺序只表示「有多新」。
措辞越像建议，这个模块越危险。

扫描文件缺失或当天没有值得写的候选时，**整个 `momentum` 字段省略**，
页面会自动不显示这个标签页。不要写一个空壳。

### 条目字段

必填：`rank`（全局连续，从 1 开始）、`tier`、`headline`、`body`。

强烈建议填：

| 字段 | 说明 |
|---|---|
| `published` | 新闻本身的发布日期，`YYYY-MM-DD`。页面靠它显示时效徽章 |
| `tickers` | 涉及的股票代码，自选股面板靠它点亮 |
| `sectors` | 板块标签 |
| `why` | 这条新闻改变了什么判断。不要复述新闻 |
| `impact` | 一句话说明影响面 |
| `sources` | 每个 `{name, url}`，可选 `angle` 写这家媒体独有的角度 |

### 深度元数据（`must-read` 层必须有，至少一项）

**`assets` — 资产波及矩阵。** 数组，每项是一个资产类别受到的方向与强度。

```json
{"asset_class": "美债", "direction": "down", "conviction": "high",
 "note": "两年期收益率跳到 4.35%，价格反向下跌。"}
```

- `asset_class` 只能是：美股、美债、美元、大宗商品、加密资产、海外股市
- `direction` 只能是：`up`（利好）、`down`（利空）、`mixed`（分化）、`none`（无影响）
- `conviction` 只能是：`high`、`medium`、`low`，渲染成三格填充条
- `note` 写**传导路径**。矩阵光有颜色没有因果，这句是必需的
- 同一个资产类别不能出现两次，会被校验挡下

判断不出来的类别就不要写。`none` 是「明确判断为无影响」，比不写更有信息量，
但也要有把握才用。

**`cross_source` — 多方信源交叉对比。**

```json
{"agreement": "split", "summary": "对升级性质的判断存在分歧。A 读作常态化消耗，B 侧重威胁升级表态。"}
```

- `agreement` 只能是 `aligned`（口径一致）、`split`（存在分歧）、`single`（单一来源）
- `summary` 点出差异所在。`split` 是最有价值的情况，差异本身就是信息
- 配合 `sources[].angle` 使用，页面会把各家角度列在卡片里

**`history` — 历史背景与演进脉络。**

```json
{"summary": "方向在八周内完全掉头。",
 "timeline": [{"when": "8 月", "event": "油价走高渗入通胀预期"},
              {"when": "9/4", "event": "非农三倍于预期"}]}
```

- `timeline` 是真实的时间序列，页面渲染成竖向时间轴，最后一个节点用品牌色点亮
- 只有一两个节点就别写 `timeline`，一句 `summary` 就够

### 准确性规则

每个数字都要能追到 `sources` 里的某一条。不确定的数字宁可不写，也不要估。
日期和时区一律写清楚（ET / PT）。**不写任何形式的买卖建议或价格预测。**

## 第 4 步 · 查漏报

写好 `briefs/<日期>.json` 之后，派一个 `coverage-checker` 子 agent，任务里给它
今天的日期、简报 JSON 的路径和时效上限。它会先独立列出今天最大的十条左右新闻，
再对照你的草稿。

扫描员是按话题分头搜的，最容易漏的恰恰是跨话题的大事，或者当天临时冒出来的
突发。所以它报「漏掉了」的，逐条判断：

- 确实是当天的大事、在时效内的，补进简报。它给的来源可以直接用，但数字要在
  第 5 步一起核查；
- 它报「层级偏低」的，按第 2 步的分层标准重新判断，该升就升；
- 你判断不该收的（超时效、其实是旧闻、影响面小），不收，在最后给 Eddie 的一句话里
  提一句「查漏报提了 X，没收，因为……」。

补完之后重新检查 `rank` 连续、`kept` 条数如实。

## 第 5 步 · 核查

把必读层每一条的关键数字、日历里每一个写了 `date` 的事件，连同来源链接，
交给 `fact-checker` 子 agent。条目多时拆成两三份并行派。

- 标成「不一致」的，按它给的证据改正；
- 标成「查不到」的，拿不准就删掉这个数字，不要估；
- 核查员给了新的一手来源链接的，补进对应条目的 `sources`。

## 第 6 步 · 合成、渲染、过质量关

```bash
cd /Users/eddie/Desktop/DSO429/taurient-lite
python3 apply_momentum.py <日期>                   # 把价量扫描结果写进 momentum.candidates
python3 fetch_sectors.py --cached --apply <日期>   # 把 data/sectors.json 写进 market
python3 render.py <日期>
python3 check_brief.py <日期>
```

**`check_brief.py` 退出码必须是 0 才能发布。** 不通过就按它指出的字段路径修改
JSON，再从 `render.py` 起重跑，直到通过。它检查的是有唯一答案的东西：各层条数、
时效、必读层的深度元数据、每条都有来源、板块热力和异动数据是不是上一交易日的
收盘、异动候选有没有过期的票、`note` 有没有补、有没有「值得关注」「可以考虑」
这类建议措辞。

唯一的例外：`data/sectors.json` 不是上一交易日的收盘数据（说明 Actions 昨晚没跑
成功），这时删掉简报里的 `market` 字段，改跑 `python3 check_brief.py <日期> --no-market`，
并在最后给 Eddie 的一句话里说明。**绝不手填涨跌幅**，那是在版面上造事实。

**`fetch_sectors.py --cached` 全自动，没有要你补的判断。** 板块数据由 GitHub Actions
在收盘后从 Nasdaq 抓好（工作流 `momentum-scan.yml`），这里只是原样写进简报。

**`apply_momentum.py` 只填数字，判断仍然要你写。** 它从
`data/momentum_scan.json` 里按档位配额挑候选（初动档全要，延续档 4 只，
已延伸 2 只做参照），把数字原样搬进简报 JSON，然后打印一份
「还需要你补 note」的清单。补完可以再跑一次——**已经写好的 `note` 与
`sources` 会被原样保留，只有数字被刷新**。

`render.py` 生成 `site/index.html` 和 `briefs/<日期>.md`；结构错误（字段写错）会直接
退出并指出字段路径，例如 `items[3].assets[0].direction`，照着路径改 JSON 再跑。

## 第 7 步 · 提交

`git add` 当天的简报 JSON、Markdown 存档和 `site/index.html`，提交并推送到 `main`。
`scratch/` 下的扫描结果是中间产物，已被 `.gitignore` 忽略，不要提交。**推送即上线**：Render 读到新提交会自动重新部署，
`https://taurient-lite-backend.onrender.com/` 随即是最新的一份。

推送完成后给 Eddie 一句话：今天的主线是什么，加上 Render 的链接。

### 关于 Artifact（已降级为按需）

**这一步不再每天做。** Artifact 那份是静态快照，Eddie 日常读的是 Render 页面，
而静态页拿不到现场取数（行情、板块热力都是活的），也跑不了外部脚本（K 线图表库
在那边用不了）。每天维护它的结果是：一个没人看的页面，还会拖住这边的技术选择——
每加一个交互功能都要迁就能力更弱的那个出口。

要一个随时秒开、不受 Render 休眠影响的分享链接时，再手动发一次：用 Artifact 工具
发布 `site/index.html`，把 `config.json` 里的 `artifact_url` 作为 `url` 参数传进去，
这样链接保持不变；发布前先 `action: "read"` 读一次线上版本；不要传 `favicon`。

---

## 代码结构

```
.claude/agents/
├── news-scanner.md      子 agent：一个话题的新闻扫描（Haiku）
├── coverage-checker.md  子 agent：独立找当天大新闻，查简报有没有漏（Haiku）
└── fact-checker.md      子 agent：只读核查数字和日期（Haiku）

taurient_lite/
├── schema.py            数据定义与校验，不依赖其他模块
├── config.py            配置读取
├── quality.py           发布前质量门，check_brief.py 调用
├── theme.py             设计 token 与样式表生成
├── components/          组件层，每个模块一组板块
├── html_renderer.py     组装整页
├── markdown_renderer.py 组装存档
├── pipeline.py          编排：读文件、调渲染、写文件
├── momentum.py          价量异动判定，纯函数，不碰网络
├── sectors.py           板块热力的抓取与聚合
├── short_interest.py    FINRA 空头持仓抓取
├── history.py / quotes.py  后端个股页用的 K 线与报价
└── fundamentals/        基本面扫描（尚未接入每日流程）
```

依赖方向永远向下，没有环。改样式只动 `theme.py`，改结构只动 `schema.py`，
两者互不影响。

**`backend/` 跟这份 RUNBOOK 描述的每日流程无关**，它是部署在 Render 的
一个 Web 服务，负责展示简报、现场刷新板块热力、个股页和划词问答，不参与新闻
扫描或简报生成。除非任务明确要求改后端，否则不用碰这个目录，也不用跑
`backend/` 下的测试——那需要装 FastAPI，云端定时任务的环境里没有。

**`managed-agents/` 也跟现在的每日流程无关**，那是迁移到 Anthropic 托管平台的
备用方案，按 API 用量计费，目前没有启用。

## 改了代码就跑测试

```bash
python3 -m unittest discover -s tests -t .
```

四百多个用例，零第三方依赖。**改完 `taurient_lite/` 下的任何文件都要跑一遍再发布。**
测试覆盖：反序列化的每条校验规则、组件的空数据分支、主题三个块的完整性、
HTML 转义、行情解析与重试、以及在临时目录里的端到端渲染。

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

这个自选股只决定第 1 步扫描时额外查哪些代码，跟 backend 那边每个人
登录后在 Supabase 里存的个人自选股是两回事，改这个不影响任何人已经
存好的个人列表。

## 改覆盖范围

编辑 `config.json` 的 `scope`，第 1 步的查询会跟着变。改条数目标就动
`target_counts`，改时效上限动 `freshness`。改版式和配色去 `taurient_lite/theme.py`，
JSON 数据不用动。
