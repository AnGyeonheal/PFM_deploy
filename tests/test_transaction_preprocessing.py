import json
import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd

import manual_holdings
import performance
import pme
import pipeline
import webapp
from analysis_fixture import AnalysisFixture
from exporter import build_import_template_xlsx
from openpyxl import load_workbook


class TransactionPreprocessingTests(unittest.TestCase):
    def account_trades(self):
        frame = pd.DataFrame([
            ("2025-01-01", "매수", 10, 100, "001"),
            ("2025-01-02", "매수", 10, 200, "002"),
            ("2025-02-01", "매도", 5, 300, "002"),
        ], columns=["일자", "구분", "수량", "단가", "계좌"])
        return frame.assign(증권사="test", 티커="005930", 종목명="삼성전자", 시장="KOSPI", 통화="KRW")

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


    def test_manual_positions_and_orders_keep_accounts(self):
        trades = self.account_trades()
        history = pd.Series([150.0], index=pd.to_datetime(["2025-02-03"]))
        with patch.object(manual_holdings, "get_history", return_value=history):
            holdings = manual_holdings.derive_holdings_from_tx(trades).set_index("계좌")
        self.assertEqual(holdings.loc["001", "수량"], 10)
        self.assertEqual(holdings.loc["001", "평균매수가"], 100)
        self.assertEqual(holdings.loc["002", "수량"], 5)
        self.assertEqual(holdings.loc["002", "평균매수가"], 200)
        orders = manual_holdings.transactions_to_orders(trades)
        self.assertEqual([order["account"] for order in orders], ["001", "002", "002"])
        snapshots = manual_holdings.manual_to_orders(holdings.reset_index())
        self.assertEqual([order["account"] for order in snapshots], ["001", "002"])

    def test_account_identifiers_survive_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(manual_holdings, "TX_CSV", str(Path(directory) / "trades.csv")):
            manual_holdings.write_transactions_csv(self.account_trades())
            restored = manual_holdings.read_transactions_csv()
            self.assertEqual(restored["계좌"].tolist(), ["001", "002", "002"])
            manual_holdings.write_transactions_csv(self.account_trades().drop(columns="계좌"))
            self.assertEqual(manual_holdings.read_transactions_csv()["계좌"].tolist(), ["", "", ""])

    def test_template_preserves_optional_account_identifiers(self):
        workbook = load_workbook(io.BytesIO(build_import_template_xlsx()))
        sheet = workbook["거래내역"]
        self.assertEqual(sheet["J1"].value, "계좌")
        self.assertEqual(sheet["J2"].number_format, "@")
        sheet["J2"] = "001"
        sheet["J3"] = "002"
        content = io.BytesIO()
        workbook.save(content)
        with patch.object(manual_holdings, "save_parsed_transactions", return_value=2) as save, \
                patch.object(manual_holdings, "save_parsed_dividends", return_value=2):
            result = manual_holdings.import_template_xlsx(content.getvalue())
        self.assertEqual(result["errors"], [])
        self.assertEqual([row["계좌"] for row in save.call_args.args[0]], ["001", "002"])

    def test_toss_fetch_and_edits_preserve_account_identity(self):
        original = {"symbol": "TEST", "currency": "USD", "side": "BUY", "execution": {
            "filledQuantity": 1, "averageFilledPrice": 100, "filledAmount": 100, "filledAt": "2025-01-01"}}
        with patch.object(pipeline, "get_access_token", return_value="test-token"), \
                patch.object(pipeline, "get_exchange_rate", return_value=1000), \
                patch.object(pipeline, "get_order_history", return_value=[original]), \
                patch.object(pipeline, "get_holdings", return_value={}), \
                patch.object(pipeline, "build_transaction_detail", return_value=pd.DataFrame()):
            _, orders, _, _ = pipeline.toss_trades({"TOSS_CLIENT_ID": "test", "TOSS_CLIENT_SECRET": "test",
                                                   "TOSS_ACCOUNT_NO": "001"})
        self.assertEqual(pme.position_key(orders[0])[:2], ("toss", "001"))
        self.assertNotIn("account", original)
        edited = pipeline._override_to_order(orders[0], {"일자": "2025-01-02", "구분": "매수",
                                                         "수량": 2, "단가": 110})
        self.assertEqual(pme.position_key(edited), pme.position_key(orders[0]))

    def test_edit_api_roundtrip_preserves_accounts(self):
        with patch.object(webapp, "_current_user", return_value="test"), \
                patch.object(pipeline, "apply_credentials"), \
                patch.object(webapp, "get_portfolio", return_value={"dividends_rows": []}), \
                patch.object(webapp, "read_transactions_csv", return_value=self.account_trades()), \
                patch.object(webapp, "read_dividends_csv", return_value=pd.DataFrame()), \
                patch.object(webapp, "list_snapshots", return_value=[]), \
                patch.object(webapp, "snapshot_imports"), \
                patch.object(webapp, "write_transactions_csv", return_value=3) as write:
            payload = json.loads(webapp.api_app_edit_data(None).body)
            request = SimpleNamespace(json=AsyncMock(return_value={"rows": payload["transactions"]}))
            response = asyncio.run(webapp.api_app_edit_transactions(request))
            self.assertTrue(json.loads(response.body)["ok"])
            self.assertEqual(write.call_args.args[0]["계좌"].tolist(), ["001", "002", "002"])


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