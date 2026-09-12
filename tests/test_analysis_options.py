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