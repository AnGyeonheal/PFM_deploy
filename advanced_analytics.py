"""배당 수익 및 환차손익(FX 손익) 계산 모듈.
토스 API에는 배당 내역이 없어 yfinance 배당/환율 데이터로 추정합니다.
- 배당: 주문 이력으로 보유 수량 타임라인을 복원한 뒤, 각 배당락일의 보유수량 × 주당배당으로 수령액 추정
- 환차손익: USD 매수 시점의 환율과 현재 환율 차이를 매수 원금(USD)에 적용
"""
import pandas as pd

from benchmark import to_yf_ticker, get_dividends, get_usdkrw_history


def _shares_held_on(buy_sell_events, as_of_date):
    """특정 날짜 시점의 누적 보유 수량을 계산합니다.
    buy_sell_events: [(date(Timestamp), signed_qty), ...]"""
    total = 0.0
    for d, q in buy_sell_events:
        if d <= as_of_date:
            total += q
    return total


def _symbol_events(orders):
    """주문 이력을 {symbol: {'events':[(date, +/-qty)], 'currency', 'market'}} 로 정리."""
    by_symbol = {}
    for o in orders:
        ex = o.get("execution") or {}
        qty = float(ex.get("filledQuantity") or 0)
        if qty == 0:
            continue
        filled_at = ex.get("filledAt") or o.get("orderedAt")
        if not filled_at:
            continue
        sym = o.get("symbol")
        signed = qty if o.get("side") == "BUY" else -qty
        entry = by_symbol.setdefault(sym, {"events": [], "currency": o.get("currency", "KRW")})
        entry["events"].append((pd.to_datetime(filled_at).tz_localize(None).normalize(), signed))
    return by_symbol


def compute_dividends(orders, current_fx=1400.0):
    """보유 이력 기반으로 종목별 누적 배당 수령액(원화 환산)을 추정합니다.
    반환: DataFrame(종목, 통화, 배당수령(원화), 배당건수)
    """
    by_symbol = _symbol_events(orders)
    rows = []
    for sym, info in by_symbol.items():
        events = sorted(info["events"], key=lambda x: x[0])
        currency = info["currency"]
        # 현재 보유수량 > 0 또는 과거 보유가 있었던 종목만
        country = "KR" if currency == "KRW" else "US"
        yft = to_yf_ticker(sym, country)
        divs = get_dividends(yft)
        if divs.empty:
            continue

        first_buy = events[0][0]
        total_div_native = 0.0
        count = 0
        for ex_date, dps in divs.items():
            if ex_date < first_buy:
                continue
            shares = _shares_held_on(events, ex_date)
            if shares > 0:
                total_div_native += shares * float(dps)
                count += 1

        if total_div_native <= 0:
            continue
        div_krw = total_div_native * current_fx if currency == "USD" else total_div_native
        rows.append({
            "종목": sym,
            "통화": currency,
            "배당수령(원본)": round(total_div_native, 2),
            "배당수령(원)": round(div_krw),
            "배당횟수": count,
        })

    return pd.DataFrame(rows).sort_values("배당수령(원)", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()


def compute_fx_pnl(orders, current_fx=1400.0):
    """USD 매수 원금에 대한 환차손익을 계산합니다.
    각 USD 매수 체결의 '그 날 환율' 대비 현재 환율 차이를 매수금액(USD)에 적용.
    반환: (요약 dict, 종목별 DataFrame)
    """
    fx_hist = get_usdkrw_history(period="2y")

    def fx_on(date):
        if fx_hist.empty:
            return current_fx
        try:
            val = fx_hist.asof(pd.to_datetime(date).tz_localize(None).normalize())
            return float(val) if pd.notna(val) else current_fx
        except Exception:
            return current_fx

    rows = []
    per_symbol = {}
    total_usd_cost = 0.0
    total_cost_krw_at_purchase = 0.0

    for o in orders:
        if o.get("currency") != "USD" or o.get("side") != "BUY":
            continue
        ex = o.get("execution") or {}
        usd_amount = float(ex.get("filledAmount") or 0)
        if usd_amount <= 0:
            continue
        filled_at = ex.get("filledAt") or o.get("orderedAt")
        buy_fx = fx_on(filled_at)
        sym = o.get("symbol")

        agg = per_symbol.setdefault(sym, {"usd": 0.0, "krw_cost": 0.0})
        agg["usd"] += usd_amount
        agg["krw_cost"] += usd_amount * buy_fx
        total_usd_cost += usd_amount
        total_cost_krw_at_purchase += usd_amount * buy_fx

    for sym, agg in per_symbol.items():
        usd = agg["usd"]
        avg_fx = agg["krw_cost"] / usd if usd else current_fx
        fx_pnl = usd * (current_fx - avg_fx)
        rows.append({
            "종목": sym,
            "매수원금(USD)": round(usd, 2),
            "평균매수환율": round(avg_fx, 1),
            "현재환율": round(current_fx, 1),
            "환차손익(원)": round(fx_pnl),
        })

    total_fx_pnl = total_usd_cost * current_fx - total_cost_krw_at_purchase
    avg_purchase_fx = (total_cost_krw_at_purchase / total_usd_cost) if total_usd_cost else current_fx
    summary = {
        "총_매수원금_USD": round(total_usd_cost, 2),
        "평균_매수환율": round(avg_purchase_fx, 1),
        "현재환율": round(current_fx, 1),
        "총_환차손익_원": round(total_fx_pnl),
    }
    df = pd.DataFrame(rows).sort_values("환차손익(원)", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()
    return summary, df
