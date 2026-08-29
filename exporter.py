"""프로젝트에서 사용하는 모든 데이터를 하나의 엑셀(다중 시트)로 내보냅니다.

build_full_excel(...) 가 .xlsx 바이트를 반환합니다. (엔진: openpyxl)
시트: 요약 · 거래내역(전체) · 달러_매매 · 보유종목 · 배당내역 · 환율_달러평단 ·
      임포트_거래내역 · 임포트_잔고 · 임포트_배당 · 보유_요약
"""
import io
from datetime import datetime

import pandas as pd


def _sanitize(df):
    """타임존 정보 등 엑셀에 못 쓰는 값을 정리한 복사본을 반환."""
    if df is None or df.empty:
        return df
    out = df.copy()
    for c in out.columns:
        try:
            if pd.api.types.is_datetime64tz_dtype(out[c]):
                out[c] = out[c].dt.tz_localize(None)
        except Exception:
            pass
    return out


def _write(writer, sheet, df):
    """비어있지 않은 DataFrame만 시트로 기록."""
    if df is not None and not df.empty:
        _sanitize(df).to_excel(writer, sheet_name=sheet[:31], index=False)
        return True
    return False


def _num(v):
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return v


def build_toss_raw_df(orders, name_map=None):
    """토스 API 원본 주문 리스트를 검토·엑셀용 DataFrame으로 평탄화합니다.
    변환 전 원본 필드(체결수량·단가·금액·수수료·세금·시각)를 그대로 담습니다.
    """
    name_map = name_map or {}
    rows = []
    for o in orders or []:
        ex = o.get("execution") or {}
        rows.append({
            "심볼": o.get("symbol"),
            "종목명": name_map.get(o.get("symbol"), o.get("symbol")),
            "매매구분": o.get("side"),
            "통화": o.get("currency", "KRW"),
            "체결수량": ex.get("filledQuantity"),
            "체결단가": ex.get("averageFilledPrice"),
            "체결금액": ex.get("filledAmount"),
            "수수료": ex.get("commission"),
            "세금": ex.get("tax"),
            "체결시각": ex.get("filledAt"),
            "주문시각": o.get("orderedAt"),
            "주문상태": o.get("status") or o.get("orderState"),
            "증권사": o.get("broker", "토스증권"),
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    try:
        df["_sort"] = pd.to_datetime(df["체결시각"], utc=True, errors="coerce")
        df = df.sort_values("_sort", ascending=False, na_position="last").drop(columns=["_sort"])
    except Exception:
        pass
    return df.reset_index(drop=True)


def _summary_frame(summary, perf, ab, fx_rate, meta):
    rows = []
    meta = meta or {}
    rows.append(("생성 시각", datetime.now().strftime("%Y-%m-%d %H:%M")))
    for k, v in meta.items():
        rows.append((k, v))
    if fx_rate:
        rows.append(("적용 환율(USD→KRW)", _num(fx_rate)))

    summary = summary or {}
    rows.append(("", ""))
    rows.append(("[ 자산 요약 ]", ""))
    for key, label in [
        ("total_asset_krw", "총자산(원)"), ("stock_eval_krw", "주식 평가액(원)"),
        ("purchase_krw", "투자 원금(원)"), ("cash_krw_native", "예수금 원화(원)"),
        ("cash_usd_native", "예수금 달러($)"),
    ]:
        if key in summary:
            rows.append((label, _num(summary.get(key))))

    if perf:
        rows.append(("", ""))
        rows.append(("[ 손익 요약 ]", ""))
        for key, label in [
            ("all_inclusive_krw", "누적 총손익(원)"), ("all_inclusive_pct", "누적 총손익률(%)"),
            ("unreal_total_krw", "보유 평가손익(원)"), ("realized_total_krw", "실현손익(원)"),
            ("pure_price_krw", "순수 주가손익(원)"), ("div_krw", "배당 수익(원)"),
            ("fx_total_krw", "환차손익(원)"),
        ]:
            if key in perf:
                rows.append((label, _num(perf.get(key))))

    if ab:
        rows.append(("", ""))
        rows.append(("[ 성과·위험 지표 ]", ""))
        for key, label in [
            ("port_xirr_pct", "내 XIRR(%)"), ("spy_xirr_pct", "S&P500 XIRR(%)"),
            ("alpha_pct", "알파(초과수익 %p)"), ("beta", "베타"),
            ("corr", "상관계수"), ("n_days", "측정 거래일수"),
        ]:
            if key in ab:
                rows.append((label, _num(ab.get(key))))

    return pd.DataFrame(rows, columns=["항목", "값"])


def _fx_frame(usd_cost, fx_pnl_df):
    """달러 평단가 요약 + 종목별 환차손익."""
    frames = []
    if usd_cost:
        kv = [
            ("달러 평단가(원/$)", _num(usd_cost.get("avg_fx"))),
            ("현재 환율(원/$)", _num(usd_cost.get("current_fx"))),
            ("총 매수원금($)", _num(usd_cost.get("total_usd"))),
            ("투자원금(원)", _num(usd_cost.get("invested_krw"))),
            ("누적 환차손익(원)", _num(usd_cost.get("fx_pnl_krw"))),
        ]
        frames.append(pd.DataFrame(kv, columns=["항목", "값"]))
    return frames[0] if frames else pd.DataFrame()


def build_full_excel(summary=None, perf=None, ab=None, holdings=None,
                     detail_df=None, holdings_breakdown=None, dividends_df=None,
                     usd_cost=None, fx_pnl_df=None, raw_tx=None, raw_holdings=None,
                     raw_dividends=None, fx_rate=None, meta=None, raw_toss=None):
    """모든 데이터를 다중 시트 엑셀 바이트로 반환합니다."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # 1) 요약 (항상 기록)
        _summary_frame(summary, perf, ab, fx_rate, meta).to_excel(
            writer, sheet_name="요약", index=False)

        # 2) 전체 거래내역 (토스 + 임포트 통합)
        _write(writer, "거래내역", detail_df)

        # 2-1) 토스 API 원본(raw) 주문 데이터
        _write(writer, "토스_원본데이터", raw_toss)

        # 3) 달러 매매 기록 (통화=USD)
        if detail_df is not None and not detail_df.empty and "통화" in detail_df.columns:
            _write(writer, "달러_매매", detail_df[detail_df["통화"] == "USD"])

        # 4) 보유 종목 성과 (실현·평가·배당·수익률)
        _write(writer, "보유종목", holdings_breakdown)

        # 5) 배당 내역
        _write(writer, "배당내역", dividends_df)

        # 6) 환율·달러 평단가 (+ 종목별 환차손익)
        _write(writer, "환율_달러평단", _fx_frame(usd_cost, fx_pnl_df))
        _write(writer, "종목별_환차손익", fx_pnl_df)

        # 7) 원시 임포트 데이터
        _write(writer, "임포트_거래내역", raw_tx)
        _write(writer, "임포트_잔고", raw_holdings)
        _write(writer, "임포트_배당", raw_dividends)

        # 8) 보유 요약(포트폴리오 스냅샷)
        if holdings:
            _write(writer, "보유_요약", pd.DataFrame(holdings))

        _autofit(writer)

    buf.seek(0)
    return buf.getvalue()


def _autofit(writer):
    """각 시트 열 너비를 내용에 맞춰 대략 조정."""
    try:
        for ws in writer.book.worksheets:
            for col in ws.columns:
                length = 8
                letter = col[0].column_letter
                for cell in col:
                    v = cell.value
                    if v is not None:
                        length = max(length, min(len(str(v)) + 2, 40))
                ws.column_dimensions[letter].width = length
    except Exception:
        pass
