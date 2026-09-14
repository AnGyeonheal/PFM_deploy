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
- Confirmation merges new rows with existing history rather than replacing an
  entire broker. Identical repeated rows retain their multiplicity. Without a
  broker execution ID, truly distinct but identical fills across different
  uploads remain ambiguous; inspect the result before performance analysis.
- Login/register requests are rate limited. Shared mode blocks legacy import and
  settings routes that bypass the new flow, rejects cross-origin writes and uses
  no-store headers for private responses. Restore accepts only local snapshot IDs.

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