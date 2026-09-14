# User Testing

This mode runs the real application with registration, each user's imports and
optional personal Toss credentials. It does not use the fixture application or
copy the operator's existing accounts or portfolio.

## Before Sharing

- Rotate credentials that were previously tracked in `.env`. Removing the file
  from Git does not remove old revisions or revoke exposed keys. Keep replacement
  values in the local `.env` only; never send them through chat or to testers.
- Build the React app in `Asset Portfolio Performance Analysis` before starting.
- Use the server's `GEMINI_API_KEY`. Per-user Gemini credentials are not selected.
- Install `cloudflared` for an external HTTPS link. No tunnel starts by default.

## Start and Stop

From the repository on Windows:

```powershell
.\run_test_web.bat
```

This starts the local-only app at `http://127.0.0.1:8001/app/`. The existing server
on port 8000 is not stopped. Use `--port 8002` if 8001 is occupied.

After rotating any previously exposed credentials, stop the local test server
with Ctrl+C and enable external sharing:

```powershell
.\run_test_web.bat --share
```

Send the printed `https://...trycloudflare.com` URL with `/app/` appended. The PC,
application and tunnel must stay running. Ctrl+C stops the app and its tunnel.
The public URL normally changes when the tunnel restarts. Quick Tunnels are for
temporary tests, not an uptime-guaranteed production service.

The server uses a different session cookie and persistent signing key from the
operator's app. Shared sessions require HTTPS. Local-only mode permits HTTP on
loopback; do not expose that mode through a separate public proxy.

## Tester Workflow

1. Register a unique account. New passwords require 8-256 characters. Usernames
   use 1-64 ASCII letters, digits, dots, underscores or hyphens, starting with a
   letter or digit. Reserved paths and case-insensitive duplicates are rejected.
2. Import CSV, TXT, Excel or text-based PDF files, or connect a personal Toss key.
3. Consent to sending the uploaded transaction content to Google Gemini. Remove
   API keys, passwords and unnecessary personal identifiers from files first.
4. Review the parsed transactions and dividends, then select Save Confirmation.
   No transaction files change during preview. Drafts expire after 15 minutes and
   cannot be confirmed by a different account. Cancel leaves existing data intact.
5. Verify/edit the imported rows and continue to portfolio analysis.

Transaction verification also includes Toss API fills. Source labels distinguish
Toss from imports. Toss changes are stored as local overrides, not sent to the
broker; exclusion and original restoration apply after saving. Sync preserves the
overrides and new orders. Reload when a save reports that the original or another
editor changed. No-ID executions use a fallback fingerprint, so provider changes
to those original fields may require manual reconciliation.

Dividend verification lists payment date (announced/estimated/unknown), ex-date,
record date when available, and entitled shares by account. Actual records take
priority for the matching event, not the symbol's entire history. Review actual
payment dates and net receipts before converting estimates. Unknown-date, future
and ambiguous-match estimates are not counted as received. The methodology document
describes Yahoo's limited historical payment dates and settlement assumptions.

Toss connection accepts the tester's Client ID, Client Secret and account ID. It
checks access before saving, never returns the credentials to the browser, and
can be disconnected from the same screen. The tester must register the displayed
server outbound IP in their own Toss developer console, not their home IP or the
Cloudflare edge IP. If the operator's IP changes, restart and update allowlists.
An unavailable IP lookup is displayed as unknown, not guessed.

## Data and Limits

- `test_user_data/` contains only test registrations, personal credentials,
  imports and backups. It is excluded from Git and Docker builds. Default
  `user_data/` is untouched. The launcher rejects that directory and its children.
- Files and per-user price overrides use request-local contexts. Toss calls use
  explicit credentials from the current account. A user with no keys does not
  inherit the operator's keys. Per-user mutations are serialized.
- This is a single-process test server. JSON storage uses in-process locks and
  atomic credential/account writes. Do not run multiple workers/instances against
  this store. A production service needs a transactional database, stronger
  authentication, quota persistence, encrypted secret storage and monitoring.
- Credentials are stored on the operator's disk, not in client storage. The
  operator can read the server files; this is not end-to-end encrypted storage.
  Use limited test credentials and revoke them after testing. Back up the test
  directory privately, restrict filesystem access and agree on deletion timing.
- Default quotas allow 20 top-level AI requests per user/hour and 100 across the
  server/hour. Each import can make multiple model requests; these are not token
  or billing caps. Limits reset on restart. Set provider billing/quota alerts too.
- Upload limits: 5 files, 5 MB/file, 12 MB/request and 20 text chunks per analysis.
  Text is split at line boundaries with its header retained. Excel includes all
  sheets. CSV decoding is strict UTF-8 with CP949 fallback. Scanned PDFs need OCR
  outside this flow. Structured-field validation does not guarantee AI accuracy.
- Unmapped ticker and invalid-field reports list every affected AI result row,
  including file, Excel sheet, chunk number, date, symbol/name, fields and reasons.
  The result row number is local to that chunk and transaction/dividend response;
  it is not an original Excel/CSV row number. Unknown tickers must remain blank
  rather than being invented or omitted by the model. Rows omitted by the model
  cannot be diagnosed by field validation alone.
- Any validation issue blocks the whole upload from saving. A new analysis
  invalidates that user's previous draft, so failed retries cannot confirm stale
  results. Correct the source and retry. The mapping summary separately lists
  saved ticker-to-name lookup failures; these are not missing trade amounts or
  evidence that market-price lookup failed. Zero issues has an explicit empty state.
- Confirmation merges new rows with existing history rather than replacing an
  entire broker. Identical repeated rows retain their multiplicity. Without a
  broker execution ID, truly distinct but identical fills across different
  uploads remain ambiguous; inspect the result before performance analysis.
- Login/register requests are rate limited. Shared mode blocks legacy import and
  settings routes that bypass the new flow, rejects cross-origin writes and uses
  no-store headers for private responses. Restore accepts only local snapshot IDs.

## Import Failure Diagnostics

Analysis errors show a safe reason, suggested next action, failed stage and, when
available, the file, sheet and split chunk. The chunk is not an Excel row number.
The error code, response wait time and request ID help the operator find the
matching server event. An analysis failure does not confirm or save any rows,
including rows parsed successfully before another chunk failed.

Common codes:

| Code | Meaning and Next Step |
| --- | --- |
| `GEMINI_QUOTA` | Google request/usage limit; retry later and check project quotas/billing. This does not necessarily mean the daily free quota. |
| `AI_REQUEST_LIMIT` | This application's hourly request limit, separate from Google's quotas. |
| `GEMINI_NOT_CONFIGURED`, `GEMINI_AUTH` | The operator must check the server key, restrictions and permissions. Do not ask testers to submit keys in error reports. |
| `GEMINI_TIMEOUT`, `GEMINI_UNAVAILABLE` | Provider timeout or connection/service failure; retry later, with smaller files if needed. |
| `GEMINI_MODEL_UNAVAILABLE` | The configured model is missing or inaccessible. |
| `GEMINI_INPUT_LIMIT`, `GEMINI_OUTPUT_LIMIT` | Input/output length limit; split the file by date or reduce unnecessary columns. |
| `GEMINI_BLOCKED` | Google restricted the response; remove unnecessary personal/free-text content and request operator review. |
| `GEMINI_INVALID_JSON`, `GEMINI_INVALID_RESPONSE` | The response is not valid JSON or not a transaction/dividend list. It is not evidence that the file contains no trades. |
| `GEMINI_EMPTY_RESPONSE`, `GEMINI_INCOMPLETE_RESPONSE` | No readable response or abnormal completion. A valid empty dividend list is allowed. |
| `FILE_READ_FAILED`, `FILE_EMPTY`, `IMPORT_ROW_TOO_LONG`, `IMPORT_TOO_LARGE` | Check file format, text extraction or upload size; the failing source is included where available. |
| `VALIDATION_FAILED` | Use the existing full unmapped/invalid-row report to correct the source. |
| `NO_RECORDS` | Both model lists are empty; verify the selected sheets contain executions or dividend receipts. |
| `GEMINI_INVALID_REQUEST`, `GEMINI_UNKNOWN`, `IMPORT_INTERNAL_ERROR` | Operator investigation is required; unrecognized errors are not assigned a guessed cause. |

The API preserves an `error` string and adds `failure` and `saved: false` for
analysis failures. `failure.requestId` matches `X-Request-ID`. Google status codes
are separate from the application's HTTP status (for example, Google 403 is
reported as server configuration failure 503). Safe model-attempt codes are
retained; the final missing-model error cannot hide an earlier quota/auth failure.

The `uvicorn.error` logger emits `import_result` JSON events with the request ID,
time, elapsed seconds, stage, chunk, status, safe error code and safe model-attempt
statuses. It does not record upload filenames, user/account identifiers, raw
transaction text, model response bodies or exception messages. Share the request
ID with the operator; do not send credentials or unredacted trade files. Configure
log retention privately if diagnostics must survive terminal/server restarts.

The browser also handles non-JSON proxy responses: HTTP 524 is a Cloudflare wait
timeout, 502/503 are server/proxy errors, 413 is an upload limit and 401 requires
login. It displays `CF-Ray` when supplied, but never renders the proxy's HTML.
A network error or proxy timeout does not prove that the server stopped working;
analysis may continue. Avoid repeated immediate uploads. No save confirmation is
sent by analysis. Request IDs may be unavailable when a proxy rejects the request
before the application responds. Existing historical failures cannot be diagnosed
retroactively from status-only logs. This change does not extend tunnel timeouts
or introduce background jobs.

## Checks

```powershell
python -m unittest discover -s tests -p test_user_isolation.py -q
python -m unittest discover -s tests -q
```

Tests use temporary user directories and mocked external API calls. A separate
browser check used two new test accounts and a synthetic two-row CSV with the
configured Gemini API. It confirmed preview-before-write, saved-data isolation,
account-ID preservation and mobile layout. Personal Toss registration was tested
with mocked API responses; each tester's real credentials/IP need their own check.