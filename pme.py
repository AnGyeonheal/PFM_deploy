"""PME(Public Market Equivalent) 기반 타이밍 반영 성과 분석.
내가 매수/매도한 '시점과 금액'을 그대로 S&P500(SPY)에 투자했다고 가정하고,
실제 내 종목 성과와 비교하여 진짜 초과수익(알파)을 계산합니다.
주가 추이만 보는 방식과 달리 매매 타이밍이 반영됩니다.
"""
import pandas as pd

from benchmark import to_yf_ticker, get_history, get_usdkrw_history, BENCHMARK_TICKER


def _trade_records(orders):
    """체결 주문을 (symbol, currency, side, qty, amount, date) 레코드로 변환."""
    recs = []
    for o in orders:
        ex = o.get("execution") or {}
        qty = float(ex.get("filledQuantity") or 0)
        amt = float(ex.get("filledAmount") or 0)
        if qty == 0 or amt == 0:
            continue
        raw = ex.get("filledAt") or o.get("orderedAt")
        try:
            date = pd.to_datetime(raw).tz_localize(None).normalize()
        except (TypeError, ValueError):
            try:
                date = pd.to_datetime(raw, utc=True).tz_localize(None).normalize()
            except Exception:
                continue  # 날짜 파싱 실패한 주문은 건너뜀
        if pd.isna(date):
            continue
        recs.append({
            "symbol": o.get("symbol"),
            "currency": o.get("currency", "KRW"),
            "side": o.get("side"),
            "qty": qty,
            "amount": amt,
            "date": date,
        })
    return recs


def _safe_asof(series, date, fallback):
    """asof가 범위 밖(NaN)이면 시계열의 첫 유효값으로 대체."""
    if series is None or series.empty:
        return fallback
    try:
        val = series.asof(date)
        if pd.notna(val):
            return float(val)
        return float(series.iloc[0])
    except Exception:
        return fallback



def build_pme_table(orders, fx_now=1400.0, name_map=None):
    """종목별로 '내 실제 수익률' vs 'S&P500 PME 수익률'을 계산합니다.
    각 매수/매도 시점에 같은 금액을 SPY에 투자했다고 가정.
    반환: DataFrame(종목, 티커, 투자원금, 내 수익률%, PME 수익률%, 초과수익%p, 초과손익(원), 보유상태)
    """
    name_map = name_map or {}
    recs = _trade_records(orders)
    if not recs:
        return pd.DataFrame()

    symbols = sorted(set(r["symbol"] for r in recs))
    spy_hist = get_history(BENCHMARK_TICKER, period="2y")
    fx_hist = get_usdkrw_history("2y")
    if spy_hist.empty:
        return pd.DataFrame()
    spy_now = float(spy_hist.iloc[-1])

    # 종목별 현재가(yfinance 최근 종가)
    price_now = {}
    for s in symbols:
        cur = next(r["currency"] for r in recs if r["symbol"] == s)
        yft = to_yf_ticker(s, "KR" if cur == "KRW" else "US")
        h = get_history(yft, period="5d")
        price_now[s] = float(h.iloc[-1]) if not h.empty else None

    by = {}
    for r in recs:
        s = r["symbol"]
        cur = r["currency"]
        sign = 1 if r["side"] == "BUY" else -1
        spy_px = _safe_asof(spy_hist, r["date"], spy_now)
        fx_d = _safe_asof(fx_hist, r["date"], fx_now)

        if cur == "USD":
            cf_krw = r["amount"] * fx_d
            spy_delta = sign * (r["amount"] / spy_px)  # USD/USD → 환율 상쇄
        else:
            cf_krw = r["amount"]
            spy_delta = sign * (r["amount"] / (spy_px * fx_d))

        e = by.setdefault(s, {"cur": cur, "qty": 0.0, "buy": 0.0, "sell": 0.0, "spy": 0.0})
        e["qty"] += sign * r["qty"]
        if sign > 0:
            e["buy"] += cf_krw
        else:
            e["sell"] += cf_krw
        e["spy"] += spy_delta

    rows = []
    for s, e in by.items():
        pn = price_now.get(s)
        if pn is None:
            continue
        stock_val = e["qty"] * pn * (fx_now if e["cur"] == "USD" else 1)
        spy_val = e["spy"] * spy_now * fx_now
        my_profit = stock_val + e["sell"] - e["buy"]
        spy_profit = spy_val + e["sell"] - e["buy"]
        invested = e["buy"]
        my_ret = (my_profit / invested * 100) if invested else 0
        spy_ret = (spy_profit / invested * 100) if invested else 0
        rows.append({
            "종목": name_map.get(s, s),
            "티커": s,
            "투자원금(원)": round(invested),
            "내 수익률(%)": round(my_ret, 2),
            "S&P500 PME(%)": round(spy_ret, 2),
            "초과수익(%p)": round(my_ret - spy_ret, 2),
            "초과손익(원)": round(my_profit - spy_profit),
            "보유상태": "보유중" if abs(e["qty"]) > 1e-6 else "청산",
        })

    return pd.DataFrame(rows).sort_values("초과수익(%p)", ascending=False).reset_index(drop=True)


def build_pme_growth(orders, fx_now=1400.0):
    """내 실제 포트폴리오 평가액 vs S&P500 PME 평가액을 시간에 따라 계산합니다.
    두 곡선 모두 실제 매매 시점·금액(현금흐름)으로 구동됩니다.
    반환: DataFrame(index=날짜, columns=[내 포트폴리오, S&P500 PME, 누적 투자원금]) (원화)
    """
    recs = _trade_records(orders)
    if not recs:
        return pd.DataFrame()

    symbols = sorted(set(r["symbol"] for r in recs))
    spy_hist = get_history(BENCHMARK_TICKER, period="2y")
    fx_hist = get_usdkrw_history("2y")
    if spy_hist.empty:
        return pd.DataFrame()

    start = min(r["date"] for r in recs)
    idx = pd.date_range(start=start, end=spy_hist.index.max(), freq="D")

    def align(series):
        return series.reindex(idx.union(series.index)).ffill().reindex(idx).bfill()

    fx_daily = align(fx_hist) if not fx_hist.empty else pd.Series(fx_now, index=idx)
    spy_daily = align(spy_hist)

    sym_cur = {s: next(r["currency"] for r in recs if r["symbol"] == s) for s in symbols}
    sym_hist = {}
    for s in symbols:
        yft = to_yf_ticker(s, "KR" if sym_cur[s] == "KRW" else "US")
        h = get_history(yft, period="2y")
        if not h.empty:
            sym_hist[s] = align(h)

    recs_sorted = sorted(recs, key=lambda r: r["date"])

    my_val = pd.Series(0.0, index=idx)
    for s in symbols:
        if s not in sym_hist:
            continue
        qty_steps = pd.Series(0.0, index=idx)
        for r in [x for x in recs_sorted if x["symbol"] == s]:
            sign = 1 if r["side"] == "BUY" else -1
            qty_steps.loc[qty_steps.index >= r["date"]] += sign * r["qty"]
        px = sym_hist[s]
        val = qty_steps * px * (fx_daily if sym_cur[s] == "USD" else 1.0)
        my_val = my_val.add(val, fill_value=0)

    spy_shares = pd.Series(0.0, index=idx)
    invested = pd.Series(0.0, index=idx)
    for r in recs_sorted:
        sign = 1 if r["side"] == "BUY" else -1
        spy_px = _safe_asof(spy_hist, r["date"], float(spy_hist.iloc[-1]))
        fx_d = _safe_asof(fx_hist, r["date"], fx_now)
        if r["currency"] == "USD":
            delta = sign * (r["amount"] / spy_px)
            cf = r["amount"] * fx_d
        else:
            delta = sign * (r["amount"] / (spy_px * fx_d))
            cf = r["amount"]
        spy_shares.loc[spy_shares.index >= r["date"]] += delta
        invested.loc[invested.index >= r["date"]] += sign * cf

    spy_val = spy_shares * spy_daily * fx_daily

    out = pd.DataFrame({
        "내 포트폴리오": my_val,
        "S&P500 PME": spy_val,
        "누적 투자원금": invested,
    })
    # 투자원금 대비 누적 수익률(%) — 절대금액의 원금 계단효과를 제거해 알파를 명확히 표시
    denom = invested.replace(0, pd.NA)
    out["내 수익률(%)"] = ((my_val / denom - 1) * 100).astype(float)
    out["S&P500 PME 수익률(%)"] = ((spy_val / denom - 1) * 100).astype(float)
    return out


def _current_prices(symbols, currencies):
    """종목별 현재가(yfinance 최근 종가) 조회. 반환: {symbol: price(native)}"""
    price_now = {}
    for s in symbols:
        cur = currencies.get(s, "KRW")
        yft = to_yf_ticker(s, "KR" if cur == "KRW" else "US")
        h = get_history(yft, period="5d")
        price_now[s] = float(h.iloc[-1]) if not h.empty else None
    return price_now


def build_trade_spy_table(orders, fx_now=1400.0, name_map=None):
    """거래별(매수 기준) S&P500 대비 초과수익 투명 비교표.
    각 매수 시점의 SPY 주가(당시)와 현재 SPY 주가, 그 기간 SPY 수익률,
    내 종목의 현재 수익률, 초과수익(%p)을 한 줄씩 보여줍니다.
    통화가 KRW면 SPY를 원화로 환산해 공정 비교합니다.
    """
    name_map = name_map or {}
    recs = [r for r in _trade_records(orders) if r["side"] == "BUY"]
    if not recs:
        return pd.DataFrame()

    spy = get_history(BENCHMARK_TICKER, period="2y")
    fx_hist = get_usdkrw_history("2y")
    if spy.empty:
        return pd.DataFrame()
    spy_now_usd = float(spy.iloc[-1])

    currencies = {r["symbol"]: r["currency"] for r in recs}
    price_now = _current_prices(sorted(currencies), currencies)

    rows = []
    for r in recs:
        sym = r["symbol"]
        cur = r["currency"]
        qty = r["qty"]
        my_price = r["amount"] / qty if qty else 0  # 내 매수 단가(해당 거래)
        spy_then_usd = _safe_asof(spy, r["date"], float(spy.iloc[0]))

        if cur == "USD":
            spy_then = spy_then_usd
            spy_now = spy_now_usd
        else:  # KRW: SPY를 원화로 환산
            fx_then = _safe_asof(fx_hist, r["date"], fx_now)
            spy_then = spy_then_usd * fx_then
            spy_now = spy_now_usd * fx_now

        spy_ret = (spy_now / spy_then - 1) * 100 if spy_then else 0
        pn = price_now.get(sym)
        my_ret = (pn / my_price - 1) * 100 if (pn and my_price) else None

        rows.append({
            "날짜": r["date"].strftime("%Y-%m-%d"),
            "종목": name_map.get(sym, sym),
            "티커": sym,
            "통화": cur,
            "수량": qty,
            "내 매수단가": round(my_price, 2),
            "당시 S&P500": round(spy_then, 2),
            "현재 S&P500": round(spy_now, 2),
            "S&P500 수익률(%)": round(spy_ret, 2),
            "내 수익률(%)": round(my_ret, 2) if my_ret is not None else None,
            "초과수익(%p)": round(my_ret - spy_ret, 2) if my_ret is not None else None,
        })

    df = pd.DataFrame(rows).sort_values("날짜").reset_index(drop=True)
    return df


def build_ticker_profit_growth(orders, fx_now=1400.0, ticker=None):
    """특정 종목의 '수익금(평가액-투자원금)' 성장 추이 vs S&P500 PME 수익금(원화).
    투자원금을 제외한 순수 수익금의 성장을 벤치마크와 비교합니다.
    반환: DataFrame(index=날짜, [내 수익금, S&P500 수익금])
    """
    recs = [r for r in _trade_records(orders) if r["symbol"] == ticker]
    if not recs:
        return pd.DataFrame()

    spy = get_history(BENCHMARK_TICKER, period="2y")
    fx_hist = get_usdkrw_history("2y")
    if spy.empty:
        return pd.DataFrame()

    cur = recs[0]["currency"]
    yft = to_yf_ticker(ticker, "KR" if cur == "KRW" else "US")
    hist = get_history(yft, period="2y")
    if hist.empty:
        return pd.DataFrame()

    start = min(r["date"] for r in recs)
    idx = pd.date_range(start=start, end=spy.index.max(), freq="D")

    def align(s):
        return s.reindex(idx.union(s.index)).ffill().reindex(idx).bfill()

    fx_daily = align(fx_hist) if not fx_hist.empty else pd.Series(fx_now, index=idx)
    spy_daily = align(spy)
    px_daily = align(hist)

    recs_sorted = sorted(recs, key=lambda r: r["date"])
    qty_steps = pd.Series(0.0, index=idx)
    spy_shares = pd.Series(0.0, index=idx)
    invested = pd.Series(0.0, index=idx)
    for r in recs_sorted:
        sign = 1 if r["side"] == "BUY" else -1
        spy_px = _safe_asof(spy, r["date"], float(spy.iloc[-1]))
        fx_d = _safe_asof(fx_hist, r["date"], fx_now)
        qty_steps.loc[qty_steps.index >= r["date"]] += sign * r["qty"]
        if cur == "USD":
            spy_shares.loc[spy_shares.index >= r["date"]] += sign * (r["amount"] / spy_px)
            invested.loc[invested.index >= r["date"]] += sign * (r["amount"] * fx_d)
        else:
            spy_shares.loc[spy_shares.index >= r["date"]] += sign * (r["amount"] / (spy_px * fx_d))
            invested.loc[invested.index >= r["date"]] += sign * r["amount"]

    my_value_krw = qty_steps * px_daily * (fx_daily if cur == "USD" else 1.0)
    spy_value_krw = spy_shares * spy_daily * fx_daily

    out = pd.DataFrame({
        "내 수익금": my_value_krw - invested,
        "S&P500 수익금": spy_value_krw - invested,
    })
    return out

