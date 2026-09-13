import json
import unittest
from itertools import product

import pandas as pd

from analysis_fixture import AnalysisFixture
import pme
import webapp


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


if __name__ == "__main__":
    unittest.main()