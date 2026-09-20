"""后端路由测试，用 FastAPI 的 TestClient。

**这里的隔离策略跟 `tests/` 里那套不一样，是有意的。** `tests/test_pipeline.py`
每个用例都在临时目录里搭一个干净项目，因为那套代码把根目录做成了可注入的
参数（`Paths(root)`）。这个后端模块图省事，把 `PATHS` 做成了模块级的全局，
固定指向这个仓库自己的根目录——对一个跑在 Render 上、只服务一个人的个人
项目，这个简化是划算的，代价是测试没法用临时目录隔离，只能：

- 读路径（`/`、`/api/brief`）直接读仓库里真实的 `briefs/2026-09-06.json`
  和 `config.json`，因为它们本来就在这里，是这个仓库的一部分；
- 真正碰网络的部分（`fetch_quote`、`fetch_latest`）用 ``unittest.mock.patch``
  换掉，一次请求都不真的发出去。

跑这些测试需要先装 backend 的依赖：

    pip install -r backend/requirements.txt
    python3 -m unittest backend.test_server -v

这套测试不属于 ``python3 -m unittest discover -s tests -t .`` 那次总跑，
是分开跑的——主测试套件必须保持零依赖，不能因为后端需要 FastAPI
就连带装到每日生成流水线的运行环境里。
"""

from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.server import app
from taurient_lite.history import Bar, HistoryError
from taurient_lite.quotes import Quote, QuoteError
from taurient_lite.short_interest import ShortInterestError, ShortInterestRecord

client = TestClient(app)

#: 仓库里真实存在的一份简报，读路径的测试用它。
REAL_DATE = "2026-09-06"


class TestHealth(unittest.TestCase):
    def test_ok(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_reports_the_running_python(self):
        """部署失败时 Render 会继续跑旧构建，所有路由照样 200。
        报出解释器版本，「线上跑的是不是我刚推的那个」才是可查的事实。"""
        import platform as pf
        self.assertEqual(client.get("/health").json()["python"], pf.python_version())

    def test_commit_is_present_even_when_empty(self):
        """本地没有 RENDER_GIT_COMMIT，字段要在但可以是空串——
        缺字段会让检查脚本报 KeyError，而不是报告「认不出版本」。"""
        self.assertIn("commit", client.get("/health").json())


class TestIndex(unittest.TestCase):
    def test_renders_real_brief(self):
        response = client.get(f"/?date={REAL_DATE}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_title_lands_inside_head(self):
        """验证 head/body 是真的分开拼的，不是把整段片段塞进一个标签。"""
        html = client.get(f"/?date={REAL_DATE}").text
        head = html.split("<head>", 1)[1].split("</head>", 1)[0]
        self.assertIn("<title>Morning Tape</title>", head)
        self.assertIn("<style>", head)

    def test_content_lands_inside_body(self):
        html = client.get(f"/?date={REAL_DATE}").text
        body = html.split("<body>", 1)[1].split("</body>", 1)[0]
        self.assertIn('class="sheet"', body)

    def test_defaults_to_latest_when_no_date_given(self):
        # 不带 date 会走实时取数，测试里一律挡掉：测试不该依赖外网，
        # 也不该因为 Yahoo 限流而变红。
        with patch("backend.server.live.live_mag7", return_value=None), \
             patch("backend.server.live.live_market", return_value=None):
            response = client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_missing_date_is_404_not_500(self):
        response = client.get("/?date=1999-01-01")
        self.assertEqual(response.status_code, 404)


class TestApiBrief(unittest.TestCase):
    def test_returns_real_json(self):
        response = client.get(f"/api/brief?date={REAL_DATE}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["date"], REAL_DATE)
        self.assertIn("thesis", body)

    def test_missing_date_is_404(self):
        response = client.get("/api/brief?date=1999-01-01")
        self.assertEqual(response.status_code, 404)


class TestTickerValidation(unittest.TestCase):
    def test_ticker_starting_with_digit_rejected(self):
        response = client.get("/api/quote/1BAD")
        self.assertEqual(response.status_code, 400)

    def test_overlong_ticker_rejected(self):
        response = client.get("/api/quote/WAYTOOLONGTICKER")
        self.assertEqual(response.status_code, 400)

    def test_lowercase_ticker_is_normalised_not_rejected(self):
        with patch(
            "backend.server.fetch_quote",
            return_value=Quote(ticker="AAPL", price=1.0, change_pct=0.1, market_time=0),
        ) as mocked:
            response = client.get("/api/quote/aapl")
        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once_with("AAPL")


class TestApiQuote(unittest.TestCase):
    def test_success_shape(self):
        quote = Quote(ticker="NVDA", price=230.36, change_pct=0.84, market_time=1788552000)
        with patch("backend.server.fetch_quote", return_value=quote):
            response = client.get("/api/quote/NVDA")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ticker": "NVDA", "price": 230.36, "change_pct": 0.84, "market_time": 1788552000},
        )

    def test_upstream_failure_becomes_502_not_500(self):
        with patch("backend.server.fetch_quote", side_effect=QuoteError("NVDA 取价失败")):
            response = client.get("/api/quote/NVDA")
        self.assertEqual(response.status_code, 502)
        self.assertIn("NVDA", response.json()["detail"])


class TestApiQuotesLive(unittest.TestCase):
    def test_returns_one_entry_per_configured_ticker(self):
        def fake_fetch(symbol):
            return Quote(ticker=symbol, price=100.0, change_pct=1.0, market_time=0)

        with patch("backend.server.fetch_quote", side_effect=fake_fetch):
            response = client.get("/api/quotes/live")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreater(len(body), 0)
        self.assertEqual({row["ticker"] for row in body} & {"NVDA", "TSLA"}, {"NVDA", "TSLA"})

    def test_partial_failure_reports_per_ticker_error(self):
        def flaky(symbol):
            if symbol == "TSLA":
                raise QuoteError("TSLA 限流了")
            return Quote(ticker=symbol, price=1.0, change_pct=0.0, market_time=0)

        with patch("backend.server.fetch_quote", side_effect=flaky):
            response = client.get("/api/quotes/live")
        body = response.json()
        tsla_row = next(row for row in body if row["ticker"] == "TSLA")
        self.assertIn("error", tsla_row)
        other_rows = [row for row in body if row["ticker"] != "TSLA"]
        self.assertTrue(all("error" not in row for row in other_rows))


class TestApiShortInterest(unittest.TestCase):
    def test_success_shape(self):
        record = ShortInterestRecord(
            symbol="AI",
            issue_name="C3.ai, Inc.",
            settlement_date=dt.date(2026, 8, 14),
            current_shares=48144524,
            previous_shares=46307686,
            change_percent=3.97,
            days_to_cover=11.46,
            avg_daily_volume=4200138,
        )
        with patch("backend.server.fetch_latest", return_value=record):
            response = client.get("/api/short-interest/AI")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["symbol"], "AI")
        self.assertEqual(body["settlement_date"], "2026-08-14")
        self.assertEqual(body["change_shares"], 1836838)
        self.assertIn("2026-08-14", body["citation"])

    def test_upstream_failure_becomes_502(self):
        with patch("backend.server.fetch_latest", side_effect=ShortInterestError("没有记录")):
            response = client.get("/api/short-interest/ZZZZ")
        self.assertEqual(response.status_code, 502)



class SearchRouteTest(unittest.TestCase):
    """``/api/search`` 供自选股面板做自动补全。网络照例 patch 掉。"""

    def setUp(self):
        self.client = TestClient(app)

    def test_empty_query_returns_empty_list(self):
        """用户还在打字时的空查询是正常状态，不是错误——
        返回 4xx 会让前端把中间状态显示成失败。"""
        response = self.client.get("/api/search", params={"q": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_overlong_query_rejected(self):
        response = self.client.get("/api/search", params={"q": "x" * 200})
        self.assertEqual(response.status_code, 400)

    def test_returns_matches(self):
        from .search import Match

        with patch("backend.server.search", return_value=[Match("AAPL", "Apple Inc.", "NasdaqGS")]):
            response = self.client.get("/api/search", params={"q": "apple"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["symbol"], "AAPL")

    def test_upstream_failure_is_502(self):
        """上游真的挂了要如实报错，前端才知道该退回老行为，
        而不是把「搜索坏了」显示成「没有匹配结果」。"""
        from .search import SearchError

        with patch("backend.server.search", side_effect=SearchError("boom")):
            response = self.client.get("/api/search", params={"q": "apple"})
        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()

class TestLiveData(unittest.TestCase):
    """页面上的数字是现场取的，新闻仍是每天一次的批处理产物。

    这组测试全部把上游挡掉：测试不该依赖外网，也不该因为 Yahoo 或
    Nasdaq 限流而变红。
    """

    MARKET = {
        "asof": "14:32 ET",
        "session": "intraday",
        "source": "Nasdaq screener",
        "sectors": [
            {
                "name": "科技",
                "change_pct": 1.23,
                "market_cap": 1e12,
                "tiles": [
                    {"ticker": "LIVE", "name": "Live Inc.",
                     "change_pct": 2.5, "market_cap": 1e12}
                ],
            }
        ],
    }

    MAG7 = {
        "asof": "盘中 · 9/18 14:32 ET",
        "rows": [{"ticker": "NVDA", "price": "999.99", "change_pct": 3.21}],
        "source": "Yahoo Finance chart endpoint",
    }

    def test_historic_date_never_gets_live_numbers(self):
        """翻看旧简报时必须是那天的数字。

        给一份旧简报配今天的行情，读者会把两者当成同一天的事实——
        整个项目反复在防的就是这类错配。
        """
        with patch("backend.server.live.live_mag7") as mag7, \
             patch("backend.server.live.live_market") as market:
            response = client.get(f"/?date={REAL_DATE}")
        self.assertEqual(response.status_code, 200)
        mag7.assert_not_called()
        market.assert_not_called()

    def test_latest_page_uses_live_numbers(self):
        with patch("backend.server.live.live_mag7", return_value=self.MAG7), \
             patch("backend.server.live.live_market", return_value=self.MARKET):
            html = client.get("/").text
        self.assertIn("LIVE", html)
        self.assertIn("999.99", html)

    def test_intraday_page_says_intraday_not_close(self):
        """盘中数据绝不能标成「截至某日收盘」。"""
        with patch("backend.server.live.live_mag7", return_value=None), \
             patch("backend.server.live.live_market", return_value=self.MARKET):
            html = client.get("/").text
        self.assertIn("盘中 · 14:32 ET", html)

    def test_falls_back_to_the_archive_when_upstream_is_down(self):
        with patch("backend.server.live.live_mag7", return_value=None), \
             patch("backend.server.live.live_market", return_value=None):
            response = client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_malformed_live_data_falls_back_instead_of_500(self):
        """上游格式变了也不能让整页崩掉。"""
        with patch("backend.server.live.live_mag7", return_value={"rows": []}), \
             patch("backend.server.live.live_market", return_value={"nope": 1}):
            response = client.get("/")
        self.assertEqual(response.status_code, 200)


class TestApiSectors(unittest.TestCase):
    def test_returns_the_live_block(self):
        with patch("backend.server.live.live_market",
                   return_value=TestLiveData.MARKET):
            response = client.get("/api/sectors")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session"], "intraday")

    def test_upstream_failure_is_502(self):
        with patch("backend.server.live.live_market", return_value=None):
            response = client.get("/api/sectors")
        self.assertEqual(response.status_code, 502)


class TestCache(unittest.TestCase):
    """缓存存在的理由是别把上游打爆，所以它必须真的挡住重复调用。"""

    def test_second_call_within_ttl_does_not_hit_upstream(self):
        from backend.live import _Cached
        calls = []

        def produce():
            calls.append(1)
            return {"v": len(calls)}

        cache = _Cached(ttl=60.0)
        self.assertEqual(cache.get(produce), {"v": 1})
        self.assertEqual(cache.get(produce), {"v": 1})
        self.assertEqual(len(calls), 1)

    def test_expired_entry_is_refetched(self):
        from backend.live import _Cached
        calls = []

        def produce():
            calls.append(1)
            return len(calls)

        cache = _Cached(ttl=0.0)
        cache.get(produce)
        cache.get(produce)
        self.assertEqual(len(calls), 2)

    def test_failure_is_cached_too(self):
        """上游挂掉时不记时间戳的话，每个请求都会重试一次，
        页面从「慢一点」变成「每次都卡满超时」。"""
        from backend.live import _Cached
        from taurient_lite.sectors import SectorError
        calls = []

        def boom():
            calls.append(1)
            raise SectorError("上游挂了")

        cache = _Cached(ttl=60.0)
        self.assertIsNone(cache.get(boom))
        self.assertIsNone(cache.get(boom))
        self.assertEqual(len(calls), 1)


class TestQuoteAsof(unittest.TestCase):
    def test_intraday_timestamp_is_not_called_a_close(self):
        from backend.live import quote_asof
        from taurient_lite.sectors import EASTERN
        moment = dt.datetime(2026, 9, 18, 14, 32, tzinfo=EASTERN)
        label = quote_asof(int(moment.timestamp()))
        self.assertIn("盘中", label)
        self.assertNotIn("收盘", label)

    def test_after_hours_timestamp_keeps_the_close_wording(self):
        from backend.live import quote_asof
        from taurient_lite.sectors import EASTERN
        moment = dt.datetime(2026, 9, 18, 18, 5, tzinfo=EASTERN)
        self.assertIn("收盘", quote_asof(int(moment.timestamp())))


class TestApiHistory(unittest.TestCase):
    BARS = [
        Bar("2026-09-17", 10.0, 11.0, 9.0, 10.5, 1000),
        Bar("2026-09-18", 10.5, 12.0, 10.0, 11.5, 2000),
    ]

    def test_returns_chart_ready_shapes(self):
        with patch("backend.server.fetch_history", return_value=self.BARS):
            body = client.get("/api/history/AAPL").json()
        self.assertEqual(body["ticker"], "AAPL")
        self.assertEqual(body["candles"][0],
                         {"time": "2026-09-17", "open": 10.0, "high": 11.0,
                          "low": 9.0, "close": 10.5})
        self.assertEqual(body["stats"]["bars"], 2)

    def test_volume_colours_come_from_the_server(self):
        """「这根是涨是跌」的判据只应该有一处，前端再判一次迟早会不一致。"""
        with patch("backend.server.fetch_history", return_value=self.BARS):
            body = client.get("/api/history/AAPL").json()
        self.assertTrue(all("color" in v for v in body["volumes"]))

    def test_unknown_range_is_400(self):
        response = client.get("/api/history/AAPL?range=99y")
        self.assertEqual(response.status_code, 400)

    def test_bad_ticker_is_400(self):
        self.assertEqual(client.get("/api/history/123$%").status_code, 400)

    def test_upstream_failure_is_502(self):
        with patch("backend.server.fetch_history",
                   side_effect=HistoryError("上游挂了")):
            self.assertEqual(client.get("/api/history/AAPL").status_code, 502)


class TestStockPage(unittest.TestCase):
    def test_renders_a_chart_container_and_the_library(self):
        with patch("backend.server.fetch_history",
                   return_value=TestApiHistory.BARS), \
             patch("backend.server.resolve", return_value=None), \
             patch("backend.server.live.live_company", return_value=None), \
             patch("backend.server.mentions_for", return_value=()):
            html = client.get("/stock/AAPL").text
        self.assertIn('id="chart"', html)
        self.assertIn("lightweight-charts", html)
        self.assertIn("AAPL", html)

    def test_data_is_inlined_so_the_chart_does_not_wait_for_a_round_trip(self):
        with patch("backend.server.fetch_history",
                   return_value=TestApiHistory.BARS), \
             patch("backend.server.resolve", return_value=None), \
             patch("backend.server.live.live_company", return_value=None), \
             patch("backend.server.mentions_for", return_value=()):
            html = client.get("/stock/AAPL").text
        self.assertIn('"time": "2026-09-18"', html)

    def test_selected_range_is_marked(self):
        with patch("backend.server.fetch_history",
                   return_value=TestApiHistory.BARS), \
             patch("backend.server.resolve", return_value=None), \
             patch("backend.server.live.live_company", return_value=None), \
             patch("backend.server.mentions_for", return_value=()):
            html = client.get("/stock/AAPL?range=1y").text
        self.assertIn('class="range-btn on" href="?range=1y"', html)

    def test_name_lookup_failure_does_not_break_the_page(self):
        """公司名是锦上添花，查不到就只显示代码。"""
        from backend.search import SearchError as SE
        with patch("backend.server.fetch_history",
                   return_value=TestApiHistory.BARS), \
             patch("backend.server.resolve", side_effect=SE("搜索挂了")), \
             patch("backend.server.live.live_company", return_value=None), \
             patch("backend.server.mentions_for", return_value=()):
            response = client.get("/stock/AAPL")
        self.assertEqual(response.status_code, 200)

    def test_upstream_failure_is_502_not_a_blank_chart(self):
        with patch("backend.server.fetch_history",
                   side_effect=HistoryError("上游挂了")):
            self.assertEqual(client.get("/stock/AAPL").status_code, 502)

    def test_escapes_hostile_ticker(self):
        """代码来自 URL，属于不可信输入。"""
        self.assertEqual(client.get("/stock/<script>").status_code, 400)


class TestPriceLines(unittest.TestCase):
    """横线的标记与存储键。

    交互本身（点按钮 → 点图表 → 落线 → 刷新还在 → 删除）用 CDP 驱动真实
    浏览器验证过，那部分不适合放进单元测试；这里守住的是服务端这一侧：
    标记在、存储键按代码隔离、脚本语法有效。
    """

    def _html(self, symbol="AAPL"):
        # 公司资料要打 Nasdaq，测试一律挡掉：测试不该依赖外网，
        # 也不该因为对方限流而变慢或变红。
        with patch("backend.server.fetch_history",
                   return_value=TestApiHistory.BARS), \
             patch("backend.server.resolve", return_value=None), \
             patch("backend.server.live.live_company", return_value=None), \
             patch("backend.server.mentions_for", return_value=()):
            return client.get(f"/stock/{symbol}").text

    def test_toolbar_and_list_are_present(self):
        html = self._html()
        for hook in ('id="add-line"', 'id="clear-lines"', 'id="line-list"',
                     'id="line-hint"'):
            self.assertIn(hook, html, hook)

    def test_uses_the_library_price_line_api(self):
        html = self._html()
        self.assertIn("createPriceLine", html)
        self.assertIn("removePriceLine", html)

    def test_storage_key_is_scoped_per_ticker(self):
        """两只票的线不能互相串。"""
        self.assertIn("tl:lines:AAPL", self._html("AAPL"))
        self.assertIn("tl:lines:MSFT", self._html("MSFT"))

    def test_click_only_adds_while_arming(self):
        """平时点图表是十字光标的正常行为，随手一点就落线会让人不敢碰图。"""
        self.assertIn("if (!arming || !param.point)", self._html())

    def test_storage_access_is_guarded(self):
        """隐私模式下 localStorage 会直接抛异常，不能让它带崩整张图。"""
        html = self._html()
        self.assertIn("try {", html)
        self.assertIn("localStorage", html)


class TestTrendLines(unittest.TestCase):
    """趋势线的服务端这一侧。

    交互（两点画线、点线选中、拖端点、缩放后跟随、刷新后仍在）用 CDP 驱动
    真实 Chrome 逐项断言过——那部分不适合放进单元测试。这里守住的是三个
    容易被后来的改动悄悄破坏的约定。
    """

    def _html(self, symbol="TSM"):
        # 公司资料要打 Nasdaq，测试一律挡掉：测试不该依赖外网，
        # 也不该因为对方限流而变慢或变红。
        with patch("backend.server.fetch_history",
                   return_value=TestApiHistory.BARS), \
             patch("backend.server.resolve", return_value=None), \
             patch("backend.server.live.live_company", return_value=None), \
             patch("backend.server.mentions_for", return_value=()):
            return client.get(f"/stock/{symbol}").text

    def test_anchors_use_logical_index_not_time(self):
        """趋势线要能延伸到最后一根 K 线右侧的空白区去预判。

        按时间换算的坐标越过最后一根就返回 null，线会在图表边缘断掉；
        逻辑序号没有这个限制。这是整个实现最关键的一个选择。
        """
        html = self._html()
        self.assertIn("logicalToCoordinate", html)
        self.assertIn("coordinateToLogical", html)

    def test_overlay_does_not_swallow_chart_events_by_default(self):
        """覆盖层默认必须让事件穿透，否则图表拖不动也缩放不了。"""
        html = self._html()
        self.assertIn("pointer-events: none", html)
        self.assertIn("#draw.drawing { pointer-events: auto;", html)

    def test_overlay_sits_above_the_canvas(self):
        """图表库内部元素带 z-index，光靠 DOM 顺序赢不了——不加 z-index
        覆盖层会沉到画布底下，点击全被吃掉，而处理器看着完全正常。"""
        self.assertIn("z-index: 5", self._html())

    def test_drag_listens_on_window(self):
        """svg 平时 pointer-events: none，拖拽途中指针移出线外就收不到事件，
        手柄会在半路脱手。"""
        self.assertIn("window.addEventListener('pointermove'", self._html())

    def test_storage_key_is_scoped_per_ticker(self):
        self.assertIn("tl:trends:TSM", self._html("TSM"))
        self.assertIn("tl:trends:NVDA", self._html("NVDA"))


class TestStockPageBlocks(unittest.TestCase):
    """个股页上的公司资料各块。

    **主体是 K 线，资料是补充。** 这组测试守的就是这条：资料取不到、
    某一块缺数据、简报里查不到这只票，页面都要照常出。
    """

    def _get(self, company=None, mentions=(), symbol="NVDA"):
        with patch("backend.server.fetch_history",
                   return_value=TestApiHistory.BARS), \
             patch("backend.server.resolve", return_value=None), \
             patch("backend.server.live.live_company", return_value=company), \
             patch("backend.server.mentions_for", return_value=mentions):
            return client.get(f"/stock/{symbol}")

    def test_page_renders_without_any_company_data(self):
        """资料拿不到不该让 K 线一起陪葬。"""
        response = self._get(company=None, mentions=())
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="chart"', response.text)
        for absent in ("简介", "关键统计", "分析师评级"):
            self.assertNotIn(f"<h2>{absent}</h2>", response.text)

    def test_blocks_appear_when_data_is_there(self):
        from backend.company import Company, Profile, Quarter, Ratings
        company = Company(
            symbol="NVDA",
            profile=Profile(name="NVIDIA", description="做 GPU 的",
                            sector="Technology"),
            stats=(("市值", "5.36 万亿"),),
            ratings=Ratings(mean="Buy", count=39, brokers=("A",) * 39),
            quarters=(Quarter("Jul 2026", "8/26/2026", 2.22, 2.09, 6.22),),
        )
        html = self._get(company=company).text
        self.assertIn("<h2>简介</h2>", html)
        self.assertIn("做 GPU 的", html)
        self.assertIn("5.36 万亿", html)
        self.assertIn("Buy", html)
        self.assertIn("Jul 2026", html)

    def test_a_missing_block_is_omitted_not_stubbed(self):
        """缺数据就不出标题——写着「暂无」的空标题信息量是零。"""
        from backend.company import Company, Profile
        company = Company(symbol="NVDA", profile=Profile(description="只有简介"))
        html = self._get(company=company).text
        self.assertIn("<h2>简介</h2>", html)
        self.assertNotIn("<h2>关键统计</h2>", html)
        self.assertNotIn("<h2>财报</h2>", html)

    def test_ratings_page_admits_what_it_cannot_show(self):
        """数据源给不了买/持有/卖出分布，页面必须说出来而不是编一个。"""
        from backend.company import Company, Ratings
        html = self._get(company=Company(symbol="NVDA",
                                         ratings=Ratings(mean="Buy", count=3))).text
        self.assertIn("不含买/持有/卖出的具体分布", html)

    def test_mentions_render_with_tier_and_date(self):
        from backend.stock_news import Mention
        html = self._get(mentions=(
            Mention("2026-09-18", 1, "must-read", "标题在这", "为什么重要", ("NVDA",)),
        )).text
        self.assertIn("<h2>相关新闻</h2>", html)
        self.assertIn("标题在这", html)
        self.assertIn("必读", html)
        self.assertIn("2026-09-18", html)

    def test_no_mentions_means_no_news_block(self):
        """冷门票查不到就整块不显示，不放「暂无新闻」的占位。"""
        self.assertNotIn("<h2>相关新闻</h2>", self._get(mentions=()).text)

    def test_hostile_company_text_is_escaped(self):
        from backend.company import Company, Profile
        evil = Company(symbol="X",
                       profile=Profile(description='<img src=x onerror=alert(1)>'))
        html = self._get(company=evil).text
        self.assertNotIn("<img src=x", html)
