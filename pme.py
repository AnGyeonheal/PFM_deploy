"""PME(Public Market Equivalent) 기반 타이밍 반영 성과 분석.
매수는 동일 원금, 매도는 동일 평가액 비중을 S&P500(SPY)에 적용하고,
실제 내 종목 성과와 비교하여 진짜 초과수익(알파)을 계산합니다.
주가 추이만 보는 방식과 달리 매매 타이밍이 반영됩니다.
"""
import math

import pandas as pd
from pyxirr import DayCount, xirr as solve_xirr

from benchmark import to_yf_ticker, get_history, get_dividends, get_usdkrw_history, BENCHMARK_TICKER
from names import is_krw_foreign


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
        if qty <= 0 or amt <= 0 or o.get("side") not in ("BUY", "SELL") or not o.get("symbol"):
            continue
        raw = ex.get("filledAt") or o.get("orderedAt")
        try:
            timestamp = pd.to_datetime(raw).tz_localize(None)
            date = timestamp.normalize()
        except (TypeError, ValueError):
            try:
                timestamp = pd.to_datetime(raw, utc=True).tz_localize(None)
                date = timestamp.normalize()
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
            "timestamp": timestamp,
        })
    return sorted(recs, key=lambda record: record["timestamp"])


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


def _held_symbols(recs):
    """순보유수량>0(현재 보유) & 티커 있는 종목 집합.
    전량/초과매도·티커누락 종목은 평가 불가 → 원금엔 잡히고 평가액엔 빠져 수익률이 음수로 왜곡되므로 제외."""
    net = {}
    for r in recs:
        net[r["symbol"]] = net.get(r["symbol"], 0) + (1 if r["side"] == "BUY" else -1) * r["qty"]
    return {s for s, n in net.items() if s and n > 0}


def compute_rolling_beta(orders, fx_now=1400.0, ticker=None, window=60, period="10y",
                         include_div=True, include_fx=True, div_events=None):
    frame = build_asset_value_growth(orders, fx_now, div_events, ticker, include_div, include_fx)
    daily = daily_returns_from_growth(frame)
    if daily.empty:
        return pd.Series(dtype=float)
    daily = daily.loc[daily.index.dayofweek < 5]
    mine, market = daily["내 수익률(%)"], daily["S&P500 수익률(%)"]
    covariance = mine.rolling(window, min_periods=min(20, window)).cov(market)
    variance = market.rolling(window, min_periods=min(20, window)).var().replace(0, float("nan"))
    return (covariance / variance).dropna().rename("베타")


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


def _cost_native_avg_fx_series(sym_recs, idx, fx_hist, fx_now):
    """USD 종목의 보유 매수원가(달러)·가중평균 매수환율 시계열(평균법)."""
    cost_native = pd.Series(0.0, index=idx)
    avg_fx = pd.Series(fx_now, index=idx)
    cn = cost_fx = hold_q = 0.0
    cur = fx_now
    for r in sorted(sym_recs, key=lambda x: x["date"]):
        fx_b = _safe_asof(fx_hist, r["date"], fx_now)
        # 원화 상장 해외 ETF는 원화 결제액을 매수시점 환율로 달러 원가로 환산(환차 분리 정합)
        amt = (r["amount"] / fx_b if (r["currency"] == "KRW" and is_krw_foreign(r["symbol"]) and fx_b)
               else r["amount"])
        if r["side"] == "BUY":
            cn += amt
            cost_fx += r["qty"] * fx_b
            hold_q += r["qty"]
        elif hold_q > 0:
            sell = min(r["qty"], hold_q)
            cn -= sell * (cn / hold_q)
            cost_fx -= sell * (cost_fx / hold_q)
            hold_q -= sell
        cur = (cost_fx / hold_q) if hold_q > 1e-9 else cur
        cost_native.loc[cost_native.index >= r["date"]] = cn
        avg_fx.loc[avg_fx.index >= r["date"]] = cur
    return cost_native, avg_fx


def _holdings_value_series(recs_sorted, symbols, sym_hist, sym_cur,
                          fx_daily, fx_hist, fx_now, idx, include_fx=True):
    """보유수량 × 주가 × 환율 일별 평가액(원화) 합계. include_fx=False면 달러 종목을 매수평균환율로 고정(환차 제거)."""
    my_val = pd.Series(0.0, index=idx)
    for s in symbols:
        if s not in sym_hist:
            continue
        sym_recs = [x for x in recs_sorted if x["symbol"] == s]
        qty = pd.Series(0.0, index=idx)
        for r in sym_recs:
            sign = 1 if r["side"] == "BUY" else -1
            qty.loc[qty.index >= r["date"]] += sign * r["qty"]
        if sym_cur[s] != "USD":
            my_val = my_val.add(qty * sym_hist[s], fill_value=0)
        elif include_fx:
            my_val = my_val.add(qty * sym_hist[s] * fx_daily, fill_value=0)
        else:
            avg_fx = _avg_buy_fx_series(sym_recs, idx, fx_hist, fx_now)
            my_val = my_val.add(qty * sym_hist[s] * avg_fx, fill_value=0)
    return my_val


def build_asset_value_growth(orders, fx_now=1400.0, div_events=None, ticker=None,
                             include_div=True, include_fx=True, end=None):
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
    end_date = pd.Timestamp(end).tz_localize(None).normalize() if end is not None else None
    if end_date is not None:
        recs = [record for record in recs if record["date"] <= end_date]
    if not recs:
        return pd.DataFrame()
    symbols = sorted(set(r["symbol"] for r in recs))
    coverage = {"requested_symbols": symbols, "included_symbols": [], "excluded_symbols": [], "warnings": []}
    spy_hist = get_history(BENCHMARK_TICKER, period="10y")
    fx_hist = get_usdkrw_history("10y")
    if spy_hist.empty:
        unavailable = pd.DataFrame()
        coverage["excluded_symbols"] = symbols.copy()
        coverage["warnings"].append("벤치마크 시세가 없어 성과를 계산할 수 없습니다.")
        unavailable.attrs.update(coverage)
        return unavailable
    sym_cur = {s: next(r["currency"] for r in recs if r["symbol"] == s) for s in symbols}
    native_history = {}
    for s in symbols:
        symbol_records = [record for record in recs if record["symbol"] == s]
        quantity = 0.0
        reason = None
        for record in symbol_records:
            if record["side"] == "SELL" and record["qty"] > quantity + 1e-8:
                reason = "매도 수량에 대응하는 매수 이력이 부족합니다."
                break
            quantity += record["qty"] if record["side"] == "BUY" else -record["qty"]
        first_trade = min(record["date"] for record in symbol_records)
        if not reason and first_trade < spy_hist.index.min():
            reason = "벤치마크 시세보다 오래된 거래가 있습니다."
        if reason:
            coverage["excluded_symbols"].append(s)
            coverage["warnings"].append(f"{s}: {reason}")
            continue
        yft = to_yf_ticker(s, "KR" if sym_cur[s] == "KRW" else "US")
        h = get_history(yft, period="10y")
        if h.empty:
            reason = "시세가 없어 성과를 계산할 수 없습니다."
        elif first_trade < h.index.min():
            reason = "최초 거래 시점의 시세가 없어 성과를 계산할 수 없습니다."
        if reason:
            coverage["excluded_symbols"].append(s)
            coverage["warnings"].append(f"{s}: {reason}")
            continue
        native_history[s] = h
        coverage["included_symbols"].append(s)

    symbols = coverage["included_symbols"]
    recs = [record for record in recs if record["symbol"] in native_history]
    if not recs:
        unavailable = pd.DataFrame()
        unavailable.attrs.update(coverage)
        return unavailable
    start = min(r["date"] for r in recs)
    latest_price_date = max([spy_hist.index.max()] + [history.index.max() for history in native_history.values()])
    valuation_end = min(end_date, latest_price_date) if end_date is not None else latest_price_date
    idx = pd.date_range(start=start, end=valuation_end, freq="D")

    def align(series):
        return series.reindex(idx.union(series.index)).ffill().reindex(idx).bfill()

    fx_daily = align(fx_hist) if not fx_hist.empty else pd.Series(fx_now, index=idx)
    spy_daily = align(spy_hist)
    sym_hist = {}
    for symbol in symbols:
        history = align(native_history[symbol])
        if sym_cur[symbol] == "KRW" and is_krw_foreign(symbol):
            history = history / fx_daily
            sym_cur[symbol] = "USD"
        sym_hist[symbol] = history

    recs_sorted = sorted(recs, key=lambda r: r["date"])
    my_val = _holdings_value_series(recs_sorted, symbols, sym_hist, sym_cur,
                                   fx_daily, fx_hist, fx_now, idx, include_fx)

    # S&P500 가상펀드(Modified PME): 매수는 SPY 매입, 매도는 '판 비중만큼' SPY도 매도.
    spy_shares = pd.Series(0.0, index=idx)
    gross_buy = pd.Series(0.0, index=idx)
    sell_cash = pd.Series(0.0, index=idx)
    spy_sell_cash = pd.Series(0.0, index=idx)
    spy_buy_fx = pd.Series(fx_now, index=idx)
    holding_cost = pd.Series(0.0, index=idx)
    held = {s: 0.0 for s in symbols}
    cost_basis = {s: 0.0 for s in symbols}
    buy_fx = {s: 0.0 for s in symbols}
    spy_now = 0.0
    spy_average_fx = fx_now

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
            spy_bought = cf / (spy_px * fx_d)
            spy_average_fx = (spy_now * spy_average_fx + spy_bought * fx_d) / (spy_now + spy_bought)
            spy_now += spy_bought
            buy_fx[s] = (held[s] * buy_fx[s] + r["qty"] * fx_d) / (held[s] + r["qty"])
            cost_basis[s] += cf
            held[s] = held.get(s, 0.0) + r["qty"]
            gross_buy.loc[gross_buy.index >= d] += cf
        else:
            port_val = sum(held[k] * _px_krw(k, d) for k in symbols if held.get(k, 0) > 0)
            sold_val = r["qty"] * _px_krw(s, d)
            w = min(max((sold_val / port_val) if port_val > 0 else 1.0, 0.0), 1.0)
            spy_sale_fx = fx_d if include_fx else spy_average_fx
            spy_sell_cash.loc[spy_sell_cash.index >= d] += spy_now * spy_px * spy_sale_fx * w
            spy_now *= (1.0 - w)  # 판 비중만큼 SPY 매도
            if not include_fx and sym_cur[s] == "USD":
                cf = cf / fx_d * buy_fx[s]
            if held[s] > 0:
                cost_basis[s] *= max(1.0 - r["qty"] / held[s], 0.0)
            held[s] = held.get(s, 0.0) - r["qty"]
            sell_cash.loc[sell_cash.index >= d] += cf
        spy_shares.loc[spy_shares.index >= d] = spy_now
        spy_buy_fx.loc[spy_buy_fx.index >= d] = spy_average_fx
        holding_cost.loc[holding_cost.index >= d] = sum(cost_basis.values())
    spy_val = spy_shares * spy_daily * (fx_daily if include_fx else spy_buy_fx)

    div_cum = pd.Series(0.0, index=idx)
    spy_div_cum = pd.Series(0.0, index=idx)
    if include_div:
        spy_dividends = get_dividends(BENCHMARK_TICKER)
        entitlement = spy_shares.shift(1).fillna(0.0)
        for dividend_date, dividend_native in spy_dividends.items():
            if dividend_date not in idx:
                continue
            dividend_fx = fx_daily.loc[dividend_date] if include_fx else spy_buy_fx.loc[dividend_date]
            dividend_krw = entitlement.loc[dividend_date] * dividend_native * dividend_fx
            spy_div_cum.loc[spy_div_cum.index >= dividend_date] += dividend_krw
        for ev in (div_events or []):
            try:
                d = pd.to_datetime(ev[0]).tz_localize(None).normalize()
                amt = float(ev[1])
                symbol = ev[2] if len(ev) > 2 else None
                if symbol and symbol not in symbols:
                    continue
                if not include_fx and symbol and sym_cur.get(symbol) == "USD":
                    records = [record for record in recs_sorted if record["symbol"] == symbol]
                    average_fx = _avg_buy_fx_series(records, idx, fx_hist, fx_now)
                    amt *= _safe_asof(average_fx, d, fx_now) / _safe_asof(fx_hist, d, fx_now)
            except Exception:
                continue
            div_cum.loc[div_cum.index >= d] += amt

    out = pd.DataFrame({
        "내 자산가치": my_val + div_cum,
        "S&P500 자산가치": spy_val + spy_div_cum,
        "순투자원금": gross_buy - sell_cash,
        "누적매수금액": gross_buy,
        "누적매도금액": sell_cash,
        "S&P500 누적매도금액": spy_sell_cash,
        "누적배당금액": div_cum,
        "S&P500 누적배당금액": spy_div_cum,
        "보유원가": holding_cost,
    })
    out["내 누적손익"] = out["내 자산가치"] - out["순투자원금"]  # 보유가치+배당 − 순투입원금 = 총손익
    if ticker and ticker in sym_hist:
        out["주가"] = sym_hist[ticker] * (fx_daily if is_krw_foreign(ticker) else 1.0)
    out.attrs.update(coverage)
    out.attrs["price_dates"] = {symbol: history.loc[:valuation_end].index[-1].strftime("%Y-%m-%d")
                               for symbol, history in native_history.items()}
    out.attrs["benchmark_price_date"] = spy_hist.loc[:valuation_end].index[-1].strftime("%Y-%m-%d")
    return out


def daily_returns_from_growth(frame):
    """일말 현금흐름 가정의 일별 TWR. 매도대금은 외부 인출, 배당은 보유 현금."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    purchases = frame["누적매수금액"].diff().fillna(frame["누적매수금액"])
    result = pd.DataFrame(index=frame.index)
    for value_column, sales_column, return_column in (
        ("내 자산가치", "누적매도금액", "내 수익률(%)"),
        ("S&P500 자산가치", "S&P500 누적매도금액", "S&P500 수익률(%)"),
    ):
        value = frame[value_column]
        previous = value.shift(1).fillna(0.0)
        sales = frame[sales_column].diff().fillna(frame[sales_column])
        factor = (value + sales - purchases) / previous.where(previous > 0)
        initial = (value + sales) / purchases.where(purchases > 0)
        factor = factor.where(previous > 0, initial).fillna(1.0)
        result[return_column] = factor - 1.0
    return result


def twr_from_growth(frame):
    return ((1.0 + daily_returns_from_growth(frame)).cumprod() - 1.0) * 100


def comparison_statistics(frame, start=None):
    """동일 현금흐름의 누적 ROI, 일별 TWR 및 선택기간 회귀 통계를 계산합니다."""
    empty = {"returns": pd.DataFrame(), "daily": pd.DataFrame(), "rolling_beta": pd.Series(dtype=float),
             "twr": None, "beta": None, "corr": None, "sharpe": None, "regression_alpha": None}
    if frame is None or frame.empty:
        return empty
    selected = frame.loc[frame.index >= start] if start is not None else frame
    if selected.empty:
        return empty
    before = frame.loc[frame.index < selected.index[0]]
    opening = before.iloc[-1] if not before.empty else pd.Series(0.0, index=frame.columns)
    purchases = selected["누적매수금액"] - opening["누적매수금액"]
    returns = pd.DataFrame(index=selected.index)
    for value, sales, label in (("내 자산가치", "누적매도금액", "portfolio"),
                                ("S&P500 자산가치", "S&P500 누적매도금액", "sp500")):
        capital = opening[value] + purchases
        withdrawals = selected[sales] - opening[sales]
        returns[label] = (selected[value] + withdrawals - capital) / capital.where(capital > 0) * 100
    daily = daily_returns_from_growth(frame)
    daily.columns = ["portfolio", "sp500"]
    daily = daily.loc[selected.index]
    stats = dict(empty, returns=returns, daily=daily)
    if returns["portfolio"].notna().any():
        stats["twr"] = float(((1.0 + daily["portfolio"]).prod() - 1.0) * 100)
    regression = daily.loc[daily.index.dayofweek < 5].replace([float("inf"), float("-inf")], float("nan")).dropna()
    market = regression["sp500"]
    portfolio = regression["portfolio"]
    stats["rolling_beta"] = portfolio.rolling(60, min_periods=20).cov(market) / market.rolling(60, min_periods=20).var().replace(0, float("nan"))
    risk_free_daily = 1.035 ** (1.0 / 252) - 1.0
    if len(regression) >= 20 and market.var() > 1e-15:
        stats["beta"] = float(portfolio.cov(market) / market.var())
        correlation = portfolio.corr(market)
        stats["corr"] = float(correlation) if pd.notna(correlation) else None
        stats["regression_alpha"] = float(((portfolio.mean() - risk_free_daily)
                                           - stats["beta"] * (market.mean() - risk_free_daily)) * 252 * 100)
        if abs(stats["regression_alpha"]) < 1e-10:
            stats["regression_alpha"] = 0.0
    if len(regression) >= 20 and portfolio.std() > 1e-15:
        stats["sharpe"] = float((portfolio.mean() - risk_free_daily) / portfolio.std() * 252 ** 0.5)
    return stats


def profit_from_growth(frame, start=None):
    if frame is None or frame.empty:
        return {}
    selected = frame.loc[frame.index >= start] if start is not None else frame
    if selected.empty:
        return {}
    before = frame.loc[frame.index < selected.index[0]]
    opening = before.iloc[-1] if not before.empty else pd.Series(0.0, index=frame.columns)
    last = selected.iloc[-1]
    realized = frame["누적매도금액"] - frame["누적매수금액"] + frame["보유원가"]
    unrealized = frame["내 자산가치"] - frame["누적배당금액"] - frame["보유원가"]
    realized_change = realized.iloc[-1] - (realized.loc[before.index[-1]] if not before.empty else 0.0)
    unrealized_change = unrealized.iloc[-1] - (unrealized.loc[before.index[-1]] if not before.empty else 0.0)
    dividend = last["누적배당금액"] - opening["누적배당금액"]
    capital = opening["내 자산가치"] + last["누적매수금액"] - opening["누적매수금액"]
    total = realized_change + unrealized_change + dividend
    return {"totalBuy": float(last["보유원가"]), "totalCurrent": float(last["내 자산가치"] - last["누적배당금액"]),
            "realizedPnL": float(realized_change), "unrealizedPnL": float(unrealized_change),
            "dividendPnL": float(dividend), "totalPnL": float(total),
            "returnPct": float(total / capital * 100) if capital > 0 else None}


def build_twr_comparison(orders, fx_now=1400.0, ticker=None, period="10y", include_fx=True,
                         div_events=None, include_div=True):
    frame = build_asset_value_growth(orders, fx_now, div_events, ticker, include_div, include_fx)
    return twr_from_growth(frame)


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


def build_stock_analytics(orders, fx_now=1400.0, name_map=None, holdings=None,
                          include_div=True, include_fx=True, div_events=None):
    """최초 거래 이후 공통 원장의 ROI·배당/환차 반영 일별 TWR 회귀·현재 비중 기여도를 계산합니다."""
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
        frame = build_asset_value_growth(orders, fx_now, div_events, s, include_div, include_fx)
        stats = comparison_statistics(frame)
        if stats["beta"] is None or stats["regression_alpha"] is None:
            continue
        beta = stats["beta"]
        alpha_ann = stats["regression_alpha"]
        my_tot = float(stats["returns"]["portfolio"].iloc[-1])
        spy_tot = float(stats["returns"]["sp500"].iloc[-1])
        rows.append({"티커": s, "종목": name_map.get(s, s), "통화": cur,
                     "현재주가": round(float(h.iloc[-1]), 2),
                     "S&P500대비(%p)": round(my_tot - spy_tot, 2),
                     "알파(연%)": round(alpha_ann, 2), "베타": round(beta, 3),
                     "_w": weight.get(s, 0.0)})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    wa = df["_w"] * df["알파(연%)"]
    wb = df["_w"] * df["베타"]
    tot_a = wa.abs().sum() or 1.0
    tot_b = wb.abs().sum() or 1.0
    df["알파기여(%)"] = (wa / tot_a * 100).round(1)
    df["베타기여(%)"] = (wb / tot_b * 100).round(1)
    return df.drop(columns=["_w"])


def build_spy_dca(orders, fx_now=1400.0, start_ym=None, ticker=None, include_div=True,
                   include_fx=True, div_events=None, end=None):
    """동일 초기자본으로 내 전략(TWR)과 SPY 일시투자를 비교하며 이후 입출금은 제외합니다."""
    frame = build_asset_value_growth(orders, fx_now, div_events, ticker, include_div, include_fx, end=end)
    empty = (pd.DataFrame(), pd.DataFrame(), {})
    if frame.empty:
        return empty
    start = pd.Timestamp(start_ym) if start_ym else frame.index[0]
    active = frame.loc[(frame.index >= start) & (frame["내 자산가치"] > 0)]
    if active.empty:
        return empty
    start = active.index[0]
    selected = frame.loc[frame.index >= start]
    initial = float(selected["내 자산가치"].iloc[0])
    daily = daily_returns_from_growth(frame).loc[selected.index, "내 수익률(%)"].copy()
    daily.iloc[0] = 0.0
    mine = initial * ((1.0 + daily).cumprod() - 1.0)
    spy = get_history(BENCHMARK_TICKER, period="10y")
    fx_history = get_usdkrw_history("10y")
    spy_price = spy.reindex(spy.index.union(selected.index)).ffill().reindex(selected.index)
    fx_daily = fx_history.reindex(fx_history.index.union(selected.index)).ffill().reindex(selected.index) if not fx_history.empty else pd.Series(fx_now, index=selected.index)
    fx_base = float(fx_daily.iloc[0])
    shares = initial / (float(spy_price.iloc[0]) * fx_base)
    spy_value = shares * spy_price * (fx_daily if include_fx else fx_base)
    if include_div:
        for date, dividend in get_dividends(BENCHMARK_TICKER).items():
            if date <= start or date not in selected.index:
                continue
            amount = shares * dividend * (float(fx_daily.loc[date]) if include_fx else fx_base)
            spy_value.loc[spy_value.index >= date] += amount
    spy_profit = spy_value - initial
    series = pd.DataFrame({"S&P500 수익금": spy_profit, "내 수익금": mine})
    monthly = series.resample("ME").last()
    rows = [{"월": date.strftime("%Y-%m"), "S&P500 수익금(원)": round(float(row["S&P500 수익금"])),
             "내 수익금(원)": round(float(row["내 수익금"]))} for date, row in monthly.iterrows()]
    summary = {"시작월": start.strftime("%Y-%m"), "시작금액": round(initial),
               "SPY시작가": float(spy_price.iloc[0]), "S&P500수익금": round(float(spy_profit.iloc[-1])),
               "내수익금": round(float(mine.iloc[-1])), "차이": round(float(mine.iloc[-1] - spy_profit.iloc[-1]))}
    return series, pd.DataFrame(rows), summary


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
    """Actual/365 기준 XIRR(소수). 날짜별 현금흐름을 합산하고 금액 단위를 정규화합니다."""
    if not cashflows:
        return None
    grouped = {}
    for date, amount in cashflows:
        try:
            date = pd.Timestamp(date)
            amount = float(amount)
            if pd.isna(date) or not math.isfinite(amount):
                return None
            date = date.tz_localize(None).normalize()
        except (TypeError, ValueError, OverflowError):
            return None
        grouped.setdefault(date, []).append(amount)
    try:
        cashflows = [(date, math.fsum(amounts)) for date, amounts in sorted(grouped.items())]
    except (ValueError, OverflowError):
        return None
    cashflows = [(date, amount) for date, amount in cashflows if amount != 0]
    if len(cashflows) < 2:
        return None
    amounts = [amount for _, amount in cashflows]
    if not (any(amount > 0 for amount in amounts) and any(amount < 0 for amount in amounts)):
        return None
    scale = max(abs(amount) for amount in amounts)
    normalized = [(date, amount / scale) for date, amount in cashflows]
    rate = solve_xirr(normalized, guess=0.1, silent=True, day_count=DayCount.ACT_365F)
    if rate is None or not math.isfinite(rate) or rate <= -1:
        return None
    return rate


def xirr_from_growth(frame, start=None, benchmark=False, end=None):
    if frame is None or frame.empty:
        return None
    if end is not None:
        frame = frame.loc[frame.index <= pd.Timestamp(end)]
    if frame.empty:
        return None
    selected = frame.loc[frame.index >= start] if start is not None else frame
    if selected.empty:
        return None
    value_column = "S&P500 자산가치" if benchmark else "내 자산가치"
    sales_column = "S&P500 누적매도금액" if benchmark else "누적매도금액"
    net_flows = frame[sales_column] - frame["누적매수금액"]
    flows = net_flows.diff().fillna(net_flows).loc[selected.index]
    cashflows = list(flows.items())
    before = frame.loc[frame.index < selected.index[0]]
    if not before.empty:
        cashflows.append((before.index[-1], -float(before[value_column].iloc[-1])))
    cashflows.append((selected.index[-1], float(selected[value_column].iloc[-1])))
    value = xirr(cashflows)
    return value * 100 if value is not None else None


def compute_alpha_beta(orders, fx_now=1400.0, period="10y", div_events=None,
                       include_div=True, include_fx=True):
    frame = build_asset_value_growth(orders, fx_now, div_events, include_div=include_div, include_fx=include_fx)
    if frame.empty:
        return None
    stats = comparison_statistics(frame)
    port_xirr = xirr_from_growth(frame)
    spy_xirr = xirr_from_growth(frame, benchmark=True)
    return {
        "port_xirr_pct": round(port_xirr, 2) if port_xirr is not None else None,
        "spy_xirr_pct": round(spy_xirr, 2) if spy_xirr is not None else None,
        "alpha_pct": round(port_xirr - spy_xirr, 2) if port_xirr is not None and spy_xirr is not None else None,
        "beta": stats["beta"], "corr": stats["corr"],
        "my_final_krw": round(float(frame["내 자산가치"].iloc[-1])),
        "spy_final_krw": round(float(frame["S&P500 자산가치"].iloc[-1])),
        "invested_krw": round(float(frame["순투자원금"].iloc[-1])),
        "n_days": len(stats["daily"]),
    }

