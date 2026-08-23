"""Streamlit 비의존 데이터 파이프라인.

웹앱(FastAPI)과 배치 스크립트에서 재사용할 수 있도록, app.py의 데이터 취합 로직을
순수 함수로 옮긴 모듈입니다. 토스 API + 임포트 데이터를 합쳐 요약/보유/성과/배당을 계산합니다.
"""
import os

import pandas as pd

from pm import (
    get_access_token, get_holdings, get_buying_power, get_exchange_rate,
    get_order_history, get_stock_info,
)
from analytics_engine import transform_to_mvp_json, build_transaction_detail
from benchmark import get_usdkrw_history
from manual_holdings import (
    set_data_dir, load_manual_holdings, manual_to_orders,
    read_manual_csv, read_transactions_csv, read_dividends_csv,
    transactions_to_orders, derive_holdings_from_tx,
    read_toss_overrides, write_toss_overrides,
)
from performance import compute_performance_summary, build_holdings_breakdown
from advanced_analytics import compute_dividends, compute_dividend_events
from pme import (
    compute_alpha_beta, build_total_profit_growth, build_ticker_profit_growth,
    build_trade_bars, build_asset_value_growth, build_stock_analytics, compute_rolling_beta,
    build_spy_dca,
)
import auth
from names import enrich_name_map


def current_usdkrw():
    s = get_usdkrw_history("5d")
    return float(s.iloc[-1]) if (s is not None and not s.empty) else 1421.0


def empty_portfolio(user, fx=1400.0):
    return {
        "user_profile": {"user_id": user, "target_benchmark": "S&P 500"},
        "asset_summary": {"total_asset_krw": 0, "stock_eval_krw": 0, "purchase_krw": 0,
                          "cash_krw": 0, "cash_krw_native": 0, "cash_usd_native": 0, "fx_rate": fx},
        "holdings": [],
    }


def apply_credentials(user):
    """저장된 사용자 API 키를 os.environ에 주입하고 데이터 폴더를 설정합니다."""
    set_data_dir(auth.user_dir(user))
    creds = auth.load_credentials(user)
    for k in auth.CRED_KEYS:
        v = creds.get(k)
        if v:
            os.environ[k] = str(v)
    return creds


def toss_portfolio(creds, account="1"):
    """토스 계좌/자산 요약(JSON)과 에러메시지를 반환합니다."""
    cid = creds.get("TOSS_CLIENT_ID")
    sec = creds.get("TOSS_CLIENT_SECRET")
    acc = str(creds.get("TOSS_ACCOUNT_NO", account) or account)
    if not (cid and sec):
        return None, "토스 API 키가 설정되어 있지 않습니다."
    token = get_access_token(cid, sec)
    if not token:
        return None, "토스증권 API 토큰 발급에 실패했습니다. API 키와 등록 IP를 확인하세요."
    toss_data = get_holdings(token, acc)
    if not toss_data:
        return None, "계좌·자산 데이터를 불러오지 못했습니다."
    krw_cash = get_buying_power(token, acc, "KRW")
    usd_cash = get_buying_power(token, acc, "USD")
    fx = get_exchange_rate(token)
    cash_krw = krw_cash + usd_cash * fx
    pj = transform_to_mvp_json("usr_web", toss_data, cash_krw, fx)
    pj.setdefault("asset_summary", {})
    pj["asset_summary"]["cash_krw_native"] = krw_cash
    pj["asset_summary"]["cash_usd_native"] = usd_cash
    pj["asset_summary"]["fx_rate"] = fx
    return pj, None


def toss_trades(creds, account="1"):
    """토스 체결내역 상세/원본주문/환율/종목명맵을 반환합니다."""
    cid = creds.get("TOSS_CLIENT_ID")
    sec = creds.get("TOSS_CLIENT_SECRET")
    acc = str(creds.get("TOSS_ACCOUNT_NO", account) or account)
    token = get_access_token(cid, sec) if (cid and sec) else None
    if not token:
        return pd.DataFrame(), [], 0.0, {}
    fx = get_exchange_rate(token)
    orders = get_order_history(token, acc)
    holdings_data = get_holdings(token, acc) or {}
    name_map = {i.get("symbol"): i.get("name") for i in holdings_data.get("result", {}).get("items", [])}
    detail = build_transaction_detail(orders, fx, name_map)
    return detail, orders, fx, name_map


# ─────────────────── 토스 거래 직접 수정(오버라이드 레이어) ───────────────────
TOSS_OVR_FIELDS = ["일자", "티커", "종목명", "구분", "수량", "단가", "통화"]


def toss_trade_key(o):
    """토스 주문의 안정적 식별키(심볼|체결시각|매매구분|수량|금액). 새로고침해도 동일."""
    ex = o.get("execution") or {}
    raw = ex.get("filledAt") or o.get("orderedAt") or ""
    return "|".join(str(x) for x in [o.get("symbol"), raw, o.get("side"),
                                     ex.get("filledQuantity"), ex.get("filledAmount")])


def toss_display_row(o, name_map=None):
    """토스 주문을 편집 표에 보여줄 표준 dict(증권사·일자·티커·종목명·시장·구분·수량·단가·통화)로 변환."""
    name_map = name_map or {}
    ex = o.get("execution") or {}
    raw = ex.get("filledAt") or o.get("orderedAt") or ""
    try:
        d = pd.to_datetime(raw).tz_localize(None).strftime("%Y-%m-%d")
    except Exception:
        try:
            d = pd.to_datetime(raw, utc=True).tz_localize(None).strftime("%Y-%m-%d")
        except Exception:
            d = ""
    sym = o.get("symbol")
    return {"증권사": o.get("broker", "토스증권"), "일자": d, "티커": sym,
            "종목명": name_map.get(sym, sym), "시장": "",
            "구분": "매도" if o.get("side") == "SELL" else "매수",
            "수량": float(ex.get("filledQuantity") or 0),
            "단가": float(ex.get("averageFilledPrice") or 0),
            "통화": o.get("currency", "KRW")}


def _override_to_order(orig, e):
    """오버라이드 dict(e)를 원본 주문(orig) 기반의 토스 주문으로 재구성합니다."""
    qty = float(e.get("수량") or 0)
    price = float(e.get("단가") or 0)
    d = str(e.get("일자") or "").strip()
    try:
        filled_at = pd.to_datetime(d).strftime("%Y-%m-%dT00:00:00+09:00")
    except Exception:
        filled_at = (orig.get("execution") or {}).get("filledAt") or orig.get("orderedAt")
    side = "SELL" if str(e.get("구분")) in ("매도", "SELL", "sell") else "BUY"
    ex = dict(orig.get("execution") or {})
    ex.update({"filledQuantity": qty, "averageFilledPrice": price,
               "filledAmount": qty * price, "filledAt": filled_at})
    out = dict(orig)
    out.update({"symbol": str(e.get("티커") or orig.get("symbol")),
                "currency": str(e.get("통화") or orig.get("currency", "KRW")).upper(),
                "side": side, "orderedAt": filled_at, "execution": ex, "_edited": True})
    return out


def apply_toss_overrides(orders, overrides=None):
    """토스 주문 리스트에 사용자 수정/삭제 오버라이드를 적용합니다."""
    overrides = read_toss_overrides() if overrides is None else overrides
    if not overrides:
        return list(orders)
    out = []
    for o in orders:
        e = overrides.get(toss_trade_key(o))
        if e is None:
            out.append(o)
        elif e.get("deleted"):
            continue
        else:
            out.append(_override_to_order(o, e))
    return out


def merge_manual_into_portfolio(portfolio_json, manual_df):
    """수동/타 증권사 보유를 포트폴리오에 병합. 같은 티커는 증권사 통합 합산."""
    if manual_df is None or manual_df.empty:
        return portfolio_json
    out = dict(portfolio_json)
    summary = dict(portfolio_json.get("asset_summary", {}))
    merged = {}
    for h in portfolio_json.get("holdings", []):
        tk = h.get("ticker")
        eval_krw = float(h.get("eval_krw", 0) or 0)
        ret = float(h.get("return_pct", 0) or 0)
        cost = eval_krw / (1 + ret / 100) if (1 + ret / 100) != 0 else eval_krw
        merged[tk] = {"ticker": tk, "name": h.get("name"), "currency": h.get("currency"),
                      "quantity": float(h.get("quantity", 0) or 0), "eval_krw": eval_krw,
                      "cost_krw": cost, "sector": h.get("sector", "Unknown"), "brokers": {"토스증권"}}
    add_eval = add_purchase = 0.0
    for _, r in manual_df.iterrows():
        tk = str(r.get("티커"))
        eval_krw = float(r.get("평가액(원)", 0) or 0)
        qty = float(r.get("수량", 0) or 0)
        avg = float(r.get("평균매수가", 0) or 0)
        cur = str(r.get("통화", "KRW")).upper()
        purchase_native = qty * avg
        if cur == "USD" and float(r.get("현재가", 0) or 0) > 0:
            fx_implied = eval_krw / (qty * float(r["현재가"])) if qty else 1
            purchase_krw = purchase_native * fx_implied
        else:
            purchase_krw = purchase_native
        add_eval += eval_krw
        add_purchase += purchase_krw
        broker = r.get("증권사", "타증권사")
        if tk in merged:
            m = merged[tk]
            m["quantity"] += qty
            m["eval_krw"] += eval_krw
            m["cost_krw"] += purchase_krw
            m["brokers"].add(broker)
        else:
            merged[tk] = {"ticker": tk, "name": r.get("종목명"), "currency": cur, "quantity": qty,
                          "eval_krw": eval_krw, "cost_krw": purchase_krw, "sector": "Unknown",
                          "brokers": {broker}}
    new_stock = sum(m["eval_krw"] for m in merged.values())
    holdings = []
    for m in merged.values():
        ret = (m["eval_krw"] / m["cost_krw"] - 1) * 100 if m["cost_krw"] else 0
        holdings.append({"ticker": m["ticker"], "name": m["name"], "currency": m["currency"],
                         "quantity": round(m["quantity"], 4), "eval_krw": round(m["eval_krw"]),
                         "weight_pct": round(m["eval_krw"] / new_stock * 100, 2) if new_stock else 0,
                         "sector": m["sector"], "return_pct": round(ret, 2),
                         "brokers": ", ".join(sorted(m["brokers"]))})
    holdings.sort(key=lambda x: x["weight_pct"], reverse=True)
    summary["stock_eval_krw"] = round(new_stock)
    base_total = float(portfolio_json.get("asset_summary", {}).get("total_asset_krw", 0) or 0)
    summary["total_asset_krw"] = round(base_total + add_eval)
    summary["purchase_krw"] = round(float(summary.get("purchase_krw", 0) or 0) + add_purchase)
    out["holdings"] = holdings
    out["asset_summary"] = summary
    return out


def _dividends(combined_orders, fx_rate, include_est=True):
    """검증(임포트) 배당 + (옵션) yfinance 추정 배당을 합산합니다.
    반환: (div_krw_native, div_usd_native, div_krw_by_ticker, rows[list])."""
    div_krw_native = div_usd_native = 0.0
    by_ticker = {}
    rows = []
    verified = set()
    recs = read_dividends_csv()
    if recs is not None and not recs.empty:
        for _, r in recs.iterrows():
            amt = float(r.get("배당금", 0) or 0)
            if amt <= 0:
                continue
            tk = str(r.get("티커"))
            is_usd = str(r.get("통화", "KRW")).upper() == "USD"
            krw = amt * fx_rate if is_usd else amt
            verified.add(tk)
            by_ticker[tk] = by_ticker.get(tk, 0.0) + krw
            if is_usd:
                div_usd_native += amt
            else:
                div_krw_native += amt
            rows.append({"일자": str(r.get("일자", "")), "종목": r.get("종목명") or tk, "티커": tk,
                         "통화": "USD" if is_usd else "KRW", "배당금": amt, "원화환산": round(krw), "구분": "검증"})
    if include_est and combined_orders:
        est = compute_dividends(combined_orders, fx_rate)
        if est is not None and not est.empty:
            for _, r in est.iterrows():
                tk = str(r.get("종목"))
                if tk in verified:
                    continue
                amt = float(r.get("배당수령(원본)", 0) or 0)
                if amt <= 0:
                    continue
                is_usd = str(r.get("통화", "KRW")).upper() == "USD"
                krw = float(r.get("배당수령(원)", 0) or 0)
                by_ticker[tk] = by_ticker.get(tk, 0.0) + krw
                if is_usd:
                    div_usd_native += amt
                else:
                    div_krw_native += amt
                rows.append({"일자": "", "종목": tk, "티커": tk, "통화": "USD" if is_usd else "KRW",
                             "배당금": round(amt, 2), "원화환산": round(krw), "구분": f"추정({int(r.get('배당횟수', 0))}회)"})
    return div_krw_native, div_usd_native, by_ticker, rows


def load_portfolio(user, use_toss=True, use_tx=True, include_div_est=True):
    """사용자의 전체 포트폴리오 데이터를 취합해 dict로 반환합니다."""
    creds = apply_credentials(user)

    portfolio_json = None
    toss_orders = []
    toss_orders_raw = []
    toss_name_map = {}
    fx_rate = None
    toss_err = None
    if use_toss:
        portfolio_json, toss_err = toss_portfolio(creds)
        if toss_err or not portfolio_json:
            use_toss = False
            portfolio_json = None
        else:
            _, toss_orders, fx_rate, toss_name_map = toss_trades(creds)
            toss_orders_raw = list(toss_orders)
            toss_orders = apply_toss_overrides(toss_orders)
    if not fx_rate:
        fx_rate = current_usdkrw()
    if portfolio_json is None:
        portfolio_json = empty_portfolio(user, fx_rate)

    # 타 증권사 거래내역/잔고
    tx_df = pd.DataFrame()
    holdings_snapshot = pd.DataFrame()
    has_tx = False
    manual_df = pd.DataFrame()
    if use_tx:
        tx_df = read_transactions_csv()
        has_tx = tx_df is not None and not tx_df.empty
        tx_brokers = set(tx_df["증권사"].unique()) if has_tx else set()
        holdings_snapshot = load_manual_holdings(fx_rate)
        if holdings_snapshot is not None and not holdings_snapshot.empty:
            holdings_snapshot = holdings_snapshot[~holdings_snapshot["증권사"].isin(tx_brokers)]
        tx_holdings = derive_holdings_from_tx(tx_df, fx_rate) if has_tx else pd.DataFrame()
        parts = [d for d in (tx_holdings, holdings_snapshot) if d is not None and not d.empty]
        manual_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    has_manual = not manual_df.empty
    if has_manual:
        portfolio_json = merge_manual_into_portfolio(portfolio_json, manual_df)

    combined_orders = list(toss_orders)
    if use_tx and has_tx:
        combined_orders += transactions_to_orders(tx_df)
    if use_tx and holdings_snapshot is not None and not holdings_snapshot.empty:
        combined_orders += manual_to_orders(holdings_snapshot)

    name_map = dict(toss_name_map)
    if has_manual:
        for _, r in manual_df.iterrows():
            name_map.setdefault(str(r.get("티커")), r.get("종목명"))
    # 국내 종목은 티커만 있는 경우 한글 종목명으로 보강
    _all_tickers = {o.get("symbol") for o in combined_orders if o.get("symbol")}
    _all_tickers |= {str(h.get("ticker")) for h in portfolio_json.get("holdings", [])}
    try:
        name_map = enrich_name_map(name_map, _all_tickers)
    except Exception:
        pass

    detail_df = build_transaction_detail(combined_orders, fx_rate, name_map)

    summary = portfolio_json.get("asset_summary", {})
    holdings = portfolio_json.get("holdings", [])
    has_data = bool(combined_orders) or bool(holdings)

    dkn, dun, div_by_ticker, div_rows = _dividends(combined_orders, fx_rate, include_div_est)

    perf = compute_performance_summary(combined_orders, fx_rate, dkn, dun) if has_data else None
    ab = compute_alpha_beta(combined_orders, fx_rate) if has_data else None
    breakdown = (build_holdings_breakdown(combined_orders, fx_rate, name_map, dict(div_by_ticker))
                 if has_data else pd.DataFrame())
    try:
        stock_ana = (build_stock_analytics(combined_orders, fx_rate, name_map, holdings)
                     if has_data else pd.DataFrame())
    except Exception:
        stock_ana = pd.DataFrame()

    return {
        "user": user,
        "fx_rate": fx_rate,
        "toss_error": toss_err,
        "has_data": has_data,
        "summary": summary,
        "holdings": holdings,
        "combined_orders": combined_orders,
        "name_map": name_map,
        "toss_orders_raw": toss_orders_raw,
        "detail_df": detail_df,
        "dividends_rows": div_rows,
        "div_krw_native": dkn,
        "div_usd_native": dun,
        "div_by_ticker": div_by_ticker,
        "perf": perf,
        "ab": ab,
        "breakdown": breakdown,
        "stock_analytics": stock_ana,
    }


def _dated_div_events(orders, fx, ticker=None):
    """배당 지급 이벤트 [(date, krw, symbol)] — 검증(임포트) 날짜 우선, 없는 종목은 yfinance 추정."""
    events = []
    verified = set()
    recs = read_dividends_csv()
    if recs is not None and not recs.empty:
        for _, r in recs.iterrows():
            tk = str(r.get("티커"))
            if ticker and tk != ticker:
                continue
            amt = float(r.get("배당금", 0) or 0)
            if amt <= 0:
                continue
            try:
                d = pd.to_datetime(r.get("일자")).tz_localize(None).normalize()
            except Exception:
                continue
            is_usd = str(r.get("통화", "KRW")).upper() == "USD"
            events.append((d, amt * fx if is_usd else amt, tk))
            verified.add(tk)
    for ed, krw, sym in compute_dividend_events(orders, fx, ticker):
        if sym in verified:
            continue
        events.append((ed, krw, sym))
    return sorted(events, key=lambda x: x[0])


def growth_frame(combined_orders, fx_rate, ticker=None):
    """보유 자산가치(원금+수익금) 성장 추이 프레임(전체 또는 개별 종목). 환율·배당·차익실현 반영."""
    tk = ticker or None
    div_events = _dated_div_events(combined_orders, fx_rate, tk)
    return build_asset_value_growth(combined_orders, fx_rate, div_events, tk)


def trade_bars(combined_orders, ticker=None, fx=1400.0):
    return build_trade_bars(combined_orders, ticker, fx)


def stock_analytics(combined_orders, fx, name_map=None, holdings=None):
    return build_stock_analytics(combined_orders, fx, name_map, holdings)


def rolling_beta(combined_orders, fx, ticker=None):
    return compute_rolling_beta(combined_orders, fx, ticker)


def spy_dca(combined_orders, fx):
    return build_spy_dca(combined_orders, fx)
