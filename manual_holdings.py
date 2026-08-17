"""한화투자증권 등 API 미지원 증권사의 보유 종목을 수동 CSV로 관리합니다.
manual_holdings.csv 를 편집하면 대시보드에 자동 반영됩니다.
CSV 컬럼: 증권사, 티커, 종목명, 시장(KOSPI/KOSDAQ/US), 수량, 평균매수가, 통화(KRW/USD), 매수일(YYYY-MM-DD)
"""
import os
from datetime import datetime

import pandas as pd

from benchmark import to_yf_ticker, get_history

MANUAL_CSV = os.path.join(os.path.dirname(__file__), "manual_holdings.csv")
TX_CSV = os.path.join(os.path.dirname(__file__), "manual_transactions.csv")

COLUMNS = ["증권사", "티커", "종목명", "시장", "수량", "평균매수가", "통화", "매수일"]
TX_COLUMNS = ["증권사", "일자", "티커", "종목명", "시장", "구분", "수량", "단가", "통화"]


def set_data_dir(directory):
    """사용자별 데이터 폴더로 CSV 저장 경로를 변경합니다(로그인 시 호출)."""
    global MANUAL_CSV, TX_CSV
    MANUAL_CSV = os.path.join(directory, "manual_holdings.csv")
    TX_CSV = os.path.join(directory, "manual_transactions.csv")


def clear_all_imports():
    """현재 사용자 폴더의 임포트 데이터(거래내역·잔고)를 모두 삭제합니다."""
    removed = 0
    for p in (MANUAL_CSV, TX_CSV):
        if os.path.exists(p):
            try:
                os.remove(p)
                removed += 1
            except Exception:
                pass
    return removed

# 티커 변경/별칭 정규화 (과거 티커 → 현재 티커)
TICKER_ALIASES = {
    "FB": "META",   # 메타 플랫폼스: 2022년 티커 변경 FB→META
}


def normalize_ticker(t):
    """과거/변경된 티커를 현재 티커로 정규화합니다."""
    if t is None:
        return t
    s = str(t).strip()
    return TICKER_ALIASES.get(s.upper(), s)


# ───────────────────────── 전체 거래내역(청산 포함) ─────────────────────────

def read_transactions_csv():
    """전체 거래내역 CSV(개별 매매)를 읽어 반환합니다."""
    if not os.path.exists(TX_CSV):
        return pd.DataFrame(columns=TX_COLUMNS)
    try:
        df = pd.read_csv(TX_CSV, encoding="utf-8-sig", dtype={"티커": str})
        for c in TX_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        for c in ("수량", "단가"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        for c in ("증권사", "일자", "티커", "종목명", "시장", "구분", "통화"):
            df[c] = df[c].fillna("").astype(str)
        df["티커"] = df["티커"].map(normalize_ticker)  # FB→META 등 정규화
        return df[TX_COLUMNS]
    except Exception as e:
        print(f"[경고] 거래내역 CSV 읽기 실패: {e}")
        return pd.DataFrame(columns=TX_COLUMNS)


def write_transactions_csv(df):
    """편집된 거래내역 DataFrame을 CSV로 저장합니다. (빈 티커 행 제외)"""
    if df is None or df.empty:
        pd.DataFrame(columns=TX_COLUMNS).to_csv(TX_CSV, index=False, encoding="utf-8-sig")
        return 0
    out = df.copy()
    for c in TX_COLUMNS:
        if c not in out.columns:
            out[c] = ""
    out = out[TX_COLUMNS]
    out = out[out["티커"].astype(str).str.strip() != ""]
    out.to_csv(TX_CSV, index=False, encoding="utf-8-sig")
    return len(out)


def save_parsed_transactions(rows, replace_broker=None):
    """AI가 파싱한 개별 거래(dict 리스트)를 manual_transactions.csv에 저장합니다."""
    new_df = pd.DataFrame(rows)
    if new_df.empty:
        return 0
    for c in TX_COLUMNS:
        if c not in new_df.columns:
            new_df[c] = ""
    new_df = new_df[TX_COLUMNS]
    if replace_broker and os.path.exists(TX_CSV):
        try:
            old = pd.read_csv(TX_CSV, encoding="utf-8-sig", dtype={"티커": str})
            old = old[old.get("증권사") != replace_broker]
            combined = pd.concat([old, new_df], ignore_index=True)
        except Exception:
            combined = new_df
    else:
        combined = new_df
    combined.to_csv(TX_CSV, index=False, encoding="utf-8-sig")
    return len(new_df)


def transactions_to_orders(tx_df):
    """거래내역 DataFrame을 토스 주문(체결) 형태의 합성 주문 리스트로 변환합니다.
    매수/매도 모두 포함하므로 청산 종목도 분석에 반영됩니다."""
    if tx_df is None or tx_df.empty:
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    orders = []
    for _, r in tx_df.iterrows():
        try:
            qty = float(r.get("수량", 0) or 0)
            price = float(r.get("단가", 0) or 0)
            if qty <= 0 or price <= 0:
                continue
            raw_date = r.get("일자", "")
            if pd.isna(raw_date):
                d = today
            else:
                d = str(raw_date).strip()
                if not d or d.lower() == "nan":
                    d = today
            try:
                d = pd.to_datetime(d).strftime("%Y-%m-%d")
            except Exception:
                d = today
            side = "SELL" if str(r.get("구분", "")).strip() in ("매도", "SELL", "sell") else "BUY"
            filled_at = f"{d}T00:00:00+09:00"
            orders.append({
                "symbol": str(r.get("티커")),
                "currency": str(r.get("통화", "KRW")).upper(),
                "side": side,
                "status": "FILLED",
                "orderedAt": filled_at,
                "broker": r.get("증권사", "타증권사"),
                "execution": {
                    "filledQuantity": qty,
                    "averageFilledPrice": price,
                    "filledAmount": qty * price,
                    "commission": 0,
                    "tax": 0,
                    "filledAt": filled_at,
                },
            })
        except Exception:
            continue
    return orders


def derive_holdings_from_tx(tx_df, fx_rate=1400.0):
    """거래내역에서 종목별 순보유(현재 수량>0)를 산출해 보유 상세 형식으로 반환합니다.
    (청산된 종목은 순수량 0이라 보유 목록에서 제외되지만, 거래는 orders로 분석에 반영됨)
    """
    if tx_df is None or tx_df.empty:
        return pd.DataFrame()
    agg = {}
    for _, r in tx_df.iterrows():
        try:
            qty = float(r.get("수량", 0) or 0)
            price = float(r.get("단가", 0) or 0)
            if qty <= 0 or price <= 0:
                continue
            key = (r.get("증권사"), str(r.get("티커")))
            e = agg.setdefault(key, {
                "증권사": r.get("증권사"), "티커": str(r.get("티커")),
                "종목명": r.get("종목명"), "시장": r.get("시장", "US"),
                "통화": str(r.get("통화", "KRW")).upper(),
                "net_qty": 0.0, "buy_qty": 0.0, "buy_cost": 0.0,
            })
            if str(r.get("구분", "")).strip() in ("매도", "SELL", "sell"):
                e["net_qty"] -= qty
            else:
                e["net_qty"] += qty
                e["buy_qty"] += qty
                e["buy_cost"] += qty * price
        except Exception:
            continue

    rows = []
    for e in agg.values():
        if e["net_qty"] <= 1e-9:  # 청산 종목은 보유 목록에서 제외
            continue
        avg_price = e["buy_cost"] / e["buy_qty"] if e["buy_qty"] else 0
        market = str(e["시장"] or "US")
        country = "KR" if market.upper() in ("KOSPI", "KOSDAQ", "KR") else "US"
        yft = to_yf_ticker(e["티커"], country, market)
        hist = get_history(yft, period="5d")
        last_price = float(hist.iloc[-1]) if not hist.empty else avg_price
        cur = e["통화"]
        eval_native = last_price * e["net_qty"]
        eval_krw = eval_native * fx_rate if cur == "USD" else eval_native
        return_pct = (last_price / avg_price - 1) * 100 if avg_price else 0
        rows.append({
            "증권사": e["증권사"], "티커": e["티커"], "종목명": e["종목명"] or e["티커"],
            "시장": market, "통화": cur, "수량": e["net_qty"],
            "평균매수가": round(avg_price, 2), "현재가": round(last_price, 2),
            "평가액(원)": round(eval_krw), "수익률(%)": round(return_pct, 2), "매수일": "",
            "yf_ticker": yft,
        })
    return pd.DataFrame(rows)


COLUMNS_HOLDINGS = COLUMNS  # 하위호환 별칭


def read_manual_csv():
    """원본 수동 보유 CSV(편집용 8개 컬럼)를 그대로 읽어 반환합니다."""
    if not os.path.exists(MANUAL_CSV):
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(MANUAL_CSV, encoding="utf-8-sig", dtype={"티커": str})
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = ""
        # 숫자 컬럼 타입 통일 (Arrow 직렬화 경고 방지)
        for c in ("수량", "평균매수가"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        for c in ("증권사", "티커", "종목명", "시장", "통화", "매수일"):
            df[c] = df[c].fillna("").astype(str)
        df["티커"] = df["티커"].map(normalize_ticker)  # FB→META 등 정규화
        return df[COLUMNS]
    except Exception as e:
        print(f"[경고] 수동 CSV 읽기 실패: {e}")
        return pd.DataFrame(columns=COLUMNS)


def write_manual_csv(df):
    """편집된 수동 보유 DataFrame을 CSV로 저장합니다. (빈 티커 행은 제외)"""
    if df is None or df.empty:
        pd.DataFrame(columns=COLUMNS).to_csv(MANUAL_CSV, index=False, encoding="utf-8-sig")
        return 0
    out = df.copy()
    for c in COLUMNS:
        if c not in out.columns:
            out[c] = ""
    out = out[COLUMNS]
    out = out[out["티커"].astype(str).str.strip() != ""]
    out.to_csv(MANUAL_CSV, index=False, encoding="utf-8-sig")
    return len(out)



def save_parsed_holdings(rows, replace_broker=None):
    """AI가 파싱한 보유 종목 리스트(dict 리스트)를 manual_holdings.csv에 저장합니다.
    replace_broker가 지정되면 해당 증권사 기존 행을 지우고 새로 추가(중복 방지),
    아니면 전체를 새 데이터로 대체합니다.
    반환: 저장된 행 수
    """
    new_df = pd.DataFrame(rows)
    if new_df.empty:
        return 0
    # 누락 컬럼 보정
    for c in COLUMNS:
        if c not in new_df.columns:
            new_df[c] = ""
    new_df = new_df[COLUMNS]

    if replace_broker and os.path.exists(MANUAL_CSV):
        try:
            old = pd.read_csv(MANUAL_CSV, encoding="utf-8-sig")
            old = old[old.get("증권사") != replace_broker]
            combined = pd.concat([old, new_df], ignore_index=True)
        except Exception:
            combined = new_df
    else:
        combined = new_df

    combined.to_csv(MANUAL_CSV, index=False, encoding="utf-8-sig")
    return len(new_df)



def load_manual_holdings(fx_rate=1400.0):
    """수동 입력 CSV를 읽어 현재가·평가액·수익률을 계산한 DataFrame을 반환합니다.
    파일이 없거나 비어 있으면 빈 DataFrame을 반환합니다.
    """
    if not os.path.exists(MANUAL_CSV):
        return pd.DataFrame()

    try:
        df = pd.read_csv(MANUAL_CSV, encoding="utf-8-sig")
    except Exception as e:
        print(f"[경고] 수동 보유 CSV 읽기 실패: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    rows = []
    for _, r in df.iterrows():
        try:
            market = str(r.get("시장", "US"))
            country = "KR" if market.upper() in ("KOSPI", "KOSDAQ", "KR") else "US"
            currency = str(r.get("통화", "KRW")).upper()
            qty = float(r.get("수량", 0) or 0)
            avg_price = float(r.get("평균매수가", 0) or 0)

            yft = to_yf_ticker(r.get("티커"), country, market)
            hist = get_history(yft, period="5d")
            last_price = float(hist.iloc[-1]) if not hist.empty else avg_price

            eval_native = last_price * qty
            eval_krw = eval_native * fx_rate if currency == "USD" else eval_native
            return_pct = (last_price / avg_price - 1) * 100 if avg_price else 0

            rows.append({
                "증권사": r.get("증권사", "수동입력"),
                "티커": normalize_ticker(r.get("티커")),
                "종목명": r.get("종목명", r.get("티커")),
                "시장": market,
                "통화": currency,
                "수량": qty,
                "평균매수가": avg_price,
                "현재가": round(last_price, 2),
                "평가액(원)": round(eval_krw),
                "수익률(%)": round(return_pct, 2),
                "매수일": str(r.get("매수일", "")),
                "yf_ticker": yft,
            })
        except Exception as e:
            print(f"[경고] 수동 보유 행 처리 실패: {e}")
            continue

    return pd.DataFrame(rows)


def manual_to_orders(manual_df):
    """수동 보유 DataFrame을 토스 주문(체결) 형태의 합성 주문 리스트로 변환합니다.
    PME·배당·환차손익 분석이 타 증권사 종목까지 포함하도록 각 보유를 1건의 매수 체결로 취급.
    매수일이 없으면 오늘 날짜를 사용합니다.
    """
    if manual_df is None or manual_df.empty:
        return []
    orders = []
    today = datetime.now().strftime("%Y-%m-%d")
    for _, r in manual_df.iterrows():
        try:
            qty = float(r.get("수량", 0) or 0)
            avg_price = float(r.get("평균매수가", 0) or 0)
            if qty <= 0 or avg_price <= 0:
                continue
            raw_date = r.get("매수일", "")
            if pd.isna(raw_date):
                buy_date = today
            else:
                buy_date = str(raw_date).strip()
                if not buy_date or buy_date.lower() == "nan":
                    buy_date = today
            # 날짜 형식 검증 (파싱 실패 시 오늘로 대체)
            try:
                buy_date = pd.to_datetime(buy_date).strftime("%Y-%m-%d")
            except Exception:
                buy_date = today
            filled_at = f"{buy_date}T00:00:00+09:00"
            orders.append({
                "symbol": str(r.get("티커")),
                "currency": str(r.get("통화", "KRW")).upper(),
                "side": "BUY",
                "status": "FILLED",
                "orderedAt": filled_at,
                "broker": r.get("증권사", "타증권사"),
                "execution": {
                    "filledQuantity": qty,
                    "averageFilledPrice": avg_price,
                    "filledAmount": qty * avg_price,
                    "commission": 0,
                    "tax": 0,
                    "filledAt": filled_at,
                },
            })
        except Exception:
            continue
    return orders

