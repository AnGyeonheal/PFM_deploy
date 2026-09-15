import json
import asyncio
import io
import tempfile
import copy
import unittest
from contextvars import Context, ContextVar
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd

import manual_holdings
import advanced_analytics
import benchmark
import performance
import pme
import pipeline
import pm
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

    def test_edit_api_includes_toss_and_saves_edits_outside_manual_csv(self):
        original = {"orderId": "order-1", "symbol": "AAPL", "currency": "USD", "broker": "토스증권",
                    "account": "001", "side": "BUY", "execution": {"filledQuantity": 3,
                    "averageFilledPrice": 100, "filledAmount": 300, "commission": 0.3,
                    "filledAt": "2025-01-02T13:04:05+09:00"}}
        data = {"toss_orders_raw": [original], "name_map": {"AAPL": "Apple"},
            "toss_name_map": {"AAPL": "Apple"}, "dividends_rows": []}
        overrides = {}
        with patch.object(webapp, "_current_user", return_value="test"), \
                patch.object(pipeline, "apply_credentials"), \
                patch.object(webapp, "get_portfolio", return_value=data), \
                patch.object(webapp, "read_transactions_csv", return_value=self.account_trades()), \
                patch.object(webapp, "read_dividends_csv", return_value=pd.DataFrame()), \
                patch.object(webapp, "list_snapshots", return_value=[]), \
                patch.object(webapp, "snapshot_imports"), \
                patch.object(pipeline, "read_toss_overrides", side_effect=lambda: dict(overrides)), \
                patch.object(pipeline, "write_toss_overrides", side_effect=lambda value: overrides.update(value)), \
                patch.object(webapp, "write_transactions_csv", return_value=3) as write:
            payload = json.loads(webapp.api_app_edit_data(None).body)
            self.assertEqual(len(payload["transactions"]), 4)
            row = next(row for row in payload["transactions"] if row["source"] == "toss")
            self.assertTrue(row["sourceId"])
            row["price"] = 110
            row["name"] = "Edited Apple"
            request = SimpleNamespace(json=AsyncMock(return_value={"rows": payload["transactions"]}))
            response = asyncio.run(webapp.api_app_edit_transactions(request))
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("AAPL", write.call_args.args[0]["티커"].tolist())
            reloaded = pipeline.apply_toss_overrides([original], overrides)
            self.assertEqual(len(reloaded), 1)
            self.assertEqual(reloaded[0]["execution"]["averageFilledPrice"], 110)
            self.assertEqual(reloaded[0]["execution"]["filledAmount"], 330)
            self.assertEqual(reloaded[0]["execution"]["filledAt"], original["execution"]["filledAt"])
            self.assertEqual(reloaded[0]["execution"]["commission"], 0.3)
            self.assertEqual(original["execution"]["averageFilledPrice"], 100)
            data["name_map"] = {"AAPL": "Edited Apple"}
            unchanged = json.loads(webapp.api_app_edit_data(None).body)
            request.json = AsyncMock(return_value={"rows": unchanged["transactions"]})
            self.assertEqual(asyncio.run(webapp.api_app_edit_transactions(request)).status_code, 200)
            self.assertEqual(overrides[row["sourceId"]]["종목명"], "Edited Apple")

    def test_toss_edits_survive_resync_and_preserve_distinct_executions(self):
        original = {"orderId": "same-id", "symbol": "TEST", "broker": "토스증권", "account": "1",
                    "currency": "USD", "side": "BUY", "execution": {"filledQuantity": 2,
                    "averageFilledPrice": 100, "filledAmount": 200, "filledAt": "2025-01-02T09:30:00+09:00"}}
        another_account = dict(original, account="2")
        another_fill = dict(original, orderId="second-id")
        overrides = {pipeline.toss_trade_key(original): {"단가": 125}}
        refreshed = copy.deepcopy(original)
        refreshed["execution"].update(averageFilledPrice=105, commission=0.5)
        result = pipeline.apply_toss_overrides([refreshed, refreshed, another_account, another_fill], overrides)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["execution"]["averageFilledPrice"], 125)
        self.assertEqual(result[0]["execution"]["commission"], 0.5)
        self.assertEqual(result[1]["execution"]["averageFilledPrice"], 100)
        self.assertEqual(result[2]["execution"]["averageFilledPrice"], 100)
        key = pipeline.toss_trade_key(original)
        self.assertEqual(pipeline.apply_toss_overrides([original], {key: {"deleted": True}}), [])
        self.assertEqual(pipeline.apply_toss_overrides([original], {}), [original])
        legacy = {pipeline._legacy_toss_trade_key(original): {"단가": 120}}
        self.assertEqual(pipeline.apply_toss_overrides([original], legacy)[0]["execution"]["averageFilledPrice"], 120)
        no_id = {field: value for field, value in original.items() if field != "orderId"}
        self.assertEqual(len(pipeline.apply_toss_overrides([no_id, no_id], {})), 2)

    def test_toss_date_edit_keeps_intraday_time_and_original_order(self):
        original = {"symbol": "TEST", "currency": "USD", "side": "SELL", "orderedAt": "2025-01-01",
                    "execution": {"filledQuantity": 2, "averageFilledPrice": 100, "filledAmount": 200,
                                  "filledAt": "2025-01-02T14:15:16+09:00", "tax": 0.1}}
        result = pipeline._override_to_order(original, {"일자": "2025-02-03"})
        self.assertEqual(result["execution"]["filledAt"], "2025-02-03T14:15:16+09:00")
        self.assertEqual(result["orderedAt"], "2025-01-01")
        self.assertEqual(result["side"], "SELL")
        self.assertEqual(result["execution"]["tax"], 0.1)
        named = pipeline._override_to_order(original, {"종목명": "Display name"})
        self.assertEqual(named["execution"], original["execution"])
        updated = copy.deepcopy(original)
        updated["execution"]["averageFilledPrice"] = 101
        self.assertNotEqual(pipeline.toss_override_revision({}, original), pipeline.toss_override_revision({}, updated))

    def test_unknown_or_stale_toss_edit_does_not_write_any_data(self):
        original = {"orderId": "order-1", "symbol": "TEST", "broker": "토스증권", "account": "1",
                    "currency": "USD", "side": "BUY", "execution": {"filledQuantity": 1,
                    "averageFilledPrice": 100, "filledAmount": 100, "filledAt": "2025-01-02"}}
        with patch.object(webapp, "_current_user", return_value="test"), patch.object(pipeline, "apply_credentials"), \
                patch.object(webapp, "get_portfolio", return_value={"toss_orders_raw": [original]}), \
                patch.object(pipeline, "read_toss_overrides", return_value={}), \
                patch.object(pipeline, "write_toss_overrides") as write_overrides, \
                patch.object(webapp, "write_transactions_csv") as write_manual, \
                patch.object(webapp, "snapshot_imports") as snapshot:
            for key, revision in (("not-owned", "stale"), (pipeline.toss_trade_key(original), "stale")):
                request = SimpleNamespace(json=AsyncMock(return_value={"rows": [
                    {"source": "toss", "sourceId": key, "revision": revision, "deleted": True}]}))
                self.assertEqual(asyncio.run(webapp.api_app_edit_transactions(request)).status_code, 409)
            write_overrides.assert_not_called()
            write_manual.assert_not_called()
            snapshot.assert_not_called()

    def test_api_deletion_restore_and_new_synced_orders_preserve_other_overrides(self):
        original = {"orderId": "old", "symbol": "TEST", "broker": "토스증권", "account": "001",
                    "currency": "USD", "side": "BUY", "execution": {"filledQuantity": 1,
                    "averageFilledPrice": 100, "filledAmount": 100, "filledAt": "2025-01-02"}}
        data = {"toss_orders_raw": [original], "dividends_rows": []}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(manual_holdings, "TOSS_OVR_JSON", str(Path(directory) / "overrides.json")), \
                patch.object(webapp, "_current_user", return_value="test"), patch.object(pipeline, "apply_credentials"), \
                patch.object(webapp, "get_portfolio", return_value=data), \
                patch.object(webapp, "read_transactions_csv", return_value=pd.DataFrame()), \
                patch.object(webapp, "read_dividends_csv", return_value=pd.DataFrame()), \
                patch.object(webapp, "list_snapshots", return_value=[]), patch.object(webapp, "snapshot_imports"), \
                patch.object(webapp, "write_transactions_csv", return_value=0):
            pipeline.write_toss_overrides({"outside-current-page": {"단가": 50}})
            row = json.loads(webapp.api_app_edit_data(None).body)["transactions"][0]
            data["toss_orders_raw"].append(dict(original, orderId="new"))
            row["deleted"] = True
            request = SimpleNamespace(json=AsyncMock(return_value={"rows": [row]}))
            self.assertEqual(asyncio.run(webapp.api_app_edit_transactions(request)).status_code, 200)
            overrides = pipeline.read_toss_overrides()
            self.assertIn("outside-current-page", overrides)
            self.assertEqual([order["orderId"] for order in pipeline.apply_toss_overrides(data["toss_orders_raw"], overrides)], ["new"])
            restored = json.loads(webapp.api_app_edit_data(None).body)["transactions"][0]
            restored["reset"] = True
            request.json = AsyncMock(return_value={"rows": [restored]})
            self.assertEqual(asyncio.run(webapp.api_app_edit_transactions(request)).status_code, 200)
            overrides = pipeline.read_toss_overrides()
            self.assertEqual(overrides, {"outside-current-page": {"단가": 50}})
            self.assertEqual(len(pipeline.apply_toss_overrides(data["toss_orders_raw"], overrides)), 2)

    def test_legacy_transaction_editor_reuses_safe_override_save(self):
        row = {"_src": "토스", "_key": "order-key", "_revision": "version", "_deleted": True,
               "일자": "2025-01-02", "티커": "TEST", "구분": "매수", "수량": 1, "단가": 100}
        request = SimpleNamespace(json=AsyncMock(return_value={"rows": [row]}))
        with patch.object(webapp, "_current_user", return_value="test"), \
                patch.object(webapp, "_save_transaction_edits", return_value="saved") as save:
            self.assertEqual(asyncio.run(webapp.edit_data_tx(request)), "saved")
        forwarded = save.call_args.args[1]["rows"][0]
        self.assertEqual(forwarded["source"], "toss")
        self.assertEqual(forwarded["sourceId"], "order-key")
        self.assertEqual(forwarded["revision"], "version")
        self.assertTrue(forwarded["deleted"])


class MergedTransactionPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(manual_holdings, "_DATA_DIR",
                                      ContextVar("test_data_dir", default=str(self.directory))))
        self.enterContext(patch.object(pipeline, "apply_credentials", return_value={}))
        self.enterContext(patch.object(pipeline, "toss_portfolio",
                                      return_value=(pipeline.empty_portfolio("test"), None)))
        self.original = {"orderId": "order-1", "symbol": "AAPL", "currency": "USD",
                         "broker": "토스증권", "account": "001", "side": "BUY",
                         "execution": {"filledQuantity": 3, "averageFilledPrice": 100,
                                       "filledAmount": 300, "filledAt": "2025-01-02T13:04:05+09:00"}}
        self.toss = self.enterContext(patch.object(pipeline, "toss_trades", side_effect=lambda *args:
            (pd.DataFrame(), copy.deepcopy([self.original, self.original]), 1400, {"AAPL": "Apple"})))
        self.enterContext(patch.object(pipeline, "load_manual_holdings", return_value=pd.DataFrame()))
        self.enterContext(patch.object(pipeline, "derive_holdings_from_tx", return_value=pd.DataFrame()))
        self.real_split_adjustments = pipeline.apply_split_adjustments
        self.split_adjustments = self.enterContext(patch.object(pipeline, "apply_split_adjustments", side_effect=lambda orders: orders))
        self.enterContext(patch.object(pipeline, "enrich_name_map", side_effect=lambda names, tickers: names))
        self.enterContext(patch.object(pipeline, "current_usdkrw", return_value=1400))
        self.enterContext(patch.object(pipeline, "_dividends", return_value=(0, 0, {}, [])))
        self.enterContext(patch.object(pipeline, "_dated_div_events", return_value=[]))
        self.enterContext(patch.object(pipeline, "compute_performance_summary", return_value=None))
        self.enterContext(patch.object(pipeline, "compute_alpha_beta", return_value=None))
        for name in ("build_transaction_detail", "build_holdings_breakdown", "build_stock_analytics"):
            self.enterContext(patch.object(pipeline, name, return_value=pd.DataFrame()))
        manual_holdings.write_transactions_csv(pd.DataFrame([{
            "증권사": "manual", "일자": "2025-01-01", "티커": "005930", "종목명": "삼성전자",
            "시장": "KOSPI", "구분": "매수", "수량": 2, "단가": 100, "통화": "KRW", "계좌": "002"}]))

    def test_load_persists_both_sources_without_reimporting_toss(self):
        original_csv = Path(manual_holdings.TX_CSV).read_bytes()
        for _ in range(2):
            data = pipeline.load_portfolio("test")
            saved = pd.read_csv(self.directory / "merged_transactions.csv", dtype=str, keep_default_na=False)
            self.assertEqual(len(saved), 2)
            self.assertEqual(len(data["combined_orders"]), 2)
            self.assertEqual(set(saved["출처"]), {"toss", "import"})
            self.assertEqual(set(saved["계좌"]), {"001", "002"})
            self.assertEqual(set(saved["티커"]), {"005930", "AAPL"})
            self.assertEqual(saved.loc[saved["출처"] == "toss", "거래ID"].iloc[0],
                             pipeline.toss_trade_key(self.original))
        self.assertEqual(Path(manual_holdings.TX_CSV).read_bytes(), original_csv)

    def test_saved_rows_include_edits_splits_and_original_source_identity(self):
        manual_holdings.write_toss_overrides({pipeline.toss_trade_key(self.original): {"단가": 110}})
        self.split_adjustments.side_effect = self.real_split_adjustments
        with patch.object(pipeline, "_split_map", return_value={pd.Timestamp("2025-02-01"): 2}):
            for _ in range(2):
                pipeline.load_portfolio("test")
                saved = pd.read_csv(self.directory / "merged_transactions.csv", dtype={"계좌": str, "티커": str})
                toss = saved[saved["출처"] == "toss"].iloc[0]
                self.assertEqual(toss["수량"], 6)
                self.assertEqual(toss["단가"], 55)
                self.assertEqual(toss["체결금액"], 330)
                self.assertTrue(toss["분할보정"])
                self.assertEqual(toss["체결시각"], self.original["execution"]["filledAt"])
                self.assertEqual(toss["거래ID"], pipeline.toss_trade_key(self.original))
                imported = saved[saved["출처"] == "import"].iloc[0]
                self.assertEqual(imported["종목명"], "삼성전자")
                self.assertEqual(imported["시장"], "KOSPI")

    def test_partial_toss_failure_keeps_previous_merged_file(self):
        pipeline.load_portfolio("test")
        saved_path = self.directory / "merged_transactions.csv"
        previous = saved_path.read_bytes()
        self.toss.side_effect = pm.OrderHistoryError("incomplete history")
        result = pipeline.load_portfolio("test")
        self.assertEqual(result["toss_error"], "incomplete history")
        self.assertEqual(saved_path.read_bytes(), previous)

    def test_deletion_and_new_executions_replace_the_derived_snapshot(self):
        pipeline.load_portfolio("test")
        manual_holdings.write_toss_overrides({pipeline.toss_trade_key(self.original): {"deleted": True}})
        self.toss.side_effect = lambda *args: (pd.DataFrame(), [self.original, dict(self.original, orderId="new")], 1400, {})
        pipeline.load_portfolio("test")
        saved = pd.read_csv(self.directory / "merged_transactions.csv")
        self.assertEqual(len(saved), 2)
        self.assertNotIn(pipeline.toss_trade_key(self.original), saved["거래ID"].tolist())
        self.assertIn(pipeline.toss_trade_key(dict(self.original, orderId="new")), saved["거래ID"].tolist())

    def test_failed_atomic_replace_keeps_previous_file_and_removes_temporary_file(self):
        pipeline.load_portfolio("test")
        previous = (self.directory / "merged_transactions.csv").read_bytes()
        with patch.object(manual_holdings.os, "replace", side_effect=OSError("test write failure")):
            with self.assertRaises(OSError):
                manual_holdings.write_merged_transactions_csv([])
        self.assertEqual((self.directory / "merged_transactions.csv").read_bytes(), previous)
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_context_local_writes_do_not_mix_users(self):
        for username in ("alice", "bob"):
            (self.directory / username).mkdir()
        alice, bob = Context(), Context()
        alice.run(manual_holdings.set_data_dir, self.directory / "alice")
        bob.run(manual_holdings.set_data_dir, self.directory / "bob")
        alice.run(pipeline.load_portfolio, "alice")
        self.toss.side_effect = lambda *args: (pd.DataFrame(), [dict(self.original, account="002")], 1400, {})
        bob.run(pipeline.load_portfolio, "bob")
        for username, account in (("alice", "001"), ("bob", "002")):
            saved = pd.read_csv(self.directory / username / "merged_transactions.csv", dtype=str)
            self.assertEqual(saved["계좌"].tolist(), [account])

    def test_distinct_no_id_fills_are_not_collapsed(self):
        original = {key: value for key, value in self.original.items() if key != "orderId"}
        self.toss.side_effect = lambda *args: (pd.DataFrame(), [original, original], 1400, {})
        pipeline.load_portfolio("test")
        saved = pd.read_csv(self.directory / "merged_transactions.csv")
        toss = saved[saved["출처"] == "toss"]
        self.assertEqual(len(toss), 2)
        self.assertEqual(toss["거래ID"].nunique(), 2)

    def test_subset_load_does_not_replace_full_snapshot(self):
        pipeline.load_portfolio("test")
        previous = (self.directory / "merged_transactions.csv").read_bytes()
        pipeline.load_portfolio("test", use_tx=False)
        self.assertEqual((self.directory / "merged_transactions.csv").read_bytes(), previous)

    def test_deleting_imports_removes_stale_merged_output(self):
        pipeline.load_portfolio("test")
        self.assertEqual(manual_holdings.delete_broker_imports("manual"), 1)
        self.assertFalse((self.directory / "merged_transactions.csv").exists())
        pipeline.load_portfolio("test")
        manual_holdings.clear_all_imports()
        self.assertFalse((self.directory / "merged_transactions.csv").exists())


class TossHistoryCompletenessTests(unittest.TestCase):
    def test_strict_fetch_rejects_partial_pages(self):
        first = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                json=lambda: {"result": {"orders": [{"orderId": "one"}],
                                                         "hasNext": True, "nextCursor": "next"}})
        with patch.object(pm.requests, "get", side_effect=[first, pm.requests.Timeout("private response")]), \
                patch.object(pm.time, "sleep"):
            with self.assertRaises(pm.OrderHistoryError) as result:
                pm.get_order_history("test-token", strict=True)
        self.assertNotIn("private response", str(result.exception))

    def test_strict_fetch_rejects_page_limit_and_malformed_response(self):
        for payload in ({"result": {"orders": [], "hasNext": True, "nextCursor": "next"}}, {"result": {}}):
            response = SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: payload)
            with patch.object(pm.requests, "get", return_value=response), patch.object(pm.time, "sleep"):
                with self.assertRaises(pm.OrderHistoryError):
                    pm.get_order_history("test-token", max_pages=1, strict=True)

    def test_strict_fetch_accepts_complete_empty_history(self):
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                   json=lambda: {"result": {"orders": [], "hasNext": False}})
        with patch.object(pm.requests, "get", return_value=response):
            self.assertEqual(pm.get_order_history("test-token", strict=True), [])


class DividendPaymentTests(unittest.TestCase):
    def setUp(self):
        self.fx = pd.Series([1000.0, 1200.0], index=pd.to_datetime(["2025-01-01", "2025-01-20"]))
        self.enterContext(patch.object(advanced_analytics, "get_usdkrw_history", return_value=self.fx))
        self.schedule = [{"exDate": "2025-01-10", "recordDate": "2025-01-13", "payDate": "2025-01-20", "amount": 1.0},
                         {"exDate": "2025-04-10", "recordDate": "2025-04-11", "payDate": "2025-04-21", "amount": 2.0}]
        self.enterContext(patch.object(advanced_analytics, "get_dividend_schedule", side_effect=lambda *args: self.schedule))
        self.orders = [{"symbol": "TEST", "currency": "USD", "broker": "test", "account": "001", "side": side,
                        "execution": {"filledQuantity": quantity, "averageFilledPrice": 100, "filledAt": date}}
                       for date, side, quantity in (("2025-01-02", "BUY", 10), ("2025-01-10", "BUY", 5), ("2025-01-15", "SELL", 12))]

    def test_pay_date_and_entitlement_date_are_separate(self):
        records = advanced_analytics.build_dividend_records(self.orders, as_of="2025-04-30")
        self.assertEqual(records[0]["shares"], 10)
        self.assertEqual(records[0]["payDate"], "2025-01-20")
        self.assertEqual(records[0]["recordDate"], "2025-01-13")
        self.assertEqual(records[0]["amountKrw"], 12000)
        self.assertEqual(records[1]["shares"], 3)
        earlier = advanced_analytics.build_dividend_records(self.orders, as_of="2025-01-19")
        self.assertFalse(earlier[0]["received"])
        self.assertIsNone(earlier[0]["amountKrw"])

    def test_actual_receipt_replaces_only_matching_dividend(self):
        receipt = {"증권사": "test", "계좌": "001", "티커": "TEST", "통화": "USD", "배당금": 8.5, "일자": "2025-01-21"}
        records = advanced_analytics.build_dividend_records(self.orders, actual_rows=[receipt, receipt], as_of="2025-04-30")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["source"], "actual")
        self.assertEqual(records[0]["amount"], 8.5)
        self.assertEqual(records[0]["payDate"], "2025-01-21")
        self.assertEqual(records[0]["exDate"], "2025-01-10")
        self.assertEqual(records[1]["source"], "estimated")
        self.assertEqual(records[1]["exDate"], "2025-04-10")
        receipt["일자"] = "2025-02-03"
        delayed = advanced_analytics.build_dividend_records(self.orders, actual_rows=[receipt], as_of="2025-04-30")
        self.assertEqual(len(delayed), 2)
        self.assertEqual(delayed[0]["source"], "actual")
        self.assertEqual(delayed[0]["payDate"], "2025-02-03")

    def test_missing_pay_dates_are_estimated_only_with_evidence(self):
        self.schedule[1]["payDate"] = None
        records = advanced_analytics.build_dividend_records(self.orders, as_of="2025-04-30")
        self.assertEqual(records[1]["dateSource"], "estimated")
        self.assertEqual(records[1]["payDate"], "2025-04-21")
        self.schedule[0]["payDate"] = None
        records = advanced_analytics.build_dividend_records(self.orders, as_of="2025-04-30")
        self.assertTrue(all(row["dateSource"] == "unknown" and not row["received"] for row in records))

    def test_unambiguous_actual_receipt_supplies_missing_payment_lag(self):
        for row in self.schedule:
            row["payDate"] = None
        receipt = {"증권사": "test", "계좌": "001", "티커": "TEST", "통화": "USD", "배당금": 8.5, "일자": "2025-01-20"}
        rows = advanced_analytics.build_dividend_records(self.orders, actual_rows=[receipt], as_of="2025-04-30")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["dateSource"], "estimated")
        self.assertEqual(rows[1]["payDate"], "2025-04-21")

    def test_actual_for_one_account_does_not_hide_anothers_dividend(self):
        orders = self.orders + [dict(self.orders[0], account="002")]
        receipt = {"증권사": "test", "계좌": "001", "티커": "TEST", "통화": "USD", "배당금": 8.5,
                   "일자": "2025-01-21", "배당락일": "2025-01-10"}
        records = advanced_analytics.build_dividend_records(orders, actual_rows=[receipt], as_of="2025-04-30")
        january = [row for row in records if row["payDate"].startswith("2025-01")]
        self.assertEqual(len(january), 2)
        self.assertEqual({row["account"] for row in january}, {"001", "002"})

    def test_provider_duplicate_ex_dates_are_not_paid_twice(self):
        self.schedule.append(dict(self.schedule[0]))
        records = advanced_analytics.build_dividend_records(self.orders, as_of="2025-04-30")
        self.assertEqual(len(records), 2)

    def test_distinct_actual_payment_ids_are_preserved(self):
        receipt = {"증권사": "test", "계좌": "001", "티커": "TEST", "통화": "USD",
                   "배당금": 5, "일자": "2025-01-20", "배당락일": "2025-01-10", "배당ID": "ordinary"}
        special = dict(receipt, 배당ID="special")
        records = advanced_analytics.build_dividend_records(self.orders, actual_rows=[receipt, special, receipt], as_of="2025-04-30")
        self.assertEqual(len([record for record in records if record["source"] == "actual"]), 2)
        self.assertEqual(len([record for record in records if record["source"] == "estimated"]), 1)

    def test_yahoo_calendar_is_joined_to_its_own_ex_date(self):
        history = pd.Series([1.0, 1.0, 2.0], index=pd.to_datetime(["2025-01-10", "2025-01-10", "2025-04-10"]))
        with patch.object(benchmark, "get_dividends", return_value=history), \
                patch.object(benchmark, "_memo", side_effect=lambda key, producer: producer()), \
                patch.object(benchmark.yf, "Ticker") as ticker:
            ticker.return_value.calendar = {"Ex-Dividend Date": "2025-04-10", "Dividend Date": "2025-04-21"}
            schedule = benchmark.get_dividend_schedule("TEST")
        self.assertEqual(len(schedule), 2)
        self.assertIsNone(schedule[0]["payDate"])
        self.assertEqual(schedule[1]["payDate"], pd.Timestamp("2025-04-21"))

    def test_pipeline_summary_and_cash_events_use_same_payment_records(self):
        receipt = pd.DataFrame([{"증권사": "test", "계좌": "001", "티커": "TEST", "통화": "USD",
                                  "배당금": 8.5, "일자": "2025-01-21"}])
        with patch.object(pipeline, "read_dividends_csv", return_value=receipt):
            native_krw, native_usd, totals, rows = pipeline._dividends(self.orders, 2000)
            events = pipeline._dated_div_events(self.orders, 2000)
        self.assertEqual(native_krw, 0)
        self.assertEqual(native_usd, 14.5)
        self.assertEqual(totals["TEST"], 17400)
        self.assertEqual([row["일자"] for row in rows], ["2025-01-21", "2025-04-21"])
        self.assertEqual(sum(event[1] for event in events), totals["TEST"])
        self.assertEqual(events[0][0], pd.Timestamp("2025-01-21"))
        with patch.object(performance, "get_usdkrw_history", return_value=self.fx), \
            patch.object(performance, "get_native_price_now", return_value=100):
            summary = performance.compute_performance_summary(self.orders, 2000, native_krw, native_usd,
                                       dividend_krw=sum(totals.values()))
        self.assertEqual(summary["div_krw"], sum(event[1] for event in events))

    def test_ambiguous_actual_date_does_not_double_count_uncertain_estimates(self):
        for row in self.schedule:
            row["payDate"] = None
        receipt = {"증권사": "test", "계좌": "001", "티커": "TEST", "통화": "USD", "배당금": 9, "일자": "2025-04-21"}
        rows = advanced_analytics.build_dividend_records(self.orders, actual_rows=[receipt], as_of="2025-04-30")
        self.assertEqual(sum(row["source"] == "actual" for row in rows), 1)
        self.assertTrue(all(not row["received"] for row in rows if row["source"] == "estimated"))
        self.assertTrue(all(row.get("matchingUncertain") for row in rows if row["source"] == "estimated"))

    def test_cash_ledger_does_not_book_before_payment(self):
        index = pd.date_range("2025-01-01", "2025-04-30")
        with patch.object(pipeline, "read_dividends_csv", return_value=pd.DataFrame()), \
                patch.object(pme, "get_history", return_value=pd.Series(100.0, index=index)), \
                patch.object(pme, "get_usdkrw_history", return_value=self.fx), \
                patch.object(pme, "get_dividends", return_value=pd.Series(dtype=float)):
            events = pipeline._dated_div_events(self.orders, 2000)
            frame = pme.build_asset_value_growth(self.orders, 2000, div_events=events)
            fixed = pme.build_asset_value_growth(self.orders, 2000, div_events=events, include_fx=False)
        self.assertEqual(frame.loc["2025-01-19", "누적배당금액"], 0)
        self.assertEqual(frame.loc["2025-01-20", "누적배당금액"], 12000)
        self.assertEqual(fixed.loc["2025-01-20", "누적배당금액"], 10000)

    def test_dividend_edit_roundtrip_keeps_event_identity_and_actual_date(self):
        record = advanced_analytics.build_dividend_records(self.orders, as_of="2025-04-30")[0]
        row = {"date": "2025-01-21", "ticker": "TEST", "name": "TEST", "currency": "USD", "amount": 8.5,
               "broker": "test", "account": "001", "exDate": record["exDate"], "recordDate": record["recordDate"],
               "eventId": record["eventId"]}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(manual_holdings, "DIV_CSV", str(Path(directory) / "dividends.csv")), \
                patch.object(webapp, "_current_user", return_value="test"), patch.object(pipeline, "apply_credentials"), \
                patch.object(webapp, "snapshot_imports"):
            request = SimpleNamespace(json=AsyncMock(return_value={"rows": [row, row]}))
            response = asyncio.run(webapp.api_app_edit_dividends(request))
            self.assertEqual(response.status_code, 200)
            saved = manual_holdings.read_dividends_csv().to_dict("records")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["계좌"], "001")
        self.assertEqual(saved[0]["배당ID"], record["eventId"])
        reconciled = advanced_analytics.build_dividend_records(self.orders, actual_rows=saved, as_of="2025-04-30")
        self.assertEqual(len(reconciled), 2)
        self.assertEqual(reconciled[0]["source"], "actual")
        self.assertEqual(reconciled[0]["amount"], 8.5)


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