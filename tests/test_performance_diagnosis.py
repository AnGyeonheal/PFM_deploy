import json
import unittest
from itertools import product
from unittest.mock import patch

import numpy as np
import pandas as pd

import pme
import webapp
from analysis_fixture import AnalysisFixture


class PerformanceDiagnosisTests(unittest.TestCase):
    def frame(self, mine, market=None, purchases=None, sales=None, index=None):
        index = index if index is not None else pd.date_range("2025-01-01", periods=len(mine))
        return pd.DataFrame({
            "내 자산가치": mine,
            "S&P500 자산가치": mine if market is None else market,
            "누적매수금액": [100.0] * len(mine) if purchases is None else purchases,
            "누적매도금액": [0.0] * len(mine) if sales is None else sales,
            "S&P500 누적매도금액": [0.0] * len(mine) if sales is None else sales,
        }, index=index)

    def test_contributions_are_not_return_or_drawdown(self):
        frame = self.frame([100, 100, 500, 500, 100, 100],
                           purchases=[100, 100, 500, 500, 500, 500], sales=[0, 0, 0, 0, 400, 400])
        result = pme.performance_diagnosis(frame)
        self.assertAlmostEqual(result["portfolio"]["totalReturnPct"], 0)
        self.assertAlmostEqual(result["portfolio"]["maxDrawdownPct"], 0)
        self.assertIsNone(result["portfolio"]["annualizedReturnPct"])
        self.assertIsNone(result["relative"]["informationRatio"])

    def test_drawdown_includes_opening_baseline_and_recovers(self):
        frame = self.frame([80, 90, 120, 96, 120])
        result = pme.performance_diagnosis(frame)
        self.assertAlmostEqual(result["portfolio"]["totalReturnPct"], 20)
        self.assertAlmostEqual(result["portfolio"]["maxDrawdownPct"], -20)
        self.assertAlmostEqual(result["portfolio"]["currentDrawdownPct"], 0)
        self.assertAlmostEqual(result["series"][1]["portfolioDrawdown"], -20)

    def test_annualization_uses_elapsed_calendar_days(self):
        index = pd.date_range("2023-12-31", "2024-12-31")
        mine = 100 * 1.1 ** (np.arange(len(index)) / 365)
        frame = self.frame(mine, index=index)
        result = pme.performance_diagnosis(frame, start=pd.Timestamp("2024-01-01"))
        self.assertEqual(result["sample"]["calendarDays"], 366)
        self.assertAlmostEqual(result["portfolio"]["annualizedReturnPct"], 10, places=8)
        self.assertAlmostEqual(result["portfolio"]["maxDrawdownPct"], 0)
        self.assertAlmostEqual(result["relative"]["excessReturnPp"], 0)

    def test_information_ratio_uses_sample_tracking_error(self):
        index = pd.bdate_range("2025-01-01", periods=81)
        stock_returns = np.array([0.0] + [0.001 + 0.003 * np.sin(step) for step in range(80)])
        market_returns = np.array([0.0] + [0.0005 + 0.002 * np.cos(step) for step in range(80)])
        frame = self.frame(100 * np.cumprod(1 + stock_returns), 100 * np.cumprod(1 + market_returns), index=index)
        result = pme.performance_diagnosis(frame)
        active = stock_returns - market_returns
        expected = active.mean() / active.std(ddof=1) * np.sqrt(252)
        self.assertAlmostEqual(result["relative"]["informationRatio"], expected, places=8)
        self.assertAlmostEqual(result["relative"]["trackingErrorPct"], active.std(ddof=1) * np.sqrt(252) * 100, places=8)

    def test_zero_risk_and_identical_benchmark_are_not_infinite(self):
        frame = self.frame([100.0] * 90, index=pd.bdate_range("2025-01-01", periods=90))
        result = pme.performance_diagnosis(frame)
        self.assertEqual(result["portfolio"]["volatilityPct"], 0)
        self.assertEqual(result["relative"]["trackingErrorPct"], 0)
        self.assertIsNone(result["relative"]["informationRatio"])

    def test_empty_period_and_invalid_returns_do_not_create_scores(self):
        frame = self.frame([100, 100, 80])
        empty = pme.performance_diagnosis(frame, start=pd.Timestamp("2026-01-01"))
        self.assertEqual(empty["series"], [])
        self.assertIsNone(empty["portfolio"]["totalReturnPct"])
        invalid = pme.performance_diagnosis(self.frame([100, -10]))
        self.assertEqual(invalid["series"], [])
        self.assertTrue(invalid["warnings"])

    def test_period_reset_uses_prior_value_and_keeps_true_daily_trough(self):
        frame = self.frame([100, 200, 160, 200, 180])
        result = pme.performance_diagnosis(frame, start=frame.index[2])
        self.assertAlmostEqual(result["portfolio"]["totalReturnPct"], -10)
        self.assertAlmostEqual(result["portfolio"]["maxDrawdownPct"], -20)
        self.assertAlmostEqual(result["series"][0]["portfolio"], 100)

    def test_monthly_comparison_omits_partial_months_from_hit_rate(self):
        index = pd.date_range("2025-01-15", "2025-03-10")
        mine = 100 * 1.001 ** np.arange(len(index))
        result = pme.performance_diagnosis(self.frame(mine, market=[100.0] * len(index), index=index))
        self.assertEqual(result["relative"]["comparableMonths"], 1)
        self.assertEqual(result["relative"]["winningMonths"], 1)
        self.assertEqual(result["relative"]["monthlyWinRatePct"], 100)
        self.assertEqual([row["partial"] for row in result["monthly"]], [True, False, True])

    def test_liquidation_does_not_extend_annualization_with_empty_days(self):
        frame = self.frame([100, 110, 0, 0, 0], sales=[0, 0, 110, 110, 110])
        result = pme.performance_diagnosis(frame)
        self.assertEqual(result["sample"]["end"], "2025-01-03")
        self.assertAlmostEqual(result["portfolio"]["totalReturnPct"], 10)


class DiagnosisApiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = self.enterContext(AnalysisFixture())

    def test_period_dividend_fx_and_symbol_options_match_existing_twr(self):
        periods = [("ALL", 0), ("1M", 0), ("YOY", self.fixture.index[0].year),
                   ("YOY", self.fixture.index[-1].year)]
        for dividend, fx, ticker, (period, year) in product((0, 1), (0, 1), ("", "NVDA", "360750"), periods):
            with self.subTest(dividend=dividend, fx=fx, ticker=ticker, period=period, year=year):
                report = json.loads(webapp.api_app_diagnosis(None, div=dividend, fx=fx, ticker=ticker,
                                                            period=period, year=year).body)
                cutoff, end = webapp._period_bounds(period, year)
                frame = pme.build_asset_value_growth(self.fixture.orders, self.fixture.data["fx_rate"],
                                                      self.fixture.dividends, ticker or None, bool(dividend), bool(fx), end=end)
                expected = pme.comparison_statistics(frame, cutoff)["twr"]
                self.assertEqual(report["method"], "twr-risk-v1")
                self.assertAlmostEqual(report["portfolio"]["totalReturnPct"], expected)
                self.assertAlmostEqual(report["portfolio"]["maxDrawdownPct"],
                                       min(row["portfolioDrawdown"] for row in report["series"]))
                if end is not None:
                    self.assertLessEqual(pd.Timestamp(report["sample"]["end"]), end)
                if cutoff is not None:
                    self.assertGreaterEqual(pd.Timestamp(report["sample"]["start"]), cutoff)
                self.assertEqual(report["analysis"]["status"], "complete")
                self.assertEqual(report["years"], webapp._available_years(self.fixture.orders))

    def test_partial_and_unavailable_data_preserve_coverage(self):
        self.fixture.histories["NVDA"] = pd.Series(dtype=float)
        partial = json.loads(webapp.api_app_diagnosis(None).body)
        self.assertEqual(partial["analysis"]["status"], "partial")
        self.assertEqual(partial["analysis"]["excludedSymbols"], ["NVDA"])
        self.assertIsNotNone(partial["portfolio"]["totalReturnPct"])
        unavailable = json.loads(webapp.api_app_diagnosis(None, ticker="NVDA").body)
        self.assertEqual(unavailable["analysis"]["status"], "unavailable")
        self.assertEqual(unavailable["series"], [])
        self.assertIsNone(unavailable["portfolio"]["totalReturnPct"])

    def test_authentication_is_required_and_invalid_year_is_rejected(self):
        with patch.object(webapp, "_current_user", return_value=None), patch.object(webapp, "get_portfolio") as load:
            self.assertEqual(webapp.api_app_diagnosis(None).status_code, 401)
            load.assert_not_called()
        with self.assertRaises(webapp.HTTPException):
            webapp.api_app_diagnosis(None, period="YOY", year=pd.Timestamp.now().year + 1)


if __name__ == "__main__":
    unittest.main()