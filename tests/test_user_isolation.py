import os
import json
import io
import tempfile
import unittest
from contextvars import Context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
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

    def test_provider_failure_reports_safe_reason_location_and_request_id(self):
        from google.api_core.exceptions import ResourceExhausted

        private_text = "private-api-key-and-transaction-content"
        failure = ResourceExhausted("Quota exceeded: " + private_text)
        with patch.object(ai_copilot.genai, "configure"), \
            patch.object(ai_copilot, "_generate_with_fallback", return_value=(None, failure)), \
            self.assertLogs("uvicorn.error", level="WARNING") as captured:
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                                       files={"files": ("MyTrades.CSV", b"TEST", "text/csv")})
        self.assertEqual(response.status_code, 429)
        payload = response.json()
        self.assertEqual(payload["failure"]["code"], "GEMINI_QUOTA")
        self.assertEqual(payload["failure"]["stage"], "transactions")
        self.assertEqual(payload["failure"]["source"]["file"], "MyTrades.CSV")
        self.assertEqual(payload["failure"]["source"]["chunk"], 1)
        self.assertTrue(payload["failure"]["action"])
        self.assertGreaterEqual(payload["failure"]["elapsedSeconds"], 0)
        self.assertEqual(payload["failure"]["requestId"], response.headers["X-Request-ID"])
        self.assertNotIn(private_text, response.text)
        self.assertFalse(payload["saved"])
        self.assertNotIn("alice", webapp._IMPORT_DRAFTS)
        log = "\n".join(captured.output)
        self.assertIn(payload["failure"]["requestId"], log)
        self.assertIn("GEMINI_QUOTA", log)
        for private_value in (private_text, "MyTrades.CSV", "shared-test-key", "alice"):
            self.assertNotIn(private_value, log)

    def test_invalid_gemini_json_is_not_reported_as_missing_trades(self):
        reply = SimpleNamespace(text='[{"private": "raw-response-content",', candidates=[], prompt_feedback=None)
        with patch.object(ai_copilot.genai, "configure"), \
                patch.object(ai_copilot, "_generate_with_fallback", return_value=(reply, None)):
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                                       files={"files": ("Trades.CSV", b"TEST", "text/csv")})
        self.assertEqual(response.json()["failure"]["code"], "GEMINI_INVALID_JSON")
        self.assertNotIn("raw-response-content", response.text)
        self.assertNotIn("alice", webapp._IMPORT_DRAFTS)

    def test_provider_failure_categories_have_safe_messages(self):
        from google.api_core import exceptions

        cases = ((exceptions.InvalidArgument("API key not valid"), "GEMINI_AUTH", 503),
                 (exceptions.PermissionDenied("private-secret"), "GEMINI_AUTH", 503),
                 (exceptions.Unauthenticated("private-secret"), "GEMINI_AUTH", 503),
                 (exceptions.DeadlineExceeded("private-secret"), "GEMINI_TIMEOUT", 504),
                 (TimeoutError("private-secret"), "GEMINI_TIMEOUT", 504),
                 (exceptions.ServiceUnavailable("private-secret"), "GEMINI_UNAVAILABLE", 503),
                 (exceptions.InternalServerError("private-secret"), "GEMINI_UNAVAILABLE", 503),
                 (exceptions.NotFound("private-secret"), "GEMINI_MODEL_UNAVAILABLE", 503),
                 (exceptions.InvalidArgument("input too long"), "GEMINI_INPUT_LIMIT", 422),
                 (exceptions.InvalidArgument("private-secret"), "GEMINI_INVALID_REQUEST", 422),
                 (RuntimeError("could not generate private-secret"), "GEMINI_UNKNOWN", 502))
        for provider_error, code, status in cases:
            with self.subTest(code=code, exception=type(provider_error).__name__), \
                    patch.object(ai_copilot.genai, "configure"), \
                    patch.object(ai_copilot, "_generate_with_fallback", return_value=(None, provider_error)):
                response = self.alice.post("/api/app/import", data={"consent": "true"},
                                           files={"files": ("Trades.CSV", b"TEST", "text/csv")})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["failure"]["code"], code)
                self.assertTrue(response.json()["failure"]["action"])
                self.assertNotIn("private-secret", response.text)
                self.assertFalse(response.json()["saved"])
                self.assertNotIn("alice", webapp._IMPORT_DRAFTS)

    def test_response_stop_reasons_and_invalid_shapes_are_distinct(self):
        from google.ai.generativelanguage import Candidate, GenerateContentResponse
        from google.generativeai.types import GenerateContentResponse as Response

        cases = [(Response.from_response(GenerateContentResponse(candidates=[Candidate(finish_reason=reason)])), code)
                 for reason, code in ((2, "GEMINI_OUTPUT_LIMIT"), (3, "GEMINI_BLOCKED"),
                                      (4, "GEMINI_BLOCKED"), (5, "GEMINI_INCOMPLETE_RESPONSE"))]
        cases.append((Response.from_response(GenerateContentResponse(prompt_feedback={"block_reason": 1})), "GEMINI_BLOCKED"))
        cases.extend((SimpleNamespace(text=text, candidates=[], prompt_feedback=None), code)
                     for text, code in (("", "GEMINI_EMPTY_RESPONSE"), ("{", "GEMINI_INVALID_JSON"),
                                        ("{}", "GEMINI_INVALID_RESPONSE"), ("null", "GEMINI_INVALID_RESPONSE"),
                                        ('{"result": {}}', "GEMINI_INVALID_RESPONSE")))
        for reply, code in cases:
            with self.subTest(code=code), patch.object(ai_copilot.genai, "configure"), \
                    patch.object(ai_copilot, "_generate_with_fallback", return_value=(reply, None)):
                response = self.alice.post("/api/app/import", data={"consent": "true"},
                                           files={"files": ("Trades.CSV", b"TEST", "text/csv")})
                self.assertEqual(response.json()["failure"]["code"], code)
                self.assertFalse(response.json()["saved"])
                self.assertNotIn("alice", webapp._IMPORT_DRAFTS)

    def test_dividend_failure_reports_later_chunk_without_partial_save(self):
        content = io.BytesIO()
        with pd.ExcelWriter(content, engine="openpyxl") as writer:
            pd.DataFrame({"ticker": ["AAPL"]}).to_excel(writer, sheet_name="Trades", index=False)
        trade = SimpleNamespace(text=json.dumps(self.parsed_trade("AAPL")), candidates=[], prompt_feedback=None)
        empty = SimpleNamespace(text='```json\n{"dividends": []}\n```', candidates=[], prompt_feedback=None)
        truncated = SimpleNamespace(text="private-response", candidates=[SimpleNamespace(finish_reason=2)], prompt_feedback=None)
        with patch.object(ai_copilot.genai, "configure"), \
                patch.object(webapp, "_import_chunks", return_value=iter(["first", "second"])), \
                patch.object(ai_copilot, "_generate_with_fallback", side_effect=[(trade, None), (empty, None), (trade, None), (truncated, None)]):
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                files={"files": ("Report.XLSX", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        failure = response.json()["failure"]
        self.assertEqual(failure["code"], "GEMINI_OUTPUT_LIMIT")
        self.assertEqual(failure["stage"], "dividends")
        self.assertEqual(failure["source"], {"file": "Report.XLSX", "sheet": "Trades", "chunk": 2})
        self.assertNotIn("private-response", response.text)
        self.assertNotIn("alice", webapp._IMPORT_DRAFTS)
        self.assertFalse(Path(self.directory, "alice", "manual_transactions.csv").exists())

    def test_valid_empty_dividend_response_allows_preview_and_retry(self):
        trade = SimpleNamespace(text=json.dumps({"transactions": self.parsed_trade("AAPL")}), candidates=[], prompt_feedback=None)
        empty = SimpleNamespace(text='{"result": []}', candidates=[], prompt_feedback=None)
        invalid = SimpleNamespace(text="{", candidates=[], prompt_feedback=None)
        with patch.object(ai_copilot.genai, "configure"), \
                patch.object(ai_copilot, "_generate_with_fallback", side_effect=[(invalid, None), (trade, None), (empty, None)]):
            for status in (502, 200):
                response = self.alice.post("/api/app/import", data={"consent": "true"},
                                           files={"files": ("Trades.CSV", b"TEST", "text/csv")})
                self.assertEqual(response.status_code, status)
                self.assertFalse(response.json()["saved"])
        self.assertEqual(response.json()["transactions"], 1)
        self.assertEqual(response.json()["dividends"], 0)
        self.assertNotIn("failure", response.json())
        self.assertFalse(Path(self.directory, "alice", "manual_transactions.csv").exists())

    def test_fallback_does_not_hide_quota_behind_a_missing_model(self):
        from google.api_core.exceptions import NotFound, ResourceExhausted

        quota = ResourceExhausted("private-quota-details")
        with patch.object(ai_copilot, "MODEL_CHAIN", ["gemini-quota-test", "gemini-missing-test"]), \
                patch.object(ai_copilot.genai, "configure"), patch.object(ai_copilot.time, "sleep"), \
                patch.object(ai_copilot.genai, "GenerativeModel", side_effect=[quota, quota, NotFound("private-model-details")]), \
                self.assertLogs("uvicorn.error", level="WARNING") as captured:
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                                       files={"files": ("Trades.CSV", b"TEST", "text/csv")})
        self.assertEqual(response.status_code, 429)
        failure = response.json()["failure"]
        self.assertEqual(failure["code"], "GEMINI_QUOTA")
        self.assertEqual([attempt["code"] for attempt in failure["attempts"]],
                         ["GEMINI_QUOTA", "GEMINI_QUOTA", "GEMINI_MODEL_UNAVAILABLE"])
        self.assertEqual([attempt["providerStatus"] for attempt in failure["attempts"]], [429, 429, 404])
        self.assertIn("gemini-missing-test", "\n".join(captured.output))
        for private_value in ("private-quota-details", "private-model-details", "Trades.CSV", "shared-test-key"):
            self.assertNotIn(private_value, "\n".join(captured.output))
        self.assertNotIn("private-", response.text)

    def test_model_fallback_success_preserves_the_preview_contract(self):
        from google.api_core.exceptions import NotFound

        trade = SimpleNamespace(text=json.dumps(self.parsed_trade("AAPL")), candidates=[], prompt_feedback=None)
        empty = SimpleNamespace(text="[]", candidates=[], prompt_feedback=None)
        with patch.object(ai_copilot, "MODEL_CHAIN", ["gemini-first-test", "gemini-next-test"]), \
                patch.object(ai_copilot.genai, "configure"), patch.object(ai_copilot.genai, "GenerativeModel") as model:
            model.return_value.generate_content.side_effect = [NotFound("private-model-details"), trade, empty]
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                                       files={"files": ("Trades.CSV", b"TEST", "text/csv")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transactions"], 1)
        self.assertEqual(response.json()["dividends"], 0)
        self.assertFalse(response.json()["saved"])
        self.assertNotIn("failure", response.json())
        self.assertNotIn("private-", response.text)

    def test_unreadable_file_reports_source_without_calling_gemini(self):
        with patch.object(ai_copilot, "_generate_with_fallback") as generate:
            response = self.alice.post("/api/app/import", data={"consent": "true"},
                files={"files": ("Broken.XLSX", b"not-an-excel-file", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        generate.assert_not_called()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["failure"]["code"], "FILE_READ_FAILED")
        self.assertEqual(response.json()["failure"]["source"]["file"], "Broken.XLSX")
        self.assertFalse(response.json()["saved"])
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
            rejected = self.preview(self.alice, "ALICE")
            self.assertEqual(rejected.status_code, 429)
            self.assertEqual(rejected.json()["failure"]["code"], "AI_REQUEST_LIMIT")
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