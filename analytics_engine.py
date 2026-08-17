import pandas as pd
from datetime import datetime


def build_transaction_detail(orders, fx_rate=1400.0, name_map=None):
    """
    체결 완료(FILLED)된 주문을 날짜별 상세 거래내역 DataFrame으로 변환합니다.
    원본 API 값(체결단가·체결금액·통화)과 원화 환산액을 함께 담습니다.
    name_map: {ticker: 종목명} 매핑 (없으면 티커로 대체)
    """
    name_map = name_map or {}
    rows = []
    for o in orders:
        execution = o.get("execution") or {}
        filled_amount = float(execution.get("filledAmount") or 0)
        if filled_amount == 0:  # 취소/거부 주문 제외
            continue
        currency = o.get("currency", "KRW")
        amount_krw = filled_amount * fx_rate if currency == "USD" else filled_amount
        filled_at = execution.get("filledAt") or o.get("orderedAt")
        if not filled_at:
            continue
        try:
            ts = pd.to_datetime(filled_at).tz_localize(None)
        except (TypeError, ValueError):
            try:
                ts = pd.to_datetime(filled_at, utc=True).tz_localize(None)
            except Exception:
                continue
        if pd.isna(ts):
            continue
        ticker = o.get("symbol")
        rows.append({
            "체결일시": ts,
            "날짜": ts.strftime("%Y-%m-%d"),
            "분기": f"{ts.year}Q{(ts.month - 1) // 3 + 1}",
            "증권사": o.get("broker", "토스증권"),
            "티커": ticker,
            "종목명": name_map.get(ticker, ticker),
            "구분": "매수" if o.get("side") == "BUY" else "매도",
            "수량": float(execution.get("filledQuantity") or o.get("quantity") or 0),
            "체결단가": float(execution.get("averageFilledPrice") or o.get("price") or 0),
            "통화": currency,
            "체결금액(원본)": filled_amount,
            "체결금액(원)": round(amount_krw),
            "수수료": float(execution.get("commission") or 0),
            "세금": float(execution.get("tax") or 0),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("체결일시", ascending=False).reset_index(drop=True)
    return df


def build_period_performance(detail_df, freq="Q"):
    """
    상세 거래내역 DataFrame을 분기(Q) 또는 연도(Y)별로 집계합니다.
    - 반환: DataFrame(기간, 매수금액, 매도금액, 매수건수, 매도건수, 순투자, 누적순투자)
    """
    if detail_df is None or detail_df.empty:
        return pd.DataFrame()

    period_col = "분기" if freq == "Q" else "연도"
    df = detail_df.copy()
    if freq != "Q":
        df["연도"] = df["체결일시"].dt.year.astype(str)

    grouped = df.groupby(period_col)
    summary = pd.DataFrame({
        "매수금액": grouped.apply(lambda g: g.loc[g["구분"] == "매수", "체결금액(원)"].sum()),
        "매도금액": grouped.apply(lambda g: g.loc[g["구분"] == "매도", "체결금액(원)"].sum()),
        "매수건수": grouped.apply(lambda g: (g["구분"] == "매수").sum()),
        "매도건수": grouped.apply(lambda g: (g["구분"] == "매도").sum()),
    }).reset_index()

    summary["순투자"] = summary["매수금액"] - summary["매도금액"]
    summary = summary.sort_values(period_col).reset_index(drop=True)
    summary["누적순투자"] = summary["순투자"].cumsum()
    return summary


def transform_to_mvp_json(user_id, toss_holdings, cash_krw=0.0, fx_rate=1400.0):
    """
    Toss Open API에서 가져온 계좌/잔고 데이터를 
    제안해주신 '데이터 입출력 JSON 규격 (Section 4)' 형태로 가공합니다.
    cash_krw: buying-power API로 조회한 실제 예수금(원화 환산 합계)
    fx_rate: USD->KRW 환율 (미국 주식 원화 환산용)
    """
    if not toss_holdings or "result" not in toss_holdings:
        return {}

    result = toss_holdings["result"]
    mv_amount = result.get("marketValue", {}).get("amount", {})
    # 최상위 합계는 통화별로 분리 저장됨: krw=국내주식, usd=미국주식
    kr_value = float(mv_amount.get("krw", 0))
    us_value_usd = float(mv_amount.get("usd", 0))
    total_market_value = kr_value + us_value_usd * fx_rate  # 전체 주식 평가액(원화 환산)

    tp_amount = result.get("totalPurchaseAmount", {})
    total_purchase_amount = float(tp_amount.get("krw", 0)) + float(tp_amount.get("usd", 0)) * fx_rate
    total_asset_krw = total_market_value + cash_krw
    
    # 1. User Profile
    user_profile = {
        "user_id": user_id,
        "target_benchmark": "S&P 500"
    }
    
    # 2. Asset Summary
    # (XIRR, PME는 과거 체결 내역(Orders History)이 있어야 정확히 계산되지만, 
    # MVP 테스트를 위해 현재 수익률 기반으로 추정치를 매핑합니다.)
    simple_return = (total_market_value / total_purchase_amount - 1) * 100 if total_purchase_amount > 0 else 0
    
    asset_summary = {
        "total_asset_krw": total_asset_krw,
        "stock_eval_krw": total_market_value,
        "purchase_krw": round(total_purchase_amount),
        "cash_krw": cash_krw,
        "xirr_annual_pct": round(simple_return, 2), # 임시 매핑
        "pme_alpha_pct": round(simple_return - 10.5, 2) # S&P500의 가상 평균 수익(10.5)을 뺀 임시 PME
    }
    
    # 3. Holdings
    holdings = []
    for item in result.get("items", []):
        # 개별 종목 amount는 종목 통화(KRW/USD) 기준 → 원화로 환산
        currency = item.get("currency", "KRW")
        eval_amount_native = float(item.get("marketValue", {}).get("amount", 0))
        eval_amount_krw = eval_amount_native * fx_rate if currency == "USD" else eval_amount_native
        
        weight_pct = (eval_amount_krw / total_market_value) * 100 if total_market_value > 0 else 0
        return_pct = float(item.get("profitLoss", {}).get("rate", 0)) * 100
        
        holdings.append({
            "ticker": item.get("symbol"),
            "name": item.get("name"),
            "currency": currency,
            "quantity": item.get("quantity"),
            "eval_krw": round(eval_amount_krw),
            "weight_pct": round(weight_pct, 2),
            "sector": "Unknown", # ETF/종목 카테고라이징 추가 구현 시 할당
            "return_pct": round(return_pct, 2)
        })

    # 비중 큰 순으로 정렬
    holdings.sort(key=lambda x: x["weight_pct"], reverse=True)
        
    return {
        "user_profile": user_profile,
        "asset_summary": asset_summary,
        "holdings": holdings
    }
