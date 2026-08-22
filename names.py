"""한국 주식 종목명 해석 — 6자리 종목코드를 한글 종목명으로 변환합니다.

FinanceDataReader의 KRX 상장목록을 1회 로드해 캐시합니다. 실패 시 원본(티커) 유지.
"""
from functools import lru_cache


@lru_cache(maxsize=1)
def _krx_map():
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("KRX")
        cols = list(df.columns)
        code_col = next((c for c in ("Code", "Symbol", "종목코드") if c in cols), cols[0])
        name_col = next((c for c in ("Name", "종목명") if c in cols), cols[1])
        return {str(c).zfill(6): str(n) for c, n in zip(df[code_col], df[name_col]) if n}
    except Exception:
        return {}


def resolve_kr_name(ticker, fallback=None):
    """국내 6자리 코드면 한글 종목명으로, 아니면 fallback(또는 티커) 반환."""
    t = str(ticker or "").strip()
    if t.isdigit() and len(t) <= 6:
        nm = _krx_map().get(t.zfill(6))
        if nm:
            return nm
    return fallback if fallback is not None else ticker


def enrich_name_map(name_map, tickers):
    """국내 종목 중 이름이 비어있거나 티커와 같은 경우 한글명으로 보강한 dict를 반환."""
    out = dict(name_map or {})
    for t in tickers:
        t = str(t)
        cur = out.get(t)
        if (not cur or str(cur) == t) and t.isdigit():
            out[t] = resolve_kr_name(t, cur or t)
    return out
