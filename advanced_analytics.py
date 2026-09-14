"""배당 수익 및 환차손익(FX 손익) 계산 모듈.
토스 API에는 배당 내역이 없어 yfinance 배당/환율 데이터로 추정합니다.
- 배당: 계좌별 권리수량 × 주당배당, 실제 입금 우선 및 지급일 기준 수령액 추정
- 환차손익: USD 매수 시점의 환율과 현재 환율 차이를 매수 원금(USD)에 적용
"""
import hashlib
import json
import math
from statistics import median

import pandas as pd

from benchmark import to_yf_ticker, get_dividend_schedule, get_usdkrw_history
from pme import _trade_records, position_key
from names import normalize_kr_ticker


def _shares_held_on(buy_sell_events, as_of_date):
    """특정 날짜 시점의 누적 보유 수량을 계산합니다.
    buy_sell_events: [(date(Timestamp), signed_qty), ...]"""
    total = 0.0
    for d, q in buy_sell_events:
        if d < as_of_date:
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
    """수령일이 지난 추정 배당을 종목별로 집계합니다."""
    totals = {}
    for record in build_dividend_records(orders, current_fx):
        if not record["received"]:
            continue
        key = (record["ticker"], record["currency"])
        total = totals.setdefault(key, {"종목": key[0], "통화": key[1], "배당수령(원본)": 0.0,
                                        "배당수령(원)": 0.0, "배당횟수": 0})
        total["배당수령(원본)"] += record["amount"]
        total["배당수령(원)"] += record["amountKrw"]
        total["배당횟수"] += 1
    return pd.DataFrame(totals.values())


def compute_dividend_events(orders, current_fx=1400.0, ticker=None):
    """보유 권리와 수령일을 분리한 (지급일, 원화금액, 종목) 이벤트입니다."""
    return [(pd.Timestamp(row["payDate"]), row["amountKrw"], row["ticker"])
            for row in build_dividend_records(orders, current_fx)
            if row["received"] and (not ticker or row["ticker"] == ticker)]


def _day(value):
    if value is None or str(value).strip() in ("", "NaT", "nan"):
        return None
    try:
        parsed = pd.Timestamp(value)
        return parsed.tz_localize(None).normalize() if pd.notna(parsed) else None
    except (TypeError, ValueError):
        return None


def _event_id(position, ex_date):
    return hashlib.sha256(json.dumps([*position, str(ex_date.date())], ensure_ascii=True).encode()).hexdigest()


def build_dividend_records(orders, current_fx=1400.0, actual_rows=None, as_of=None, include_est=True):
    """계좌·배당 사건별 실제 입금 우선 원장. 지급일 미확인·미도래분은 수령액에서 제외합니다."""
    today = _day(as_of) if as_of is not None else pd.Timestamp.now().normalize()
    fx_history = get_usdkrw_history("10y")
    actual, estimates, seen_actual = [], [], set()
    for row in actual_rows or []:
        try:
            amount = float(row.get("배당금") or 0)
        except (ValueError, TypeError):
            continue
        if not math.isfinite(amount) or amount <= 0:
            continue
        symbol = normalize_kr_ticker(str(row.get("티커") or ""))
        position = position_key(dict(row, 티커=symbol))
        pay_date, ex_date = _day(row.get("일자")), _day(row.get("배당락일"))
        identity = (position, pay_date, ex_date, amount, str(row.get("배당ID") or ""))
        if identity in seen_actual:
            continue
        seen_actual.add(identity)
        actual.append({"ticker": symbol, "name": row.get("종목명") or symbol,
                       "broker": str(row.get("증권사") or ""), "account": position[1], "currency": position[2],
                       "position": position, "payDate": pay_date, "exDate": ex_date,
                       "recordDate": _day(row.get("기준일")), "amount": amount, "shares": None,
                       "eventId": str(row.get("배당ID") or ""), "source": "actual", "dateSource": "actual"})
    positions = {}
    for record in _trade_records(orders):
        position = record["position"]
        info = positions.setdefault(position, {"events": [], "broker": position[0], "account": position[1]})
        info["events"].append((record["date"], record["qty"] if record["side"] == "BUY" else -record["qty"]))
    schedules = {}
    if include_est:
        for position, info in positions.items():
            currency, symbol = position[2:]
            if (symbol, currency) not in schedules:
                schedules[(symbol, currency)] = get_dividend_schedule(to_yf_ticker(symbol, "KR" if currency == "KRW" else "US"))
            seen = set()
            for entry in schedules[(symbol, currency)]:
                ex_date = _day(entry.get("exDate"))
                if ex_date is None or ex_date > today or ex_date in seen:
                    continue
                seen.add(ex_date)
                shares = _shares_held_on(info["events"], ex_date)
                amount = shares * float(entry["amount"])
                if shares <= 0 or not math.isfinite(amount) or amount <= 0:
                    continue
                pay_date = _day(entry.get("payDate"))
                if pay_date is not None and pay_date < ex_date:
                    pay_date = None
                estimates.append({"ticker": symbol, "name": symbol, "broker": info["broker"], "account": info["account"],
                                  "currency": currency, "position": position, "exDate": ex_date,
                                  "recordDate": _day(entry.get("recordDate")), "payDate": pay_date,
                                  "dateSource": "announced" if pay_date is not None else "unknown",
                                  "amount": amount, "shares": shares, "eventId": _event_id(position, ex_date), "source": "estimated"})

    def scope_matches(receipt, estimate):
        return (receipt["ticker"] == estimate["ticker"] and receipt["currency"] == estimate["currency"]
                and (not receipt["position"][0] or receipt["position"][0] == estimate["position"][0])
                and (not receipt["account"] or receipt["account"] == estimate["account"]))

    lags = {}
    for entry in actual + estimates:
        if entry["payDate"] is not None and entry["exDate"] is not None and entry["payDate"] <= today:
            lag = (entry["payDate"] - entry["exDate"]).days
            if 0 <= lag <= 180:
                lags.setdefault((entry["ticker"], entry["currency"]), set()).add(lag)
    for estimate in estimates:
        observed = lags.get((estimate["ticker"], estimate["currency"]))
        if estimate["payDate"] is None and observed:
            estimate["payDate"] = (estimate["exDate"] + pd.Timedelta(days=round(median(observed))) + pd.offsets.BDay(0)).normalize()
            estimate["dateSource"] = "estimated"
    matched, uncertain = set(), set()
    def link_receipt(receipt, indexes):
        matched.update(indexes)
        first = estimates[indexes[0]]
        receipt["exDate"] = receipt["exDate"] or first["exDate"]
        receipt["recordDate"] = receipt["recordDate"] or first["recordDate"]
        if len(indexes) == 1:
            receipt["eventId"] = receipt["eventId"] or first["eventId"]

    for receipt in actual:
        candidates = [index for index, estimate in enumerate(estimates) if scope_matches(receipt, estimate)]
        explicit = [index for index in candidates if receipt["eventId"] and receipt["eventId"] == estimates[index]["eventId"]]
        if not explicit:
            explicit = [index for index in candidates if receipt["exDate"] is not None
                        and receipt["exDate"] == estimates[index]["exDate"]]
        if explicit:
            link_receipt(receipt, explicit)
            continue
        if receipt["exDate"] is not None or receipt["payDate"] is None:
            continue
        near = [index for index in candidates if estimates[index]["payDate"] is not None
                and abs((receipt["payDate"] - estimates[index]["payDate"]).days) <= 7]
        if near:
            difference = min(abs((receipt["payDate"] - estimates[index]["payDate"]).days) for index in near)
            near = [index for index in near if abs((receipt["payDate"] - estimates[index]["payDate"]).days) == difference]
        else:
            near = [index for index in candidates
                if 0 <= (receipt["payDate"] - estimates[index]["exDate"]).days <= 120]
        if len({estimates[index]["exDate"] for index in near}) == 1:
            link_receipt(receipt, near)
        else:
            uncertain.update(near)
    for receipt in actual:
        if receipt["payDate"] is not None and receipt["exDate"] is not None and receipt["payDate"] <= today:
            lag = (receipt["payDate"] - receipt["exDate"]).days
            if 0 <= lag <= 180:
                lags.setdefault((receipt["ticker"], receipt["currency"]), set()).add(lag)
    for estimate in estimates:
        observed = lags.get((estimate["ticker"], estimate["currency"]))
        if estimate["payDate"] is None and observed:
            estimate["payDate"] = (estimate["exDate"] + pd.Timedelta(days=round(median(observed))) + pd.offsets.BDay(0)).normalize()
            estimate["dateSource"] = "estimated"
    unique_actual = {}
    for receipt in actual:
        key = (receipt["position"], receipt["payDate"], receipt["exDate"], receipt["amount"], receipt["eventId"])
        unique_actual[key] = receipt
    result = list(unique_actual.values()) + [dict(row, matchingUncertain=index in uncertain)
                       for index, row in enumerate(estimates) if index not in matched]
    for row in result:
        pay_date = row["payDate"]
        row["received"] = pay_date is not None and pay_date <= today and not row.get("matchingUncertain", False)
        rate = fx_history.asof(pay_date) if pay_date is not None and not fx_history.empty else current_fx
        rate = float(rate) if pd.notna(rate) else current_fx
        row["amountKrw"] = row["amount"] * rate if row["currency"] == "USD" else row["amount"]
        row["amountKrw"] = row["amountKrw"] if row["received"] else None
        for field in ("payDate", "exDate", "recordDate"):
            row[field] = row[field].strftime("%Y-%m-%d") if row[field] is not None else ""
    return sorted(result, key=lambda row: (row["payDate"] or "9999", row["ticker"], row["account"], row["eventId"]))


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
