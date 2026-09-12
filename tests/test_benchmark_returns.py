import json
import unittest
from unittest.mock import patch

import pandas as pd

import pme
import webapp


class BenchmarkReturnTests(unittest.TestCase):
    def setUp(self):
        self.today = pd.Timestamp.now().normalize()
        self.index = pd.date_range(self.today - pd.Timedelta(days=70), self.today)
        self.stock = pd.Series(100.0, index=self.index)
        self.spy = pd.Series(100.0, index=self.index)
        self.stock.loc[self.today - pd.Timedelta(days=15):] = 110.0
        self.spy.loc[self.today - pd.Timedelta(days=15):] = 120.0

    def order(self, side, quantity, price, date):
        return {
            "symbol": "TEST", "currency": "USD", "side": side,
            "execution": {"filledQuantity": quantity, "averageFilledPrice": price,
                          "filledAt": str(date)},
        }

    def response(self, sold=9, period="", dividend=0, include_div=True, rebuy=False):
        orders = [self.order("BUY", 10, 100, self.index[0])]
        if sold:
            orders.append(self.order("SELL", sold, float(self.stock.iloc[-1]),
                                     self.today - pd.Timedelta(days=10)))
        if rebuy:
            orders.append(self.order("BUY", 5, 110, self.today - pd.Timedelta(days=5)))
        with patch.object(pme, "get_history", side_effect=lambda symbol, **kwargs:
                          self.spy if symbol == pme.BENCHMARK_TICKER else self.stock), \
                patch.object(pme, "get_usdkrw_history", return_value=pd.Series(1.0, index=self.index)):
            frame = pme.build_asset_value_growth(
                orders, fx_now=1, ticker="TEST", include_div=include_div,
                div_events=[(self.today, dividend, "TEST")],
            )
        data = {"combined_orders": orders, "fx_rate": 1, "ab": {},
                "breakdown": pd.DataFrame(), "stock_analytics": pd.DataFrame(), "name_map": {}}
        with patch.object(webapp, "_current_user", return_value="test"), \
                patch.object(webapp, "get_portfolio", return_value=data), \
                patch.object(webapp.pipeline, "growth_frame", return_value=frame), \
                patch.object(webapp.pipeline, "twr_comparison", return_value=pd.DataFrame()), \
                patch.object(webapp.pipeline, "rolling_beta", return_value=pd.Series(dtype=float)), \
                patch.object(webapp.pipeline, "spy_dca", return_value=(None, None, {})):
            response = webapp.api_app_benchmark(None, ticker="TEST", period=period, div=int(include_div))
        return json.loads(response.body)

    def assert_returns(self, response, mine=10.0, spy=20.0):
        self.assertEqual(response["summary"]["portfolioReturn"], mine)
        self.assertEqual(response["summary"]["sp500Return"], spy)
        self.assertEqual(response["growth"][-1]["portfolioPct"], mine)
        self.assertEqual(response["growth"][-1]["alpha"], round(mine - spy, 1))

    def test_partial_sale_does_not_inflate_returns(self):
        self.assert_returns(self.response())

    def test_full_sale_preserves_realized_returns(self):
        self.assert_returns(self.response(sold=10))

    def test_buy_and_hold_is_unchanged(self):
        self.assert_returns(self.response(sold=0))

    def test_period_uses_opening_value_not_remaining_net_capital(self):
        self.assert_returns(self.response(period="1M"))

    def test_dividend_option_is_preserved(self):
        self.assert_returns(self.response(dividend=10), mine=11.0)
        self.assert_returns(self.response(dividend=10, include_div=False))

    def test_reinvestment_uses_gross_purchases(self):
        response = self.response(rebuy=True)
        self.assertEqual(response["summary"]["portfolioReturn"], 6.5)
        self.assertEqual(response["summary"]["sp500Return"], 12.9)

    def test_realized_losses_are_preserved(self):
        self.stock.loc[self.today - pd.Timedelta(days=15):] = 90.0
        self.spy.loc[self.today - pd.Timedelta(days=15):] = 80.0
        self.assert_returns(self.response(), mine=-10.0, spy=-20.0)

    def test_empty_selected_period_returns_no_growth(self):
        self.today -= pd.DateOffset(years=2)
        self.index -= pd.DateOffset(years=2)
        self.stock.index = self.index
        self.spy.index = self.index
        self.assertEqual(self.response(period="1M")["growth"], [])


if __name__ == "__main__":
    unittest.main()