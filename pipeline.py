"""Streamlit 비의존 데이터 파이프라인.

웹앱(FastAPI)과 배치 스크립트에서 재사용할 수 있도록, app.py의 데이터 취합 로직을
순수 함수로 옮긴 모듈입니다. 토스 API + 임포트 데이터를 합쳐 요약/보유/성과/배당을 계산합니다.
"""
import os
import hashlib
import json

import pandas as pd

from pm import (
    get_access_token, get_holdings, get_buying_power, get_exchange_rate,
    get_order_history, get_stock_info,
)
from analytics_engine import transform_to_mvp_json, build_transaction_detail
from benchmark import get_usdkrw_history, get_splits, to_yf_ticker, set_price_overrides
from manual_holdings import (
    set_data_dir, load_manual_holdings, manual_to_orders,
    read_manual_csv, read_transactions_csv, read_dividends_csv, read_splits_csv,
    transactions_to_orders, derive_holdings_from_tx,
    read_toss_overrides, write_toss_overrides,
    read_holdings_overrides, write_holdings_overrides,
)
from performance import compute_performance_summary, build_holdings_breakdown
from advanced_analytics import build_dividend_records
from pme import (
    compute_alpha_beta,
    build_trade_bars, build_asset_value_growth, build_stock_analytics, compute_rolling_beta,
    build_spy_dca, build_twr_comparison, position_key,
)
import auth
from names import enrich_name_map, resolve_ticker_map, normalize_kr_ticker, register_krw_foreign


def current_usdkrw():
    s = get_usdkrw_history("5d")
    return float(s.iloc[-1]) if (s is not None and not s.empty) else 1421.0


def empty_portfolio(user, fx=1400.0):
    return {
        "user_profile": {"user_id": user, "target_benchmark": "S&P 500"},
        "asset_summary": {"total_asset_krw": 0, "stock_eval_krw": 0, "purchase_krw": 0,
                          "cash_krw": 0, "cash_krw_native": 0, "cash_usd_native": 0, "cash_available": False, "fx_rate": fx},
        "holdings": [],
    }


def apply_credentials(user):
    """요청별 데이터 폴더를 선택하고 해당 사용자의 자격 증명을 반환합니다."""
    set_data_dir(auth.user_dir(user))
    set_price_overrides(holdings_price_overrides(), replace=True)
    return auth.load_credentials(user)


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
    krw_cash = get_buying_power(token, acc, "KRW", default=None)
    usd_cash = get_buying_power(token, acc, "USD", default=None)
    fx = get_exchange_rate(token)
    cash_krw = (krw_cash or 0.0) + (usd_cash or 0.0) * fx
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
    orders = [dict(order, broker="토스증권", account=acc) for order in get_order_history(token, acc)]
    holdings_data = get_holdings(token, acc) or {}
    name_map = {i.get("symbol"): i.get("name") for i in holdings_data.get("result", {}).get("items", [])}
    detail = build_transaction_detail(orders, fx, name_map)
    return detail, orders, fx, name_map


# ─────────────────── 토스 거래 직접 수정(오버라이드 레이어) ───────────────────
TOSS_OVR_FIELDS = ["일자", "티커", "종목명", "구분", "수량", "단가", "통화"]


def toss_trade_key(o):
    """원본 주문 ID와 계좌로 편집값과 독립적인 식별자를 생성합니다."""
    identity = o.get("orderId") or o.get("id")
    scope = position_key(o)[:2]
    if identity is not None:
        value = json.dumps([*scope, str(identity)], ensure_ascii=True)
        return "toss:id:" + hashlib.sha256(value.encode()).hexdigest()
    value = json.dumps([*scope, _legacy_toss_trade_key(o)], ensure_ascii=True)
    return "toss:fill:" + hashlib.sha256(value.encode()).hexdigest()


def _legacy_toss_trade_key(o):
    ex = o.get("execution") or {}
    raw = ex.get("filledAt") or o.get("orderedAt") or ""
    return "|".join(str(x) for x in [o.get("symbol"), raw, o.get("side"),
                                     ex.get("filledQuantity"), ex.get("filledAmount")])


def indexed_toss_orders(orders):
    indexed, occurrences = {}, {}
    for order in orders:
        key = toss_trade_key(order)
        if key.startswith("toss:fill:"):
            occurrences[key] = occurrences.get(key, 0) + 1
            if occurrences[key] > 1:
                key = f"{key}:{occurrences[key]}"
        indexed[key] = order
    return indexed


def toss_override(overrides, key, order):
    return overrides.get(key, overrides.get(_legacy_toss_trade_key(order)))


def toss_override_revision(override, original=None):
    content = {"override": override or {}, "original": original or {}}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


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
    return {"증권사": o.get("broker", "토스증권"), "계좌": position_key(o)[1], "일자": d, "티커": sym,
            "종목명": o.get("name") or name_map.get(sym, sym), "시장": o.get("market") or "",
            "구분": "매도" if o.get("side") == "SELL" else "매수",
            "수량": float(ex.get("filledQuantity") or 0),
            "단가": float(ex.get("averageFilledPrice") or 0),
            "통화": o.get("currency", "KRW")}


def _override_to_order(orig, e):
    """오버라이드 dict(e)를 원본 주문(orig) 기반의 토스 주문으로 재구성합니다."""
    original_execution = orig.get("execution") or {}
    qty = float(e.get("수량", original_execution.get("filledQuantity")) or 0)
    price = float(e.get("단가", original_execution.get("averageFilledPrice")) or 0)
    raw = original_execution.get("filledAt") or orig.get("orderedAt")
    filled_at = raw
    try:
        timestamp = pd.Timestamp(raw)
        selected_date = str(e.get("일자") or timestamp.strftime("%Y-%m-%d"))
        if selected_date != timestamp.strftime("%Y-%m-%d"):
            day = pd.Timestamp(selected_date)
            filled_at = (timestamp + (day - timestamp.tz_localize(None).normalize())).isoformat()
    except Exception:
        pass
    side = orig.get("side")
    if "구분" in e:
        side = "SELL" if str(e["구분"]) in ("매도", "SELL", "sell") else "BUY"
    ex = dict(orig.get("execution") or {})
    if "수량" in e:
        ex["filledQuantity"] = qty
    if "단가" in e:
        ex["averageFilledPrice"] = price
    if "수량" in e or "단가" in e:
        ex["filledAmount"] = qty * price
    if filled_at != raw:
        ex["filledAt"] = filled_at
    out = dict(orig)
    out.update({"symbol": str(e.get("티커") or orig.get("symbol")),
                "currency": str(e.get("통화") or orig.get("currency", "KRW")).upper(),
                "side": side, "execution": ex, "_edited": True})
    for field, target in (("증권사", "broker"), ("계좌", "account"), ("종목명", "name"), ("시장", "market")):
        if field in e:
            out[target] = e[field]
    return out


def apply_toss_overrides(orders, overrides=None):
    """토스 주문 리스트에 사용자 수정/삭제 오버라이드를 적용합니다."""
    overrides = read_toss_overrides() if overrides is None else overrides
    out = []
    for key, o in indexed_toss_orders(orders).items():
        e = toss_override(overrides, key, o)
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
    base_fx = float(summary.get("fx_rate") or 0)
    merged = {}
    for h in portfolio_json.get("holdings", []):
        tk = h.get("ticker")
        eval_krw = float(h.get("eval_krw", 0) or 0)
        eval_native = h.get("eval_native")
        if eval_native is None:
            eval_native = (eval_krw / base_fx if base_fx > 0 else None) if h.get("currency") == "USD" else eval_krw
        ret = float(h.get("return_pct", 0) or 0)
        cost = eval_krw / (1 + ret / 100) if (1 + ret / 100) != 0 else eval_krw
        merged[tk] = {"ticker": tk, "name": h.get("name"), "currency": h.get("currency"),
                      "quantity": float(h.get("quantity", 0) or 0), "eval_krw": eval_krw,
                      "eval_native": float(eval_native) if eval_native is not None else None,
                      "cost_krw": cost, "sector": h.get("sector", "Unknown"), "brokers": {"토스증권"}}
    add_eval = add_purchase = 0.0
    for _, r in manual_df.iterrows():
        tk = str(r.get("티커"))
        eval_krw = float(r.get("평가액(원)", 0) or 0)
        qty = float(r.get("수량", 0) or 0)
        avg = float(r.get("평균매수가", 0) or 0)
        cur = str(r.get("통화", "KRW")).upper()
        current_price = r.get("현재가")
        eval_native = (qty * float(current_price) if current_price is not None and pd.notna(current_price) else None) if cur == "USD" else eval_krw
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
            m["eval_native"] = m["eval_native"] + eval_native if m["eval_native"] is not None and eval_native is not None else None
            m["cost_krw"] += purchase_krw
            m["brokers"].add(broker)
        else:
            merged[tk] = {"ticker": tk, "name": r.get("종목명"), "currency": cur, "quantity": qty,
                          "eval_krw": eval_krw, "eval_native": eval_native, "cost_krw": purchase_krw, "sector": "Unknown",
                          "brokers": {broker}}
    new_stock = sum(m["eval_krw"] for m in merged.values())
    holdings = []
    for m in merged.values():
        ret = (m["eval_krw"] / m["cost_krw"] - 1) * 100 if m["cost_krw"] else 0
        holdings.append({"ticker": m["ticker"], "name": m["name"], "currency": m["currency"],
                         "quantity": round(m["quantity"], 4), "eval_krw": round(m["eval_krw"]),
                         "eval_native": m["eval_native"],
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
    for record in _dividend_records(combined_orders, fx_rate, include_est):
        label = "검증" if record["source"] == "actual" else "추정"
        if record.get("matchingUncertain"):
            label += "(실제 내역 대응 확인 필요)"
        elif not record["payDate"]:
            label += "(수령일 미확인)"
        elif not record["received"]:
            label += "(지급 예정)"
        if record["received"]:
            by_ticker[record["ticker"]] = by_ticker.get(record["ticker"], 0.0) + record["amountKrw"]
            if record["currency"] == "USD":
                div_usd_native += record["amount"]
            else:
                div_krw_native += record["amount"]
        rows.append({"일자": record["payDate"], "종목": record["name"], "티커": record["ticker"],
                     "증권사": record["broker"], "계좌": record["account"], "통화": record["currency"],
                     "배당금": record["amount"], "원화환산": record["amountKrw"], "구분": label,
                     "배당락일": record["exDate"], "기준일": record["recordDate"], "배당ID": record["eventId"],
                     "권리수량": record["shares"], "지급일구분": record["dateSource"], "수령반영": record["received"]})
    return div_krw_native, div_usd_native, by_ticker, rows


def load_portfolio(user, use_toss=True, use_tx=True, include_div_est=True,
                   include_div=True, include_fx=True):
    """사용자의 전체 포트폴리오 데이터를 취합해 dict로 반환합니다.
    include_div/include_fx: 배당·환차손익을 성과지표(손익·알파·베타·수익률)에 반영할지."""
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
        # 종목명만 있고 티커가 비면 KRX·Gemini로 보강(캐시로 1회만 조회)
        if has_tx:
            _blank = ((tx_df["티커"].astype(str).str.strip() == "")
                      & (tx_df["종목명"].astype(str).str.strip() != ""))
            if _blank.any():
                _tmap = resolve_ticker_map(tx_df.loc[_blank, "종목명"].tolist())
                for _i in tx_df.index[_blank]:
                    _t = _tmap.get(str(tx_df.at[_i, "종목명"]).strip())
                    if _t:
                        tx_df.at[_i, "티커"] = _t
        tx_accounts = {position_key(row)[:2] for _, row in tx_df.iterrows()} if has_tx else set()
        holdings_snapshot = load_manual_holdings(fx_rate)
        if holdings_snapshot is not None and not holdings_snapshot.empty:
            has_history = holdings_snapshot.apply(lambda row: position_key(row)[:2] in tx_accounts, axis=1)
            holdings_snapshot = holdings_snapshot[~has_history]
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
    for _o in combined_orders:  # 국내 A접두사 통일(A360750→360750): 중복 집계·시세 조회 실패 방지
        _o["symbol"] = normalize_kr_ticker(_o.get("symbol"))
    combined_orders = apply_split_adjustments(combined_orders)  # 분할/역분할을 현재 주식 수 기준으로 통일
    combined_orders = apply_holdings_overrides(combined_orders)  # 대시보드 보유 표 수정을 거래로 대체 반영
    set_price_overrides(holdings_price_overrides(), replace=True)  # 보유 표 현재가 수정 주입

    name_map = dict(toss_name_map)
    for order in toss_orders:
        if order.get("_edited") and order.get("name"):
            name_map[order["symbol"]] = order["name"]
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
    register_krw_foreign(name_map)  # 원화 상장 해외 ETF(환노출) 등록 → 환차손익 분리 계산

    detail_df = build_transaction_detail(combined_orders, fx_rate, name_map)

    summary = portfolio_json.get("asset_summary", {})
    holdings = portfolio_json.get("holdings", [])
    has_data = bool(combined_orders) or bool(holdings)

    dkn, dun, div_by_ticker, div_rows = _dividends(combined_orders, fx_rate, include_div_est)

    div_events = _dated_div_events(combined_orders, fx_rate) if has_data else []
    perf = compute_performance_summary(combined_orders, fx_rate, dkn, dun,
                                       include_div, include_fx, dividend_krw=sum(div_by_ticker.values())) if has_data else None
    ab = compute_alpha_beta(combined_orders, fx_rate, div_events=div_events,
                            include_div=include_div, include_fx=include_fx) if has_data else None
    breakdown = (build_holdings_breakdown(combined_orders, fx_rate, name_map, dict(div_by_ticker),
                                          include_div, include_fx)
                 if has_data else pd.DataFrame())
    try:
        stock_ana = (build_stock_analytics(combined_orders, fx_rate, name_map, holdings,
                                           include_div, include_fx, div_events)
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
        "toss_name_map": toss_name_map,
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


def _dividend_records(orders, fx, include_est=True):
    recs = read_dividends_csv()
    return build_dividend_records(orders, fx, actual_rows=recs.fillna("").to_dict("records")
                                  if recs is not None and not recs.empty else [], include_est=include_est)


def _dated_div_events(orders, fx, ticker=None):
    """동일 배당 원장의 수령일·금액과 계좌·권리 기준일을 성과 계산에 전달합니다."""
    return [(pd.Timestamp(row["payDate"]), row["amountKrw"], row["ticker"], row["position"], row["exDate"])
            for row in _dividend_records(orders, fx) if row["received"] and (not ticker or row["ticker"] == ticker)]


def _split_map(symbol, currency, manual_df=None):
    """종목의 분할 이벤트 {분할일: 비율}. yfinance + 수동 입력 병합(수동이 우선)."""
    m = {}
    try:
        yft = to_yf_ticker(symbol, "KR" if currency == "KRW" else "US")
        for d, r in get_splits(yft).items():
            m[pd.Timestamp(d).tz_localize(None).normalize()] = float(r)
    except Exception:
        pass
    if manual_df is not None and not manual_df.empty:
        for _, row in manual_df.iterrows():
            if str(row.get("티커")) != str(symbol):
                continue
            try:
                d = pd.to_datetime(row.get("분할일")).tz_localize(None).normalize()
                r = float(row.get("비율"))
            except Exception:
                continue
            if r > 0:
                m[d] = r  # 수동이 yfinance 값을 덮어씀
    return m


def apply_split_adjustments(orders):
    """거래를 현재 주식 수 기준으로 통일. 거래일 이후 분할계수 R을 곱해 수량×R, 단가÷R (투자원금 불변).
    정방향(비율>1)·역방향(비율<1) 모두 처리. yfinance 분할 + 수동 분할(manual_splits.csv) 반영.
    """
    if not orders:
        return orders
    try:
        manual_df = read_splits_csv()
    except Exception:
        manual_df = None
    cache = {}
    out = []
    for o in orders:
        ex = dict(o.get("execution") or {})
        sym = o.get("symbol")
        raw = ex.get("filledAt") or o.get("orderedAt")
        try:
            d = pd.to_datetime(raw).tz_localize(None).normalize()
        except Exception:
            try:
                d = pd.to_datetime(raw, utc=True).tz_localize(None).normalize()
            except Exception:
                out.append(o)
                continue
        if sym not in cache:
            cache[sym] = _split_map(sym, o.get("currency", "KRW"), manual_df)
        R = 1.0
        for sd, ratio in cache[sym].items():
            if sd > d:  # 거래일 이후 분할만 반영
                R *= ratio
        if R != 1.0:
            qty = float(ex.get("filledQuantity") or 0)
            avg = float(ex.get("averageFilledPrice") or 0)
            if qty:
                ex["filledQuantity"] = qty * R
            if avg:
                ex["averageFilledPrice"] = avg / R
            o = dict(o)
            o["execution"] = ex  # filledAmount(투자원금)는 불변
        out.append(o)
    return out


def apply_holdings_overrides(orders, overrides=None):
    """대시보드 보유 표 수정을 반영합니다. 오버라이드된 티커의 기존 주문을 제거하고,
    사용자가 지정한 수량·평단가로 1건의 합성 매수로 대체합니다(삭제 표시 종목은 제외).
    합성 주문 날짜는 기존 최초 매수일을 유지해 보유기간·알파/베타가 자연스럽게 이어집니다."""
    overrides = read_holdings_overrides() if overrides is None else overrides
    if not overrides:
        return orders
    overrides = {normalize_kr_ticker(k): v for k, v in overrides.items()}  # A360750→360750 키 통일
    first_dt = {}
    for o in orders:
        sym = o.get("symbol")
        if sym not in overrides:
            continue
        ex = o.get("execution") or {}
        raw = ex.get("filledAt") or o.get("orderedAt")
        try:
            d = pd.to_datetime(raw).tz_localize(None)
        except Exception:
            try:
                d = pd.to_datetime(raw, utc=True).tz_localize(None)
            except Exception:
                continue
        if pd.isna(d):
            continue
        if sym not in first_dt or d < first_dt[sym]:
            first_dt[sym] = d
    out = [o for o in orders if o.get("symbol") not in overrides]
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    for sym, e in overrides.items():
        if e.get("deleted"):
            continue
        try:
            qty = float(e.get("수량") or 0)
            price = float(e.get("평단가") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or price <= 0:
            continue
        dt = first_dt.get(sym)
        buy_date = dt.strftime("%Y-%m-%d") if dt is not None else today
        filled_at = f"{buy_date}T00:00:00+09:00"
        out.append({
            "symbol": str(sym),
            "currency": str(e.get("통화", "KRW")).upper(),
            "side": "BUY",
            "status": "FILLED",
            "orderedAt": filled_at,
            "broker": e.get("증권사", "직접수정"),
            "_holdings_override": True,
            "execution": {
                "filledQuantity": qty,
                "averageFilledPrice": price,
                "filledAmount": qty * price,
                "commission": 0, "tax": 0,
                "filledAt": filled_at,
            },
        })
    return out


def holdings_price_overrides(overrides=None):
    """보유 오버라이드 중 현재가가 지정된 항목을 {티커: 현재가}로 반환합니다."""
    overrides = read_holdings_overrides() if overrides is None else overrides
    out = {}
    for sym, e in (overrides or {}).items():
        if e.get("deleted"):
            continue
        try:
            p = float(e.get("현재가") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            out[normalize_kr_ticker(sym)] = p
    return out


def growth_frame(combined_orders, fx_rate, ticker=None, include_div=True, include_fx=True, end=None):
    """보유 자산가치(원금+수익금) 성장 추이 프레임. 배당·환차손익 반영 여부 토글."""
    tk = ticker or None
    div_events = _dated_div_events(combined_orders, fx_rate, tk)
    return build_asset_value_growth(combined_orders, fx_rate, div_events, tk, include_div, include_fx, end=end)


def trade_bars(combined_orders, ticker=None, fx=1400.0):
    return build_trade_bars(combined_orders, ticker, fx)


def stock_analytics(combined_orders, fx, name_map=None, holdings=None):
    return build_stock_analytics(combined_orders, fx, name_map, holdings)


def rolling_beta(combined_orders, fx, ticker=None, include_div=True, include_fx=True):
    events = _dated_div_events(combined_orders, fx, ticker) if include_div else []
    return compute_rolling_beta(combined_orders, fx, ticker, include_div=include_div, include_fx=include_fx, div_events=events)


def spy_dca(combined_orders, fx, start_ym=None, ticker=None, include_div=True, include_fx=True, end=None):
    events = _dated_div_events(combined_orders, fx, ticker) if include_div else []
    return build_spy_dca(combined_orders, fx, start_ym, ticker, include_div, include_fx, events, end=end)


def twr_comparison(combined_orders, fx, ticker=None, include_fx=True, include_div=True):
    events = _dated_div_events(combined_orders, fx, ticker) if include_div else []
    return build_twr_comparison(combined_orders, fx, ticker, include_fx=include_fx, include_div=include_div, div_events=events)
