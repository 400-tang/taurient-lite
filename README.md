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
- **独立的日历标签页**：接下来的事件摆在滚动周网格上，哪几天扎堆一眼可见；
  日期没定的事件（比如还没排期的 FOMC 决议）单独列在「日期待定」，
  不会为了视觉整齐编一个假日期
- **独立的异动标签页**：每天开盘前扫约 2500 只流动性达标的美股，按「离起涨点
  多近」分成初动/延续/基底/已延伸四档。它解决的是「等我从新闻里知道，
  这波已经走完了」——新闻天然滞后，价量不滞后。每只标的都标注当天的新闻
  覆盖度，而且是**反着读**的：无报道 = 市场还没注意到 = 线索最早

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
├── scan_momentum.py        命令行入口：全市场价量异动扫描
├── apply_momentum.py       命令行入口：把扫描结果写进当天的简报 JSON
├── fetch_short_interest.py 命令行入口：查 FINRA 官方空头持仓
├── import_watchlist.py     导入 TradingView 的自选股导出
├── render.yaml             Render 部署配置（Blueprint）
├── taurient_lite/          渲染流水线，零第三方依赖
│   ├── schema.py           数据定义与校验
│   ├── config.py           配置读取
│   ├── theme.py            设计 token 与样式表
│   ├── components/         组件层
│   ├── html_renderer.py    组装整页
│   ├── markdown_renderer.py 组装存档
│   ├── pipeline.py         编排
│   ├── quotes.py           行情抓取
│   ├── momentum.py         价量异动判定，纯函数
│   └── short_interest.py   FINRA 空头持仓抓取，研究/核实工具
├── backend/                Web 后端，部署在 Render，唯一需要装依赖的地方
│   ├── server.py           FastAPI，复用 taurient_lite，不重新实现逻辑
│   ├── auth_panel.py       登录与个人自选股面板（Supabase），backend 独有
│   ├── requirements.txt    fastapi / uvicorn / httpx
│   └── test_server.py      路由测试，独立于主测试套件
├── tests/                  296 个用例，零依赖
├── briefs/                 每日 JSON（真相来源）与 Markdown 存档
└── site/index.html         渲染产物，发布成 Artifact
```

数据和呈现是分开的。JSON 是唯一的真实来源，Markdown 存档和网页都从它生成。
想换配色或版式只改 `taurient_lite/theme.py`，历史数据不动；想改覆盖范围只改
`config.json`，渲染逻辑不动。

依赖方向严格向下，没有环：`schema` 不依赖任何模块，`components` 只依赖
`schema` 和 `theme`，`pipeline` 只依赖渲染器。所以每一层都能单独测试。

## 每天发生什么

1. 扫描：至少 12 组查询加逐个自选股，重要条目用原文核对数字。三类
   硬数字优先查一手源头而不是二手汇总站：联储会议日期查
   federalreserve.gov，财报日期与公司公告查 SEC EDGAR 备案，
   空头持仓用 `fetch_short_interest.py` 查 FINRA 官方数据
2. 筛选：同一事件跨媒体合并，来源数量当重要性信号，分成三层
3. 写 JSON：必读层补齐资产矩阵、交叉信源、历史脉络
4. 取行情并渲染：`fetch_quotes.py` 然后 `render.py`；异动候选从
   `data/momentum_scan.json` 里挑，补上新闻覆盖度和一句话
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

## 价量异动扫描

新闻是滞后的：一只票的催化剂先反映在成交量和价格结构上，几天甚至几周
之后才成为头条。等它进入新闻视野，可交易的部分往往已经结束。这个模块
换一层数据——只吃 OHLCV，不读任何文本——把观察窗口从「新闻发生后」
前移到「价量异动时」。

判定的核心不是「谁涨得多」，而是**这只票走到这波的第几天**：

| 阶段 | 含义 |
|---|---|
| 初动 | 突破 50 日高点后 3 天内，且当日放量到 20 日中位量的 2.5 倍以上 |
| 延续 | 突破后两周内，趋势还在，但最好的位置已经过去 |
| 基底 | 尚未突破，区间收窄，属于观察名单 |
| 已延伸 | 距 20 日均线超过 35%、或突破已逾 10 天、或自基底翻倍 |

「已延伸」这一档是刻意保留并展示的：不把它剔除，读者才能认出
「这个我已经错过了」；只显示涨得凶的，结果和看新闻一样晚。

**突破位失守就是一波行情的终点。** 这条判定是拿真实数据试出来的——
不加的话，一只三个月前突破、此后早已回落盘整的票会被算成「运行了
74 天的趋势」，进而污染整个阶段判定。

### 它做不到什么

**这不是买卖信号。** 全量回测：2515 只流动性达标的美股、两年、**5090 次
初动信号**（早期版本只用了 59 只手挑的高波动标的、153 次信号，样本偏斜
导致结论完全相反，两组数字都保留在这里，因为犯错的过程本身是结论的一部分）。

信号本身略好过抛硬币：

| 持有方式 | 胜率 | 期望值 | 中位 |
|---|---|---|---|
| 10 日 | 51.6% | +0.61% | +0.35% |
| 20 日 | 51.4% | +1.06% | +0.31% |
| 30 日 | 51.7% | +1.79% | +0.49% |

但**期望值几乎全部来自极少数走出趋势的标的**——最好一笔 +223%，而中位数
只有 +0.3%。一半以上的单子基本不赚钱。

**「越早越好」这个出发点被自己的数据证伪了。** 按模块的早期度分数排序：

| 分组 | 20 日期望 | 中位 |
|---|---|---|
| 分数最高 25%（最早） | **−0.19%** | −0.35% |
| 分数最低 25%（最延伸） | **+1.92%** | +0.27% |

单因子也一样反直觉：乖离 >30% 的一组期望 +2.9%，高于乖离 <15% 的 +0.9%；
自基底已涨超 80% 的一组期望 +4.6%，远高于涨幅不到 30% 的 +0.2%。
（但这些高期望组的中位数是负的，收益全在尾部——所以「那就追强势」
同样不是能照做的结论，只是把赌注换了个方向。）

这没有改变模块的结构，因为阶段划分本来就是**事实陈述而非收益预测**：
知道「刚突破三天」和知道「已经涨了三个月」对使用者都有用，只是
**不能把前者当成买入理由**。分数因此只决定陈列顺序。

**止盈会让胜率变好看，让收益变差。** 常被问到的一个想法是「+5% 就锁定」：

| 策略 | 胜率 | 期望值 |
|---|---|---|
| 不止盈，持有 30 日 | 51.7% | **+1.79%** |
| 止盈 +5% | **73.6%** | +0.41% |
| 止盈 +10% | 60.4% | +0.60% |
| 止盈 +20% | 53.7% | +1.15% |
| 止盈 +5% / 止损 −8% | 61.6% | +0.12% |
| 只止损 −10%，让盈利跑 | 42.8% | **+1.17%** |

止盈线越高、胜率越低而期望值越高，这是一条干净的单调关系。原因就是上面
那条：收益集中在肥尾，而 +5% 止盈恰好卖掉的就是那几只唯一能补偿其余亏损
的票，亏损端却没有截断。**胜率是这里最容易骗人的指标。**

### 三个必须记住的样本前提

1. **区间偏多头**（2024–2026），动量策略在这种环境里天然好看。
2. **有幸存者偏差**：universe 是**今天**仍在交易且流动性达标的 2515 只，
   两年内退市或崩掉的票根本不在样本里，这会系统性高估收益。
3. **未计交易成本**。期望值 +0.4% 这个量级，佣金、点差、滑点吃掉一大半
   很正常；止盈方案交易频率最高，受伤也最重。

所以它真正提供的是**时间**，不是胜率：BE 这只票在 2025-06-30、$23.92 就进过
初动档，而它现在是 $258。这不代表模块能预测 BE 会涨十倍，只代表它在价量
层面比新闻层面早了几个月看见这件事。至于哪一只能走出来，模块答不了。

### 怎么跑

```bash
python3 apply_momentum.py <日期>            # 把扫描结果写进简报（数字自动填，判断你写）
python3 scan_momentum.py                    # 日常扫描，读 data/universe.txt
python3 scan_momentum.py --refresh-universe # 重建流动性名单，每周一次
python3 scan_momentum.py --limit 200        # 只扫前 200 只，本地调试
```

跑在 GitHub Actions 上（`.github/workflows/momentum-scan.yml`），
理由和行情快照一样：云端定时任务的沙箱连不了 Yahoo，runner 可以。
工作日 12:10 UTC 扫描，周日 09:00 UTC 重建流动性名单。

名单来自 Nasdaq 官方代码目录，按日均成交额 1000 万美元、股价 3 美元
两道门槛筛出约 2500 只。发现层另外从 Yahoo 预置筛选器捞当日异动的
代码，保证完全不在名单里的新名字也能进候选。

## 后端服务

`backend/` 是一个独立的 FastAPI 服务，部署在 Render，直接复用 `taurient_lite`
包，不重新实现任何抓取或渲染逻辑。它解决 Artifact 静态页面做不到的两件事：

- **现场刷新**：`/api/quotes/live` 和 `/api/quote/{ticker}` 现场去查 Yahoo，
  拿到的是此刻的价格，不用等第二天的定时任务
- **任意股票查询**：`/api/short-interest/{ticker}` 能查任何一只股票在 FINRA
  的最新空头持仓，不限于 `config.json` 里固定的名单

`/` 现场读 `briefs/` 目录里最新的 JSON 并渲染成页面，跟 Artifact 上那份的
区别是它永远反映仓库里最新的数据，不需要手动发布。

新闻扫描、分层、深度元数据这些需要模型判断力的活，还是云端的 Claude Code
定时任务在做——这个后端不碰那部分，只在已生成的数据上加一层「现场再问
一次」的能力。

### 账号与个人自选股

`backend/auth_panel.py` 加了一个登录面板，用 Supabase 做账号系统：邮箱
魔法链接登录（不设密码），每个人自己的自选股存在 Supabase 的一张表里，
用行级安全策略锁死——谁都只能读写自己那一行。登录后，当天已经扫描好的
新闻里凡是涉及自己关心的股票的条目会高亮，还有个开关可以直接把不相关的
条目全部隐藏，只看跟自己有关的。

这一层**只存在于 backend 渲染的页面里，不影响 Artifact 发布的那份**——
`taurient_lite/` 核心包对 Supabase 一无所知，保持零依赖，账号系统需要的
东西全在 `backend/` 目录下自成一体。每条新闻在渲染时会带一个
`data-tickers` 属性标出涉及哪些代码（`taurient_lite/components/items.py`
里加的），这个属性本身对 Artifact 版本完全无害，只有登录面板的 JS 会用它。

配置在 `config.json` 的 `supabase` 块：

```json
"supabase": {
  "url": "https://你的项目.supabase.co",
  "anon_key": "eyJ..."
}
```

`anon_key` 设计成可以公开——它本来就要被嵌进浏览器代码里，真正挡住越权
读写的是 Supabase 那边的行级安全策略。两个字段留空就是没开这个功能，
`/` 页面上不会出现登录面板。

**要接自己的 Supabase 项目：**

1. supabase.com 建一个免费项目
2. 项目的 SQL Editor 里建表并开行级安全：

   ```sql
   create table watchlists (
     user_id uuid references auth.users(id) primary key,
     symbols text[] not null default '{}',
     updated_at timestamptz not null default now()
   );

   alter table watchlists enable row level security;

   create policy "read own watchlist"
     on watchlists for select using (auth.uid() = user_id);
   create policy "write own watchlist"
     on watchlists for insert with check (auth.uid() = user_id);
   create policy "update own watchlist"
     on watchlists for update using (auth.uid() = user_id);
   ```

3. Authentication → Providers 确认 Email 是开着的（默认开）
4. Project Settings → API 里的 Project URL 和 anon/publishable key 填进
   `config.json` 的 `supabase` 块

免费额度：每月 5 万活跃用户、500MB 数据库，几个人用完全够，唯一要注意的
是项目连续一周没人访问会自动暂停，需要去后台手动点一下唤醒。

**部署到 Render：** 后台选 New → Blueprint，连上这个仓库，读
`render.yaml` 自动建好服务，不需要手动填 build/start 命令。

**本地跑：**

```bash
pip install -r backend/requirements.txt
uvicorn backend.server:app --reload
```

要在仓库根目录下跑，`taurient_lite` 包才能被正常导入。

**测试：**

```bash
python3 -m unittest backend.test_server -v
```

这套测试独立于主测试套件（`tests/`），因为主套件必须保持零依赖，
不能因为后端需要 FastAPI 就连带装进每日生成流水线的运行环境。

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

243 个用例，只用标准库。改完 `taurient_lite/` 下的任何文件都要跑一遍。
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
