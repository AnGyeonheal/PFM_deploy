"""한국 주식 종목명 해석 — 6자리 종목코드를 한글 종목명으로 변환합니다.

FinanceDataReader의 KRX 상장목록을 1회 로드해 캐시합니다. 실패 시 원본(티커) 유지.
"""
from functools import lru_cache
import os
import json


_KR_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".kr_names_cache.json")


@lru_cache(maxsize=1)
def _krx_map():
    """국내 종목코드→종목명(KRX 주식 + ETF). 디스크 캐시→없으면 fdr 로드 후 저장."""
    try:
        if os.path.exists(_KR_CACHE_FILE):
            with open(_KR_CACHE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if d:
                return d
    except Exception:
        pass
    out = {}
    try:
        import FinanceDataReader as fdr
        for listing in ("KRX", "ETF/KR"):
            try:
                df = fdr.StockListing(listing)
                cols = list(df.columns)
                code_col = next((c for c in ("Code", "Symbol", "종목코드") if c in cols), cols[0])
                name_col = next((c for c in ("Name", "종목명") if c in cols), cols[1])
                for c, n in zip(df[code_col], df[name_col]):
                    if n:
                        out.setdefault(str(c).zfill(6), str(n))
            except Exception:
                continue
    except Exception:
        return {}
    try:
        if out:
            with open(_KR_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
    except Exception:
        pass
    return out


def _kr_code(ticker):
    """국내 종목코드로 정규화. 6자리 숫자·A접두사·.KS/.KQ 접미사, 그리고
    KRX 목록에 있는 6자리 영숫자 코드(ETN/ETF 신형: 0183J0 등)까지 국내로 인정. 아니면 None."""
    t = str(ticker or "").strip().upper()
    for suf in (".KS", ".KQ", ".KRX", ".KOSPI", ".KOSDAQ"):
        if t.endswith(suf):
            t = t[:-len(suf)]
            break
    if len(t) >= 2 and t[0] == "A" and t[1:].isdigit():
        t = t[1:]
    if t.isdigit() and len(t) <= 6:
        return t.zfill(6)
    if len(t) == 6 and t in _krx_map():
        return t
    return None


def resolve_kr_name(ticker, fallback=None):
    """국내 종목코드(6자리, A접두사·.KS 등 허용)면 한글 종목명으로, 아니면 fallback(또는 티커) 반환."""
    code = _kr_code(ticker)
    if code:
        nm = _krx_map().get(code)
        if nm:
            return nm
    return fallback if fallback is not None else ticker


_US_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".us_names_cache.json")


@lru_cache(maxsize=1)
def _us_map():
    """미국 상장 티커→회사명 매핑(NASDAQ/NYSE/AMEX). 디스크 캐시→없으면 fdr 로드 후 저장."""
    try:
        if os.path.exists(_US_CACHE_FILE):
            with open(_US_CACHE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if d:
                return d
    except Exception:
        pass
    out = {}
    try:
        import FinanceDataReader as fdr
        for market in ("NASDAQ", "NYSE", "AMEX"):
            try:
                df = fdr.StockListing(market)
                cols = list(df.columns)
                sym_col = next((c for c in ("Symbol", "Code", "Ticker") if c in cols), cols[0])
                name_col = next((c for c in ("Name", "종목명") if c in cols), cols[1])
                for sym, nm in zip(df[sym_col], df[name_col]):
                    if sym and nm:
                        out.setdefault(str(sym).strip().upper(), str(nm).strip())
            except Exception:
                continue
    except Exception:
        return {}
    try:
        if out:
            with open(_US_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
    except Exception:
        pass
    return out


def resolve_us_name(ticker, fallback=None):
    """미국 티커면 회사명으로, 아니면 fallback(또는 티커) 반환."""
    t = str(ticker or "").strip().upper()
    nm = _us_map().get(t)
    if nm:
        return nm
    return fallback if fallback is not None else ticker


def enrich_name_map(name_map, tickers):
    """이름이 비었거나 티커와 같은 경우 한글명(국내)·회사명(미국)으로 보강한 dict를 반환."""
    out = dict(name_map or {})
    for t in tickers:
        t = str(t)
        cur = out.get(t)
        if not cur or str(cur) == t:
            out[t] = resolve_kr_name(t, cur or t) if _kr_code(t) else resolve_us_name(t, cur or t)
    return out


def _norm_name(s):
    """종목명 비교용 정규화: 공백 제거 + 대문자."""
    return "".join(str(s or "").split()).upper()


@lru_cache(maxsize=1)
def _krx_name_to_code():
    """국내 종목명→코드 역매핑(KRX 주식+ETF). 정확 키와 정규화(공백·대소문자 무시) 키를 함께 담는다."""
    m = {}
    for code, name in _krx_map().items():
        c = str(code)
        for key in (str(name).strip(), _norm_name(name)):
            if key:
                m.setdefault(key, c)
    return m


def resolve_kr_code(name):
    """국내 종목명으로 코드를 찾습니다(정확 일치 → 공백·대소문자 무시 정규화 순). 없으면 None."""
    if not name:
        return None
    idx = _krx_name_to_code()
    return idx.get(str(name).strip()) or idx.get(_norm_name(name))


_NAME_TICKER_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".name_ticker_cache.json")


def _load_name_ticker_cache():
    try:
        if os.path.exists(_NAME_TICKER_CACHE_FILE):
            with open(_NAME_TICKER_CACHE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def _save_name_ticker_cache(d):
    try:
        with open(_NAME_TICKER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


def resolve_ticker_map(names):
    """종목명 리스트 → {종목명: 티커}. 캐시 → KRX 국내매칭 → Gemini(미매칭만 배치) 순.
    Gemini 조회 결과는 캐시에 저장해 이후 재조회하지 않습니다(빈 결과도 캐시해 반복 호출 방지)."""
    uniq = sorted({str(n).strip() for n in (names or []) if str(n).strip()})
    if not uniq:
        return {}
    cache = _load_name_ticker_cache()
    out = {}
    missing = []
    for n in uniq:
        if n in cache:
            if cache[n]:
                out[n] = cache[n]
            continue
        code = resolve_kr_code(n)  # KRX 국내 종목명 정확/정규화 매칭이 먼저(무료·즉시)
        if code:
            out[n] = code
            cache[n] = code
        else:
            missing.append(n)
    if missing:
        try:
            from ai_copilot import ai_resolve_tickers
            ai = ai_resolve_tickers(missing)
        except Exception:
            ai = {}
        for n in missing:
            t = str(ai.get(n, "") or "").strip()
            cache[n] = t  # 빈 값도 저장 → 다음부터 Gemini 재호출 안 함
            if t:
                out[n] = t
    _save_name_ticker_cache(cache)
    return out


def normalize_kr_ticker(t):
    """국내 종목코드의 A 접두사를 제거해 6자리로 통일합니다(A360750 → 360750).
    'A+숫자' 형태가 아닌 티커(AAPL 등)는 그대로 유지합니다."""
    if t is None:
        return t
    s = str(t).strip()
    if len(s) >= 2 and s[0] in ("A", "a") and s[1:].isdigit():
        return s[1:].zfill(6)
    return s
