import json
import unittest
from unittest.mock import patch

import pandas as pd

import manual_holdings
import performance
import pme
import webapp
from analysis_fixture import AnalysisFixture


class TransactionPreprocessingTests(unittest.TestCase):
    def holdings(self, trades, price):
        frame = pd.DataFrame(trades, columns=["일자", "구분", "수량", "단가"])
        frame["티커"] = "005930"
        frame["종목명"] = "삼성전자"
        frame["증권사"] = "test"
        frame["시장"] = "KOSPI"
        frame["통화"] = "KRW"
        history = pd.Series([price], index=pd.to_datetime(["2026-09-11"]))
        with patch.object(manual_holdings, "get_history", return_value=history):
            return manual_holdings.derive_holdings_from_tx(frame).iloc[0]

    def test_repurchase_does_not_reuse_closed_position_cost(self):
        row = self.holdings([
            ("2026-07-09", "매수", 2, 200),
            ("2025-09-18", "매도", 10, 90),
            ("2021-05-18", "매수", 10, 100),
        ], price=150)
        self.assertEqual(row["수량"], 2)
        self.assertEqual(row["평균매수가"], 200)
        self.assertEqual(row["수익률(%)"], -25)

    def test_partial_sale_reduces_cost_before_next_purchase(self):
        row = self.holdings([
            ("2025-01-01", "매수", 10, 100),
            ("2025-02-01", "매도", 8, 90),
            ("2025-03-01", "매수", 2, 200),
        ], price=120)
        self.assertEqual(row["수량"], 4)
        self.assertEqual(row["평균매수가"], 150)
        self.assertEqual(row["수익률(%)"], -20)

    def test_buy_only_average_is_unchanged(self):
        row = self.holdings([
            ("2026-07-09", "매수", 1, 220),
            ("2026-06-30", "매수", 1, 260),
        ], price=180)
        self.assertEqual(row["수량"], 2)
        self.assertEqual(row["평균매수가"], 240)
        self.assertEqual(row["수익률(%)"], -25)

    def test_display_average_matches_remaining_position_cost(self):
        frame = pd.DataFrame([
            {"일자": "2021-05-18", "구분": "매수", "수량": 10, "단가": 100},
            {"일자": "2025-09-18", "구분": "매도", "수량": 10, "단가": 90},
            {"일자": "2026-07-09", "구분": "매수", "수량": 2, "단가": 200},
        ])
        frame["티커"] = "005930"
        frame["통화"] = "KRW"
        orders = manual_holdings.transactions_to_orders(frame)
        with patch.object(performance, "get_native_price_now", return_value=150.0), \
                patch.object(performance, "get_usdkrw_history", return_value=pd.Series(dtype=float)):
            row = performance.build_holdings_breakdown(orders, include_div=False).iloc[0]
        self.assertEqual(row["평단가(원화)"], 200)
        self.assertEqual(row["투자원금(원)"], row["보유수량"] * row["평단가(원화)"])
        self.assertEqual(row["평가손익(원)"], -100)
        self.assertEqual(row["실현손익(원)"], -100)
        self.assertEqual(row["수익률(%)"], -25)


class KoreanValuationDateTests(unittest.TestCase):
    def frame(self, symbol, end=None):
        dates = pd.to_datetime(["2026-09-10", "2026-09-11", "2026-09-14"])
        stock = pd.Series([100.0, 100.0, 80.0], index=dates)
        spy = pd.Series([100.0, 100.0], index=dates[:2])
        orders = [{"symbol": symbol, "currency": "KRW", "side": "BUY",
                   "execution": {"filledQuantity": 10, "averageFilledPrice": 100,
                                 "filledAt": "2026-09-10"}}]
        with patch.object(pme, "get_history", side_effect=lambda ticker, **kwargs:
                          spy if ticker == pme.BENCHMARK_TICKER else stock), \
                patch.object(pme, "get_usdkrw_history", return_value=pd.Series(1000.0, index=dates)), \
                patch.object(pme, "to_yf_ticker", side_effect=lambda ticker, *args: ticker):
            return pme.build_asset_value_growth(orders, ticker=symbol, include_div=False, end=end)

    def test_korean_prices_after_latest_us_session_are_included(self):
        for symbol in ("005930", "000660"):
            with self.subTest(symbol=symbol):
                frame = self.frame(symbol)
                self.assertEqual(frame.index[-1], pd.Timestamp("2026-09-14"))
                profit = pme.profit_from_growth(frame)
                self.assertEqual(profit["totalCurrent"], 800)
                self.assertEqual(profit["totalPnL"], -200)
                self.assertEqual(profit["returnPct"], -20)
                self.assertEqual(frame["S&P500 자산가치"].iloc[-1], 1000)
                self.assertEqual(frame.attrs["price_dates"][symbol], "2026-09-14")
                self.assertEqual(frame.attrs["benchmark_price_date"], "2026-09-11")

    def test_explicit_end_date_still_limits_valuation(self):
        frame = self.frame("005930", end="2026-09-11")
        self.assertEqual(frame.index[-1], pd.Timestamp("2026-09-11"))
        self.assertEqual(pme.profit_from_growth(frame)["returnPct"], 0)


class HoldingReturnTests(unittest.TestCase):
    def test_holding_loss_is_separate_from_turnover_based_return(self):
        with AnalysisFixture() as fixture:
            fixture.fx.loc[:] = 1000.0
            fixture.histories["NVDA"].loc[:] = 100.0
            fixture.histories["NVDA"].iloc[-10:] = 80.0
            fixture.orders[:] = [
                {"symbol": "NVDA", "currency": "USD", "side": side,
                 "execution": {"filledQuantity": 10, "averageFilledPrice": 100,
                               "filledAmount": 1000, "filledAt": str(fixture.index[offset])}}
                for offset, side in ((0, "BUY"), (150, "SELL"), (300, "BUY"))
            ]
            responses = []
            for include_div in (0, 1):
                for period in ("ALL", "1M"):
                    response = webapp.api_app_dashboard(None, ticker="NVDA", period=period, div=include_div)
                    result = json.loads(response.body)
                    responses.append(result)
                    self.assertAlmostEqual(result["stocks"][0]["holdingReturnPct"], -20.0)
                    self.assertAlmostEqual(result["stocks"][0]["holdingUnrealizedPnL"], -200000.0)
                    self.assertAlmostEqual(result["metrics"]["holdingReturnPct"], -20.0)
            self.assertAlmostEqual(responses[0]["metrics"]["returnPct"], -10.0)
            self.assertAlmostEqual(responses[1]["metrics"]["returnPct"], -20.0)


if __name__ == "__main__":
    unittest.main()