"""Taurient Lite 的后端服务：FastAPI，直接复用 `taurient_lite` 包。

这个服务解决的是静态 Artifact 页面做不到的两件事：

1. **现场刷新。** Artifact 上的数字是当天早上批处理生成时的快照，
   这里的 ``/api/quotes/live`` 和 ``/api/quote/{ticker}`` 现场去查
   Yahoo，拿到的是此刻的价格，不用等第二天的定时任务。
2. **任意股票查询。** 不限于 `config.json` 里固定的七巨头或自选股，
   ``/api/short-interest/{ticker}`` 能查任何一只股票在 FINRA 的
   最新空头持仓。

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
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from taurient_lite.config import Config
from taurient_lite.html_renderer import render_body, render_head
from taurient_lite.pipeline import Paths, PipelineError, latest_date, load_brief
from taurient_lite.quotes import Quote, QuoteError, fetch_quote
from taurient_lite.schema import Brief
from taurient_lite.short_interest import ShortInterestError, fetch_latest

from . import auth_panel

ROOT = Path(__file__).resolve().parent.parent
PATHS = Paths(ROOT)

#: 股票代码的粗校验。挡掉明显不是代码的输入（空格、脚本片段之类），
#: 不是为了穷举合法代码——真伪交给上游接口去判断，这里只挡显然的垃圾输入，
#: 避免带着奇怪字符去敲 Yahoo/FINRA 的接口。
TICKER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")

app = FastAPI(
    title="Taurient Lite Backend",
    description="盘前简报的现场刷新与任意股票查询接口。",
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
    panel = auth_panel.render(config.supabase)  # 没配 Supabase 时是空串
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


@app.get("/health")
def health() -> dict:
    """给 Render 的健康检查用。"""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(date: str | None = Query(default=None, description="YYYY-MM-DD，缺省取最新一份")):
    """现场渲染当天（或指定日期）的简报，直接读仓库里的 JSON。

    跟 Artifact 上那份的区别：Artifact 是「发布」出去的静态快照，
    这里每次请求都重新读一遍 `briefs/` 目录、重新渲染一遍——如果
    云端任务刚推送了新的一天，这里立刻就是最新的，不需要任何手动发布。
    """
    try:
        target = date or latest_date(PATHS)
        brief = load_brief(PATHS, target)
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    config = Config.load(PATHS.config)
    return HTMLResponse(_wrap_page(brief, config))


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
    """现场查一只股票的最新价，不限于七巨头名单。"""
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


@app.get("/api/quotes/live")
def api_quotes_live() -> list[dict]:
    """现场刷新 `config.json` 里配置的七巨头名单，绕开当天存档的快照。"""
    config = Config.load(PATHS.config)
    if not config.mag7:
        raise HTTPException(status_code=404, detail="config.json 里的 mag7 是空的")

    results = []
    for symbol in config.mag7:
        try:
            quote = fetch_quote(symbol)
        except QuoteError as exc:
            results.append({"ticker": symbol, "error": str(exc)})
            continue
        results.append(
            {
                "ticker": quote.ticker,
                "price": quote.price,
                "change_pct": quote.change_pct,
                "market_time": quote.market_time,
            }
        )
    return results


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
