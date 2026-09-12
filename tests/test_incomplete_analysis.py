import json
import unittest
from itertools import product
from unittest.mock import patch

import pandas as pd

from analysis_fixture import AnalysisFixture
import pme
import webapp
import benchmark


class IncompleteAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.fixture = self.enterContext(AnalysisFixture())

    def test_one_missing_quote_does_not_discard_other_positions(self):
        def history(symbol, **kwargs):
            if symbol == "NVDA":
                return pd.Series(dtype=float)
            return self.fixture.histories.get(symbol, pd.Series(dtype=float)).copy()

        with patch.object(pme, "get_history", side_effect=history):
            total = pme.build_asset_value_growth(self.fixture.orders, include_div=False)
            healthy = pme.build_asset_value_growth(self.fixture.orders, ticker="360750", include_div=False)

        self.assertFalse(total.empty)
        pd.testing.assert_series_equal(total["내 자산가치"], healthy["내 자산가치"])
        pd.testing.assert_series_equal(total["누적매수금액"], healthy["누적매수금액"])
        self.assertTrue(total.attrs["warnings"])
        self.assertEqual(total.attrs["excluded_symbols"], ["NVDA"])

    def test_unmatched_sale_does_not_discard_other_positions(self):
        first = self.fixture.orders[0]
        first["side"] = "SELL"
        total = pme.build_asset_value_growth(self.fixture.orders, include_div=False)
        healthy = pme.build_asset_value_growth(self.fixture.orders, ticker="360750", include_div=False)
        self.assertFalse(total.empty)
        pd.testing.assert_series_equal(total["내 자산가치"], healthy["내 자산가치"])
        pd.testing.assert_series_equal(total["누적매도금액"], healthy["누적매도금액"])
        self.assertEqual(total.attrs["excluded_symbols"], ["NVDA"])

    def test_all_options_preserve_healthy_values_and_explain_missing_values(self):
        self.fixture.histories["NVDA"] = pd.Series(dtype=float)
        for dividend, fx, period, ticker in product(
            (0, 1), (0, 1), ("1M", "3M", "6M", "1Y", "5Y", "ALL"), ("", "NVDA", "360750")
        ):
            with self.subTest(dividend=dividend, fx=fx, period=period, ticker=ticker):
                options = dict(div=dividend, fx=fx, period=period, ticker=ticker)
                dashboard = json.loads(webapp.api_app_dashboard(None, **options).body)
                benchmark = json.loads(webapp.api_app_benchmark(None, **options).body)
                expected = "unavailable" if ticker == "NVDA" else "complete" if ticker else "partial"
                self.assertEqual(dashboard["analysis"]["status"], expected)
                self.assertEqual(benchmark["analysis"]["status"], expected)
                if ticker == "NVDA":
                    for key in ("totalPnL", "returnPct", "xirr", "projectionRate"):
                        self.assertIsNone(dashboard["metrics"][key])
                    self.assertEqual(dashboard["growth"], [])
                    self.assertTrue(dashboard["analysis"]["warnings"])
                    self.assertIsNone(dashboard["stocks"][0]["returnPct"])
                    self.assertIsNone(dashboard["stocks"][0]["unrealizedPnL"])
                else:
                    self.assertIsNotNone(dashboard["metrics"]["xirr"])
                    self.assertTrue(dashboard["growth"])
                    self.assertAlmostEqual(dashboard["metrics"]["returnPct"], benchmark["summary"]["portfolioReturn"], places=1)
                    self.assertEqual(dashboard["analysis"]["includedSymbols"], ["360750"])
                    if not ticker:
                        self.assertEqual(dashboard["analysis"]["excludedSymbols"], ["NVDA"])
                        self.assertIsNone(dashboard["metrics"]["projectionRate"])

    def test_empty_period_is_not_displayed_as_zero_profit(self):
        self.fixture.data["perf"] = {"all_inclusive_krw": 1234, "all_inclusive_pct": 12.34}
        for order in self.fixture.orders:
            date = pd.Timestamp(order["execution"]["filledAt"]) - pd.DateOffset(years=2)
            order["execution"]["filledAt"] = str(date)
        for history in self.fixture.histories.values():
            history.index = history.index - pd.DateOffset(years=2)
        response = json.loads(webapp.api_app_dashboard(None, ticker="NVDA", period="1M").body)
        self.assertEqual(response["analysis"]["status"], "no_period_data")
        self.assertIsNone(response["metrics"]["totalPnL"])
        self.assertIsNone(response["metrics"]["xirr"])
        self.assertIsNone(response["stocks"][0]["returnPct"])

    def test_closed_position_before_period_has_no_period_metrics(self):
        bought = self.fixture.orders[0]
        sold = dict(bought, side="SELL", execution={
            "filledAt": str(self.fixture.index[60]), "filledQuantity": 10,
            "averageFilledPrice": float(self.fixture.stock.iloc[60])})
        self.fixture.orders[:] = [bought, sold]
        self.fixture.dividends.clear()
        dashboard = json.loads(webapp.api_app_dashboard(None, ticker="NVDA", period="1M", div=0).body)
        benchmark = json.loads(webapp.api_app_benchmark(None, ticker="NVDA", period="1M", div=0).body)
        self.assertEqual(dashboard["analysis"]["status"], "no_period_data")
        self.assertEqual(benchmark["analysis"]["status"], "no_period_data")
        self.assertIsNone(dashboard["metrics"]["totalPnL"])
        self.assertIsNone(dashboard["stocks"][0]["returnPct"])
        self.assertEqual(dashboard["growth"], [])
        self.assertEqual(benchmark["growth"], [])


class KoreanMarketRoutingTests(unittest.TestCase):
    def test_market_metadata_routes_kosdaq_and_keeps_kospi(self):
        with patch.object(benchmark, "_krx_market_map", return_value={"047080": "KOSDAQ", "005930": "KOSPI"}):
            self.assertEqual(benchmark.to_yf_ticker("A047080", "KR"), "047080.KQ")
            self.assertEqual(benchmark.to_yf_ticker("005930", "KR"), "005930.KS")
            self.assertEqual(benchmark.to_yf_ticker("NVDA", "US"), "NVDA")
            self.assertEqual(benchmark.to_yf_ticker("047080", "KR", "KOSPI"), "047080.KS")
            self.assertEqual(benchmark.to_yf_ticker("047080.KQ", "KR"), "047080.KQ")

    def test_correct_market_recovers_entire_history(self):
        with AnalysisFixture() as fixture:
            dates = fixture.index
            order = {"symbol": "047080", "currency": "KRW", "side": "BUY",
                     "execution": {"filledAt": str(dates[0]), "filledQuantity": 10,
                                   "averageFilledPrice": 100}}
            fixture.orders.append(order)
            fixture.histories["047080.KS"] = pd.Series(100.0, index=dates[-40:])
            fixture.histories["047080.KQ"] = pd.Series(100.0, index=dates)
            with patch.object(benchmark, "_krx_market_map", return_value={"047080": "KOSDAQ"}):
                frame = pme.build_asset_value_growth(fixture.orders, include_div=False)
            self.assertFalse(frame.empty)
            self.assertEqual(frame.attrs["excluded_symbols"], [])
            self.assertIn("047080", frame.attrs["included_symbols"])


if __name__ == "__main__":
    unittest.main()