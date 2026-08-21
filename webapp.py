"""FastAPI 웹앱 — 기존 분석 모듈(pipeline/auth/exporter/report/ai_copilot)을 재사용하는 홈페이지.

실행: uvicorn webapp:app --host 0.0.0.0 --port 8000
기존 Streamlit 앱(app.py)과 독립적으로 동작합니다.
"""
import io
import os
import time
import secrets as _secrets

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import pandas as pd

import auth
import pipeline
from manual_holdings import read_transactions_csv, read_manual_csv, read_dividends_csv
from exporter import build_full_excel
from report import build_portfolio_pdf
from ai_copilot import generate_rebalancing_report, chat_with_portfolio
from advanced_analytics import compute_fx_pnl
from pme import compute_usd_avg_cost

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="자산관리 대시보드")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("WEB_SECRET_KEY", _secrets.token_hex(32)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "web", "templates"))

SOURCE_LABELS = {"tx": "거래내역 임포트", "toss": "토스증권 API", "both": "거래내역 + 토스증권 API"}

# 사용자별 포트폴리오 결과 캐시 (5분)
_CACHE = {}


def _current_user(request: Request):
    return request.session.get("user")


def get_portfolio(user, force=False):
    now = time.time()
    ent = _CACHE.get(user)
    if not force and ent and now - ent[0] < 300:
        return ent[1]
    data = pipeline.load_portfolio(user, use_toss=auth.has_toss_credentials(user), use_tx=True)
    _CACHE[user] = (now, data)
    return data


def _df_records(df, limit=None):
    if df is None or getattr(df, "empty", True):
        return []
    d = df.head(limit) if limit else df
    return d.to_dict(orient="records")


# ─────────────────────────── 인증 ───────────────────────────
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, msg: str = "", err: str = ""):
    if _current_user(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"msg": msg, "err": err})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ok, message = auth.verify_user(username, password)
    if ok:
        request.session["user"] = username.strip()
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"err": message, "msg": ""})


@app.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...)):
    ok, message = auth.register_user(username, password)
    return templates.TemplateResponse(
        request, "login.html", {"msg": message if ok else "", "err": "" if ok else message})


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ─────────────────────────── 대시보드 ───────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, refresh: int = 0):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    data = get_portfolio(user, force=bool(refresh))

    detail_df = data["detail_df"]
    tx_records = _df_records(
        detail_df.sort_values("체결일시", ascending=False) if (detail_df is not None and not detail_df.empty) else detail_df,
        limit=300)
    breakdown_records = _df_records(data["breakdown"])
    tickers = sorted(data["breakdown"]["티커"].unique()) if (data["breakdown"] is not None and not data["breakdown"].empty) else []

    ctx = {
        "request": request, "user": user, "fx_rate": data["fx_rate"],
        "toss_ok": auth.has_toss_credentials(user), "toss_error": data["toss_error"],
        "has_data": data["has_data"], "summary": data["summary"], "holdings": data["holdings"],
        "perf": data["perf"], "ab": data["ab"], "tx_records": tx_records,
        "dividends": data["dividends_rows"], "breakdown": breakdown_records, "tickers": tickers,
        "div_krw_native": data["div_krw_native"], "div_usd_native": data["div_usd_native"],
        "name_map": data["name_map"],
    }
    return templates.TemplateResponse(request, "dashboard.html", ctx)


# ─────────────────────────── 성장 추이 차트(JSON) ───────────────────────────
@app.get("/api/growth")
def api_growth(request: Request, ticker: str = ""):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    orders = data["combined_orders"]
    fx = data["fx_rate"]
    if not orders:
        return JSONResponse({"error": "no_data"}, status_code=404)

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.utils
    import json as _json

    tk = ticker or None
    gdf = pipeline.growth_frame(orders, fx, tk)
    if gdf is None or gdf.empty:
        return JSONResponse({"error": "no_growth"}, status_code=404)
    bars_buys, bars_sells = pipeline.trade_bars(orders, tk)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
                        vertical_spacing=0.06, specs=[[{"secondary_y": False}], [{"secondary_y": False}]])
    gidx = gdf.index
    fig.add_trace(go.Scatter(x=gidx, y=gdf["내 수익금"], name="내 수익금", mode="lines",
                             line=dict(color="#EF553B", width=2.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=gidx, y=gdf["S&P500 수익금"], name="S&P500 수익금", mode="lines",
                             line=dict(color="#636EFA", dash="dash", width=2)), row=1, col=1)
    span = max((pd.Timestamp(gidx.max()) - pd.Timestamp(gidx.min())).days, 1)
    bw = max(span / 130.0, 1.0) * 86400000
    if bars_buys is not None and not bars_buys.empty:
        fig.add_trace(go.Bar(x=bars_buys["date"], y=bars_buys["qty"], name="매수 수량",
                             marker_color="#16A34A", opacity=0.85, width=bw), row=2, col=1)
    if bars_sells is not None and not bars_sells.empty:
        fig.add_trace(go.Bar(x=bars_sells["date"], y=bars_sells["qty"], name="매도 수량",
                             marker_color="#DC2626", opacity=0.6, width=bw), row=2, col=1)
    fig.update_yaxes(title_text="누적 수익금(원)", row=1, col=1)
    fig.update_yaxes(title_text="수량(주)", rangemode="tozero", row=2, col=1)
    fig.update_layout(margin=dict(t=10, r=10, l=10, b=10), legend=dict(orientation="h", y=1.05),
                      height=460, barmode="overlay")
    return JSONResponse(_json.loads(_json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)))


# ─────────────────────────── 설정(토스/API 키) ───────────────────────────
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, msg: str = ""):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    creds = auth.load_credentials(user)
    return templates.TemplateResponse(request, "settings.html", {
        "user": user, "msg": msg,
        "toss_id": creds.get("TOSS_CLIENT_ID", ""), "toss_acc": creds.get("TOSS_ACCOUNT_NO", "1") or "1",
        "toss_ok": auth.has_toss_credentials(user)})


@app.post("/settings")
def settings_save(request: Request, client_id: str = Form(""), client_secret: str = Form(""),
                  account_no: str = Form("1")):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    creds = {"TOSS_CLIENT_ID": client_id, "TOSS_ACCOUNT_NO": account_no or "1"}
    if client_secret.strip():  # 비밀키는 입력했을 때만 갱신
        creds["TOSS_CLIENT_SECRET"] = client_secret
    auth.save_credentials(user, creds)
    _CACHE.pop(user, None)
    return RedirectResponse("/settings?msg=저장되었습니다", status_code=302)


# ─────────────────────────── 임포트(거래내역 업로드) ───────────────────────────
@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, msg: str = ""):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "import.html", {"user": user, "msg": msg})


@app.post("/import")
async def import_save(request: Request, broker: str = Form("한화투자증권"),
                      pasted: str = Form(""), files: list[UploadFile] = File(default=[])):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from ai_copilot import parse_brokerage_full_transactions, parse_brokerage_dividends
    from manual_holdings import save_parsed_transactions, save_parsed_dividends
    pipeline.apply_credentials(user)

    raw_texts = []
    for up in files or []:
        try:
            content = await up.read()
            if up.filename.lower().endswith((".xlsx", ".xls")):
                raw_texts.append(pd.read_excel(io.BytesIO(content)).to_csv(index=False))
            else:
                raw_texts.append(content.decode("utf-8", errors="ignore"))
        except Exception:
            continue
    if pasted.strip():
        raw_texts.append(pasted)

    rows, divs = [], []
    for rt in raw_texts:
        parsed, err = parse_brokerage_full_transactions(rt, broker)
        if parsed:
            rows.extend(parsed)
        dparsed, _ = parse_brokerage_dividends(rt, broker)
        if dparsed:
            divs.extend(dparsed)
    n = save_parsed_transactions(rows, replace_broker=broker) if rows else 0
    dn = save_parsed_dividends(divs, replace_broker=broker) if divs else 0
    _CACHE.pop(user, None)
    return RedirectResponse(f"/import?msg={n}건 거래·{dn}건 배당 저장됨", status_code=302)


# ─────────────────────────── 내보내기(엑셀/PDF) ───────────────────────────
@app.get("/export.xlsx")
def export_xlsx(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    data = get_portfolio(user)
    try:
        usd_cost = compute_usd_avg_cost(data["combined_orders"], data["fx_rate"])
    except Exception:
        usd_cost = None
    try:
        _, fx_df = compute_fx_pnl(data["combined_orders"], data["fx_rate"])
    except Exception:
        fx_df = pd.DataFrame()
    xlsx = build_full_excel(
        summary=data["summary"], perf=data["perf"], ab=data["ab"], holdings=data["holdings"],
        detail_df=data["detail_df"], holdings_breakdown=data["breakdown"],
        dividends_df=pd.DataFrame(data["dividends_rows"]), usd_cost=usd_cost, fx_pnl_df=fx_df,
        raw_tx=read_transactions_csv(), raw_holdings=read_manual_csv(), raw_dividends=read_dividends_csv(),
        fx_rate=data["fx_rate"], meta={"사용자": user, "데이터 소스": SOURCE_LABELS.get("both")})
    fname = f"portfolio_data_{user}_{time.strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(io.BytesIO(xlsx),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/report.pdf")
def report_pdf(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    data = get_portfolio(user)
    ai = request.session.pop("rebal_report", None)
    pdf = build_portfolio_pdf(user, SOURCE_LABELS.get("both"), summary=data["summary"], perf=data["perf"],
                              ab=data["ab"], holdings=data["holdings"], ai_report=ai, fx_rate=data["fx_rate"])
    fname = f"portfolio_report_{user}_{time.strftime('%Y%m%d_%H%M')}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={fname}"})


# ─────────────────────────── AI ───────────────────────────
@app.post("/api/rebalance")
def api_rebalance(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    data = get_portfolio(user)
    pj = {"user_profile": {"user_id": user}, "asset_summary": data["summary"], "holdings": data["holdings"]}
    text = generate_rebalancing_report(pj, data["ab"], data["perf"])
    request.session["rebal_report"] = text
    return JSONResponse({"report": text})


@app.post("/api/chat")
async def api_chat(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    q = (body.get("message") or "").strip()
    history = body.get("history") or []
    if not q:
        return JSONResponse({"error": "empty"}, status_code=400)
    pipeline.apply_credentials(user)
    data = get_portfolio(user)
    pj = {"user_profile": {"user_id": user}, "asset_summary": data["summary"], "holdings": data["holdings"]}
    ctx_lines = []
    if data["ab"]:
        ctx_lines.append(f"알파 {data['ab'].get('alpha_pct')}%p, 베타 {data['ab'].get('beta')}, XIRR {data['ab'].get('port_xirr_pct')}%")
    answer = chat_with_portfolio(q, history, pj, "\n".join(ctx_lines))
    return JSONResponse({"answer": answer})


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
