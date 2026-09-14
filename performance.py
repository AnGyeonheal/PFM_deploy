"""직관적 성과 지표 계산 모듈.
평균매수단가(average cost) 기준으로 종목별 실현·미실현 손익을
'순수 주가 손익'과 '환차손익'으로 분해하고, 배당을 합산해
전체/보유/실현 성과를 한 번에 산출합니다. (토스 + 임포트 주문 합산)
"""
import pandas as pd

from benchmark import to_yf_ticker, get_history, get_usdkrw_history, get_native_price_now
from pme import _trade_records


def _fx_asof(fx_hist, date, fx_now):
    if fx_hist is None or fx_hist.empty:
        return fx_now
    try:
        v = fx_hist.asof(pd.to_datetime(date).tz_localize(None).normalize())
        return float(v) if pd.notna(v) else float(fx_hist.iloc[0])
    except Exception:
        return fx_now


def _records(orders):
    records = _trade_records(orders)
    quantities = {}
    unavailable = set()
    for record in records:
        position = record["position"]
        quantity = quantities.get(position, 0.0)
        if record["side"] == "SELL" and record["qty"] > quantity + 1e-8:
            unavailable.add(record["symbol"])
        quantities[position] = quantity + (record["qty"] if record["side"] == "BUY" else -record["qty"])
    return [dict(record, price=record["amount"] / record["qty"], ts=record["timestamp"])
            for record in records if record["symbol"] not in unavailable]


def compute_performance_summary(orders, fx_now=1400.0, div_krw_native=0.0, div_usd_native=0.0,
                                include_div=True, include_fx=True, dividend_krw=None):
    """전체/보유/실현 성과를 원화·외화로 분해한 요약 dict를 반환합니다.
    배당은 검증된 임포트 기록(div_krw_native 원화·div_usd_native 달러)만 사용합니다.
    분해: 총손익(원) = 순수 주가손익(원) + 환차손익(원) + 배당(원).
    반환 None: 유효한 거래 없음.
    """
    recs = _records(orders)
    if not recs:
        return None

    fx_hist = get_usdkrw_history("10y")
    symbols = sorted(set(r["symbol"] for r in recs))

    cur_map = {}
    price_now = {}
    for s in symbols:
        cur = next(r["currency"] for r in recs if r["symbol"] == s)
        cur_map[s] = cur
        price_now[s] = get_native_price_now(s, "KR" if cur == "KRW" else "US")

    t = dict(
        realized_price_krw=0.0, realized_fx_krw=0.0,
        unreal_price_krw=0.0, unreal_fx_krw=0.0, unreal_total_krw=0.0,
        buy_krw=0.0, sell_krw=0.0,
        unreal_native_usd=0.0, cost_native_usd_remaining=0.0,
        cur_value_krw=0.0, cost_krw_remaining=0.0,
    )

    positions = {record["position"]: record["symbol"] for record in recs}
    for position, s in positions.items():
        cur = position[2]
        srecs = [record for record in recs if record["position"] == position]
        qty = cost_native = cost_krw = cost_fx_weight = 0.0
        for r in srecs:
            fx_d = _fx_asof(fx_hist, r["date"], fx_now) if cur == "USD" else 1.0
            if r["side"] == "BUY":
                cost_native += r["qty"] * r["price"]
                cost_krw += r["qty"] * r["price"] * fx_d
                cost_fx_weight += r["qty"] * fx_d
                qty += r["qty"]
                t["buy_krw"] += r["amount"] * fx_d
            else:  # SELL — 평균단가 기준 매칭
                if qty <= 1e-9:
                    continue  # 데이터에 선행 매수가 없는 매도는 원가 미상 → 건너뜀
                sell_qty = min(r["qty"], qty)
                avg_native_per = cost_native / qty
                avg_krw_per = cost_krw / qty
                avg_fx = cost_fx_weight / qty
                cost_out_native = avg_native_per * sell_qty
                cost_out_krw = avg_krw_per * sell_qty
                fixed_proceeds = sell_qty * r["price"] * avg_fx
                t["realized_price_krw"] += fixed_proceeds - cost_out_krw
                if cur == "USD":
                    t["realized_fx_krw"] += sell_qty * r["price"] * (fx_d - avg_fx)
                t["sell_krw"] += sell_qty * r["price"] * fx_d
                cost_fx_weight -= sell_qty * avg_fx
                qty -= sell_qty
                cost_native -= cost_out_native
                cost_krw -= cost_out_krw

        pn = price_now.get(s)
        if qty > 1e-9 and pn is not None:
            avg_native_per = cost_native / qty if qty else 0.0
            avg_fx = cost_fx_weight / qty
            u_price_native = (pn - avg_native_per) * qty
            fx_apply = fx_now if cur == "USD" else 1.0
            cur_val_krw = pn * qty * fx_apply
            t["unreal_price_krw"] += pn * qty * avg_fx - cost_krw
            if cur == "USD":
                t["unreal_fx_krw"] += pn * qty * (fx_now - avg_fx)
                t["unreal_native_usd"] += u_price_native
                t["cost_native_usd_remaining"] += cost_native
            t["unreal_total_krw"] += cur_val_krw - cost_krw
            t["cur_value_krw"] += cur_val_krw
            t["cost_krw_remaining"] += cost_krw

    div_krw = (dividend_krw if dividend_krw is not None else div_krw_native + div_usd_native * fx_now) if include_div else 0.0

    fx_total_krw = (t["realized_fx_krw"] + t["unreal_fx_krw"]) if include_fx else 0.0
    realized_total_krw = t["realized_price_krw"] + (t["realized_fx_krw"] if include_fx else 0.0)
    unreal_total_krw = t["unreal_total_krw"] if include_fx else t["unreal_price_krw"]
    pure_price_krw = t["realized_price_krw"] + t["unreal_price_krw"]
    all_inclusive = realized_total_krw + unreal_total_krw + div_krw
    invested = t["buy_krw"]
    cost_rem = t["cost_krw_remaining"]
    cost_usd_rem = t["cost_native_usd_remaining"]

    def pct(num, den):
        return (num / den * 100) if den else 0.0

    return {
        # 1. 전체 포트폴리오 누적 성과
        "all_inclusive_krw": all_inclusive,
        "all_inclusive_pct": pct(all_inclusive, invested),
        "pure_price_krw": pure_price_krw,
        "pure_price_pct": pct(pure_price_krw, invested),
        # 2. 보유 자산 성과
        "unreal_total_krw": unreal_total_krw,
        "unreal_total_pct": pct(unreal_total_krw, cost_rem),
        "unreal_native_usd": t["unreal_native_usd"],
        "unreal_native_usd_pct": pct(t["unreal_native_usd"], cost_usd_rem),
        # 3. 실현 및 부가 수익
        "realized_total_krw": realized_total_krw,
        "div_krw": div_krw,
        "div_krw_native": div_krw_native,
        "div_usd_native": div_usd_native,
        "fx_total_krw": fx_total_krw,
        # 참고
        "invested_krw": invested,
        "cur_value_krw": t["cur_value_krw"],
        "cost_krw_remaining": cost_rem,
        "cost_usd_remaining": cost_usd_rem,
    }


def build_holdings_breakdown(orders, fx_now=1400.0, name_map=None, div_krw_by_ticker=None,
                             include_div=True, include_fx=True):
    """종목별로 분할매도를 반영한 평균단가 회계 표를 만듭니다.
    청산 종목은 '매도 시점 실현' 기준(현재가 아님), 보유 종목은 잔여수량 평가 기준으로 계산합니다.
    미국(USD) 종목은 달러 네이티브 컬럼과 환차 제거된 달러 기준 수익률(%)을 함께 제공합니다.
    누적배당금은 검증된 임포트 기록(div_krw_by_ticker: {티커: 원화배당})만 사용합니다.
    """
    name_map = name_map or {}
    div_krw_map = div_krw_by_ticker or {}
    recs = _records(orders)
    if not recs:
        return pd.DataFrame()

    fx_hist = get_usdkrw_history("10y")
    symbols = sorted(set(r["symbol"] for r in recs))

    price_now = {}
    cur_map = {}
    for s in symbols:
        cur = next(r["currency"] for r in recs if r["symbol"] == s)
        cur_map[s] = cur
        price_now[s] = get_native_price_now(s, "KR" if cur == "KRW" else "US")

    rows = []
    for s in symbols:
        cur = cur_map[s]
        srecs = sorted((r for r in recs if r["symbol"] == s), key=lambda r: r["ts"])
        positions = {}
        buy_qty = buy_native = buy_krw = 0.0
        realized_pnl_krw = sell_proceeds_krw = 0.0
        realized_pnl_native = sell_proceeds_native = 0.0
        for r in srecs:
            state = positions.setdefault(r["position"], {"qty": 0.0, "cost_native": 0.0,
                                                         "cost_krw": 0.0, "cost_fx": 0.0})
            fx_d = _fx_asof(fx_hist, r["date"], fx_now) if cur == "USD" else 1.0
            if r["side"] == "BUY":
                state["cost_native"] += r["qty"] * r["price"]
                state["cost_krw"] += r["qty"] * r["price"] * fx_d
                state["cost_fx"] += r["qty"] * fx_d
                state["qty"] += r["qty"]
                buy_qty += r["qty"]
                buy_native += r["qty"] * r["price"]
                buy_krw += r["qty"] * r["price"] * fx_d
            else:  # SELL — 평균단가 기준 실현 (분할매도 반영)
                if state["qty"] <= 1e-9:
                    continue
                sell_qty = min(r["qty"], state["qty"])
                avg_native_per = state["cost_native"] / state["qty"]
                avg_krw_per = state["cost_krw"] / state["qty"]
                avg_fx = state["cost_fx"] / state["qty"]
                cost_out_native = avg_native_per * sell_qty
                cost_out_krw = avg_krw_per * sell_qty
                proceeds_native = sell_qty * r["price"]  # 매도대금(네이티브) — 환율 미적용
                proceeds_krw = proceeds_native * (fx_d if include_fx else avg_fx)
                realized_pnl_native += proceeds_native - cost_out_native
                realized_pnl_krw += proceeds_krw - cost_out_krw
                sell_proceeds_native += proceeds_native
                sell_proceeds_krw += proceeds_krw
                state["qty"] -= sell_qty
                state["cost_native"] -= cost_out_native
                state["cost_krw"] -= cost_out_krw
                state["cost_fx"] -= sell_qty * avg_fx

        if buy_qty <= 1e-9:
            continue
        qty = sum(state["qty"] for state in positions.values())
        cost_native = sum(state["cost_native"] for state in positions.values())
        cost_krw = sum(state["cost_krw"] for state in positions.values())
        held_qty = qty if qty > 1e-9 else 0.0
        avg_buy_native = cost_native / held_qty if held_qty else buy_native / buy_qty
        avg_buy_krw = cost_krw / held_qty if held_qty else buy_krw / buy_qty

        pn = price_now.get(s)
        unreal_pnl_krw = unreal_pnl_native = 0.0
        if held_qty > 0 and pn is not None:
            cur_val_krw = pn * held_qty * (fx_now if cur == "USD" else 1.0)
            if cur == "USD" and not include_fx:
                cur_val_krw = pn * sum(state["cost_fx"] for state in positions.values())
            unreal_pnl_krw = cur_val_krw - cost_krw
            unreal_pnl_native = pn * held_qty - cost_native  # 달러 기준 미실현손익(환차 제외)

        # 투자원금 = 현재 보유분의 매입원가(청산 종목은 실현된 총 매수원가).
        # include_fx=True면 원화(환차 포함)+배당 기준, False면 네이티브(환차 제거·배당 제외) 기준 수익률.
        div_amt = div_krw_map.get(s, 0.0) if include_div else 0.0
        if held_qty > 0:
            principal_krw = cost_krw
            principal_native = cost_native
            if include_fx:
                ret_pct = ((unreal_pnl_krw + div_amt) / cost_krw * 100) if cost_krw else 0.0
            else:
                ret_pct = (unreal_pnl_native / cost_native * 100) if cost_native else 0.0
        else:
            principal_krw = buy_krw
            principal_native = buy_native
            if include_fx:
                ret_pct = ((realized_pnl_krw + div_amt) / buy_krw * 100) if buy_krw else 0.0
            else:
                ret_pct = (realized_pnl_native / buy_native * 100) if buy_native else 0.0

        is_usd = cur == "USD"
        rows.append({
            "종목": name_map.get(s, s),
            "티커": s,
            "통화": cur,
            "상태": "보유중" if held_qty > 0 else "청산",
            "보유수량": round(held_qty, 4),
            "평단가(달러)": round(avg_buy_native, 2) if is_usd else None,
            "평단가(원화)": round(avg_buy_krw, 2),
            "투자원금(달러)": round(principal_native, 2) if is_usd else None,
            "투자원금(원)": round(principal_krw),
            "매도실현금액(원)": round(sell_proceeds_krw),
            "실현손익(달러)": round(realized_pnl_native, 2) if is_usd else None,
            "실현손익(원)": round(realized_pnl_krw),
            "평가손익(달러)": round(unreal_pnl_native, 2) if is_usd else None,
            "평가손익(원)": round(unreal_pnl_krw),
            "누적배당금(원)": round(div_amt),
            "수익률(%)": round(ret_pct, 2),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("수익률(%)", ascending=False).reset_index(drop=True)
