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
from manual_holdings import (
    read_transactions_csv, read_manual_csv, read_dividends_csv,
    write_transactions_csv, write_dividends_csv, TX_COLUMNS, DIV_COLUMNS,
    read_splits_csv, write_splits_csv, SPLIT_COLUMNS,
    clear_all_imports, delete_broker_imports, imported_brokers,
    snapshot_imports, list_snapshots, restore_snapshot,
)
from exporter import build_full_excel
from report import build_portfolio_pdf
from ai_copilot import generate_rebalancing_report, chat_with_portfolio
from advanced_analytics import compute_fx_pnl
from pme import compute_usd_avg_cost, build_usdkrw_history_frame

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="자산관리 대시보드")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("WEB_SECRET_KEY", _secrets.token_hex(32)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")), name="static")


@app.middleware("http")
async def _no_store_api(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "web", "templates"))

SOURCE_LABELS = {"tx": "거래내역 임포트", "toss": "토스증권 API", "both": "거래내역 + 토스증권 API"}

# 사용자별 포트폴리오 결과 캐시 (5분)
_CACHE = {}


def _current_user(request: Request):
    return request.session.get("user")


def get_portfolio(user, force=False, include_div=True, include_fx=True):
    pipeline.apply_credentials(user)  # 캐시 히트 시에도 사용자 데이터 경로(set_data_dir) 보장
    now = time.time()
    sub = _CACHE.get(user) or {}
    ent = sub.get((include_div, include_fx))
    if not force and ent and now - ent[0] < 300:
        return ent[1]
    data = pipeline.load_portfolio(user, use_toss=auth.has_toss_credentials(user), use_tx=True,
                                   include_div=include_div, include_fx=include_fx)
    sub[(include_div, include_fx)] = (now, data)
    _CACHE[user] = sub
    return data


def _df_records(df, limit=None):
    if df is None or getattr(df, "empty", True):
        return []
    d = df.head(limit) if limit else df
    return d.to_dict(orient="records")


def _fig_json(fig):
    import plotly.utils
    import json as _json
    return _json.loads(_json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder))


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
def dashboard(request: Request, refresh: int = 0, div: int = 1, fx: int = 1):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    data = get_portfolio(user, force=bool(refresh), include_div=bool(div), include_fx=bool(fx))

    detail_df = data["detail_df"]
    tx_records = _df_records(
        detail_df.sort_values("체결일시", ascending=False) if (detail_df is not None and not detail_df.empty) else detail_df,
        limit=300)
    breakdown_records = _df_records(data["breakdown"])
    tickers = sorted(data["breakdown"]["티커"].unique()) if (data["breakdown"] is not None and not data["breakdown"].empty) else []

    # 종목별 분석(현재주가·알파·베타·기여도) 병합 + 한글 종목명 보강
    name_map = data["name_map"]
    sa = data.get("stock_analytics")
    sa_map = {str(r["티커"]): r for r in sa.to_dict("records")} if (sa is not None and not sa.empty) else {}
    _ana_cols = ["현재주가", "S&P500대비(%p)", "알파(연%)", "베타", "알파기여(%)", "베타기여(%)"]
    for rec in breakdown_records:
        tkey = str(rec.get("티커"))
        if name_map.get(tkey):
            rec["종목"] = name_map[tkey]
        a = sa_map.get(tkey)
        for c in _ana_cols:
            rec[c] = (a.get(c) if a else None)

    ctx = {
        "request": request, "user": user, "fx_rate": data["fx_rate"],
        "toss_ok": auth.has_toss_credentials(user), "toss_error": data["toss_error"],
        "has_data": data["has_data"], "summary": data["summary"], "holdings": data["holdings"],
        "perf": data["perf"], "ab": data["ab"], "tx_records": tx_records,
        "dividends": data["dividends_rows"], "breakdown": breakdown_records, "tickers": tickers,
        "div_krw_native": data["div_krw_native"], "div_usd_native": data["div_usd_native"],
        "name_map": data["name_map"],
        "inc_div": bool(div), "inc_fx": bool(fx),
    }
    return templates.TemplateResponse(request, "dashboard.html", ctx)


# ─────────────────────────── 성장 추이 차트(JSON) ───────────────────────────
@app.get("/api/growth")
def api_growth(request: Request, ticker: str = "", mode: str = "value", showdiv: int = 1, showfx: int = 1, period: str = "all"):
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

    _PMONTHS = {"1m": 1, "3m": 3, "6m": 6, "1y": 12, "5y": 60}
    def _cut(df, col=None):
        if period in _PMONTHS and df is not None and not df.empty:
            cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(months=_PMONTHS[period])
            return df[df[col] >= cutoff] if col else df[df.index >= cutoff]
        return df

    if mode == "return":
        rdf = pipeline.twr_comparison(orders, fx, tk)
        if rdf is None or rdf.empty:
            return JSONResponse({"error": "no_return"}, status_code=404)
        rdf = _cut(rdf)
        rfig = go.Figure()
        rfig.add_trace(go.Scatter(x=rdf.index, y=rdf["내 수익률(%)"], name="내 수익률", mode="lines",
                                  line=dict(color="#EF553B", width=2.4),
                                  hovertemplate="%{x|%Y-%m-%d}<br>내 수익률 %{y:.1f}%<extra></extra>"))
        rfig.add_trace(go.Scatter(x=rdf.index, y=rdf["S&P500 수익률(%)"], name="S&P500 수익률", mode="lines",
                                  line=dict(color="#636EFA", width=2.0, dash="dash"),
                                  hovertemplate="%{x|%Y-%m-%d}<br>S&P500 수익률 %{y:.1f}%<extra></extra>"))
        rfig.add_hline(y=0, line_dash="dot", line_color="#B0B8C1")
        rfig.update_yaxes(title_text="수익률(%)", ticksuffix="%")
        rfig.update_layout(margin=dict(t=10, r=10, l=10, b=10), height=460,
                           legend=dict(orientation="h", y=1.05))
        return JSONResponse(_json.loads(_json.dumps(rfig, cls=plotly.utils.PlotlyJSONEncoder)))

    gdf = pipeline.growth_frame(orders, fx, tk, include_div=bool(showdiv), include_fx=bool(showfx))
    if gdf is None or gdf.empty:
        return JSONResponse({"error": "no_growth"}, status_code=404)
    gdf = _cut(gdf)
    bars_buys, bars_sells = pipeline.trade_bars(orders, tk, fx)
    bars_buys, bars_sells = _cut(bars_buys, "date"), _cut(bars_sells, "date")
    name_map = data["name_map"]
    is_ind = bool(tk)
    tk_cur = next((o.get("currency", "KRW") for o in orders if o.get("symbol") == tk), "KRW") if tk else "KRW"
    px_fmt = ",.0f" if tk_cur == "KRW" else ",.2f"

    if is_ind:
        rbeta = pipeline.rolling_beta(orders, fx, tk)
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.56, 0.2, 0.24],
                            vertical_spacing=0.05,
                            specs=[[{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]])
        bar_row = 3
    else:
        rbeta = None
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
                            vertical_spacing=0.06, specs=[[{"secondary_y": False}], [{"secondary_y": False}]])
        bar_row = 2

    gidx = gdf.index
    fig.add_trace(go.Scatter(x=gidx, y=gdf["내 자산가치"], name="내 자산가치", mode="lines",
                             line=dict(color="#EF553B", width=2.4),
                             hovertemplate="%{x|%Y-%m-%d}<br>내 자산가치 %{y:,.0f}원<extra></extra>"),
                  row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=gidx, y=gdf["S&P500 자산가치"], name="S&P500 동일투자(매도 반영)", mode="lines",
                             line=dict(color="#636EFA", dash="dash", width=2),
                             hovertemplate="%{x|%Y-%m-%d}<br>S&P500 %{y:,.0f}원<extra></extra>"),
                  row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=gidx, y=gdf["순투자원금"], name="순투자원금(매수−매도)", mode="lines",
                             line=dict(color="#9AA4AE", width=1.4, dash="dot"),
                             hovertemplate="%{x|%Y-%m-%d}<br>순투자원금 %{y:,.0f}원<extra></extra>"),
                  row=1, col=1, secondary_y=False)
    if "내 누적손익" in gdf.columns:
        fig.add_trace(go.Scatter(x=gidx, y=gdf["내 누적손익"], name="내 누적손익", mode="lines",
                                 line=dict(color="#14B8A6", width=1.8), fill="tozeroy",
                                 fillcolor="rgba(20,184,166,0.10)",
                                 hovertemplate="%{x|%Y-%m-%d}<br>누적손익 %{y:,.0f}원<extra></extra>"),
                      row=1, col=1, secondary_y=False)
    if is_ind and "주가" in gdf.columns:
        fig.add_trace(go.Scatter(x=gidx, y=gdf["주가"], name="주가", mode="lines",
                                 line=dict(color="#F9A825", width=1.2), opacity=0.75,
                                 hovertemplate="%{x|%Y-%m-%d}<br>주가 %{y:" + px_fmt + "}<extra></extra>"),
                      row=1, col=1, secondary_y=True)
        fig.update_yaxes(title_text="주가", secondary_y=True, showgrid=False, row=1, col=1)
        alpha = (gdf["내 자산가치"] - gdf["S&P500 자산가치"]).dropna()
        if not alpha.empty:
            mx_x, mx_y, mx_t, mn_x, mn_y, mn_t = [], [], [], [], [], []
            for yr, grp in alpha.groupby(alpha.index.year):
                dmax, dmin = grp.idxmax(), grp.idxmin()
                mx_x.append(dmax); mx_y.append(float(gdf["내 자산가치"].loc[dmax])); mx_t.append(f"{yr} 최대 알파 {grp.loc[dmax]:,.0f}원")
                mn_x.append(dmin); mn_y.append(float(gdf["내 자산가치"].loc[dmin])); mn_t.append(f"{yr} 최소 알파 {grp.loc[dmin]:,.0f}원")
            fig.add_trace(go.Scatter(x=mx_x, y=mx_y, name="연 최대 알파", mode="markers",
                                     marker=dict(symbol="star", size=12, color="#16A34A", line=dict(width=1, color="#052E16")),
                                     text=mx_t, hovertemplate="%{text}<extra></extra>"), row=1, col=1, secondary_y=False)
            fig.add_trace(go.Scatter(x=mn_x, y=mn_y, name="연 최소 알파", mode="markers",
                                     marker=dict(symbol="star-triangle-down", size=12, color="#DC2626", line=dict(width=1, color="#450A0A")),
                                     text=mn_t, hovertemplate="%{text}<extra></extra>"), row=1, col=1, secondary_y=False)

    if is_ind and rbeta is not None and not rbeta.empty:
        fig.add_trace(go.Scatter(x=rbeta.index, y=rbeta.values, name="베타(60일)", mode="lines",
                                 line=dict(color="#8B5CF6", width=1.6),
                                 hovertemplate="%{x|%Y-%m-%d}<br>베타 %{y:.2f}<extra></extra>"), row=2, col=1)
        fig.add_hline(y=1.0, line_dash="dot", line_color="#B0B8C1", row=2, col=1)
        fig.update_yaxes(title_text="베타", row=2, col=1)

    span = max((pd.Timestamp(gidx.max()) - pd.Timestamp(gidx.min())).days, 1)
    bw = max(span / 130.0, 1.0) * 86400000

    def _bar_custom(bdf):
        rows = []
        for _, row in bdf.iterrows():
            nm = name_map.get(row["symbol"], row["symbol"])
            ps = (f"{row['price']:,.0f}원" if row["currency"] == "KRW" else f"${row['price']:,.2f}")
            rows.append([nm, ps, f"{row['qty']:g}"])
        return rows

    _bar_hover = ("%{customdata[0]}<br>%{x|%Y-%m-%d}<br>"
                  "%{customdata[2]}주 @ %{customdata[1]}<br>%{y:,.0f}원<extra></extra>")
    if bars_buys is not None and not bars_buys.empty:
        fig.add_trace(go.Bar(x=bars_buys["date"], y=bars_buys["amount_krw"], name="매수 금액",
                             marker_color="#16A34A", opacity=0.85, width=bw, customdata=_bar_custom(bars_buys),
                             hovertemplate="매수 · " + _bar_hover),
                      row=bar_row, col=1)
    if bars_sells is not None and not bars_sells.empty:
        fig.add_trace(go.Bar(x=bars_sells["date"], y=bars_sells["amount_krw"], name="매도 금액",
                             marker_color="#DC2626", opacity=0.6, width=bw, customdata=_bar_custom(bars_sells),
                             hovertemplate="매도 · " + _bar_hover),
                      row=bar_row, col=1)

    fig.update_yaxes(title_text="자산가치(원)", secondary_y=False, row=1, col=1)
    fig.update_yaxes(title_text="금액(원)", rangemode="tozero", row=bar_row, col=1)
    fig.update_layout(margin=dict(t=10, r=10, l=10, b=10), legend=dict(orientation="h", y=1.06),
                      height=(640 if is_ind else 460), barmode="overlay")
    return JSONResponse(_json.loads(_json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)))

@app.get("/api/allocation")
def api_allocation(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    hs = [h for h in data["holdings"] if float(h.get("weight_pct") or 0) > 0]
    if not hs:
        return JSONResponse({"error": "no_data"}, status_code=404)
    import plotly.graph_objects as go
    labels = [h.get("name") or h.get("ticker") for h in hs]
    values = [float(h.get("weight_pct") or 0) for h in hs]
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.5,
                           textinfo="percent+label", textposition="inside"))
    fig.update_layout(margin=dict(t=10, r=10, l=10, b=10), height=380, showlegend=False,
                      colorway=["#3182F6", "#F04452", "#00A676", "#F9A825", "#8B5CF6", "#6B7684",
                                "#EF553B", "#636EFA", "#12B981", "#FF9F40"])
    return JSONResponse(_fig_json(fig))


@app.get("/api/fx")
def api_fx(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    orders = data["combined_orders"]
    fx = data["fx_rate"]
    usd = compute_usd_avg_cost(orders, fx) if orders else None
    figj = None
    frame = build_usdkrw_history_frame("10y")
    if frame is not None and not frame.empty:
        import plotly.graph_objects as go
        fpx = frame.reset_index()
        xcol = fpx.columns[0]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=fpx[xcol], y=fpx["원/달러"], name="USD/KRW",
                                 line=dict(color="#3182F6", width=1.6)))
        if usd:
            fig.add_hline(y=usd["avg_fx"], line_dash="dash", line_color="#EF553B",
                          annotation_text=f"달러 평단가 {usd['avg_fx']:,.1f}원")
        fig.update_layout(margin=dict(t=10, r=10, l=10, b=10), height=380,
                          legend=dict(orientation="h", y=1.05))
        figj = _fig_json(fig)
    return JSONResponse({"fig": figj, "summary": usd})


@app.get("/api/dca")
def api_dca(request: Request, start: str = ""):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    orders = data["combined_orders"]
    if not orders:
        return JSONResponse({"error": "no_data"}, status_code=404)
    ts, monthly, summary = pipeline.spy_dca(orders, data["fx_rate"], start or None)
    if ts is None or ts.empty:
        return JSONResponse({"error": "no_dca"}, status_code=404)
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ts.index, y=ts["S&P500 수익금"], name="S&P500 수익금", mode="lines",
                             line=dict(color="#636EFA", width=2.4),
                             hovertemplate="%{x|%Y-%m-%d}<br>S&P500 수익금 %{y:,.0f}원<extra></extra>"))
    fig.add_trace(go.Scatter(x=ts.index, y=ts["내 수익금"], name="내 수익금(실제)", mode="lines",
                             line=dict(color="#EF553B", width=2.0),
                             hovertemplate="%{x|%Y-%m-%d}<br>내 수익금 %{y:,.0f}원<extra></extra>"))
    fig.add_hline(y=0, line_dash="dot", line_color="#B0B8C1")
    fig.update_layout(margin=dict(t=10, r=10, l=10, b=10), height=420,
                      legend=dict(orientation="h", y=1.08))
    return JSONResponse({"fig": _fig_json(fig), "summary": summary,
                         "monthly": monthly.to_dict("records") if not monthly.empty else []})

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
    pipeline.apply_credentials(user)
    return templates.TemplateResponse(request, "import.html",
                                      {"user": user, "msg": msg,
                                       "brokers": imported_brokers(), "snapshots": list_snapshots()})


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


@app.post("/import/clear")
def import_clear(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    pipeline.apply_credentials(user)
    snapshot_imports("전체 초기화 전")
    n = clear_all_imports()
    _CACHE.pop(user, None)
    return RedirectResponse(f"/import?msg=임포트 데이터를 초기화했습니다({n}개 파일 삭제). 아래 '삭제 내역 복구'에서 되돌릴 수 있습니다.", status_code=302)


@app.post("/import/clear-broker")
def import_clear_broker(request: Request, broker: str = Form(...)):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    pipeline.apply_credentials(user)
    snapshot_imports(f"{broker} 삭제 전")
    n = delete_broker_imports(broker)
    _CACHE.pop(user, None)
    return RedirectResponse(f"/import?msg={broker} 임포트 {n}건을 삭제했습니다. 아래 '삭제 내역 복구'에서 되돌릴 수 있습니다.", status_code=302)


@app.post("/import/restore")
def import_restore(request: Request, snap_id: str = Form(...)):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    pipeline.apply_credentials(user)
    n = restore_snapshot(snap_id)
    _CACHE.pop(user, None)
    if n:
        return RedirectResponse("/import?msg=선택한 시점으로 복구했습니다. (복구 직전 상태도 자동 백업됨)", status_code=302)
    return RedirectResponse("/import?msg=복구할 백업을 찾지 못했습니다.", status_code=302)


# ─────────────────────────── 데이터 편집(거래/배당 직접 수정) ───────────────────────────
def _toss_row_differs(sub, orig):
    for f in ("일자", "티커", "종목명", "구분", "통화"):
        if str(sub.get(f, "")).strip() != str(orig.get(f, "")).strip():
            return True
    for f in ("수량", "단가"):
        try:
            if abs(float(sub.get(f) or 0) - float(orig.get(f) or 0)) > 1e-9:
                return True
        except Exception:
            return True
    return False


@app.get("/edit-data", response_class=HTMLResponse)
def edit_data_page(request: Request, msg: str = ""):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    data = get_portfolio(user)
    pipeline.apply_credentials(user)
    name_map = data.get("name_map", {})

    # 거래: 임포트(CSV) + 토스(오버라이드 반영)
    tx = read_transactions_csv()
    tx_rows = []
    if tx is not None and not tx.empty:
        for r in tx.fillna("").to_dict("records"):
            r["_src"] = "임포트"; r["_key"] = ""
            tx_rows.append(r)
    overrides = pipeline.read_toss_overrides()
    for o in data.get("toss_orders_raw", []):
        k = pipeline.toss_trade_key(o)
        e = overrides.get(k)
        if e and e.get("deleted"):
            continue
        base = pipeline.toss_display_row(o, name_map)
        row = dict(base)
        if e:
            row.update({f: e.get(f, base.get(f)) for f in pipeline.TOSS_OVR_FIELDS})
        row["_src"] = "토스"; row["_key"] = k
        tx_rows.append(row)

    # 배당: 검증(CSV) + 추정(토스 보유 기반 yfinance 추정)
    dv = read_dividends_csv()
    div_rows = []
    if dv is not None and not dv.empty:
        for r in dv.fillna("").to_dict("records"):
            r["_src"] = "검증"
            div_rows.append(r)
    for r in data.get("dividends_rows", []):
        if str(r.get("구분", "")).startswith("추정"):
            div_rows.append({"증권사": "토스(추정)", "일자": r.get("일자", ""), "티커": r.get("티커"),
                             "종목명": r.get("종목"), "통화": r.get("통화"), "배당금": r.get("배당금"),
                             "_src": "추정"})

    sp = read_splits_csv()
    split_rows = sp.fillna("").to_dict("records") if (sp is not None and not sp.empty) else []

    ctx = {"request": request, "user": user, "msg": msg,
           "tx_rows": tx_rows, "div_rows": div_rows, "split_rows": split_rows,
           "tx_cols": TX_COLUMNS, "div_cols": DIV_COLUMNS, "split_cols": SPLIT_COLUMNS}
    return templates.TemplateResponse(request, "edit_data.html", ctx)


@app.post("/edit-data/tx")
async def edit_data_tx(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    pipeline.apply_credentials(user)
    payload = await request.json()
    rows = payload.get("rows", [])
    manual_rows = [r for r in rows if r.get("_src") != "토스"]
    toss_rows = [r for r in rows if r.get("_src") == "토스"]

    # 임포트(CSV) 거래 저장
    snapshot_imports("거래 편집 전")
    df = pd.DataFrame([{c: r.get(c, "") for c in TX_COLUMNS} for r in manual_rows], columns=TX_COLUMNS)
    n = write_transactions_csv(df)

    # 토스 거래: 원본과 다른 행만 오버라이드, 삭제된 행은 deleted 표시
    raw_by_key = {pipeline.toss_trade_key(o): o for o in data.get("toss_orders_raw", [])}
    submitted = set()
    ov = {}
    for r in toss_rows:
        k = r.get("_key")
        if not k or k not in raw_by_key:
            continue
        submitted.add(k)
        orig = pipeline.toss_display_row(raw_by_key[k], data.get("name_map", {}))
        if _toss_row_differs(r, orig):
            ov[k] = {f: r.get(f, "") for f in pipeline.TOSS_OVR_FIELDS}
    for k in raw_by_key:
        if k not in submitted:
            ov[k] = {"deleted": True}
    pipeline.write_toss_overrides(ov)
    _CACHE.pop(user, None)
    edited = sum(1 for v in ov.values() if not v.get("deleted"))
    deleted = sum(1 for v in ov.values() if v.get("deleted"))
    return JSONResponse({"ok": True, "count": n, "toss_edited": edited, "toss_deleted": deleted})


@app.post("/edit-data/div")
async def edit_data_div(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    payload = await request.json()
    rows = payload.get("rows", [])
    snapshot_imports("배당 편집 전")
    df = pd.DataFrame([{c: r.get(c, "") for c in DIV_COLUMNS} for r in rows], columns=DIV_COLUMNS) if rows else pd.DataFrame(columns=DIV_COLUMNS)
    n = write_dividends_csv(df)
    _CACHE.pop(user, None)
    return JSONResponse({"ok": True, "count": n})


@app.post("/edit-data/split")
async def edit_data_split(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    payload = await request.json()
    rows = payload.get("rows", [])
    df = pd.DataFrame([{c: r.get(c, "") for c in SPLIT_COLUMNS} for r in rows],
                      columns=SPLIT_COLUMNS) if rows else pd.DataFrame(columns=SPLIT_COLUMNS)
    n = write_splits_csv(df)
    _CACHE.pop(user, None)
    return JSONResponse({"ok": True, "count": n})


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
def report_pdf(request: Request, ai: int = 1, tickers: str = ""):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    data = get_portfolio(user)
    pipeline.apply_credentials(user)

    # 종목별 분석 병합 + 한글 종목명(대시보드 표와 동일)
    breakdown_records = _df_records(data["breakdown"])
    sa = data.get("stock_analytics")
    sa_map = {str(r["티커"]): r for r in sa.to_dict("records")} if (sa is not None and not sa.empty) else {}
    name_map = data.get("name_map", {})
    for rec in breakdown_records:
        tkey = str(rec.get("티커"))
        if name_map.get(tkey):
            rec["종목"] = name_map[tkey]
        a = sa_map.get(tkey)
        for c in ("현재주가", "S&P500대비(%p)", "알파(연%)", "베타", "알파기여(%)", "베타기여(%)"):
            rec[c] = (a.get(c) if a else None)

    # 차트 이미지(matplotlib): 전체 성장 + 보유 비중 + 선택 개별 종목
    charts = []
    try:
        import report_charts
        orders = data["combined_orders"]
        gdf = None
        if orders:
            gdf = pipeline.growth_frame(orders, data["fx_rate"], None)
            charts.append(("자산 성장 추이 · S&P500(매도 반영) 비교", report_charts.growth_png(gdf)))
        charts.append(("보유 비중", report_charts.allocation_png(data["holdings"])))
        if orders:
            ts_dca, _m, _s = pipeline.spy_dca(orders, data["fx_rate"])
            charts.append(("S&P500 vs 내 수익금(시작월 기준)", report_charts.dca_png(ts_dca, gdf)))
        sel = [t.strip() for t in (tickers or "").split(",") if t.strip()][:10]
        valid = (set(str(x) for x in data["breakdown"]["티커"].tolist())
                 if (data["breakdown"] is not None and not data["breakdown"].empty) else set())
        for tk in sel:
            if orders and (not valid or tk in valid):
                gt = pipeline.growth_frame(orders, data["fx_rate"], tk)
                png = report_charts.growth_png(gt, title=f"{tk} - Growth vs S&P500 (KRW)")
                if png:
                    charts.append((f"{name_map.get(tk, tk)} ({tk}) 성장 추이", png))
    except Exception:
        pass
    charts = [(t, p) for t, p in charts if p]

    # AI 진단: 대시보드에서 생성했으면 재사용, 없으면 생성(키 없으면 건너뜀)
    ai_text = request.session.pop("rebal_report", None)
    if not ai_text and ai:
        try:
            pj = {"user_profile": {"user_id": user}, "asset_summary": data["summary"], "holdings": data["holdings"]}
            ai_text = generate_rebalancing_report(pj, data["ab"], data["perf"])
        except Exception:
            ai_text = None

    pdf = build_portfolio_pdf(user, SOURCE_LABELS.get("both"), summary=data["summary"], perf=data["perf"],
                              ab=data["ab"], holdings=data["holdings"], ai_report=ai_text, fx_rate=data["fx_rate"],
                              charts=charts, breakdown=breakdown_records)
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
