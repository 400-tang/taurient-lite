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
from taurient_lite.quotes import Quote, QuoteError
from taurient_lite.short_interest import ShortInterestError, ShortInterestRecord

client = TestClient(app)

#: 仓库里真实存在的一份简报，读路径的测试用它。
REAL_DATE = "2026-09-06"


class TestHealth(unittest.TestCase):
    def test_ok(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


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


if __name__ == "__main__":
    unittest.main()
