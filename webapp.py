"""FastAPI 웹앱 — 기존 분석 모듈(pipeline/auth/exporter/report/ai_copilot)을 재사용하는 홈페이지.

실행: uvicorn webapp:app --host 0.0.0.0 --port 8000
기존 Streamlit 앱(app.py)과 독립적으로 동작합니다.
"""
import io
import os
import json
import math
import time
import secrets as _secrets
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
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
    read_holdings_overrides, write_holdings_overrides,
)
from exporter import build_full_excel
from report import build_portfolio_pdf
from ai_copilot import generate_rebalancing_report, chat_with_portfolio
from advanced_analytics import compute_fx_pnl
from names import register_krw_foreign
from pme import (compute_usd_avg_cost, build_usdkrw_history_frame, comparison_statistics,
                 xirr_from_growth, profit_from_growth)

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="자산관리 대시보드")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("WEB_SECRET_KEY", _secrets.token_hex(32)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")), name="static")

# Figma 기반 React SPA(빌드 산출물)를 /app 에서 서빙
_FIGMA_DIST = os.path.join(BASE_DIR, "Asset Portfolio Performance Analysis", "dist")
if os.path.isdir(_FIGMA_DIST):
    app.mount("/app", StaticFiles(directory=_FIGMA_DIST, html=True), name="figma")


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
        register_krw_foreign(ent[1].get("name_map"))
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


_PERIOD_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60}


def _period_bounds(period="", year=0, today=None):
    today = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.now().normalize()
    if (period or "").upper() == "YOY":
        selected_year = year or today.year
        if not isinstance(selected_year, int) or not 1900 <= selected_year <= today.year:
            raise HTTPException(status_code=422, detail="조회 가능한 연도를 선택하세요.")
        return pd.Timestamp(selected_year, 1, 1), min(pd.Timestamp(selected_year, 12, 31), today)
    months = _PERIOD_MONTHS.get((period or "").upper())
    return (today - pd.DateOffset(months=months) if months else None), None


def _available_years(orders):
    current_year = pd.Timestamp.now().year
    first_year = current_year
    for order in orders:
        try:
            date = pd.Timestamp((order.get("execution") or {}).get("filledAt") or order.get("orderedAt"))
            if pd.notna(date) and 1900 <= date.year <= current_year:
                first_year = min(first_year, date.year)
        except (TypeError, ValueError):
            continue
    return list(range(current_year, first_year - 1, -1))


def _twr_growth_series(twr, period=""):
    """TWR 비교 DF를 기간 필터 후 시작=100 기준으로 월별 rebase한 (portfolio, sp500) 시리즈."""
    if twr is None or twr.empty:
        return None, None
    n = _PERIOD_MONTHS.get((period or "").upper())
    if n:
        cut = pd.Timestamp.now().normalize() - pd.DateOffset(months=n)
        twr = twr[twr.index >= cut]
    if twr.empty:
        return None, None
    p = twr["내 수익률(%)"]
    s = twr["S&P500 수익률(%)"]
    p0, s0 = p.iloc[0], s.iloc[0]
    pl = 100 * (1 + p / 100) / (1 + p0 / 100)
    sl = 100 * (1 + s / 100) / (1 + s0 / 100)
    return pl.resample("ME").last().dropna(), sl.resample("ME").last().dropna()


def _pdf_to_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


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


# React 앱(/app) 전용 JSON API
@app.post("/api/app/login")
async def api_app_login(request: Request):
    body = await request.json()
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    ok, message = auth.verify_user(username, password)
    if ok:
        request.session["user"] = username
        return JSONResponse({"ok": True, "user": username})
    return JSONResponse({"ok": False, "error": message or "로그인 실패"}, status_code=401)


@app.post("/api/app/register")
async def api_app_register(request: Request):
    body = await request.json()
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    ok, message = auth.register_user(username, password)
    if ok:
        request.session["user"] = username  # 가입 즉시 자동 로그인
        return JSONResponse({"ok": True, "user": username})
    return JSONResponse({"ok": False, "error": message or "회원가입 실패"}, status_code=400)


@app.post("/api/app/logout")
def api_app_logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})


@app.get("/api/app/me")
def api_app_me(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    return JSONResponse({"ok": True, "user": user})


def _daily_metrics_path(user):
    return os.path.join(auth.user_dir(user), "daily_metrics.json")


def _load_daily_metrics(user):
    p = _daily_metrics_path(user)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def _save_daily_metrics(user, date_str, snapshot):
    """오늘 지표 스냅샷을 저장(날짜별 upsert, 최근 120일치 보관)."""
    data = _load_daily_metrics(user)
    data[date_str] = snapshot
    if len(data) > 120:
        for k in sorted(data.keys())[:-120]:
            data.pop(k, None)
    try:
        with open(_daily_metrics_path(user), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _analysis_status(frame, cutoff=None):
    attributes = frame.attrs if frame is not None else {}
    warnings = list(attributes.get("warnings", []))
    included = list(attributes.get("included_symbols", []))
    excluded = list(attributes.get("excluded_symbols", []))
    if frame is None or frame.empty:
        status = "unavailable" if warnings else "no_data"
        if not warnings:
            warnings.append("분석할 거래 이력이 없습니다.")
    elif cutoff is not None and frame.loc[frame.index >= cutoff].empty:
        status = "no_period_data"
        warnings.append("선택기간에 분석할 데이터가 없습니다.")
    elif profit_from_growth(frame, cutoff).get("returnPct") is None:
        status = "no_period_data"
        warnings.append("선택기간에 분석 가능한 투자 자산이나 매수 이력이 없습니다.")
    else:
        status = "partial" if excluded else "complete"
    return {"status": status, "includedSymbols": included, "excludedSymbols": excluded,
            "warnings": warnings, "asOf": frame.index[-1].strftime("%Y-%m-%d") if frame is not None and not frame.empty else None,
            "priceDates": attributes.get("price_dates", {}),
            "benchmarkAsOf": attributes.get("benchmark_price_date")}


def _account_balances(data):
    def amount(value):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    fx_rate = amount(data.get("fx_rate"))
    if fx_rate is not None and fx_rate <= 0:
        fx_rate = None

    def bucket(krw, usd):
        total = None
        if krw is not None and usd is not None and (fx_rate is not None or usd == 0):
            total = krw + usd * (fx_rate or 0)
        return {"krw": round(krw, 2) if krw is not None else None,
                "usd": round(usd, 2) if usd is not None else None,
                "totalKrw": round(total, 2) if total is not None else None}

    summary = data.get("summary") or {}
    cash_krw = amount(summary.get("cash_krw_native"))
    cash_usd = amount(summary.get("cash_usd_native"))
    if summary.get("cash_available") is False:
        cash_krw = cash_usd = None
    invested = {"KRW": 0.0, "USD": 0.0}
    for holding in data.get("holdings") or []:
        currency = str(holding.get("currency") or "KRW").upper()
        if currency not in invested:
            continue
        value = amount(holding.get("eval_native"))
        if value is None:
            value = amount(holding.get("eval_krw"))
            if currency == "USD":
                value = value / fx_rate if value is not None and fx_rate is not None else None
        if value is None or invested[currency] is None:
            invested[currency] = None
        else:
            invested[currency] += value
    total_krw = cash_krw + invested["KRW"] if cash_krw is not None and invested["KRW"] is not None else None
    total_usd = cash_usd + invested["USD"] if cash_usd is not None and invested["USD"] is not None else None
    return {"cash": bucket(cash_krw, cash_usd), "invested": bucket(invested["KRW"], invested["USD"]),
            "total": bucket(total_krw, total_usd), "fxRate": fx_rate}


@app.get("/api/app/dashboard")
def api_app_dashboard(request: Request, div: int = 1, fx: int = 1, ticker: str = "", period: str = "", year: int = 0):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    cutoff, period_end = _period_bounds(period, year)
    data = get_portfolio(user, include_div=bool(div), include_fx=bool(fx))
    summary = data["summary"] or {}
    perf = data["perf"] or {}
    fx_rate = data["fx_rate"]
    name_map = data["name_map"]
    frames = {}

    def analysis_frame(symbol, with_fx):
        key = (symbol, with_fx)
        if key not in frames:
            frames[key] = pipeline.growth_frame(data["combined_orders"], fx_rate, symbol,
                                                 include_div=bool(div), include_fx=with_fx, end=period_end)
        return frames[key]
    sa = data.get("stock_analytics")
    sa_map = {str(r["티커"]): r for r in sa.to_dict("records")} if (sa is not None and not sa.empty) else {}
    stocks = []
    current_values = {}
    per_fx = _per_ticker_fx(data["combined_orders"], fx_rate) if data["combined_orders"] else {}
    for r in _df_records(data["breakdown"]):
        tk = str(r.get("티커"))
        a = sa_map.get(tk)
        buy = float(r.get("투자원금(원)") or 0)
        upnl = float(r.get("평가손익(원)") or 0)
        cur = r.get("통화", "KRW")
        _pf = per_fx.get(tk)
        avg_fx = _pf["avg_fx"] if (cur == "USD" and _pf) else None
        if cur == "USD":
            avg_price = float(r.get("평단가(달러)") or 0)
            avg_price_krw = float(r.get("평단가(원화)") or 0)
        else:
            avg_price = float(r.get("평단가(원화)") or 0)
            avg_price_krw = avg_price
        # 순수 주가손익(원, 환차 제외) = 달러 평가손익 × 매수평균환율 → 달러 수익률과 일관
        upnl_native = float(r.get("평가손익(달러)") or 0)
        if cur == "USD" and avg_fx:
            pure_krw = upnl_native * avg_fx
            fx_pnl_stock = upnl - pure_krw
        else:
            pure_krw = upnl
            fx_pnl_stock = 0.0
        display_upnl = pure_krw if (cur == "USD" and not bool(fx)) else upnl  # 환차 토글 반영
        current_values[tk] = buy + display_upnl
        stocks.append({
            "ticker": tk, "name": name_map.get(tk) or r.get("종목") or tk,
            "currency": cur, "quantity": float(r.get("보유수량") or 0),
            "currentPrice": (a.get("현재주가") if a else None),
            "avgPrice": avg_price, "avgPriceKrw": avg_price_krw,
            "avgBuyFx": (round(avg_fx, 1) if avg_fx else None),
            "buyTotal": buy, "currentTotal": buy + display_upnl, "unrealizedPnL": display_upnl,
            "pureStockKrw": round(pure_krw), "fxPnLStock": round(fx_pnl_stock if bool(fx) else 0),
            "realizedPnL": float(r.get("실현손익(원)") or 0),
            "dividend": float(r.get("누적배당금(원)") or 0),
            "returnPct": float(r.get("수익률(%)") or 0), "status": r.get("상태", ""),
        })
        stock_profit = profit_from_growth(analysis_frame(tk, bool(fx)), cutoff)
        pure_profit = profit_from_growth(analysis_frame(tk, False), cutoff)
        stock_analysis = _analysis_status(analysis_frame(tk, bool(fx)), cutoff)
        if stock_analysis["status"] not in ("complete", "partial"):
            stock_profit = {}
        if stock_profit:
            stocks[-1].update(buyTotal=stock_profit["totalBuy"], currentTotal=stock_profit["totalCurrent"],
                              unrealizedPnL=stock_profit["unrealizedPnL"], realizedPnL=stock_profit["realizedPnL"],
                              dividend=stock_profit["dividendPnL"], returnPct=stock_profit["returnPct"],
                              pureStockKrw=pure_profit.get("unrealizedPnL"),
                              fxPnLStock=stock_profit["unrealizedPnL"] - pure_profit["unrealizedPnL"] if pure_profit else None)
        else:
            stocks[-1].update(unrealizedPnL=None, realizedPnL=None, dividend=None,
                              returnPct=None, pureStockKrw=None, fxPnLStock=None)
            if period_end is not None:
                closing = profit_from_growth(analysis_frame(tk, bool(fx)))
                stocks[-1].update(currentTotal=closing.get("totalCurrent"), buyTotal=closing.get("totalBuy"))
        stocks[-1]["analysis"] = stock_analysis
        closing = profit_from_growth(analysis_frame(tk, bool(fx)))
        holding_cost = closing.get("totalBuy")
        holding_pnl = closing["totalCurrent"] - holding_cost if holding_cost is not None else None
        stocks[-1].update(holdingUnrealizedPnL=holding_pnl,
                  holdingReturnPct=holding_pnl / holding_cost * 100 if holding_cost and holding_cost > 0 else None)
    holdings = data["holdings"]
    allocation = [{"name": (h.get("name") or h.get("ticker")), "value": round(float(h.get("weight_pct") or 0), 1)}
                  for h in holdings if float(h.get("weight_pct") or 0) > 0]
    metrics = {
        "totalAsset": summary.get("total_asset_krw") or 0,
        "totalCurrent": summary.get("stock_eval_krw") or 0,
        "cash": (summary.get("cash_krw_native") or 0) + (summary.get("cash_usd_native") or 0) * fx_rate,
        "totalBuy": perf.get("invested_krw") or 0,
        "unrealizedPnL": perf.get("unreal_total_krw") or 0,
        "realizedPnL": perf.get("realized_total_krw") or 0,
        "dividendPnL": perf.get("div_krw") or 0,
        "fxPnL": perf.get("fx_total_krw") or 0,
        "pureStockPnL": perf.get("pure_price_krw") or 0,
        "totalPnL": perf.get("all_inclusive_krw") or 0,
        "returnPct": perf.get("all_inclusive_pct") or 0,
    }
    all_tickers = [{"ticker": s["ticker"], "name": s["name"]} for s in stocks]
    if ticker:
        sel = [x for x in stocks if x["ticker"] == ticker]
        if sel:
            s0 = sel[0]
            components = [s0["unrealizedPnL"], s0["realizedPnL"], s0["dividend"]]
            _tp = sum(components) if all(value is not None for value in components) else None
            metrics = {
                "totalAsset": current_values[ticker] if period_end is not None else s0["currentTotal"], "totalCurrent": s0["currentTotal"], "cash": 0,
                "totalBuy": s0["buyTotal"], "unrealizedPnL": s0["unrealizedPnL"],
                "realizedPnL": s0["realizedPnL"], "dividendPnL": s0["dividend"], "fxPnL": s0["fxPnLStock"],
                "pureStockPnL": s0["pureStockKrw"], "totalPnL": _tp,
                "returnPct": s0["returnPct"],
            }
            stocks = sel
            allocation = [{"name": s0["name"], "value": 100.0}]
    frame = analysis_frame(ticker or None, bool(fx))
    analysis = _analysis_status(frame, cutoff)
    profit = profit_from_growth(frame, cutoff)
    pure_profit = profit_from_growth(analysis_frame(ticker or None, False), cutoff)
    if analysis["status"] not in ("complete", "partial"):
        profit = {}
    if profit:
        metrics.update(profit)
        metrics["pureStockPnL"] = pure_profit["totalPnL"] - pure_profit["dividendPnL"] if pure_profit else None
        metrics["fxPnL"] = profit["totalPnL"] - profit["dividendPnL"] - metrics["pureStockPnL"] if pure_profit else None
    else:
        metrics.update(totalPnL=None, realizedPnL=None, unrealizedPnL=None, dividendPnL=None,
                       pureStockPnL=None, fxPnL=None, returnPct=None)
        if period_end is not None:
            closing = profit_from_growth(frame)
            metrics.update(totalCurrent=closing.get("totalCurrent"), totalBuy=closing.get("totalBuy"))
    metrics["xirr"] = xirr_from_growth(frame, cutoff)
    closing = profit_from_growth(frame)
    holding_cost = closing.get("totalBuy")
    metrics["holdingReturnPct"] = ((closing["totalCurrent"] - holding_cost) / holding_cost * 100
                                   if holding_cost and holding_cost > 0 else None)
    projection_frame = pipeline.growth_frame(data["combined_orders"], fx_rate, ticker or None,
                                               include_div=bool(div), include_fx=bool(fx)) if period_end is not None else frame
    metrics["projectionRate"] = xirr_from_growth(projection_frame) if not projection_frame.attrs.get("excluded_symbols") else None
    stats = comparison_statistics(frame, cutoff)
    indexed = (1.0 + stats["daily"]).cumprod() * 100
    if analysis["status"] not in ("complete", "partial"):
        indexed = pd.DataFrame()
    growth = [{"month": date.strftime("%y/%m"), "portfolio": round(float(row["portfolio"]), 2),
               "sp500": round(float(row["sp500"]), 2)} for date, row in indexed.resample("ME").last().iterrows()] if not indexed.empty else []
    # 전일 대비 변동(전체 포트 기준): 오늘 값을 저장하고 직전 저장일과 비교
    changes = None
    if not ticker and bool(div) and bool(fx) and period_end is None:
        try:
            sa2 = data.get("stock_analytics")
            stocks_ab = {}
            if sa2 is not None and not sa2.empty:
                for _r in sa2.to_dict("records"):
                    stocks_ab[str(_r.get("티커"))] = {
                        "alpha": round(float(_r.get("알파(연%)") or 0), 2),
                        "beta": round(float(_r.get("베타") or 0), 3),
                    }
            today_str = datetime.now().strftime("%Y-%m-%d")
            dm = _load_daily_metrics(user)
            prev_dates = [dd for dd in dm.keys() if dd < today_str]
            prev = dm.get(max(prev_dates)) if prev_dates else None
            _save_daily_metrics(user, today_str, {"totalAsset": metrics["totalAsset"], "stocks": stocks_ab})
            if prev:
                ta_prev = float(prev.get("totalAsset") or 0)
                st = []
                for _tk, _ab in stocks_ab.items():
                    _pab = (prev.get("stocks") or {}).get(_tk)
                    if not _pab:
                        continue
                    st.append({
                        "ticker": _tk, "name": name_map.get(_tk) or _tk,
                        "alpha": _ab["alpha"], "beta": _ab["beta"],
                        "alphaDelta": round(_ab["alpha"] - float(_pab.get("alpha") or 0), 2),
                        "betaDelta": round(_ab["beta"] - float(_pab.get("beta") or 0), 3),
                    })
                changes = {
                    "asOf": max(prev_dates),
                    "totalAssetDelta": round(metrics["totalAsset"] - ta_prev),
                    "totalAssetDeltaPct": round((metrics["totalAsset"] - ta_prev) / ta_prev * 100, 2) if ta_prev else None,
                    "stocks": st,
                }
        except Exception:
            changes = None
    return JSONResponse({"metrics": metrics, "stocks": stocks, "allocation": allocation, "fx": fx_rate,
                         "growth": growth, "tickers": all_tickers, "changes": changes, "analysis": analysis,
                         "years": _available_years(data["combined_orders"]), "accountBalances": _account_balances(data)})


@app.get("/api/app/tickers")
def api_app_tickers(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    bd = data["breakdown"]
    nm = data["name_map"]
    out = []
    if bd is not None and not bd.empty:
        for r in bd.to_dict("records"):
            tk = str(r.get("티커"))
            out.append({"ticker": tk, "name": nm.get(tk) or r.get("종목") or tk})
    return JSONResponse({"tickers": out})


@app.get("/api/app/transactions")
def api_app_transactions(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    detail_df = data["detail_df"]
    src = (detail_df.sort_values("체결일시", ascending=False)
           if (detail_df is not None and not detail_df.empty) else detail_df)
    txs = []
    for r in _df_records(src, limit=500):
        gubun = str(r.get("구분") or "")
        txs.append({
            "date": r.get("날짜"), "ticker": str(r.get("티커") or ""),
            "name": r.get("종목명") or "", "type": "buy" if gubun == "매수" else "sell",
            "quantity": float(r.get("수량") or 0), "price": float(r.get("체결단가") or 0),
            "currency": r.get("통화") or "KRW", "amount": float(r.get("체결금액(원)") or 0),
            "broker": r.get("증권사") or "",
        })
    divs = []
    _nm = data["name_map"]
    for d in (data["dividends_rows"] or []):
        gubun = str(d.get("구분") or "")
        _tk = str(d.get("티커") or "")
        _dnm = d.get("종목") or ""
        if not _dnm or _dnm == _tk:
            _dnm = _nm.get(_tk) or _dnm or _tk
        divs.append({
            "date": d.get("일자") or "", "ticker": _tk,
            "name": _dnm, "amount": float(d.get("배당금") or 0),
            "currency": d.get("통화") or "KRW", "amountKRW": float(d.get("원화환산") or 0),
            "verified": gubun.startswith("검증"), "status": gubun,
        })
    return JSONResponse({"transactions": txs, "dividends": divs})


# ─── React 앱 전용: 임포트(수동) 거래·배당 편집 (토스 원본은 읽기전용) ───
@app.get("/api/app/edit/data")
def api_app_edit_data(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    data = get_portfolio(user)

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    tx = read_transactions_csv()
    tx_rows = []
    if tx is not None and not tx.empty:
        for r in tx.fillna("").to_dict("records"):
            tx_rows.append({
                "date": str(r.get("일자") or ""), "ticker": str(r.get("티커") or ""),
                "name": str(r.get("종목명") or ""), "market": str(r.get("시장") or ""),
                "type": "sell" if str(r.get("구분")) == "매도" else "buy",
                "quantity": _num(r.get("수량")), "price": _num(r.get("단가")),
                "currency": str(r.get("통화") or "KRW"), "broker": str(r.get("증권사") or ""),
            })
    dv = read_dividends_csv()
    div_rows = []
    if dv is not None and not dv.empty:
        for r in dv.fillna("").to_dict("records"):
            div_rows.append({
                "date": str(r.get("일자") or ""), "ticker": str(r.get("티커") or ""),
                "name": str(r.get("종목명") or ""), "currency": str(r.get("통화") or "KRW"),
                "amount": _num(r.get("배당금")), "broker": str(r.get("증권사") or ""),
            })
    est = []
    for r in (data.get("dividends_rows") or []):
        if str(r.get("구분", "")).startswith("추정"):
            est.append({
                "date": str(r.get("일자") or ""), "ticker": str(r.get("티커") or ""),
                "name": r.get("종목") or "", "currency": r.get("통화") or "KRW",
                "amount": _num(r.get("배당금")),
            })
    snaps = [{"id": s["id"], "label": s.get("label") or "", "time": s.get("time") or "",
              "tx": s.get("counts", {}).get("manual_transactions.csv", 0),
              "div": s.get("counts", {}).get("manual_dividends.csv", 0)}
             for s in list_snapshots()]
    return JSONResponse({"transactions": tx_rows, "dividends": div_rows,
                         "estimatedDividends": est, "snapshots": snaps})


@app.post("/api/app/edit/transactions")
async def api_app_edit_transactions(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    payload = await request.json()
    rows = payload.get("rows", [])
    snapshot_imports("거래 편집 전")
    out = [{
        "증권사": str(r.get("broker") or "").strip(),
        "일자": str(r.get("date") or "").strip(),
        "티커": str(r.get("ticker") or "").strip(),
        "종목명": str(r.get("name") or "").strip(),
        "시장": str(r.get("market") or "").strip(),
        "구분": "매도" if str(r.get("type")) == "sell" else "매수",
        "수량": r.get("quantity") or 0,
        "단가": r.get("price") or 0,
        "통화": str(r.get("currency") or "KRW").upper(),
    } for r in rows]
    df = pd.DataFrame(out, columns=TX_COLUMNS) if out else pd.DataFrame(columns=TX_COLUMNS)
    n = write_transactions_csv(df)
    _CACHE.pop(user, None)
    return JSONResponse({"ok": True, "count": n})


@app.post("/api/app/edit/dividends")
async def api_app_edit_dividends(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    payload = await request.json()
    rows = payload.get("rows", [])
    snapshot_imports("배당 편집 전")
    out = [{
        "증권사": str(r.get("broker") or "").strip(),
        "일자": str(r.get("date") or "").strip(),
        "티커": str(r.get("ticker") or "").strip(),
        "종목명": str(r.get("name") or "").strip(),
        "통화": str(r.get("currency") or "KRW").upper(),
        "배당금": r.get("amount") or 0,
    } for r in rows]
    df = pd.DataFrame(out, columns=DIV_COLUMNS) if out else pd.DataFrame(columns=DIV_COLUMNS)
    n = write_dividends_csv(df)
    _CACHE.pop(user, None)
    return JSONResponse({"ok": True, "count": n})


@app.post("/api/app/edit/restore")
async def api_app_edit_restore(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    payload = await request.json()
    snap_id = str(payload.get("snapId") or "").strip()
    n = restore_snapshot(snap_id)
    _CACHE.pop(user, None)
    return JSONResponse({"ok": bool(n)})


def _per_ticker_fx(orders, fx):
    tickers = {o.get("symbol") for o in orders if o.get("currency") == "USD"}
    out = {}
    for tk in tickers:
        sub = [o for o in orders if o.get("symbol") == tk]
        r = compute_usd_avg_cost(sub, fx)
        if r:
            out[tk] = r
    return out


@app.get("/api/app/fx")
def api_app_fx(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    orders = data["combined_orders"]
    fx = data["fx_rate"]
    usd = compute_usd_avg_cost(orders, fx) if orders else None
    avg_buy_fx = (usd or {}).get("avg_fx")
    history = []
    frame = build_usdkrw_history_frame("5y")
    if frame is not None and not frame.empty:
        monthly = frame["원/달러"].resample("ME").last().dropna()
        for dt, v in monthly.items():
            row = {"month": dt.strftime("%y/%m"), "fx": round(float(v), 1)}
            if avg_buy_fx:
                row["avgBuy"] = round(float(avg_buy_fx), 1)
            history.append(row)
    per_fx = _per_ticker_fx(orders, fx) if orders else {}
    fx_stocks = []
    for h in data["holdings"]:
        if h.get("currency") == "USD":
            r = per_fx.get(h.get("ticker"))
            eval_krw = float(h.get("eval_krw") or 0)
            fx_stocks.append({
                "ticker": h.get("ticker"), "name": h.get("name"),
                "avgBuyFx": round(r["avg_fx"], 1) if r else None,
                "evalKrw": eval_krw, "fxPnL": (r["fx_pnl_krw"] if r else 0.0),
            })
    return JSONResponse({
        "currentFx": fx, "avgBuyFx": avg_buy_fx,
        "fxPnlTotal": (usd or {}).get("fx_pnl_krw") or 0,
        "history": history, "stocks": fx_stocks,
    })


def _benchmark_view(frame, period="", year=0):
    cutoff, period_end = _period_bounds(period, year)
    if frame is not None and not frame.empty and period_end is not None:
        frame = frame.loc[frame.index <= period_end]
    stats = comparison_statistics(frame, cutoff)
    summary = {"portfolioReturn": None, "sp500Return": None, "alpha": None,
               "beta": stats["beta"], "corr": stats["corr"], "sharpe": stats["sharpe"],
               "regressionAlpha": stats["regression_alpha"],
               "twrReturn": round(stats["twr"], 2) if stats["twr"] is not None else None}
    analysis = _analysis_status(frame, cutoff)
    result = {"summary": summary, "growth": [], "rollingBeta": [], "monthlyAlpha": [],
              "warnings": analysis["warnings"], "analysis": analysis}
    if stats["returns"].empty or analysis["status"] not in ("complete", "partial"):
        return result
    selected = frame.loc[stats["returns"].index]
    monthly = selected.resample("ME").last()
    returns = stats["returns"].resample("ME").last()
    rolling = stats["rolling_beta"].resample("ME").last()
    for date, row in monthly.iterrows():
        mine = returns.loc[date, "portfolio"]
        spy = returns.loc[date, "sp500"]
        beta = rolling.get(date)
        result["growth"].append({
            "month": date.strftime("%y/%m"), "portfolio": round(float(row["내 자산가치"])),
            "sp500": round(float(row["S&P500 자산가치"])), "principal": round(float(row["순투자원금"])),
            "portfolioPct": round(float(mine), 2) if pd.notna(mine) else None,
            "sp500Pct": round(float(spy), 2) if pd.notna(spy) else None,
            "alpha": round(float(mine - spy), 2) if pd.notna(mine) and pd.notna(spy) else None,
            "beta": round(float(beta), 3) if pd.notna(beta) else None,
        })
    last = result["growth"][-1]
    summary.update(portfolioReturn=last["portfolioPct"], sp500Return=last["sp500Pct"], alpha=last["alpha"])
    result["rollingBeta"] = [{"month": date.strftime("%y/%m"), "beta": round(float(value), 3)}
                             for date, value in rolling.dropna().items()]
    monthly_returns = ((1.0 + stats["daily"]).resample("ME").prod() - 1.0) * 100
    result["monthlyAlpha"] = [{"month": date.strftime("%y/%m"), "alpha": round(float(row["portfolio"] - row["sp500"]), 2)}
                              for date, row in monthly_returns.iterrows()]
    return result


@app.get("/api/app/benchmark")
def api_app_benchmark(request: Request, div: int = 1, fx: int = 1, start: str = "", ticker: str = "", period: str = "", year: int = 0):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    cutoff, period_end = _period_bounds(period, year)
    data = get_portfolio(user, include_div=bool(div), include_fx=bool(fx))
    orders = data["combined_orders"]
    fxr = data["fx_rate"]
    if not orders:
        return JSONResponse({"error": "no_data"}, status_code=404)
    tkr = ticker or None
    gdf = pipeline.growth_frame(orders, fxr, tkr, include_div=bool(div), include_fx=bool(fx), end=period_end)
    result = _benchmark_view(gdf, period, year)
    per_stock = []
    symbols = [tkr] if tkr else sorted({order.get("symbol") for order in orders if order.get("symbol")})
    for symbol in symbols:
        frame = gdf if symbol == tkr else pipeline.growth_frame(orders, fxr, symbol, include_div=bool(div), include_fx=bool(fx), end=period_end)
        stats = comparison_statistics(frame, cutoff)
        if stats["returns"].empty:
            continue
        value = stats["returns"]["portfolio"].iloc[-1]
        per_stock.append({"ticker": symbol, "name": (data.get("name_map") or {}).get(symbol, symbol),
                          "returnPct": round(float(value), 2) if pd.notna(value) else None,
                          "alpha": stats["regression_alpha"], "beta": stats["beta"],
                          "alphaContrib": None, "betaContrib": None,
                          "weightValue": max(float(frame["내 자산가치"].iloc[-1]), 0.0)})
    alpha_total = sum(abs(row["weightValue"] * row["alpha"]) for row in per_stock if row["alpha"] is not None)
    beta_total = sum(abs(row["weightValue"] * row["beta"]) for row in per_stock if row["beta"] is not None)
    for row in per_stock:
        weight = row.pop("weightValue")
        row["alphaContrib"] = weight * row["alpha"] / alpha_total * 100 if alpha_total and row["alpha"] is not None else None
        row["betaContrib"] = weight * row["beta"] / beta_total * 100 if beta_total and row["beta"] is not None else None

    simulation = None
    try:
        simulation_start = pd.Timestamp(start) if start else cutoff
        if cutoff is not None and simulation_start is not None:
            simulation_start = max(cutoff, simulation_start)
        _ts, _monthly, sim_summary = pipeline.spy_dca(orders, fxr, simulation_start, tkr,
                                                       include_div=bool(div), include_fx=bool(fx), end=period_end)
        if sim_summary:
            simulation = {
                "startYm": sim_summary.get("시작월"), "startKrw": sim_summary.get("시작금액"),
                "myProfit": sim_summary.get("내수익금"), "spyProfit": sim_summary.get("S&P500수익금"),
                "diff": sim_summary.get("차이"),
            }
    except Exception:
        simulation = None

    all_tickers = []
    _bd = data["breakdown"]
    if _bd is not None and not _bd.empty:
        _nm = data["name_map"] or {}
        for _r in _bd.to_dict("records"):
            _tk = str(_r.get("티커"))
            all_tickers.append({"ticker": _tk, "name": _nm.get(_tk) or _r.get("종목") or _tk})
    return JSONResponse({
        **result, "perStock": per_stock, "simulation": simulation,
        "tickers": all_tickers, "years": _available_years(orders),
    })


@app.get("/api/app/datasources")
def api_app_datasources(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = get_portfolio(user)
    detail_df = data["detail_df"]
    tx_count = int(len(detail_df)) if (detail_df is not None and not detail_df.empty) else 0
    div_count = len(data["dividends_rows"] or [])
    name_map = data["name_map"] or {}
    bd = data["breakdown"]
    tickers = [str(t) for t in bd["티커"].unique()] if (bd is not None and not bd.empty) else []
    mapped = sum(1 for t in tickers if name_map.get(t) and name_map.get(t) != t)
    sources = []
    if detail_df is not None and not detail_df.empty and "증권사" in detail_df.columns:
        vc = detail_df["증권사"].value_counts()
        sources = [{"name": str(k), "count": int(v)} for k, v in vc.items()]
    return JSONResponse({
        "tossConnected": auth.has_toss_credentials(user),
        "txCount": tx_count, "divCount": div_count,
        "tickerCount": len(tickers), "mappedCount": mapped,
        "unmappedCount": len(tickers) - mapped, "sources": sources,
    })


@app.post("/api/app/import")
async def api_app_import(request: Request, broker: str = Form("증권사"),
                        files: list[UploadFile] = File(default=[])):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from ai_copilot import parse_brokerage_full_transactions, parse_brokerage_dividends
    from manual_holdings import save_parsed_transactions, save_parsed_dividends
    pipeline.apply_credentials(user)
    raw_texts = []
    for up in (files or []):
        try:
            content = await up.read()
            fn = (up.filename or "").lower()
            if fn.endswith((".xlsx", ".xls")):
                raw_texts.append(pd.read_excel(io.BytesIO(content)).to_csv(index=False))
            elif fn.endswith(".pdf"):
                t = _pdf_to_text(content)
                if t.strip():
                    raw_texts.append(t)
            else:
                raw_texts.append(content.decode("utf-8", errors="ignore"))
        except Exception:
            continue
    if not raw_texts:
        return JSONResponse({"ok": False, "error": "업로드한 파일에서 내용을 읽지 못했습니다."}, status_code=400)
    rows, divs, errors = [], [], []
    for rt in raw_texts:
        parsed, err = parse_brokerage_full_transactions(rt, broker)
        if parsed:
            rows.extend(parsed)
        elif err:
            errors.append(err)
        dparsed, _derr = parse_brokerage_dividends(rt, broker)
        if dparsed:
            divs.extend(dparsed)
    if not rows and not divs:
        return JSONResponse({"ok": False, "error": (errors[0] if errors else "거래·배당 내역을 찾지 못했습니다.")}, status_code=502)
    n = save_parsed_transactions(rows, replace_broker=broker) if rows else 0
    dn = save_parsed_dividends(divs, replace_broker=broker) if divs else 0
    _CACHE.pop(user, None)
    return JSONResponse({"ok": True, "transactions": n, "dividends": dn,
                         "txPreview": rows[:30], "divPreview": divs[:30]})


@app.post("/api/app/datasources/clear")
def api_app_datasources_clear(request: Request, broker: str = Form("")):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    b = (broker or "").strip()
    if b:
        snapshot_imports(f"{b} 삭제 전")
        n = delete_broker_imports(b)
    else:
        snapshot_imports("전체 초기화 전")
        n = clear_all_imports()
    _CACHE.pop(user, None)
    return JSONResponse({"ok": True, "removed": n, "broker": b})


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
    hov = read_holdings_overrides()
    for rec in breakdown_records:
        tkey = str(rec.get("티커"))
        if name_map.get(tkey):
            rec["종목"] = name_map[tkey]
        a = sa_map.get(tkey)
        for c in _ana_cols:
            rec[c] = (a.get(c) if a else None)
        ov = hov.get(tkey)
        if ov and not ov.get("deleted"):
            rec["_ovr"] = True
            if ov.get("종목명"):
                rec["종목"] = ov["종목명"]
            if ov.get("현재가") not in (None, ""):
                rec["현재주가"] = float(ov["현재가"])

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


@app.get("/import/template.xlsx")
def import_template(request: Request):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from exporter import build_import_template_xlsx
    xlsx = build_import_template_xlsx()
    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="import_template.xlsx"'})


@app.post("/import/direct")
async def import_direct(request: Request, files: list[UploadFile] = File(default=[])):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from manual_holdings import import_template_xlsx
    pipeline.apply_credentials(user)
    snapshot_imports("직접 임포트 전")
    tx = dv = 0
    errs = []
    for up in files or []:
        if not (up.filename or "").lower().endswith((".xlsx", ".xls")):
            errs.append(f"{up.filename}: 엑셀(.xlsx) 파일만 지원합니다")
            continue
        content = await up.read()
        res = import_template_xlsx(content)
        tx += res["tx"]
        dv += res["div"]
        errs += res["errors"]
    _CACHE.pop(user, None)
    msg = f"직접 임포트 완료: 거래 {tx}건·배당 {dv}건 저장"
    if errs:
        msg += f" (경고 {len(errs)}건: " + "; ".join(errs[:3]) + ("…" if len(errs) > 3 else "") + ")"
    return RedirectResponse(f"/import?msg={msg}", status_code=302)


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


@app.post("/holdings/override")
async def holdings_override(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    payload = await request.json()
    rows = payload.get("rows", [])
    ovr = read_holdings_overrides()
    snapshot_imports("보유 수정 전")
    changed = 0
    for r in rows:
        tk = str(r.get("티커") or "").strip()
        if not tk:
            continue
        if r.get("_delete"):
            ovr[tk] = {"deleted": True}
            changed += 1
            continue
        try:
            qty = float(r.get("수량") or 0)
            price = float(r.get("평단가") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or price <= 0:
            continue
        entry = {"종목명": str(r.get("종목명") or "").strip(),
                 "수량": qty, "평단가": price,
                 "통화": str(r.get("통화") or "KRW").upper()}
        cur_price = r.get("현재가")
        if cur_price not in (None, ""):
            try:
                entry["현재가"] = float(cur_price)
            except (TypeError, ValueError):
                pass
        ovr[tk] = entry
        changed += 1
    write_holdings_overrides(ovr)
    _CACHE.pop(user, None)
    return JSONResponse({"ok": True, "count": changed})


@app.post("/holdings/override/reset")
async def holdings_override_reset(request: Request):
    user = _current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pipeline.apply_credentials(user)
    payload = await request.json()
    tk = str(payload.get("티커") or "").strip()
    ovr = read_holdings_overrides()
    if tk:
        if tk in ovr:
            snapshot_imports("보유 수정 되돌리기 전")
            del ovr[tk]
            write_holdings_overrides(ovr)
            _CACHE.pop(user, None)
        return JSONResponse({"ok": True})
    snapshot_imports("보유 수정 전체 초기화 전")
    write_holdings_overrides({})
    _CACHE.pop(user, None)
    return JSONResponse({"ok": True})


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
