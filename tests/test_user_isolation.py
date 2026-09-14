import os
import json
import io
import tempfile
import unittest
from contextvars import Context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pandas as pd

import auth
import ai_copilot
import benchmark
import manual_holdings
import pipeline
import webapp
import share_web
from fastapi.testclient import TestClient


class UserIsolationTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        data_directory = manual_holdings._DATA_DIR.get()
        prices = benchmark._PRICE_OVERRIDE.get()
        self.addCleanup(manual_holdings._DATA_DIR.set, data_directory)
        self.addCleanup(benchmark._PRICE_OVERRIDE.set, prices)
        for username in ("alice", "bob"):
            Path(self.directory, username).mkdir()
        for name in ("MANUAL_CSV", "TX_CSV", "DIV_CSV", "SPLIT_CSV", "TOSS_OVR_JSON",
                     "HOLDINGS_OVR_JSON", "TRASH_DIR"):
            self.enterContext(patch.object(manual_holdings, name, getattr(manual_holdings, name)))
        self.enterContext(patch.object(auth, "user_dir", side_effect=lambda user: str(Path(self.directory, user))))

    def test_interleaved_users_keep_their_own_transaction_files(self):
        with patch.object(auth, "load_credentials", return_value={}):
            alice = Context()
            bob = Context()
            alice.run(pipeline.apply_credentials, "alice")
            bob.run(pipeline.apply_credentials, "bob")
        alice.run(manual_holdings.write_transactions_csv,
                  pd.DataFrame([{"티커": "ALICE", "수량": 1, "단가": 100}]))
        bob.run(manual_holdings.write_transactions_csv,
                pd.DataFrame([{"티커": "BOB", "수량": 2, "단가": 200}]))
        self.assertEqual(alice.run(manual_holdings.read_transactions_csv)["티커"].tolist(), ["ALICE"])
        self.assertEqual(bob.run(manual_holdings.read_transactions_csv)["티커"].tolist(), ["BOB"])

    def test_user_credentials_never_mutate_shared_environment(self):
        server = {"GEMINI_API_KEY": "shared-test-key", "TOSS_CLIENT_ID": "owner-test-id",
                  "TOSS_CLIENT_SECRET": "owner-test-secret", "TOSS_ACCOUNT_NO": "1"}
        alice = {"GEMINI_API_KEY": "ignored-user-key", "TOSS_CLIENT_ID": "alice-test-id",
                 "TOSS_CLIENT_SECRET": "alice-test-secret", "TOSS_ACCOUNT_NO": "2"}
        with patch.dict(os.environ, server), \
                patch.object(auth, "load_credentials", side_effect=[alice, {}]):
            self.assertEqual(pipeline.apply_credentials("alice"), alice)
            self.assertEqual(pipeline.apply_credentials("bob"), {})
            self.assertEqual({key: os.environ.get(key) for key in server}, server)

    def test_shared_ai_never_falls_back_to_operators_toss_credentials(self):
        with patch.dict(os.environ, {"TOSS_CLIENT_ID": "owner-test-id", "TOSS_CLIENT_SECRET": "owner-test-secret"}), \
                patch.object(ai_copilot, "_SHARED_GEMINI_KEY", "shared-test-key"), \
                patch.object(ai_copilot.genai, "configure") as configure, \
                patch.object(ai_copilot.genai, "GenerativeModel") as model, \
                patch.object(ai_copilot, "get_access_token") as token, \
                patch.object(ai_copilot, "_build_toss_tools", return_value=[]) as tools:
            model.return_value.start_chat.return_value.send_message.return_value.text = "OK"
            self.assertEqual(ai_copilot.chat_with_portfolio("test", [], {}), "OK")
            token.assert_not_called()
            tools.assert_not_called()
            self.assertEqual(configure.call_args.kwargs["api_key"], "shared-test-key")
            token.return_value = "alice-test-token"
            ai_copilot.chat_with_portfolio("test", [], {}, toss_credentials={
                "TOSS_CLIENT_ID": "alice-test-id", "TOSS_CLIENT_SECRET": "alice-test-secret", "TOSS_ACCOUNT_NO": "2"})
            token.assert_called_once_with("alice-test-id", "alice-test-secret")
            tools.assert_called_once_with("alice-test-token", "2")

    def test_edited_prices_are_context_local(self):
        alice = Context()
        bob = Context()
        alice.run(benchmark.set_price_overrides, {"TEST": 100}, True)
        bob.run(benchmark.set_price_overrides, {"TEST": 200}, True)
        self.assertEqual(alice.run(benchmark.get_native_price_now, "TEST"), 100)
        self.assertEqual(bob.run(benchmark.get_native_price_now, "TEST"), 200)

    def test_snapshot_restore_rejects_other_users_absolute_path(self):
        alice = Context()
        bob = Context()
        alice.run(manual_holdings.set_data_dir, str(Path(self.directory, "alice")))
        bob.run(manual_holdings.set_data_dir, str(Path(self.directory, "bob")))
        bob.run(manual_holdings.write_transactions_csv, pd.DataFrame([{"티커": "BOB", "수량": 1, "단가": 100}]))
        for snapshot in (str(Path(self.directory, "bob")), "../../bob", "..\\..\\bob"):
            self.assertEqual(alice.run(manual_holdings.restore_snapshot, snapshot), 0)
        self.assertTrue(alice.run(manual_holdings.read_transactions_csv).empty)


class AccountStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(auth, "BASE_DIR", self.directory))
        self.enterContext(patch.object(auth, "USERS_FILE", str(Path(self.directory, "users.json"))))
        self.enterContext(patch.object(auth, "SESSIONS_FILE", str(Path(self.directory, "sessions.json"))))

    def test_invalid_usernames_cannot_share_or_escape_directories(self):
        for username in ("..", ".", "../alice", "alice/bob", "alice\\bob", "CON", "alice.", "users.json", "SESSIONS.JSON"):
            with self.subTest(username=username):
                self.assertFalse(auth.register_user(username, "test-password")[0])
                with self.assertRaises(ValueError):
                    auth.user_dir(username)
        self.assertTrue(auth.register_user("alice", "test-password")[0])
        self.assertFalse(auth.register_user("ALICE", "test-password")[0])

    def test_concurrent_registrations_preserve_every_account(self):
        names = [f"user{number}" for number in range(8)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda name: auth.register_user(name, "test-password"), names))
        self.assertTrue(all(result[0] for result in results))
        self.assertEqual(set(auth._load_users()), set(names))

    def test_saved_toss_keys_and_disconnect_are_user_specific(self):
        for user in ("alice", "bob"):
            auth.save_credentials(user, {"TOSS_CLIENT_ID": user, "TOSS_CLIENT_SECRET": f"{user}-test-secret"})
        auth.remove_toss_credentials("alice")
        self.assertFalse(auth.has_toss_credentials("alice"))
        self.assertEqual(auth.load_credentials("bob")["TOSS_CLIENT_SECRET"], "bob-test-secret")


class UserConnectionApiTests(unittest.TestCase):
    def setUp(self):
        AccountStorageTests.setUp(self)
        webapp._USER_REQUEST_LOCKS.clear()
        webapp._REQUEST_LIMITS.clear()
        webapp._IMPORT_DRAFTS.clear()
        self.addCleanup(webapp._USER_REQUEST_LOCKS.clear)
        self.addCleanup(webapp._REQUEST_LIMITS.clear)
        self.addCleanup(webapp._IMPORT_DRAFTS.clear)
        self.enterContext(patch.object(ai_copilot, "_SHARED_GEMINI_KEY", "shared-test-key"))
        self.alice = TestClient(webapp.app)
        self.bob = TestClient(webapp.app)
        for client, username in ((self.alice, "alice"), (self.bob, "bob")):
            response = client.post("/api/app/register", json={"username": username, "password": "test-password"})
            self.assertEqual(response.status_code, 200)

    def test_connections_use_only_current_users_credentials_and_hide_secrets(self):
        body = {"clientId": "alice-test-id", "clientSecret": "alice-test-secret", "account": "2"}
        with patch.object(pipeline, "get_access_token", return_value="alice-test-token") as token, \
                patch.object(pipeline, "get_holdings", return_value={"result": {"items": []}}) as holdings:
            response = self.alice.post("/api/app/connections/toss", json=body)
            self.assertEqual(response.status_code, 200)
            token.assert_called_once_with("alice-test-id", "alice-test-secret")
            holdings.assert_called_once_with("alice-test-token", "2")
        alice_status = self.alice.get("/api/app/connections")
        bob_status = self.bob.get("/api/app/connections")
        self.assertTrue(alice_status.json()["tossConfigured"])
        self.assertFalse(bob_status.json()["tossConfigured"])
        self.assertTrue(bob_status.json()["geminiAvailable"])
        for response in (alice_status, bob_status):
            for secret in ("alice-test-secret", "alice-test-id", "shared-test-key", "alice-test-token"):
                self.assertNotIn(secret, response.text)
        self.bob.delete("/api/app/connections/toss")
        self.assertTrue(auth.has_toss_credentials("alice"))
        self.alice.delete("/api/app/connections/toss")
        self.assertFalse(auth.has_toss_credentials("alice"))

    def test_bad_key_cannot_replace_existing_key(self):
        auth.save_credentials("alice", {"TOSS_CLIENT_ID": "valid-id", "TOSS_CLIENT_SECRET": "valid-secret"})
        with patch.object(pipeline, "get_access_token", return_value=None):
            response = self.alice.post("/api/app/connections/toss", json={"clientId": "bad-id", "clientSecret": "bad-secret"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(auth.load_credentials("alice")["TOSS_CLIENT_SECRET"], "valid-secret")

    def test_unauthenticated_connections_are_rejected(self):
        client = TestClient(webapp.app)
        self.assertEqual(client.get("/api/app/connections").status_code, 401)
        self.assertEqual(client.post("/api/app/connections/toss", json={}).status_code, 401)
        self.assertEqual(client.delete("/api/app/connections/toss").status_code, 401)

    def parsed_trade(self, ticker):
        return [{"증권사": "model-broker", "일자": "2025-01-01", "티커": ticker, "종목명": ticker,
                 "시장": "US", "구분": "매수", "수량": 1, "단가": 100, "통화": "USD", "계좌": "001"}]

    def preview(self, client, ticker, consent="true"):
        with patch.object(ai_copilot, "parse_brokerage_full_transactions", return_value=(self.parsed_trade(ticker), None)), \
                patch.object(ai_copilot, "parse_brokerage_dividends", return_value=([], None)):
            return client.post("/api/app/import", data={"broker": "test-broker", "consent": consent},
                               files={"files": ("trades.csv", b"date,ticker\n2025-01-01,TEST", "text/csv")})

    def test_private_import_requires_consent_preview_and_owner_confirmation(self):
        self.assertEqual(self.preview(self.alice, "ALICE", consent="false").status_code, 400)
        alice_draft = self.preview(self.alice, "ALICE")
        bob_draft = self.preview(self.bob, "BOB")
        self.assertEqual(alice_draft.status_code, 200)
        self.assertFalse(Path(self.directory, "alice", "manual_transactions.csv").exists())
        stolen = self.bob.post("/api/app/import/confirm", json={"draftId": alice_draft.json()["draftId"]})
        self.assertEqual(stolen.status_code, 409)
        for client, user, draft in ((self.alice, "alice", alice_draft), (self.bob, "bob", bob_draft)):
            response = client.post("/api/app/import/confirm", json={"draftId": draft.json()["draftId"]})
            self.assertEqual(response.status_code, 200)
            context = Context()
            context.run(pipeline.apply_credentials, user)
            self.assertEqual(context.run(manual_holdings.read_transactions_csv)["티커"].tolist(), [user.upper()])
        repeated = self.preview(self.alice, "ALICE")
        saved = self.alice.post("/api/app/import/confirm", json={"draftId": repeated.json()["draftId"]})
        self.assertEqual(saved.json()["transactions"], 0)

    def test_long_file_tail_is_not_truncated(self):
        text = "date,ticker\n" + "2025-01-01,TEST\n" * 1500 + "LAST_ROW\n"
        chunks = list(webapp._import_chunks(text))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 12000 for chunk in chunks))
        self.assertIn("LAST_ROW", chunks[-1])

    def test_invalid_ai_output_is_rejected_without_a_draft(self):
        with patch.object(ai_copilot, "parse_brokerage_full_transactions", return_value=([{"unexpected": "value"}], None)), \
                patch.object(ai_copilot, "parse_brokerage_dividends", return_value=([], None)):
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                                       files={"files": ("trades.csv", b"TEST", "text/csv")})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("alice", webapp._IMPORT_DRAFTS)

    def test_import_reports_every_unmapped_row_and_its_source(self):
        trades = [dict(self.parsed_trade("")[0], 종목명="Unknown fund"),
                  dict(self.parsed_trade("AAPL")[0], 일자="bad-date", 수량=-1)]
        dividends = [{"일자": "2025-01-02", "티커": "", "종목명": "Unknown dividend",
                      "통화": "USD", "배당금": 5, "private_field": "not-for-display"}]
        with patch.object(ai_copilot, "parse_brokerage_full_transactions", return_value=(trades, None)), \
                patch.object(ai_copilot, "parse_brokerage_dividends", return_value=(dividends, None)):
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                                       files={"files": ("MyTrades.CSV", b"TEST", "text/csv")})
        self.assertEqual(response.status_code, 422)
        issues = response.json()["issues"]
        self.assertEqual(len(issues), 3)
        self.assertEqual([issue["name"] for issue in issues], ["Unknown fund", "AAPL", "Unknown dividend"])
        self.assertEqual([issue["responseRow"] for issue in issues], [1, 2, 1])
        self.assertEqual([issue["kind"] for issue in issues], ["transaction", "transaction", "dividend"])
        self.assertTrue(all(issue["source"]["file"] == "MyTrades.CSV" for issue in issues))
        self.assertIn("티커", issues[0]["fields"])
        self.assertEqual(set(issues[1]["fields"]), {"일자", "수량"})
        self.assertTrue(all(issue["reasons"] for issue in issues))
        self.assertNotIn("not-for-display", response.text)
        self.assertNotIn("alice", webapp._IMPORT_DRAFTS)
        self.assertFalse(Path(self.directory, "alice", "manual_transactions.csv").exists())

    def test_datasources_lists_unmapped_symbols_instead_of_only_a_count(self):
        data = {"detail_df": pd.DataFrame(), "dividends_rows": [],
                "name_map": {"AAPL": "Apple", "UNKNOWN": "UNKNOWN"},
                "breakdown": pd.DataFrame([{"티커": "AAPL"}, {"티커": "UNKNOWN"}])}
        with patch.object(webapp, "get_portfolio", return_value=data):
            response = self.alice.get("/api/app/datasources")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["unmappedCount"], len(payload["unmappedTickers"]))
        self.assertEqual([row["ticker"] for row in payload["unmappedTickers"]], ["UNKNOWN"])
        self.assertTrue(payload["unmappedTickers"][0]["reason"])

    def test_unmapped_details_preserve_workbook_sheets_and_chunk_numbers(self):
        content = io.BytesIO()
        with pd.ExcelWriter(content, engine="openpyxl") as writer:
            pd.DataFrame({"종목명": ["Unknown investment fund"] * 1200}).to_excel(writer, sheet_name="매매", index=False)
            pd.DataFrame({"종목명": ["Unknown distribution"]}).to_excel(writer, sheet_name="분배", index=False)
        with patch.object(ai_copilot, "parse_brokerage_full_transactions", return_value=(self.parsed_trade(""), None)), \
                patch.object(ai_copilot, "parse_brokerage_dividends", return_value=([], None)):
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                files=[("files", ("Report.XLSX", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
                       ("files", ("Second.CSV", b"TEST", "text/csv"))])
        self.assertEqual(response.status_code, 422)
        issues = response.json()["issues"]
        workbook_issues = [issue for issue in issues if issue["source"]["file"] == "Report.XLSX"]
        self.assertEqual({issue["source"]["sheet"] for issue in workbook_issues}, {"매매", "분배"})
        self.assertGreater(max(issue["source"]["chunk"] for issue in workbook_issues), 1)
        self.assertEqual(issues[-1]["source"], {"file": "Second.CSV", "sheet": "", "chunk": 1})
        self.assertTrue(all(issue["responseRow"] == 1 for issue in issues))
        self.assertEqual(response.json()["issueCount"], len(issues))

    def test_unmapped_details_are_not_limited_to_the_thirty_row_preview(self):
        trades = [dict(self.parsed_trade("")[0], 종목명=f"Unknown {number}") for number in range(40)]
        with patch.object(ai_copilot, "parse_brokerage_full_transactions", return_value=(trades, None)), \
                patch.object(ai_copilot, "parse_brokerage_dividends", return_value=([], None)):
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                                       files={"files": ("Trades.CSV", b"TEST", "text/csv")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["issueCount"], 40)
        self.assertEqual(response.json()["issues"][-1]["name"], "Unknown 39")
        retry = self.preview(self.alice, "AAPL")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json().get("issues", []), [])

    def test_invalid_new_import_discards_only_its_owners_previous_draft(self):
        previous = self.preview(self.alice, "AAPL").json()["draftId"]
        bob = self.preview(self.bob, "MSFT").json()["draftId"]
        self.assertEqual(self.preview(self.alice, "").status_code, 422)
        self.assertNotIn("alice", webapp._IMPORT_DRAFTS)
        self.assertEqual(webapp._IMPORT_DRAFTS["bob"]["id"], bob)
        response = self.alice.post("/api/app/import/confirm", json={"draftId": previous})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Path(self.directory, "alice", "manual_transactions.csv").exists())

    def test_complete_and_empty_mapping_lists_have_no_unmapped_items(self):
        for symbols in ([], ["AAPL"]):
            data = {"detail_df": pd.DataFrame(), "dividends_rows": [], "name_map": {"AAPL": "Apple"},
                    "breakdown": pd.DataFrame({"티커": symbols})}
            with self.subTest(symbols=symbols), patch.object(webapp, "get_portfolio", return_value=data):
                payload = self.alice.get("/api/app/datasources").json()
                self.assertEqual(payload["unmappedCount"], 0)
                self.assertEqual(payload["unmappedTickers"], [])
                self.assertEqual(payload["mappedCount"], len(symbols))

    def test_shared_ai_quota_is_user_scoped_and_enforced(self):
        with patch.dict(os.environ, {"PFM_AI_REQUESTS_PER_HOUR": "1"}):
            self.assertEqual(self.preview(self.alice, "ALICE").status_code, 200)
            self.assertEqual(self.preview(self.alice, "ALICE").status_code, 429)
            self.assertEqual(self.preview(self.bob, "BOB").status_code, 200)

    def test_concurrent_http_imports_keep_worker_contexts_separate(self):
        barrier = Barrier(2)

        def parse(uploads, broker):
            before = os.fspath(manual_holdings.TX_CSV)
            barrier.wait(timeout=5)
            self.assertEqual(os.fspath(manual_holdings.TX_CSV), before)
            username = Path(before).parent.name
            return self.parsed_trade(username.upper()), []

        def upload(client):
            return client.post("/api/app/import", data={"consent": "true"},
                               files={"files": ("trades.csv", b"TEST", "text/csv")})

        with patch.object(webapp, "_parse_import_files", side_effect=parse), ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(upload, (self.alice, self.bob)))
        for response, username in zip(responses, ("alice", "bob")):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["txPreview"][0]["티커"], username.upper())
            self.assertEqual(webapp._IMPORT_DRAFTS[username]["id"], response.json()["draftId"])

    def test_shared_server_blocks_legacy_import_and_cross_origin_updates(self):
        with patch.object(webapp, "_SHARE_MODE", True):
            self.assertEqual(self.alice.post("/import", data={"pasted": "TEST"}).status_code, 404)
            self.assertEqual(self.alice.post("/settings", data={}).status_code, 404)
            self.assertEqual(self.alice.delete("/api/app/connections/toss", headers={"Origin": "https://other.example"}).status_code, 403)


class SharedServerConfigTests(unittest.TestCase):
    def test_shared_storage_and_sessions_are_separate_and_stable(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "WEB_SECRET_KEY": "owner-test-secret", "TOSS_CLIENT_ID": "owner-test-id",
                "TOSS_CLIENT_SECRET": "owner-test-secret", "GEMINI_API_KEY": "shared-test-key"}):
            root = share_web.configure_test_server(directory, https=True)
            first_key = os.environ["WEB_SECRET_KEY"]
            self.assertNotEqual(first_key, "owner-test-secret")
            self.assertEqual(os.environ["PFM_DATA_DIR"], str(root))
            self.assertEqual(os.environ["WEB_HTTPS_ONLY"], "1")
            self.assertNotIn("TOSS_CLIENT_ID", os.environ)
            self.assertEqual(os.environ["GEMINI_API_KEY"], "shared-test-key")
            share_web.configure_test_server(directory, https=True)
            self.assertEqual(os.environ["WEB_SECRET_KEY"], first_key)
            self.assertFalse(Path(directory, "1234").exists())

    def test_cannot_publish_existing_owner_storage(self):
        owner_directory = Path(share_web.__file__).resolve().parent / "user_data"
        for directory in (owner_directory, owner_directory / "1234", owner_directory.parent):
            with self.subTest(directory=str(directory)), self.assertRaises(ValueError):
                share_web.configure_test_server(directory, https=True)


if __name__ == "__main__":
    unittest.main()