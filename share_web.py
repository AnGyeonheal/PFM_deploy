import argparse
import os
import secrets
import shutil
import socket
import subprocess
from pathlib import Path

from dotenv import load_dotenv


def configure_test_server(directory, https):
    root = Path(directory).resolve()
    owner_data = Path(__file__).resolve().parent / "user_data"
    if root == owner_data or root in owner_data.parents or owner_data in root.parents:
        raise ValueError("The test server must not use the existing user_data directory.")
    root.mkdir(parents=True, exist_ok=True)
    key_path = root / ".session_key"
    try:
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        session_key = key_path.read_text(encoding="ascii").strip()
    else:
        session_key = secrets.token_hex(32)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(session_key)
    if len(session_key) < 64:
        raise ValueError("The test session key is invalid.")
    os.environ["PFM_DATA_DIR"] = str(root)
    os.environ["PFM_SHARE_MODE"] = "1"
    os.environ["WEB_HTTPS_ONLY"] = "1" if https else "0"
    os.environ["WEB_SECRET_KEY"] = session_key
    for key in ("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET", "TOSS_ACCOUNT_NO"):
        os.environ.pop(key, None)
    return root


def main():
    parser = argparse.ArgumentParser(description="Run an isolated PFM user-testing server.")
    parser.add_argument("--share", action="store_true", help="Publish an HTTPS Cloudflare Quick Tunnel.")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parent / "test_user_data"))
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parent / ".env")
    configure_test_server(args.data_dir, https=args.share)
    from ai_copilot import shared_gemini_available
    if not shared_gemini_available():
        parser.error("Configure the server GEMINI_API_KEY in .env first. Do not send the key to testers.")
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        candidate = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "cloudflared" / "cloudflared.exe"
        cloudflared = str(candidate) if candidate.is_file() else None
    if args.share and not cloudflared:
        parser.error("cloudflared is not installed.")
    try:
        import requests
        response = requests.get("https://api.ipify.org", timeout=5)
        response.raise_for_status()
        import ipaddress
        os.environ["PFM_OUTBOUND_IP"] = str(ipaddress.ip_address(response.text.strip()))
    except Exception:
        os.environ.pop("PFM_OUTBOUND_IP", None)
    import uvicorn
    import webapp
    if not Path(webapp._FIGMA_DIST, "index.html").is_file():
        parser.error("Build the React app before starting the test server.")
    tunnel = None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", args.port))
            listener.listen(128)
        except OSError:
            parser.error(f"Port {args.port} is unavailable. Choose another --port; no existing server was stopped.")
        try:
            if args.share:
                tunnel_environment = {key: value for key, value in os.environ.items()
                                      if key not in ("GEMINI_API_KEY", "WEB_SECRET_KEY", "DISCORD_WEBHOOK_URL")
                                      and not key.startswith("TOSS_")}
                tunnel = subprocess.Popen([cloudflared, "tunnel", "--url", f"http://127.0.0.1:{args.port}"],
                                           env=tunnel_environment)
                print("Share the printed https://*.trycloudflare.com URL with /app/ appended.", flush=True)
            else:
                print(f"Local user-testing app: http://127.0.0.1:{args.port}/app/ (not public)", flush=True)
            config = uvicorn.Config(webapp.app, host="127.0.0.1", port=args.port, workers=1,
                                    proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_level="info")
            uvicorn.Server(config).run(sockets=[listener])
        finally:
            if tunnel is not None and tunnel.poll() is None:
                tunnel.terminate()
                try:
                    tunnel.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    tunnel.kill()
                    tunnel.wait()


if __name__ == "__main__":
    main()