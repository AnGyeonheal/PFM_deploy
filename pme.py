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
        avg_px = float(ex.get("averageFilledPrice") or 0)
        if qty and avg_px:
            amt = qty * avg_px  # 당시 체결단가 기준(평가액 오염 방지)
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
        price_now[s] = float(h.iloc[-1]) if (not h.empty and pd.notna(h.iloc[-1])) else None

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
        is_open = abs(e["qty"]) > 1e-6
        if is_open and pn is None:
            continue  # 보유중인데 현재가를 못 구하면 평가 불가 → 제외
        stock_val = e["qty"] * (pn or 0.0) * (fx_now if e["cur"] == "USD" else 1)  # 청산(qty≈0)은 0
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
            "보유상태": "보유중" if is_open else "청산",
        })

    if not rows:
        return pd.DataFrame()
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
    spy_hist = get_history(BENCHMARK_TICKER, period="10y")
    fx_hist = get_usdkrw_history("10y")
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
        h = get_history(yft, period="10y")
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
        price_now[s] = float(h.iloc[-1]) if (not h.empty and pd.notna(h.iloc[-1])) else None
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


def build_ticker_profit_growth(orders, fx_now=1400.0, ticker=None, native=False):
    """특정 종목의 '수익금(평가액-투자원금)' 성장 추이 vs S&P500 PME 수익금.
    native=True이고 미국(USD) 종목이면 환율 효과를 제거해 달러 기준으로 계산합니다.
    반환: DataFrame(index=날짜, [내 수익금, S&P500 수익금, 투자원금])
    """
    recs = [r for r in _trade_records(orders) if r["symbol"] == ticker]
    if not recs:
        return pd.DataFrame()

    spy = get_history(BENCHMARK_TICKER, period="10y")
    fx_hist = get_usdkrw_history("10y")
    if spy.empty:
        return pd.DataFrame()

    cur = recs[0]["currency"]
    use_native = bool(native) and cur == "USD"  # 달러 기준(환율 제거)
    yft = to_yf_ticker(ticker, "KR" if cur == "KRW" else "US")
    hist = get_history(yft, period="10y")
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
            inv_amt = r["amount"] if use_native else r["amount"] * fx_d
            invested.loc[invested.index >= r["date"]] += sign * inv_amt
        else:
            spy_shares.loc[spy_shares.index >= r["date"]] += sign * (r["amount"] / (spy_px * fx_d))
            invested.loc[invested.index >= r["date"]] += sign * r["amount"]

    if use_native:  # 달러 기준: 환율 곱 제거
        my_value = qty_steps * px_daily
        spy_value = spy_shares * spy_daily
    else:
        my_value = qty_steps * px_daily * (fx_daily if cur == "USD" else 1.0)
        spy_value = spy_shares * spy_daily * fx_daily

    out = pd.DataFrame({
        "내 수익금": my_value - invested,
        "S&P500 수익금": spy_value - invested,
        "투자원금": invested,
    })
    return out


def compute_rolling_beta(orders, fx_now=1400.0, ticker=None, window=60, period="10y"):
    """대상(전체 또는 특정 종목)의 시장(S&P500) 대비 롤링 베타 시계열을 계산합니다.
    - 종목: 해당 종목 주가 수익률 vs S&P500 수익률(통화 일치)
    - 전체: 기여금 제거 포트폴리오 일간 수익률 vs S&P500(원화) 수익률
    반환: pd.Series(index=날짜, 값=롤링 베타)
    """
    recs = _trade_records(orders)
    if ticker:
        recs = [r for r in recs if r["symbol"] == ticker]
    if not recs:
        return pd.Series(dtype=float)

    spy = get_history(BENCHMARK_TICKER, period=period)
    fx_hist = get_usdkrw_history(period)
    if spy.empty:
        return pd.Series(dtype=float)

    symbols = sorted(set(r["symbol"] for r in recs))
    sym_cur = {s: next(r["currency"] for r in recs if r["symbol"] == s) for s in symbols}
    start = min(r["date"] for r in recs)
    idx = pd.date_range(start=start, end=spy.index.max(), freq="D")

    def align(s):
        return s.reindex(idx.union(s.index)).ffill().reindex(idx).bfill()

    fx_daily = align(fx_hist) if not fx_hist.empty else pd.Series(fx_now, index=idx)
    spy_daily = align(spy)

    if ticker:
        cur = sym_cur[ticker]
        yft = to_yf_ticker(ticker, "KR" if cur == "KRW" else "US")
        h = get_history(yft, period=period)
        if h.empty:
            return pd.Series(dtype=float)
        px = align(h)
        rp = px.pct_change()
        market = spy_daily if cur == "USD" else spy_daily * fx_daily
        rm = market.pct_change()
    else:
        my_val = pd.Series(0.0, index=idx)
        invested = pd.Series(0.0, index=idx)
        recs_sorted = sorted(recs, key=lambda r: r["date"])
        sym_hist = {}
        for s in symbols:
            yft = to_yf_ticker(s, "KR" if sym_cur[s] == "KRW" else "US")
            hh = get_history(yft, period=period)
            if not hh.empty:
                sym_hist[s] = align(hh)
        for s in symbols:
            if s not in sym_hist:
                continue
            qty = pd.Series(0.0, index=idx)
            for r in [x for x in recs_sorted if x["symbol"] == s]:
                sign = 1 if r["side"] == "BUY" else -1
                qty.loc[qty.index >= r["date"]] += sign * r["qty"]
            my_val = my_val.add(qty * sym_hist[s] * (fx_daily if sym_cur[s] == "USD" else 1.0), fill_value=0)
        for r in recs_sorted:
            sign = 1 if r["side"] == "BUY" else -1
            fx_d = _safe_asof(fx_hist, r["date"], fx_now)
            cf = r["amount"] * fx_d if r["currency"] == "USD" else r["amount"]
            invested.loc[invested.index >= r["date"]] += sign * cf
        prev = my_val.shift(1)
        rp = ((my_val - prev - invested.diff().fillna(0.0)) / prev).where(prev > 0)
        rm = (spy_daily * fx_daily).pct_change()

    reg = (pd.concat([rp, rm], axis=1, keys=["rp", "rm"])
           .replace([float("inf"), float("-inf")], pd.NA).dropna())
    reg = reg[reg["rm"] != 0.0]  # 거래일만(주말·휴장 평탄 잡음 제거)
    if len(reg) < window:
        return pd.Series(dtype=float)
    cov = reg["rp"].rolling(window).cov(reg["rm"])
    var = reg["rm"].rolling(window).var()
    beta = (cov / var).replace([float("inf"), float("-inf")], pd.NA).dropna()
    beta.name = "베타"
    return beta


def build_total_profit_growth(orders, fx_now=1400.0):
    """전체 자산의 '수익금(평가액−투자원금)' 성장 추이 vs S&P500 PME 수익금(원화).
    build_pme_growth 결과를 재사용해 개별 종목 그래프와 동일한 형식으로 반환합니다.
    반환: DataFrame(index=날짜, [내 수익금, S&P500 수익금, 투자원금])
    """
    g = build_pme_growth(orders, fx_now)
    if g is None or g.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "내 수익금": g["내 포트폴리오"] - g["누적 투자원금"],
        "S&P500 수익금": g["S&P500 PME"] - g["누적 투자원금"],
        "투자원금": g["누적 투자원금"],
    })


def _avg_buy_fx_series(sym_recs, idx, fx_hist, fx_now):
    """USD 종목의 보유분 가중평균 매수환율 시계열(평균법). 환차손익 제거용."""
    eff = pd.Series(fx_now, index=idx)
    cost_fx, hold_q, cur = 0.0, 0.0, fx_now
    for r in sorted(sym_recs, key=lambda x: x["date"]):
        fx_b = _safe_asof(fx_hist, r["date"], fx_now)
        if r["side"] == "BUY":
            cost_fx += r["qty"] * fx_b
            hold_q += r["qty"]
        elif hold_q > 0:
            cost_fx -= r["qty"] * (cost_fx / hold_q)
            hold_q -= r["qty"]
        cur = (cost_fx / hold_q) if hold_q > 1e-9 else cur
        eff.loc[eff.index >= r["date"]] = cur
    return eff


def build_asset_value_growth(orders, fx_now=1400.0, div_events=None, ticker=None,
                             include_div=True, include_fx=True):
    """보유 자산가치(원금+수익금) 성장 추이.
    내 자산가치 = 주식평가액(일별 환율) + 누적 배당(지급일 반영).
    S&P500 자산가치 = 매수는 SPY 매입, 매도는 '판 비중만큼' SPY도 매도(Modified PME) → 유령자본 제거.
    div_events: [(date, krw, symbol), ...]. ticker=None이면 전체(합산).
    include_div=False면 배당을 자산가치/손익에서 제외.
    include_fx=False면 달러 자산을 매수 가중평균 환율로 고정(환차손익 제거, 순수 주가손익).
    반환 DataFrame(index=날짜): [내 자산가치, S&P500 자산가치, 순투자원금, 내 누적손익, (개별시)주가]
    """
    recs = _trade_records(orders)
    if ticker:
        recs = [r for r in recs if r["symbol"] == ticker]
    if not recs:
        return pd.DataFrame()
    symbols = sorted(set(r["symbol"] for r in recs))
    spy_hist = get_history(BENCHMARK_TICKER, period="10y")
    fx_hist = get_usdkrw_history("10y")
    if spy_hist.empty:
        return pd.DataFrame()
    start = min(r["date"] for r in recs)
    idx = pd.date_range(start=start, end=spy_hist.index.max(), freq="D")

    def align(s):
        return s.reindex(idx.union(s.index)).ffill().reindex(idx).bfill()

    fx_daily = align(fx_hist) if not fx_hist.empty else pd.Series(fx_now, index=idx)
    spy_daily = align(spy_hist)
    sym_cur = {s: next(r["currency"] for r in recs if r["symbol"] == s) for s in symbols}
    sym_hist = {}
    for s in symbols:
        yft = to_yf_ticker(s, "KR" if sym_cur[s] == "KRW" else "US")
        h = get_history(yft, period="10y")
        if not h.empty:
            sym_hist[s] = align(h)

    recs_sorted = sorted(recs, key=lambda r: r["date"])
    my_val = pd.Series(0.0, index=idx)
    for s in symbols:
        if s not in sym_hist:
            continue
        if sym_cur[s] == "USD":
            fx_use = fx_daily if include_fx else _avg_buy_fx_series(
                [x for x in recs_sorted if x["symbol"] == s], idx, fx_hist, fx_now)
        else:
            fx_use = 1.0
        qty = pd.Series(0.0, index=idx)
        for r in [x for x in recs_sorted if x["symbol"] == s]:
            sign = 1 if r["side"] == "BUY" else -1
            qty.loc[qty.index >= r["date"]] += sign * r["qty"]
        my_val = my_val.add(qty * sym_hist[s] * fx_use, fill_value=0)

    # S&P500 가상펀드(Modified PME): 매수는 SPY 매입, 매도는 '판 비중만큼' SPY도 매도.
    spy_shares = pd.Series(0.0, index=idx)
    gross_buy = pd.Series(0.0, index=idx)
    sell_cash = pd.Series(0.0, index=idx)
    held = {s: 0.0 for s in symbols}
    spy_now = 0.0

    def _px_krw(sym, d):
        if sym not in sym_hist:
            return 0.0
        fxv = float(fx_daily.asof(d)) if sym_cur[sym] == "USD" else 1.0
        return float(sym_hist[sym].asof(d)) * fxv

    for r in recs_sorted:
        d = r["date"]
        s = r["symbol"]
        fx_d = _safe_asof(fx_hist, d, fx_now)
        cf = r["amount"] * fx_d if r["currency"] == "USD" else r["amount"]
        spy_px = _safe_asof(spy_hist, d, float(spy_hist.iloc[-1]))
        if r["side"] == "BUY":
            spy_now += cf / (spy_px * fx_d)  # 원화 매수금액 ÷ SPY 원화가
            held[s] = held.get(s, 0.0) + r["qty"]
            gross_buy.loc[gross_buy.index >= d] += cf
        else:
            port_val = sum(held[k] * _px_krw(k, d) for k in symbols if held.get(k, 0) > 0)
            sold_val = r["qty"] * _px_krw(s, d)
            w = min(max((sold_val / port_val) if port_val > 0 else 1.0, 0.0), 1.0)
            spy_now *= (1.0 - w)  # 판 비중만큼 SPY 매도
            held[s] = held.get(s, 0.0) - r["qty"]
            sell_cash.loc[sell_cash.index >= d] += cf
        spy_shares.loc[spy_shares.index >= d] = spy_now
    spy_val = spy_shares * spy_daily * fx_daily

    div_cum = pd.Series(0.0, index=idx)
    if include_div:
        for ev in (div_events or []):
            try:
                d = pd.to_datetime(ev[0]).tz_localize(None).normalize()
                amt = float(ev[1])
            except Exception:
                continue
            div_cum.loc[div_cum.index >= d] += amt

    out = pd.DataFrame({
        "내 자산가치": my_val + div_cum,
        "S&P500 자산가치": spy_val,
        "순투자원금": gross_buy - sell_cash,
    })
    out["내 누적손익"] = out["내 자산가치"] - out["순투자원금"]  # 보유가치+배당 − 순투입원금 = 총손익
    if ticker and ticker in sym_hist:
        out["주가"] = sym_hist[ticker]
    return out


def build_twr_comparison(orders, fx_now=1400.0, ticker=None, period="10y"):
    """투자금(현금흐름) 효과를 제거한 시간가중수익률(TWR) 비교.
    월급 등 추가 투입과 무관하게 '1원당 성과'로 내 포트폴리오 vs S&P500(원화)을 비교합니다.
    둘 다 시작 0%에서 출발. 반환: DataFrame[내 수익률(%), S&P500 수익률(%)]
    """
    recs = _trade_records(orders)
    if ticker:
        recs = [r for r in recs if r["symbol"] == ticker]
    if not recs:
        return pd.DataFrame()
    symbols = sorted(set(r["symbol"] for r in recs))
    spy = get_history(BENCHMARK_TICKER, period=period)
    fx_hist = get_usdkrw_history(period)
    if spy.empty:
        return pd.DataFrame()
    start = min(r["date"] for r in recs)
    idx = pd.date_range(start=start, end=spy.index.max(), freq="D")

    def align(s):
        return s.reindex(idx.union(s.index)).ffill().reindex(idx).bfill()

    fx_daily = align(fx_hist) if not fx_hist.empty else pd.Series(fx_now, index=idx)
    spy_daily = align(spy)
    sym_cur = {s: next(r["currency"] for r in recs if r["symbol"] == s) for s in symbols}
    sym_hist = {}
    for s in symbols:
        h = get_history(to_yf_ticker(s, "KR" if sym_cur[s] == "KRW" else "US"), period=period)
        if not h.empty:
            sym_hist[s] = align(h)

    recs_sorted = sorted(recs, key=lambda r: r["date"])
    my_val = pd.Series(0.0, index=idx)
    for s in symbols:
        if s not in sym_hist:
            continue
        qty = pd.Series(0.0, index=idx)
        for r in [x for x in recs_sorted if x["symbol"] == s]:
            qty.loc[qty.index >= r["date"]] += (1 if r["side"] == "BUY" else -1) * r["qty"]
        my_val = my_val.add(qty * sym_hist[s] * (fx_daily if sym_cur[s] == "USD" else 1.0), fill_value=0)

    invested = pd.Series(0.0, index=idx)
    for r in recs_sorted:
        fx_d = _safe_asof(fx_hist, r["date"], fx_now)
        cf = r["amount"] * fx_d if r["currency"] == "USD" else r["amount"]
        invested.loc[invested.index >= r["date"]] += (1 if r["side"] == "BUY" else -1) * cf

    # 시간가중수익률: 기여금(입출금) 제거한 일간 수익률을 누적 곱
    prev = my_val.shift(1)
    contrib = invested.diff().fillna(0.0)
    r_my = ((my_val - prev - contrib) / prev).where(prev > 1.0)
    r_my = r_my.replace([float("inf"), float("-inf")], pd.NA).fillna(0.0).clip(-0.95, 5.0)
    my_twr = (1.0 + r_my).cumprod()
    market = spy_daily * fx_daily

    active = my_val[my_val > 0]
    if active.empty:
        return pd.DataFrame()
    t0 = active.index[0]
    my_twr = my_twr / float(my_twr.loc[t0])
    spy_twr = market / float(market.loc[t0])
    out = pd.DataFrame({
        "내 수익률(%)": (my_twr - 1.0) * 100,
        "S&P500 수익률(%)": (spy_twr - 1.0) * 100,
    })
    return out.loc[out.index >= t0]


def build_ticker_price_trades(orders, ticker, start=None):
    """개별 종목의 주가 시계열과 내 매수/매도 시점(체결단가·수량, native)을 반환합니다.
    반환: (price(Series, native), buys(DataFrame[date,price,qty]), sells(DataFrame[date,price,qty]), currency)
    """
    recs = [r for r in _trade_records(orders) if r["symbol"] == ticker]
    if not recs:
        empty = pd.DataFrame(columns=["date", "price", "qty"])
        return pd.Series(dtype=float), empty, empty, "KRW"
    cur = recs[0]["currency"]
    yft = to_yf_ticker(ticker, "KR" if cur == "KRW" else "US")
    start_str = pd.to_datetime(start).strftime("%Y-%m-%d") if start is not None else None
    hist = get_history(yft, start=start_str, period="10y")
    buys = [{"date": r["date"], "price": r["amount"] / r["qty"], "qty": r["qty"]}
            for r in recs if r["side"] == "BUY" and r["qty"]]
    sells = [{"date": r["date"], "price": r["amount"] / r["qty"], "qty": r["qty"]}
             for r in recs if r["side"] == "SELL" and r["qty"]]
    cols = ["date", "price", "qty"]
    return hist, pd.DataFrame(buys, columns=cols), pd.DataFrame(sells, columns=cols), cur


def build_trade_bars(orders, ticker=None, fx_now=1400.0):
    """매수/매도 이벤트를 막대 그래프용 DataFrame으로 반환합니다.
    amount_krw = 당시 체결단가 × 수량 × 당시 환율(원화 환산), price = 당시 체결단가(native).
    반환: (buys[date,qty,amount,amount_krw,price,currency,symbol], sells[...]). ticker=None이면 전체.
    """
    recs = _trade_records(orders)
    if ticker:
        recs = [r for r in recs if r["symbol"] == ticker]
    fx_hist = get_usdkrw_history("10y")

    def _row(r):
        native_px = r["amount"] / r["qty"] if r["qty"] else 0.0  # 당시 체결단가
        fx = _safe_asof(fx_hist, r["date"], fx_now) if r["currency"] == "USD" else 1.0
        return {"date": r["date"], "qty": r["qty"], "amount": r["amount"],
                "amount_krw": r["amount"] * fx, "price": native_px,
                "currency": r["currency"], "symbol": r["symbol"]}

    cols = ["date", "qty", "amount", "amount_krw", "price", "currency", "symbol"]
    buys = [_row(r) for r in recs if r["side"] == "BUY" and r["qty"]]
    sells = [_row(r) for r in recs if r["side"] == "SELL" and r["qty"]]
    return pd.DataFrame(buys, columns=cols), pd.DataFrame(sells, columns=cols)


def build_stock_analytics(orders, fx_now=1400.0, name_map=None, holdings=None):
    """종목별 현재주가·S&P500 대비 수익률·알파(연)·베타·알파기여%·베타기여%를 계산합니다.
    베타/알파는 최초 매수 이후 일간 수익률을 S&P500(원화 환산) 대비 회귀해 산출합니다.
    반환: DataFrame(티커, 현재주가, 통화, S&P500대비(%p), 알파(연%), 베타, 알파기여(%), 베타기여(%))
    """
    name_map = name_map or {}
    recs = _trade_records(orders)
    if not recs:
        return pd.DataFrame()
    weight = {}
    for h in (holdings or []):
        weight[str(h.get("ticker"))] = float(h.get("weight_pct") or 0)

    symbols = sorted(set(r["symbol"] for r in recs))
    spy = get_history(BENCHMARK_TICKER, period="5y")
    fx_hist = get_usdkrw_history("5y")
    if spy.empty:
        return pd.DataFrame()

    rows = []
    for s in symbols:
        srecs = [r for r in recs if r["symbol"] == s]
        cur = srecs[0]["currency"]
        yft = to_yf_ticker(s, "KR" if cur == "KRW" else "US")
        h = get_history(yft, period="5y")
        if h.empty:
            continue
        first_buy = min(r["date"] for r in srecs)
        idx = h.index[h.index >= first_buy]
        if len(idx) < 30:
            idx = h.index
        px = h.reindex(idx).ffill()
        sp = spy.reindex(idx.union(spy.index)).ffill().reindex(idx)
        fxd = (fx_hist.reindex(idx.union(fx_hist.index)).ffill().reindex(idx)
               if not fx_hist.empty else pd.Series(fx_now, index=idx))
        stock_krw = px * fxd if cur == "USD" else px   # 투자자(원화) 관점 평가액
        mkt_krw = sp * fxd                              # SPY 원화 환산
        mkt_native = sp if cur == "USD" else sp * fxd   # 베타/알파는 종목 통화 기준
        rs = px.pct_change()                            # 종목 자국통화 수익률
        rm = mkt_native.pct_change()
        reg = (pd.concat([rs, rm], axis=1, keys=["s", "m"])
               .replace([float("inf"), float("-inf")], pd.NA).dropna())
        if len(reg) < 20 or reg["m"].var() == 0:
            continue
        beta = float(reg["s"].cov(reg["m"]) / reg["m"].var())
        alpha_ann = float((reg["s"].mean() - beta * reg["m"].mean()) * 252 * 100)
        my_tot = float(stock_krw.iloc[-1] / stock_krw.iloc[0] - 1) * 100
        spy_tot = float(mkt_krw.iloc[-1] / mkt_krw.iloc[0] - 1) * 100
        rows.append({"티커": s, "종목": name_map.get(s, s), "통화": cur,
                     "현재주가": round(float(px.iloc[-1]), 2),
                     "S&P500대비(%p)": round(my_tot - spy_tot, 2),
                     "알파(연%)": round(alpha_ann, 2), "베타": round(beta, 3),
                     "_w": weight.get(s, 0.0)})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    wa = df["_w"] * df["알파(연%)"]
    wb = df["_w"] * df["베타"]
    tot_a = wa.abs().sum() or 1.0
    tot_b = wb.sum() or 1.0
    df["알파기여(%)"] = (wa / tot_a * 100).round(1)
    df["베타기여(%)"] = (wb / tot_b * 100).round(1)
    return df.drop(columns=["_w"])


def build_spy_dca(orders, fx_now=1400.0, start_ym=None):
    """시작월 기준 '내 자산(순보유 평가액)'을 그 시점에 S&P500(SPY)에 일시투자(lump-sum)해
    현재까지 보유했다면의 결과. 시작월 이전에는 실제 포트폴리오 가치를 그대로 따라가고,
    시작월에 전량 SPY로 전환했다고 가정합니다. start_ym이 없으면 첫 매수 시점 기준.
    반환: (ts[S&P500 일시투자, 내 포트폴리오, 시작 금액], monthly_df, summary)
    """
    recs = _trade_records(orders)
    buys = [r for r in recs if r["side"] == "BUY"]
    empty = (pd.DataFrame(), pd.DataFrame(), {})
    if not buys:
        return empty
    spy = get_history(BENCHMARK_TICKER, period="10y")
    fx_hist = get_usdkrw_history("10y")
    if spy.empty:
        return empty

    first_buy = min(r["date"] for r in buys)
    if start_ym:
        try:
            T0 = pd.to_datetime(str(start_ym)).replace(day=1).normalize()
        except Exception:
            T0 = pd.Timestamp(first_buy).normalize()
    else:
        T0 = pd.Timestamp(first_buy).normalize()

    end = spy.index.max()
    idx = pd.date_range(start=min(pd.Timestamp(first_buy).normalize(), T0), end=end, freq="D")

    def align(s):
        return s.reindex(idx.union(s.index)).ffill().reindex(idx).bfill()

    spy_daily = align(spy)
    fx_daily = align(fx_hist) if not fx_hist.empty else pd.Series(fx_now, index=idx)

    # 내 실제 보유 평가액(전체 매매 반영) — 시작금액 산출 & 비교용
    symbols = sorted(set(r["symbol"] for r in recs))
    sym_cur = {s: next(r["currency"] for r in recs if r["symbol"] == s) for s in symbols}
    my_hold = pd.Series(0.0, index=idx)
    for s in symbols:
        h = get_history(to_yf_ticker(s, "KR" if sym_cur[s] == "KRW" else "US"), period="10y")
        if h.empty:
            continue
        px = align(h)
        qty = pd.Series(0.0, index=idx)
        for r in [x for x in recs if x["symbol"] == s]:
            qty.loc[qty.index >= r["date"]] += (1 if r["side"] == "BUY" else -1) * r["qty"]
        my_hold = my_hold.add(qty * px * (fx_daily if sym_cur[s] == "USD" else 1.0), fill_value=0)

    # 시작월 시점 내 자산을 SPY에 일시투자
    after = idx[idx >= T0]
    T0_eff = after[0] if len(after) else idx[-1]
    start_krw = float(my_hold.loc[T0_eff])
    spy_last = float(spy_daily.iloc[-1])
    fx_last = float(fx_daily.iloc[-1])
    spy_T0 = _safe_asof(spy, T0_eff, spy_last)
    fx_T0 = _safe_asof(fx_hist, T0_eff, fx_last)
    start_shares = start_krw / (spy_T0 * fx_T0) if (start_krw > 0 and spy_T0 * fx_T0) else 0.0

    sim = my_hold.copy()  # 시작월 이전은 실제 포트폴리오를 그대로 따라감
    mask = idx >= T0_eff
    sim.loc[mask] = start_shares * spy_daily.loc[mask] * fx_daily.loc[mask]

    # 내 투자원금(수익금 계산용): 시작월 시점 자산 + 이후 순투입(추가 매수 − 매도 회수)
    my_principal = pd.Series(0.0, index=idx)
    my_principal.loc[mask] = start_krw
    for r in recs:
        if r["date"] >= T0_eff:
            cf = r["amount"] * _safe_asof(fx_hist, r["date"], fx_last) if r["currency"] == "USD" else r["amount"]
            my_principal.loc[my_principal.index >= r["date"]] += (1 if r["side"] == "BUY" else -1) * cf

    # 투자원금을 제외한 '수익금'만 비교 (둘 다 시작월 기준 0에서 출발)
    spy_profit = pd.Series(0.0, index=idx)
    my_profit = pd.Series(0.0, index=idx)
    spy_profit.loc[mask] = sim.loc[mask] - start_krw
    my_profit.loc[mask] = my_hold.loc[mask] - my_principal.loc[mask]

    ts = pd.DataFrame({"S&P500 수익금": spy_profit, "내 수익금": my_profit})

    months = pd.date_range(start=pd.Timestamp(T0_eff).replace(day=1),
                           end=pd.Timestamp(end).replace(day=1), freq="MS")
    rows = []
    for i, m in enumerate(months):
        d = idx[-1] if i == len(months) - 1 else (m if m in idx else idx[idx >= m][0])
        rows.append({
            "월": m.strftime("%Y-%m"),
            "SPY(USD)": round(_safe_asof(spy, d, spy_last), 2),
            "S&P500 수익금(원)": round(float(spy_profit.loc[d])),
            "내 수익금(원)": round(float(my_profit.loc[d])),
        })

    spy_p = float(spy_profit.iloc[-1])
    my_p = float(my_profit.iloc[-1])
    summary = {
        "시작월": T0.strftime("%Y-%m"),
        "시작금액": round(start_krw),
        "SPY시작가": round(spy_T0, 2),
        "S&P500수익금": round(spy_p),
        "내수익금": round(my_p),
        "차이": round(my_p - spy_p),
    }
    return ts, pd.DataFrame(rows), summary


# ───────────── 달러 평단가 · 10년 환율 · S&P500 알파/베타 (방법 A: 현금흐름 PME) ─────────────

def compute_usd_avg_cost(orders, fx_now=1400.0):
    """USD 매수 체결의 '그 날 환율'을 매수금액(USD)으로 가중평균한 달러 평단가(원/달러).
    매수일이 오래되어도 정확하도록 10년 환율 이력을 사용합니다.
    반환: dict(avg_fx, total_usd, current_fx, invested_krw, fx_pnl_krw) 또는 None(USD 매수 없음)
    """
    fx_hist = get_usdkrw_history(period="10y")

    def fx_on(date):
        if fx_hist.empty:
            return fx_now
        try:
            v = fx_hist.asof(pd.to_datetime(date).tz_localize(None).normalize())
            return float(v) if pd.notna(v) else float(fx_hist.iloc[0])
        except Exception:
            return fx_now

    total_usd = 0.0
    weighted = 0.0
    for o in orders:
        if o.get("currency") != "USD" or o.get("side") != "BUY":
            continue
        ex = o.get("execution") or {}
        usd_amt = float(ex.get("filledAmount") or 0)
        if usd_amt <= 0:
            continue
        weighted += usd_amt * fx_on(ex.get("filledAt") or o.get("orderedAt"))
        total_usd += usd_amt

    if total_usd <= 0:
        return None
    avg_fx = weighted / total_usd
    return {
        "avg_fx": avg_fx,
        "total_usd": total_usd,
        "current_fx": fx_now,
        "invested_krw": weighted,
        "fx_pnl_krw": total_usd * (fx_now - avg_fx),
    }


def build_usdkrw_history_frame(period="10y"):
    """USD/KRW 환율 시계열을 그래프용 DataFrame(index=날짜, 열='원/달러')으로 반환합니다."""
    s = get_usdkrw_history(period=period)
    if s is None or s.empty:
        return pd.DataFrame()
    return s.rename("원/달러").to_frame()


def _xnpv(rate, cashflows):
    """불규칙 현금흐름의 순현재가치(NPV). cashflows: [(Timestamp, amount)]."""
    t0 = min(d for d, _ in cashflows)
    return sum(cf / (1.0 + rate) ** ((d - t0).days / 365.0) for d, cf in cashflows)


def xirr(cashflows):
    """불규칙 현금흐름의 연환산 내부수익률(XIRR, 소수)을 이분법으로 계산합니다.
    cashflows: [(Timestamp, amount)] — 유출(-)·유입(+). 해가 없으면 None.
    """
    if not cashflows:
        return None
    amounts = [cf for _, cf in cashflows]
    if not (any(a > 0 for a in amounts) and any(a < 0 for a in amounts)):
        return None
    lo, hi = -0.9999, 100.0
    f_lo = _xnpv(lo, cashflows)
    f_hi = _xnpv(hi, cashflows)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if f_lo * f_hi > 0:  # 부호 변화가 없으면 유효한 해가 없음
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = _xnpv(mid, cashflows)
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def compute_alpha_beta(orders, fx_now=1400.0, period="10y"):
    """방법 A(현금흐름 기반 S&P500 가상펀드)로 포트폴리오 전체 알파와 베타를 계산합니다.
    - 알파: 내 포트폴리오 XIRR − S&P500 가상펀드 XIRR (청산·보유 종목 모두 현금흐름으로 반영)
    - 베타: 기여금(매수·매도)을 제거한 일간 수익률의 시장(SPY 원화 환산) 대비 회귀계수
    반환: dict 또는 None
    """
    recs = _trade_records(orders)
    if not recs:
        return None

    symbols = sorted(set(r["symbol"] for r in recs))
    spy_hist = get_history(BENCHMARK_TICKER, period=period)
    fx_hist = get_usdkrw_history(period)
    if spy_hist.empty:
        return None

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
        h = get_history(yft, period=period)
        if not h.empty:
            sym_hist[s] = align(h)

    recs_sorted = sorted(recs, key=lambda r: r["date"])

    # 내 포트폴리오 일별 평가액(원화)
    my_val = pd.Series(0.0, index=idx)
    for s in symbols:
        if s not in sym_hist:
            continue
        qty_steps = pd.Series(0.0, index=idx)
        for r in [x for x in recs_sorted if x["symbol"] == s]:
            sign = 1 if r["side"] == "BUY" else -1
            qty_steps.loc[qty_steps.index >= r["date"]] += sign * r["qty"]
        val = qty_steps * sym_hist[s] * (fx_daily if sym_cur[s] == "USD" else 1.0)
        my_val = my_val.add(val, fill_value=0)

    # S&P500 가상펀드(Modified PME): 매수는 SPY 매입, 매도는 '판 비중만큼' SPY 매도 → 음수 지분 방지.
    spy_shares = pd.Series(0.0, index=idx)
    invested = pd.Series(0.0, index=idx)
    my_cashflows = []
    spy_cashflows = []
    held = {s: 0.0 for s in symbols}
    spy_now = 0.0

    def _px_krw(sym, d):
        if sym not in sym_hist:
            return 0.0
        fxv = float(fx_daily.asof(d)) if sym_cur[sym] == "USD" else 1.0
        return float(sym_hist[sym].asof(d)) * fxv

    for r in recs_sorted:
        d = r["date"]
        s = r["symbol"]
        spy_px = _safe_asof(spy_hist, d, float(spy_hist.iloc[-1]))
        fx_d = _safe_asof(fx_hist, d, fx_now)
        cf = r["amount"] * fx_d if r["currency"] == "USD" else r["amount"]
        if r["side"] == "BUY":
            spy_now += cf / (spy_px * fx_d)
            held[s] = held.get(s, 0.0) + r["qty"]
            invested.loc[invested.index >= d] += cf
            my_cashflows.append((d, -cf))
            spy_cashflows.append((d, -cf))
        else:  # 판 비중(w)만큼 SPY도 인출
            port_val = sum(held[k] * _px_krw(k, d) for k in symbols if held.get(k, 0) > 0)
            sold_val = r["qty"] * _px_krw(s, d)
            w = min(max((sold_val / port_val) if port_val > 0 else 1.0, 0.0), 1.0)
            spy_dist = spy_now * spy_px * fx_d * w  # SPY 가상펀드에서 인출한 금액
            spy_now *= (1.0 - w)
            held[s] = held.get(s, 0.0) - r["qty"]
            invested.loc[invested.index >= d] -= cf
            my_cashflows.append((d, cf))
            spy_cashflows.append((d, spy_dist))
        spy_shares.loc[spy_shares.index >= d] = spy_now

    spy_val = spy_shares * spy_daily * fx_daily
    today = idx.max()
    my_final = float(my_val.iloc[-1])
    spy_final = float(spy_val.iloc[-1])

    port_xirr = xirr(my_cashflows + [(today, my_final)])
    spy_xirr = xirr(spy_cashflows + [(today, spy_final)])
    alpha_pct = ((port_xirr - spy_xirr) * 100.0) if (port_xirr is not None and spy_xirr is not None) else None

    # 베타: 기여금 제거 일간 수익률 vs 시장(SPY 원화)
    market = spy_daily * fx_daily
    contrib = invested.diff().fillna(0.0)
    prev_val = my_val.shift(1)
    gain = my_val - prev_val - contrib
    rp = (gain / prev_val).where(prev_val > 0)
    rm = market.pct_change()
    reg = (
        pd.concat([rp, rm], axis=1, keys=["rp", "rm"])
        .replace([float("inf"), float("-inf")], pd.NA)
        .dropna()
    )
    reg = reg[reg["rm"] != 0.0]  # 주말·휴장(ffill로 평탄) 잡음 제거 → 실제 거래일만 회귀
    beta = corr = None
    if len(reg) > 5 and reg["rm"].var() > 0:
        beta = float(reg["rp"].cov(reg["rm"]) / reg["rm"].var())
        corr = float(reg["rp"].corr(reg["rm"]))

    return {
        "port_xirr_pct": round(port_xirr * 100, 2) if port_xirr is not None else None,
        "spy_xirr_pct": round(spy_xirr * 100, 2) if spy_xirr is not None else None,
        "alpha_pct": round(alpha_pct, 2) if alpha_pct is not None else None,
        "beta": round(beta, 3) if beta is not None else None,
        "corr": round(corr, 3) if corr is not None else None,
        "my_final_krw": round(my_final),
        "spy_final_krw": round(spy_final),
        "invested_krw": round(float(invested.iloc[-1])),
        "n_days": int(len(reg)),
    }

