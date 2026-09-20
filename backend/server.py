"""Taurient Lite 的后端服务：FastAPI，直接复用 `taurient_lite` 包。

这个服务解决的是静态 Artifact 页面做不到的两件事：

1. **现场刷新。** 页面上的板块热力与 ``/api/quote/{ticker}`` 都是现场
   去查，拿到的是此刻的数字，不用等第二天的定时任务。
2. **任意股票查询。** 不限于 `config.json` 里固定的自选股，
   ``/api/short-interest/{ticker}`` 能查任何一只股票在 FINRA 的
   最新空头持仓。
3. **按名字找代码。** ``/api/search`` 让自选股面板能做自动补全——
   在此之前用户必须知道确切代码才能添加，不知道 AAPL 就加不了苹果。

**这个服务不做新闻抓取、不做 LLM 判断。** 每天的新闻扫描、分层、
深度元数据这些需要模型去读原文、做取舍的活，还是云端的 Claude Code
定时任务在做，写进 `briefs/<日期>.json` 再推回仓库——那部分工作
本质上需要判断力，不是这个后端能替代的。这个服务只是在已经生成的
数据上面，加一层「现场再问一次」的能力。

**部署在 Render。** 见仓库根目录的 `render.yaml`。本地跑：

    pip install -r backend/requirements.txt
    uvicorn backend.server:app --reload

要在仓库根目录下跑这条命令，`taurient_lite` 包才能被正常导入。
"""

from __future__ import annotations

import json
import os
import platform
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from taurient_lite.config import Config
from taurient_lite.html_renderer import render_body, render_head
from taurient_lite.pipeline import Paths, PipelineError, latest_date, load_brief
from taurient_lite.quotes import Quote, QuoteError, fetch_quote
from taurient_lite.schema import Brief, Market, SchemaError
from taurient_lite.history import DEFAULT_RANGE, RANGES, HistoryError, fetch_history, summarise
from taurient_lite.short_interest import ShortInterestError, fetch_latest
from taurient_lite.theme import GOOGLE_FONTS, TOKENS, build_palette_css, load_style


from . import assets, auth_bar, auth_panel, keepalive, live, stock_page
from .stock_news import mentions_for
from .search import MAX_RESULTS, SearchError, resolve, search

ROOT = Path(__file__).resolve().parent.parent
PATHS = Paths(ROOT)

#: 股票代码的粗校验。挡掉明显不是代码的输入（空格、脚本片段之类），
#: 不是为了穷举合法代码——真伪交给上游接口去判断，这里只挡显然的垃圾输入，
#: 避免带着奇怪字符去敲 Yahoo/FINRA 的接口。
TICKER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")


@asynccontextmanager
async def _lifespan(_: FastAPI):
    """进程起来时挂上保活线程，见 :mod:`backend.keepalive`。

    **在本地和测试里它什么也不做**，判据是 Render 注入的环境变量在不在，
    所以这里不需要任何 if。返回值也不用留着：那是个守护线程，进程退出
    时自己就没了。
    """
    keepalive.start()
    yield


app = FastAPI(
    title="Taurient Lite Backend",
    description="盘前简报的现场刷新与任意股票查询接口。",
    lifespan=_lifespan,
)


def _clean_ticker(raw: str) -> str:
    ticker = raw.strip().upper()
    if not TICKER_PATTERN.match(ticker):
        raise HTTPException(status_code=400, detail=f"{raw!r} 不是一个合法的股票代码")
    return ticker


def _wrap_page(brief: Brief, config: Config) -> str:
    """套上完整的 HTML 骨架。

    `html_renderer` 里 `render_head()`/`render_body()` 是分开的两个函数——
    ``render_html()`` 只是把两者接在一起，产出 Artifact 要的那种「片段」
    （Artifact 平台自己会包 ``<!doctype>``/``<html>``/``<head>``/``<body>``）。
    这里没有那层平台，所以不调用合并版的 ``render_html()``，而是分别拿到
    head 和 body 的内容，各自放进真正的 ``<head>`` 和 ``<body>``——不用
    像凑合页面那样把整段内容塞进一个标签再指望浏览器自己纠错。
    """
    head = render_head()
    body = render_body(brief, config)
    panel = auth_bar.render(config.supabase)  # 没配 Supabase 时是空串
    return (
        "<!doctype html>\n"
        '<html lang="zh">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}\n"
        "</head>\n"
        f"<body>\n{panel}\n{body}\n</body>\n"
        "</html>\n"
    )


def _with_live_data(brief: Brief, config: Config, requested_date: str | None) -> Brief:
    """把行情与板块热力换成现场取的实时数据。

    **只对最新那份简报生效。** 翻看 ``?date=2026-09-10`` 这种历史存档时，
    页面上必须是那天的数字——给一份旧简报配今天的行情，读者会把两者当成
    同一天的事实，而那正是这个项目反复在防的错误。

    取不到就原样返回：实时数据是锦上添花，Yahoo 或 Nasdaq 不通的时候，
    页面该照常显示存档里的收盘数字，而不是整页 502。
    """
    if requested_date is not None:
        return brief

    updates: dict = {}

    market = live.live_market()
    if market:
        try:
            updates["market"] = Market.from_dict(market, "market")
        except SchemaError:
            pass

    return replace(brief, **updates) if updates else brief


@app.get("/health")
def health() -> dict:
    """给 Render 的健康检查用，同时报告**跑的是哪个版本**。

    **加这两个字段是有代价换来的。** 部署失败时 Render 会继续跑上一个成功
    的构建，于是所有路由照样 200，从外面看服务是好的——这个项目已经因此
    误判过一次：连着两次推送都没真正上线，而检查脚本一路绿灯。

    有了这两个字段，「线上跑的是不是我刚推的那个提交」就是一个可以直接
    查的事实，不再靠猜路由在不在。commit 由 Render 注入，本地跑时为空。
    """
    return {
        "status": "ok",
        "python": platform.python_version(),
        "commit": os.environ.get("RENDER_GIT_COMMIT", "")[:7],
    }


@app.get("/", response_class=HTMLResponse)
def index(date: str | None = Query(default=None, description="YYYY-MM-DD，缺省取最新一份")):
    """现场渲染当天（或指定日期）的简报，直接读仓库里的 JSON。

    跟 Artifact 上那份的区别：Artifact 是「发布」出去的静态快照，
    这里每次请求都重新读一遍 `briefs/` 目录、重新渲染一遍——如果
    云端任务刚推送了新的一天，这里立刻就是最新的，不需要任何手动发布。

    **行情与板块热力还会就地换成实时的**（见 :func:`_with_live_data`）。
    新闻仍然是每天一次的批处理产物，因为那部分需要模型判断；但数字不该
    跟着新闻一起等到明天早上。
    """
    try:
        target = date or latest_date(PATHS)
        brief = load_brief(PATHS, target)
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    config = Config.load(PATHS.config)
    return HTMLResponse(_wrap_page(_with_live_data(brief, config, date), config))


@app.get("/api/brief")
def api_brief(date: str | None = Query(default=None)) -> JSONResponse:
    """当天（或指定日期）简报的原始 JSON，供别的程序消费。"""
    try:
        target = date or latest_date(PATHS)
        path = PATHS.brief_json(target)
        if not path.exists():
            raise PipelineError(f"找不到 {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(raw)


@app.get("/api/quote/{ticker}")
def api_quote(ticker: str) -> dict:
    """现场查一只股票的最新价。"""
    symbol = _clean_ticker(ticker)
    try:
        quote: Quote = fetch_quote(symbol)
    except QuoteError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ticker": quote.ticker,
        "price": quote.price,
        "change_pct": quote.change_pct,
        "market_time": quote.market_time,
    }


@app.get("/api/search")
def api_search(
    q: str = Query(default="", description="公司名或代码，支持中文常用名"),
    limit: int = Query(default=MAX_RESULTS, ge=1, le=MAX_RESULTS),
) -> list[dict]:
    """按名字或代码搜股票，供自选股面板的自动补全使用。

    **搜不到返回空数组而不是报错。** 用户还在往输入框里打字时，
    每一次按键都会打到这里，「还没打完所以没有结果」是正常状态，
    不是错误——返回 4xx 会让前端把正常的中间状态显示成失败。

    上游挂掉才返回 502：那是真的坏了，前端应该退回「只能输精确代码」
    的老行为，而不是假装搜索结果为空。
    """
    term = (q or "").strip()
    if len(term) > 64:
        raise HTTPException(status_code=400, detail="查询词过长")
    if not term:
        return []
    try:
        return [m.as_dict() for m in search(term, limit=limit)]
    except SearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/short-interest/{ticker}")
def api_short_interest(ticker: str) -> dict:
    """查任意一只股票在 FINRA 的最新空头持仓快照。"""
    symbol = _clean_ticker(ticker)
    try:
        record = fetch_latest(symbol)
    except ShortInterestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "symbol": record.symbol,
        "issue_name": record.issue_name,
        "settlement_date": record.settlement_date.isoformat(),
        "current_shares": record.current_shares,
        "previous_shares": record.previous_shares,
        "change_shares": record.change_shares,
        "change_percent": record.change_percent,
        "days_to_cover": record.days_to_cover,
        "avg_daily_volume": record.avg_daily_volume,
        "citation": record.as_citation(),
    }


@app.get("/api/sectors")
def api_sectors() -> JSONResponse:
    """现场抓一份板块热力数据，绕开简报里存档的那份。

    页面自己已经在用它了（见 `_with_live_data`），单独开一个路由是为了
    让别的程序也能拿到同一份数据，跟 `/api/quote/{ticker}` 的关系类似。走的是同一个缓存，所以频繁调用不会真的去打 Nasdaq。
    """
    block = live.live_market()
    if not block:
        raise HTTPException(status_code=502, detail="板块数据暂时取不到")
    return JSONResponse(block)


@app.get("/api/history/{ticker}")
def api_history(
    ticker: str,
    range: str = Query(default=DEFAULT_RANGE, description="1mo/3mo/6mo/1y/5y"),
) -> JSONResponse:
    """一只股票的历史 K 线，形状就是图表库直接能吃的那种。

    颜色在服务端就配好塞进成交量柱里，而不是让前端自己判断涨跌再上色——
    「这根是涨是跌」的判据只应该有一处，两边各写一遍迟早会不一致。
    """
    symbol = _clean_ticker(ticker)
    if range not in RANGES:
        raise HTTPException(status_code=400, detail=f"不支持的区间 {range!r}")
    try:
        bars = fetch_history(symbol, span=range)
    except HistoryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    up, down = TOKENS["up"][0], TOKENS["down"][0]
    return JSONResponse(
        {
            "ticker": symbol,
            "range": range,
            "candles": [b.as_candle() for b in bars],
            "volumes": [b.as_volume(up_color=up, down_color=down) for b in bars],
            "stats": summarise(bars),
        }
    )


@app.get("/stock/{ticker}", response_class=HTMLResponse)
def stock(
    ticker: str,
    range: str = Query(default=DEFAULT_RANGE, description="1mo/3mo/6mo/1y/5y"),
):
    """个股页面：一张可缩放、可拖动、带十字光标的 K 线图。

    **这是唯一一个带前端交互的页面**，理由见 `backend/stock_page.py` 的
    模块注释。其余页面仍然是零 JavaScript 的服务端渲染。
    """
    symbol = _clean_ticker(ticker)
    if range not in RANGES:
        raise HTTPException(status_code=400, detail=f"不支持的区间 {range!r}")
    try:
        bars = fetch_history(symbol, span=range)
    except HistoryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # 公司名是锦上添花：查不到就只显示代码，不该为了一个名字让整页失败。
    name = ""
    try:
        match = resolve(symbol)
        name = match.name if match else ""
    except SearchError:
        pass

    config = Config.load(PATHS.config)
    body = stock_page.render(
        symbol,
        name=name,
        span=range,
        bars=bars,
        stats=summarise(bars),
        backend_url=config.backend_url,
        up_color=TOKENS["up"][0],
        down_color=TOKENS["down"][0],
        # 公司资料取不到就少几块，不影响 K 线——个股页的主体是图，
        # 资料是补充，补充拿不到不该让主体一起陪葬。
        company=live.live_company(symbol),
        mentions=mentions_for(PATHS.briefs, symbol),
        headlines=live.live_headlines(symbol, name),
    )
    return HTMLResponse(
        "<!doctype html>\n"
        '<html lang="zh">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{symbol} · Morning Tape</title>\n"
        f'<link rel="stylesheet" href="{GOOGLE_FONTS}">\n'
        f"<style>{build_palette_css()}\n{load_style('layout.css')}\n{assets.load('stock_page.css')}</style>\n"
        f"</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


@app.get("/account", response_class=HTMLResponse)
def account():
    """账号页：登录、退出、管理自选股。

    **登录表单从简报页搬到了这里。** 一个登录框嵌在正文上方，读者每天打开
    看新闻时都要先越过它，而登录是一辈子做一两次的事。简报页现在只在右上角
    留一个按钮，指向这里。

    高亮与过滤没有跟着搬——它们作用的对象就是简报页的新闻列表，
    搬到这一页就失去了对象。
    """
    config = Config.load(PATHS.config)
    if not config.supabase.configured:
        raise HTTPException(status_code=404, detail="没有配置 Supabase，账号功能未启用")

    body = auth_panel.render_page(config.supabase)
    back = config.backend_url.rstrip("/")
    return HTMLResponse(
        "<!doctype html>\n"
        '<html lang="zh">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>账号 · Morning Tape</title>\n"
        f'<link rel="stylesheet" href="{GOOGLE_FONTS}">\n'
        f"<style>{build_palette_css()}\n{load_style('layout.css')}\n{assets.load('account_shell.css')}</style>\n"
        "</head>\n<body>\n"
        f'<div class="account">\n'
        f'<a class="stock-back" href="{back}/">&larr; 回简报</a>\n'
        f"<h1>账号</h1>\n{body}\n</div>\n"
        "</body>\n</html>\n"
    )
