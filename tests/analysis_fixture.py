from contextlib import ExitStack
from unittest.mock import patch

import numpy as np
import pandas as pd

import names
import benchmark
import pipeline
import pme
import webapp


class AnalysisFixture:
    def __init__(self):
        self.index = pd.date_range(pd.Timestamp.now().normalize() - pd.Timedelta(days=499), periods=500)
        changes = pd.Series([0.001 + 0.008 * np.sin(step * 0.9) if date.dayofweek < 5 else 0.0
                             for step, date in enumerate(self.index)], index=self.index)
        self.fx = pd.Series(np.linspace(1000.0, 1250.0, len(self.index)), index=self.index)
        self.spy = 100.0 * (1.0 + changes).cumprod()
        self.stock = 100.0 * (1.0 + changes * 1.5).cumprod()
        self.histories = {"SPY": self.spy, "NVDA": self.stock, "360750.KS": self.spy * self.fx}
        self.name_map = {"NVDA": "NVIDIA", "360750": "TIGER 미국S&P500"}
        self.orders = []
        for symbol, currency, price in (("NVDA", "USD", self.stock), ("360750", "KRW", self.spy * self.fx)):
            for offset, quantity, side in ((0, 10, "BUY"), (200, 5, "BUY"), (350, 4, "SELL")):
                self.orders.append({"symbol": symbol, "currency": currency, "side": side,
                                    "execution": {"filledAt": str(self.index[offset]), "filledQuantity": quantity,
                                                  "averageFilledPrice": float(price.iloc[offset]),
                                                  "filledAmount": float(price.iloc[offset] * quantity)}})
        self.dividends = [(self.index[-10], 25000.0, "NVDA"), (self.index[-10], 10000.0, "360750")]
        self.data = {"combined_orders": self.orders, "fx_rate": float(self.fx.iloc[-1]),
                     "summary": {"total_asset_krw": 5000000, "stock_eval_krw": 5000000}, "perf": {}, "ab": {},
                     "name_map": self.name_map, "stock_analytics": pd.DataFrame(), "holdings": [],
                     "breakdown": pd.DataFrame([{"티커": symbol, "통화": currency, "보유수량": 11, "상태": "보유중"}
                                                for symbol, currency in (("NVDA", "USD"), ("360750", "KRW"))])}

    def __enter__(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(benchmark, "_krx_market_map", return_value={"360750": "KOSPI"}))
        names.register_krw_foreign(self.name_map)
        self.stack.enter_context(patch.object(pme, "get_history", side_effect=lambda symbol, **kwargs:
                                              self.histories.get(symbol, pd.Series(dtype=float)).copy()))
        self.stack.enter_context(patch.object(pme, "get_usdkrw_history", return_value=self.fx))
        self.stack.enter_context(patch.object(pme, "get_dividends", return_value=pd.Series([0.2], index=[self.index[-10]])))
        self.stack.enter_context(patch.object(pipeline, "_dated_div_events", return_value=self.dividends))
        self.stack.enter_context(patch.object(webapp, "get_portfolio", side_effect=self.portfolio))
        self.stack.enter_context(patch.object(webapp, "_current_user", return_value="analysis-test"))
        self.stack.enter_context(patch.object(webapp, "_per_ticker_fx", return_value={}))
        self.stack.enter_context(patch.object(webapp, "_load_daily_metrics", return_value={}))
        self.stack.enter_context(patch.object(webapp, "_save_daily_metrics"))
        return self

    def portfolio(self, *args, **kwargs):
        names.register_krw_foreign(self.name_map)
        return self.data

    def __exit__(self, *args):
        self.stack.close()
        names.register_krw_foreign({})