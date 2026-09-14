import json
import unittest
from itertools import product
from unittest.mock import patch

import pandas as pd

from analysis_fixture import AnalysisFixture
import pme
import pipeline
import pm
import webapp
from analytics_engine import transform_to_mvp_json


class ApiOptionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = self.enterContext(AnalysisFixture())

    def test_all_48_option_combinations_agree_across_views(self):
        for dividend, fx, period, ticker in product((0, 1), (0, 1), ("1M", "3M", "6M", "1Y", "5Y", "ALL"), ("", "NVDA")):
            with self.subTest(dividend=dividend, fx=fx, period=period, ticker=ticker):
                options = dict(div=dividend, fx=fx, period=period, ticker=ticker)
                benchmark = json.loads(webapp.api_app_benchmark(None, **options).body)
                dashboard = json.loads(webapp.api_app_dashboard(None, **options).body)
                last = benchmark["growth"][-1]
                self.assertEqual(benchmark["summary"]["portfolioReturn"], last["portfolioPct"])
                self.assertEqual(benchmark["summary"]["sp500Return"], last["sp500Pct"])
                self.assertEqual(benchmark["summary"]["alpha"], last["alpha"])
                metrics = dashboard["metrics"]
                self.assertAlmostEqual(metrics["returnPct"], last["portfolioPct"], places=1)
                self.assertAlmostEqual(metrics["totalPnL"], metrics["pureStockPnL"] + metrics["fxPnL"] + metrics["dividendPnL"])
                self.assertAlmostEqual(metrics["totalPnL"], metrics["realizedPnL"] + metrics["unrealizedPnL"] + metrics["dividendPnL"])
                self.assertAlmostEqual(dashboard["growth"][-1]["portfolio"] - 100, benchmark["summary"]["twrReturn"], places=2)
                self.assertTrue(set(row["month"] for row in benchmark["monthlyAlpha"]).issubset({row["month"] for row in benchmark["growth"]}))
                if not dividend:
                    self.assertEqual(metrics["dividendPnL"], 0)
                if not fx:
                    self.assertAlmostEqual(metrics["fxPnL"], 0)
                if ticker:
                    self.assertEqual([row["ticker"] for row in benchmark["perStock"]], [ticker])
                    self.assertEqual(benchmark["perStock"][0]["returnPct"], last["portfolioPct"])
                    self.assertEqual([row["ticker"] for row in dashboard["stocks"]], [ticker])
                self.assertIsNotNone(benchmark["simulation"])

    def test_period_excludes_earlier_gain_from_twr_and_regression(self):
        frame = pme.build_asset_value_growth(self.fixture.orders, ticker="NVDA", include_div=False, include_fx=False)
        cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(months=1)
        view = webapp._benchmark_view(frame, "1M")
        daily = pme.daily_returns_from_growth(frame).loc[cutoff:, "내 수익률(%)"]
        expected = ((1 + daily).prod() - 1) * 100
        self.assertAlmostEqual(view["summary"]["twrReturn"], expected, places=2)
        self.assertNotEqual(view["summary"]["twrReturn"], webapp._benchmark_view(frame, "ALL")["summary"]["twrReturn"])

    def test_account_realized_profit_matches_scope_fx_and_period(self):
        self.fixture.histories["NVDA"].loc[:] = 100.0
        self.fixture.fx.loc[:] = 1000.0
        self.fixture.fx.iloc[1:] = 1200.0
        self.fixture.fx.iloc[150:] = 1300.0
        self.fixture.data["fx_rate"] = 1300.0
        self.fixture.dividends.clear()
        self.fixture.orders[:] = [
            {"symbol": "NVDA", "currency": "USD", "broker": "test", "account": account, "side": side,
             "execution": {"filledQuantity": quantity, "averageFilledPrice": price,
                           "filledAmount": quantity * price, "filledAt": str(self.fixture.index[offset])}}
            for offset, account, side, quantity, price in
            ((0, "001", "BUY", 10, 100), (1, "002", "BUY", 10, 200), (150, "002", "SELL", 5, 300))
        ]
        sale_date = self.fixture.index[150]
        periods = (("ALL", 0), ("1M", 0), ("YOY", sale_date.year), ("YOY", self.fixture.index[-1].year))
        for dividend, fx, ticker, (period, year) in product((0, 1), (0, 1), ("", "NVDA"), periods):
            with self.subTest(dividend=dividend, fx=fx, ticker=ticker, period=period, year=year):
                start, end = webapp._period_bounds(period, year)
                contains_sale = (start is None or start <= sale_date) and (end is None or sale_date <= end)
                expected = (750000.0 if fx else 600000.0) if contains_sale else 0.0
                payload = json.loads(webapp.api_app_dashboard(None, div=dividend, fx=fx, ticker=ticker,
                                                               period=period, year=year).body)
                self.assertEqual(payload["analysis"]["status"], "complete")
                self.assertAlmostEqual(payload["metrics"]["realizedPnL"], expected)
                stock = next(row for row in payload["stocks"] if row["ticker"] == "NVDA")
                self.assertAlmostEqual(stock["realizedPnL"], expected)
                self.assertAlmostEqual(stock["buyTotal"], 2200000.0)

    def test_wrong_account_sale_is_unavailable_not_funded_by_other_account(self):
        for order in self.fixture.orders:
            order["broker"] = "test"
            order["account"] = "001" if order["side"] == "BUY" else "002"
        payload = json.loads(webapp.api_app_dashboard(None, ticker="NVDA", period="ALL").body)
        self.assertEqual(payload["analysis"]["status"], "unavailable")
        self.assertIsNone(payload["metrics"]["realizedPnL"])
        self.assertIsNone(payload["stocks"][0]["realizedPnL"])
        self.assertTrue(payload["analysis"]["warnings"])

    def test_identical_assets_have_unit_beta_zero_alpha(self):
        self.fixture.histories["NVDA"] = self.fixture.spy
        self.fixture.orders[0]["execution"]["averageFilledPrice"] = float(self.fixture.spy.iloc[0])
        frame = pme.build_asset_value_growth(self.fixture.orders[:1], include_div=False, include_fx=False)
        stats = pme.comparison_statistics(frame)
        self.assertAlmostEqual(stats["beta"], 1.0)
        self.assertAlmostEqual(stats["regression_alpha"], 0.0)

    def test_missing_period_has_no_fallback_metrics(self):
        frame = pme.build_asset_value_growth(self.fixture.orders, ticker="NVDA")
        frame.index -= pd.DateOffset(years=10)
        result = webapp._benchmark_view(frame, "1M")
        self.assertEqual(result["growth"], [])
        self.assertTrue(all(value is None for value in result["summary"].values()))

    def test_year_end_excludes_later_transactions_and_valuation(self):
        year_end = pd.Timestamp(year=self.fixture.index[0].year, month=12, day=31)
        expected = pme.build_asset_value_growth(self.fixture.orders, ticker="NVDA", include_div=False)
        future_sale = {"symbol": "NVDA", "currency": "USD", "side": "SELL",
                       "execution": {"filledAt": str(year_end + pd.Timedelta(days=1)),
                                     "filledQuantity": 1000, "averageFilledPrice": 100}}
        frame = pme.build_asset_value_growth(self.fixture.orders + [future_sale], ticker="NVDA",
                                             include_div=False, end=year_end)
        self.assertFalse(frame.empty)
        self.assertEqual(frame.index[-1], year_end)
        pd.testing.assert_frame_equal(frame, expected.loc[:year_end])

    def test_calendar_year_options_use_identical_boundaries_across_views(self):
        for dividend, fx, ticker, year in product((0, 1), (0, 1), ("", "NVDA", "360750"),
                                                  (self.fixture.index[0].year, self.fixture.index[-1].year)):
            with self.subTest(dividend=dividend, fx=fx, ticker=ticker, year=year):
                options = dict(div=dividend, fx=fx, ticker=ticker, period="YOY", year=year)
                dashboard = json.loads(webapp.api_app_dashboard(None, **options).body)
                benchmark = json.loads(webapp.api_app_benchmark(None, **options).body)
                full = pme.build_asset_value_growth(self.fixture.orders, div_events=self.fixture.dividends,
                                                     ticker=ticker or None, include_div=bool(dividend), include_fx=bool(fx))
                truncated = full.loc[:pd.Timestamp(year, 12, 31)]
                stats = pme.comparison_statistics(truncated, pd.Timestamp(year, 1, 1))
                expected = stats["returns"]["portfolio"].iloc[-1]
                self.assertAlmostEqual(dashboard["metrics"]["returnPct"], expected)
                self.assertAlmostEqual(dashboard["metrics"]["xirr"], pme.xirr_from_growth(truncated, pd.Timestamp(year, 1, 1)))
                self.assertAlmostEqual(dashboard["metrics"]["projectionRate"], pme.xirr_from_growth(full))
                self.assertEqual(benchmark["summary"]["portfolioReturn"], round(expected, 2))
                self.assertIsNone(dashboard["changes"])
                for chart in (dashboard["growth"], benchmark["growth"], benchmark["monthlyAlpha"], benchmark["rollingBeta"]):
                    self.assertTrue(all(row["month"].startswith(f"{year % 100:02d}/") for row in chart))
                self.assertEqual(dashboard["analysis"]["asOf"], truncated.index[-1].strftime("%Y-%m-%d"))
                self.assertIn(year, dashboard["years"])
                self.assertEqual(dashboard["years"], benchmark["years"])
                if ticker:
                    self.assertEqual(benchmark["perStock"][0]["returnPct"], round(expected, 2))

    def test_calendar_year_before_first_investment_is_unavailable(self):
        year = self.fixture.index[0].year - 1
        for endpoint in (webapp.api_app_dashboard, webapp.api_app_benchmark):
            result = json.loads(endpoint(None, ticker="NVDA", period="YOY", year=year).body)
            self.assertEqual(result["growth"], [])
            if "metrics" in result:
                self.assertIsNone(result["metrics"]["xirr"])
                self.assertIsNone(result["metrics"]["returnPct"])
            else:
                self.assertIsNone(result["summary"]["portfolioReturn"])

    def test_year_bounds_reject_future_years_and_preserve_leap_day(self):
        start, end = webapp._period_bounds("YOY", 2024, today="2024-02-29")
        self.assertEqual(start, pd.Timestamp("2024-01-01"))
        self.assertEqual(end, pd.Timestamp("2024-02-29"))
        with self.assertRaises(webapp.HTTPException) as error:
            webapp._period_bounds("YOY", 2027, today="2026-09-13")
        self.assertEqual(error.exception.status_code, 422)


class AccountBalanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = self.enterContext(AnalysisFixture())
        self.fixture.data["fx_rate"] = 1300.0
        self.fixture.data["summary"].update(cash_krw_native=1000000, cash_usd_native=500.15)
        self.fixture.data["holdings"] = [
            {"ticker": "005930", "currency": "KRW", "quantity": 10, "eval_native": 3000000, "eval_krw": 3000000},
            {"ticker": "360750", "currency": "KRW", "quantity": 20, "eval_native": 500000, "eval_krw": 500000},
            {"ticker": "NVDA", "currency": "USD", "quantity": 10, "eval_native": 2000.25, "eval_krw": 2600325},
            {"ticker": "AAPL", "currency": "USD", "quantity": 5, "eval_krw": 1300000},
        ]

    def balances(self, **options):
        response = webapp.api_app_dashboard(None, **options)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.body)["accountBalances"]

    def test_cash_and_investments_are_separate_in_original_currency(self):
        balances = self.balances()
        self.assertEqual(balances["cash"], {"krw": 1000000, "usd": 500.15, "totalKrw": 1650195})
        self.assertEqual(balances["invested"], {"krw": 3500000, "usd": 3000.25, "totalKrw": 7400325})
        self.assertEqual(balances["total"], {"krw": 4500000, "usd": 3500.4, "totalKrw": 9050520})
        self.assertEqual(balances["fxRate"], 1300)

    def test_account_balances_do_not_change_with_performance_filters(self):
        expected = self.balances()
        for dividend, fx, period, ticker in product((0, 1), (0, 1), ("ALL", "1M", "YOY"), ("", "NVDA")):
            with self.subTest(dividend=dividend, fx=fx, period=period, ticker=ticker):
                self.assertEqual(self.balances(div=dividend, fx=fx, period=period, ticker=ticker,
                                               year=self.fixture.index[0].year), expected)

    def test_missing_cash_is_distinct_from_zero_balance(self):
        self.fixture.data["summary"].pop("cash_usd_native")
        balances = self.balances()
        self.assertIsNone(balances["cash"]["usd"])
        self.assertIsNone(balances["cash"]["totalKrw"])
        self.assertIsNone(balances["total"]["totalKrw"])
        self.assertEqual(balances["invested"]["usd"], 3000.25)
        self.fixture.data["summary"]["cash_usd_native"] = 0
        self.assertEqual(self.balances()["cash"]["usd"], 0)

    def test_unlinked_account_does_not_report_known_zero_cash(self):
        self.fixture.data["summary"] = pipeline.empty_portfolio("test")["asset_summary"]
        balances = self.balances()
        self.assertIsNone(balances["cash"]["krw"])
        self.assertIsNone(balances["cash"]["usd"])
        self.assertEqual(balances["invested"]["krw"], 3500000)


class AccountBalanceSourceTests(unittest.TestCase):
    def test_native_dollar_valuation_survives_account_merging(self):
        fx_rate = 1333.37
        source = {"result": {"marketValue": {"amount": {"krw": 0, "usd": 123.45}},
                              "items": [{"symbol": "NVDA", "currency": "USD", "quantity": 1,
                                         "marketValue": {"amount": 123.45}}]}}
        portfolio = transform_to_mvp_json("test", source, fx_rate=fx_rate)
        portfolio["asset_summary"]["fx_rate"] = fx_rate
        self.assertEqual(portfolio["holdings"][0]["eval_native"], 123.45)
        manual = pd.DataFrame([{"티커": "NVDA", "통화": "USD", "수량": 0.3, "현재가": 15.27,
                                "평균매수가": 10, "평가액(원)": round(0.3 * 15.27 * fx_rate)}])
        merged = pipeline.merge_manual_into_portfolio(portfolio, manual)
        self.assertAlmostEqual(merged["holdings"][0]["eval_native"], 123.45 + 0.3 * 15.27)

    def test_missing_native_value_is_not_misread_as_dollars(self):
        portfolio = {"asset_summary": {}, "holdings": [
            {"ticker": "NVDA", "currency": "USD", "quantity": 5, "eval_krw": 1300000}]}
        manual = pd.DataFrame([{"티커": "005930", "통화": "KRW", "수량": 1, "현재가": 100,
                                "평균매수가": 100, "평가액(원)": 100}])
        merged = pipeline.merge_manual_into_portfolio(portfolio, manual)
        balances = webapp._account_balances({"summary": merged["asset_summary"],
                                             "holdings": merged["holdings"], "fx_rate": 1300})
        self.assertEqual(balances["invested"]["usd"], 1000)
        self.assertEqual(balances["invested"]["krw"], 100)

    def test_buying_power_zero_and_missing_response_are_distinct(self):
        with patch.object(pm.requests, "get") as request:
            request.return_value.json.return_value = {"result": {"cashBuyingPower": 0}}
            self.assertEqual(pm.get_buying_power("test", default=None), 0)
            request.return_value.json.return_value = {"result": {}}
            self.assertIsNone(pm.get_buying_power("test", default=None))
            self.assertEqual(pm.get_buying_power("test"), 0)

    def test_failed_cash_currency_remains_unavailable_in_portfolio(self):
        source = {"result": {"items": []}}
        with patch.object(pipeline, "get_access_token", return_value="test"), \
                patch.object(pipeline, "get_holdings", return_value=source), \
                patch.object(pipeline, "get_buying_power", side_effect=[1000.0, None]), \
                patch.object(pipeline, "get_exchange_rate", return_value=1300.0):
            portfolio, error = pipeline.toss_portfolio({"TOSS_CLIENT_ID": "test", "TOSS_CLIENT_SECRET": "test"})
        self.assertIsNone(error)
        self.assertEqual(portfolio["asset_summary"]["cash_krw_native"], 1000)
        self.assertIsNone(portfolio["asset_summary"]["cash_usd_native"])


if __name__ == "__main__":
    unittest.main()