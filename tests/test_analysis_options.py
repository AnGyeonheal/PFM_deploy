import unittest
from unittest.mock import patch

import pandas as pd

import pme
import benchmark
import names
import advanced_analytics


class AnalysisOptionTests(unittest.TestCase):
    def setUp(self):
        self.index = pd.date_range("2025-01-01", periods=61)
        self.price = pd.Series(100.0, index=self.index)
        self.fx = pd.Series(1000.0, index=self.index)
        self.fx.iloc[30:] = 1200.0
        self.orders = [{
            "symbol": "TEST", "currency": "USD", "side": "BUY",
            "execution": {"filledQuantity": 10, "averageFilledPrice": 100,
                          "filledAt": str(self.index[0])},
        }]
        self.enterContext(patch.object(pme, "get_history", return_value=self.price))
        self.enterContext(patch.object(pme, "get_usdkrw_history", return_value=self.fx))
        self.enterContext(patch.object(pme, "get_dividends", return_value=pd.Series(dtype=float)))

    def test_twr_excludes_fx_for_both_portfolio_and_benchmark(self):
        result = pme.build_twr_comparison(self.orders, include_fx=False)
        self.assertAlmostEqual(result["내 수익률(%)"].iloc[-1], 0.0)
        self.assertAlmostEqual(result["S&P500 수익률(%)"].iloc[-1], 0.0)

    def test_growth_excludes_fx_for_benchmark_too(self):
        result = pme.build_asset_value_growth(self.orders, include_fx=False)
        self.assertAlmostEqual(result["내 자산가치"].iloc[-1], 1000000.0)
        self.assertAlmostEqual(result["S&P500 자산가치"].iloc[-1], 1000000.0)

    def test_realized_fx_is_excluded_after_full_sale(self):
        self.orders.append({
            "symbol": "TEST", "currency": "USD", "side": "SELL",
            "execution": {"filledQuantity": 10, "averageFilledPrice": 100,
                          "filledAt": str(self.index[-1])},
        })
        result = pme.build_asset_value_growth(self.orders, ticker="TEST", include_fx=False)
        self.assertAlmostEqual(result["누적매도금액"].iloc[-1], 1000000.0)
        self.assertAlmostEqual(result["S&P500 누적매도금액"].iloc[-1], 1000000.0)

    def test_dividend_drop_is_offset_once_for_both_sides(self):
        self.price.iloc[30:] = 99.0
        dividends = pd.Series([1.0], index=[self.index[30]])
        with patch.object(pme, "get_dividends", return_value=dividends):
            included = pme.build_twr_comparison(
                self.orders, include_fx=False, div_events=[(self.index[30], 12000, "TEST")])
            excluded = pme.build_twr_comparison(self.orders, include_fx=False, include_div=False)
        for column in included:
            self.assertAlmostEqual(included[column].iloc[-1], 0.0)
            self.assertAlmostEqual(excluded[column].iloc[-1], -1.0)

    def test_other_stock_dividend_does_not_leak_into_selected_stock(self):
        frame = pme.build_asset_value_growth(
            self.orders, ticker="TEST", include_fx=False,
            div_events=[(self.index[30], 50000, "OTHER")])
        self.assertEqual(frame["누적배당금액"].iloc[-1], 0.0)

    def test_xirr_includes_closed_position_and_matches_fx_option(self):
        self.orders.append({"symbol": "TEST", "currency": "USD", "side": "SELL",
                            "execution": {"filledQuantity": 10, "averageFilledPrice": 100,
                                          "filledAt": str(self.index[-1])}})
        result = pme.compute_alpha_beta(self.orders, include_fx=False)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["port_xirr_pct"], 0.0)
        self.assertAlmostEqual(result["spy_xirr_pct"], 0.0)

    def test_period_xirr_includes_opening_position(self):
        frame = pme.build_asset_value_growth(self.orders, include_fx=False)
        self.assertAlmostEqual(pme.xirr_from_growth(frame, self.index[30]), 0.0)

    def test_profit_components_and_return_share_same_basis(self):
        self.price.iloc[30:] = 110.0
        self.orders.append({"symbol": "TEST", "currency": "USD", "side": "SELL",
                            "execution": {"filledQuantity": 5, "averageFilledPrice": 110,
                                          "filledAt": str(self.index[-1])}})
        frame = pme.build_asset_value_growth(self.orders, include_fx=False)
        profit = pme.profit_from_growth(frame)
        self.assertAlmostEqual(profit["totalPnL"], 100000.0)
        self.assertAlmostEqual(profit["realizedPnL"], 50000.0)
        self.assertAlmostEqual(profit["unrealizedPnL"], 50000.0)
        self.assertAlmostEqual(profit["returnPct"], 10.0)
        self.assertAlmostEqual(profit["returnPct"], pme.comparison_statistics(frame)["returns"]["portfolio"].iloc[-1])

    def test_same_day_xirr_is_undefined(self):
        self.assertIsNone(pme.xirr([(self.index[0], -100), (self.index[0], 100)]))

    def test_lump_sum_simulation_uses_same_capital_and_fx_option(self):
        self.orders.append({"symbol": "TEST", "currency": "USD", "side": "BUY",
                            "execution": {"filledQuantity": 90, "averageFilledPrice": 100,
                                          "filledAt": str(self.index[35])}})
        _, _, summary = pme.build_spy_dca(self.orders, include_fx=False)
        self.assertEqual(summary["시작금액"], 1000000)
        self.assertEqual(summary["내수익금"], 0)
        self.assertEqual(summary["S&P500수익금"], 0)

    def test_missing_prices_do_not_become_a_total_loss(self):
        with patch.object(pme, "get_history", side_effect=lambda symbol, **kwargs:
                          self.price if symbol == pme.BENCHMARK_TICKER else pd.Series(dtype=float)):
            frame = pme.build_asset_value_growth(self.orders)
        self.assertTrue(frame.empty)
        self.assertTrue(frame.attrs["warnings"])

    def test_same_day_records_follow_execution_time(self):
        bought = dict(self.orders[0], execution={"filledQuantity": 10, "averageFilledPrice": 100,
                                                "filledAt": "2025-01-01T09:00:00"})
        sold = dict(bought, side="SELL", execution={"filledQuantity": 10, "averageFilledPrice": 100,
                                                    "filledAt": "2025-01-01T15:00:00"})
        frame = pme.build_asset_value_growth([sold, bought], include_fx=False)
        self.assertFalse(frame.empty)
        self.assertEqual(frame["보유원가"].iloc[-1], 0.0)


class XirrAccuracyTests(unittest.TestCase):
    def test_known_irregular_cashflows(self):
        cashflows = [(pd.Timestamp(date), amount) for date, amount in (
            ("2008-01-01", -10000), ("2008-03-01", 2750), ("2008-10-30", 4250),
            ("2009-02-15", 3250), ("2009-04-01", 2750),
        )]
        rate = pme.xirr(cashflows)
        self.assertAlmostEqual(rate, 0.3733625335, places=8)
        self.assertAlmostEqual(pme._xnpv(rate, cashflows), 0.0, places=5)

    def test_annual_gain_loss_and_scale_invariance(self):
        for final, expected in ((110, 0.1), (75, -0.25), (100, 0.0)):
            for scale in (1e-9, 1.0, 1e9):
                with self.subTest(final=final, scale=scale):
                    cashflows = [(pd.Timestamp("2021-01-01"), -100 * scale),
                                 (pd.Timestamp("2022-01-01"), final * scale)]
                    self.assertAlmostEqual(pme.xirr(cashflows), expected, places=8)

    def test_short_period_is_annualized_without_arbitrary_rate_cap(self):
        cashflows = [(pd.Timestamp("2025-01-01"), -100),
                     (pd.Timestamp("2025-01-02"), 102)]
        rate = pme.xirr(cashflows)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate / (1.02 ** 365 - 1), 1.0, places=8)

    def test_nonfinite_amounts_and_dates_are_unavailable(self):
        for date, amount in ((pd.Timestamp("2022-01-01"), float("nan")),
                             (pd.Timestamp("2022-01-01"), float("inf")), (pd.NaT, 110)):
            with self.subTest(date=date, amount=amount):
                self.assertIsNone(pme.xirr([(pd.Timestamp("2021-01-01"), -100), (date, amount)]))

    def test_calendar_year_xirr_uses_opening_value_and_leap_year_days(self):
        index = pd.date_range("2023-12-31", "2025-01-10")
        value = pd.Series([100 * 1.1 ** ((date - index[0]).days / 365) for date in index], index=index)
        frame = pd.DataFrame({"내 자산가치": value, "S&P500 자산가치": value,
                              "누적매수금액": 100.0, "누적매도금액": 0.0, "S&P500 누적매도금액": 0.0}, index=index)
        frame.loc["2025-01-01":, "내 자산가치"] = 1000000.0
        self.assertAlmostEqual(pme.xirr_from_growth(frame, "2024-01-01", end="2024-12-31"), 10.0, places=7)
        self.assertAlmostEqual(pme.xirr_from_growth(frame, "2024-01-01", benchmark=True, end="2024-12-31"), 10.0, places=7)

    def test_period_flows_do_not_double_count_opening_day_trades_or_dividends(self):
        index = pd.date_range("2023-12-31", "2025-01-10")
        frame = pd.DataFrame({"내 자산가치": 100.0, "누적매수금액": 100.0, "누적매도금액": 0.0}, index=index)
        frame.loc["2024-01-01":, "누적매수금액"] += 50.0
        frame.loc["2024-07-01":, "누적매도금액"] += 40.0
        frame.loc["2024-12-31":, "내 자산가치"] = 130.0
        expected = pme.xirr([(pd.Timestamp("2023-12-31"), -100), (pd.Timestamp("2024-01-01"), -50),
                              (pd.Timestamp("2024-07-01"), 40), (pd.Timestamp("2024-12-31"), 130)]) * 100
        self.assertAlmostEqual(pme.xirr_from_growth(frame, "2024-01-01", end="2024-12-31"), expected, places=7)

    def test_generated_rate_with_deposit_and_withdrawal_is_recovered(self):
        dates = pd.to_datetime(["2023-12-31", "2024-04-20", "2024-09-15", "2024-12-31"])
        for expected in (-0.2, 0.0, 0.12, 0.5):
            with self.subTest(rate=expected):
                initial, purchase, sale = 100000.0, 40000.0, 25000.0
                terminal = (initial * (1 + expected) ** ((dates[-1] - dates[0]).days / 365)
                            + purchase * (1 + expected) ** ((dates[-1] - dates[1]).days / 365)
                            - sale * (1 + expected) ** ((dates[-1] - dates[2]).days / 365))
                frame = pd.DataFrame({"내 자산가치": [initial, initial + purchase, initial + purchase - sale, terminal],
                                      "누적매수금액": [initial, initial + purchase, initial + purchase, initial + purchase],
                                      "누적매도금액": [0.0, 0.0, sale, sale]}, index=dates)
                self.assertAlmostEqual(pme.xirr_from_growth(frame, "2024-01-01", end="2024-12-31"), expected * 100, places=6)


class MarketDataTests(unittest.TestCase):
    def test_only_unhedged_us_etfs_are_treated_as_usd_exposed(self):
        names.register_krw_foreign({"A360750": "TIGER 미국S&P500", "000001": "TIGER 미국S&P500(H)",
                                    "000002": "TIGER 일본니케이225", "000003": "미국회사",
                                    "000004": "ACE 미국나스닥100"})
        self.assertTrue(names.is_krw_foreign("360750"))
        self.assertTrue(names.is_krw_foreign("000004"))
        for symbol in ("000001", "000002", "000003"):
            self.assertFalse(names.is_krw_foreign(symbol))
        names.register_krw_foreign({})
        self.assertFalse(names.is_krw_foreign("360750"))

    def test_dividend_entitlement_is_before_ex_date(self):
        date = pd.Timestamp("2025-01-02")
        events = [(date - pd.Timedelta(days=1), 10), (date, 5)]
        self.assertEqual(advanced_analytics._shares_held_on(events, date), 10)

    def test_close_is_not_dividend_adjusted(self):
        with patch.object(benchmark.yf, "Ticker") as ticker:
            ticker.return_value.history.return_value = pd.DataFrame(
                {"Close": [100.0]}, index=pd.to_datetime(["2025-01-01"]))
            benchmark._get_history_uncached("TEST")
            self.assertIs(ticker.return_value.history.call_args.kwargs["auto_adjust"], False)


if __name__ == "__main__":
    unittest.main()