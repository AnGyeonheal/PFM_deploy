"""yfinance 기반 장기 시세·벤치마크 분석 모듈.
토스 캔들 API(최근 200일 제한)를 넘어서는 과거 데이터와 S&P500 비교를 제공합니다.
"""
import time

import pandas as pd
import yfinance as yf

BENCHMARK_TICKER = "SPY"  # S&P 500 추종 ETF

# 동일 렌더링 중 반복되는 yfinance 호출(KRW=X·SPY 등)를 줄이기 위한 프로세스 내 TTL 캐시.
_HTTP_CACHE = {}
_HTTP_CACHE_TTL = 900  # 15분


def _memo(key, producer):
    """key별로 producer() 결과를 TTL 동안 재사용합니다. pandas 객체는 복사본을 반환해
    호출측의 in-place 변경(name/index 재설정)이 캐시를 오염시키지 않게 합니다."""
    now = time.time()
    cached = _HTTP_CACHE.get(key)
    if cached is not None and (now - cached[0]) < _HTTP_CACHE_TTL:
        val = cached[1]
        return val.copy() if hasattr(val, "copy") else val
    val = producer()
    _HTTP_CACHE[key] = (now, val)
    return val.copy() if hasattr(val, "copy") else val


def to_yf_ticker(symbol, market_country="US", market=None):
    """토스/수동입력 심볼을 yfinance 티커로 변환합니다.
    - 미국 주식: 그대로 사용 (BRK.B → BRK-B 처럼 점은 하이픈으로)
    - 국내 주식: KOSPI는 .KS, KOSDAQ은 .KQ 접미사
    """
    if symbol is None:
        return None
    symbol = str(symbol).strip().upper()
    country = (market_country or "US").upper()

    if country in ("KR", "KOR", "KOREA"):
        suffix = ".KQ" if (market or "").upper() in ("KOSDAQ", "KQ") else ".KS"
        # 이미 접미사가 있으면 그대로
        return symbol if symbol.endswith((".KS", ".KQ")) else f"{symbol.zfill(6)}{suffix}"
    # 미국 등 해외
    return symbol.replace(".", "-")


def get_history(yf_ticker, start=None, period="2y"):
    """일봉 종가 시계열(pandas Series, 날짜 인덱스)을 반환합니다."""
    return _memo(("hist", yf_ticker, start, period),
                 lambda: _get_history_uncached(yf_ticker, start, period))


def _get_history_uncached(yf_ticker, start=None, period="2y"):
    try:
        tk = yf.Ticker(yf_ticker)
        df = tk.history(start=start, period=None if start else period, interval="1d")
        if df.empty:
            return pd.Series(dtype=float)
        s = df["Close"].copy()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        s = s.dropna()  # yfinance가 붙이는 당일 미완성 봉(NaN 종가) 제거
        s.name = yf_ticker
        return s
    except Exception as e:
        print(f"[경고] yfinance {yf_ticker} 조회 실패: {e}")
        return pd.Series(dtype=float)


def get_dividends(yf_ticker):
    """종목의 주당 배당금 이력(pandas Series, 배당락일 인덱스)을 반환합니다. (tz 제거)"""
    return _memo(("div", yf_ticker), lambda: _get_dividends_uncached(yf_ticker))


def _get_dividends_uncached(yf_ticker):
    try:
        div = yf.Ticker(yf_ticker).dividends
        if div is None or div.empty:
            return pd.Series(dtype=float)
        div = div.copy()
        div.index = pd.to_datetime(div.index).tz_localize(None).normalize()
        return div
    except Exception as e:
        print(f"[경고] yfinance {yf_ticker} 배당 조회 실패: {e}")
        return pd.Series(dtype=float)


def get_usdkrw_history(period="2y"):
    """USD/KRW 환율 일별 종가 시계열을 반환합니다. (yfinance 'KRW=X')"""
    return get_history("KRW=X", period=period)


# ─────────────────── 보유 종목 현재가(네이티브) 제공 ───────────────────
# 우선순위: 토스 실시간 배치(_PRICE_OVERRIDE) → pykrx(국내 공식 종가) → yfinance 최근 종가.
# pipeline이 로드 시 토스 배치 시세를 set_price_overrides()로 주입해 최고 싱크로율을 확보합니다.
_PRICE_OVERRIDE = {}


def set_price_overrides(price_map):
    """토스 실시간 배치 현재가 {symbol: price}를 주입(병합)합니다. 시세는 사용자 무관이라 병합해도 안전."""
    if price_map:
        _PRICE_OVERRIDE.update({str(k): v for k, v in price_map.items() if v})


def _pykrx_close(symbol):
    """pykrx로 국내 종목의 최신 종가(KRX 공식)를 반환. 실패 시 None."""
    import datetime as _dt
    try:
        from pykrx import stock
    except Exception:
        return None
    code = str(symbol).zfill(6)
    today = _dt.datetime.now().strftime("%Y%m%d")
    frm = (_dt.datetime.now() - _dt.timedelta(days=14)).strftime("%Y%m%d")
    try:
        df = stock.get_market_ohlcv_by_date(frm, today, code)
        if df is not None and not df.empty:
            return float(df["종가"].iloc[-1])
    except Exception:
        return None
    return None


def get_native_price_now(symbol, country="US", market=None):
    """보유 종목의 현재가(네이티브 통화)를 최고 싱크로율로 반환합니다.
    토스 실시간 → pykrx(국내) → yfinance 순으로 시도. pykrx/yfinance는 TTL 캐시.
    """
    if symbol is None:
        return None
    ov = _PRICE_OVERRIDE.get(str(symbol))
    if ov:
        return float(ov)
    return _memo(("pxnow", str(symbol), (country or "US").upper()),
                 lambda: _native_price_uncached(symbol, country, market))


def _native_price_uncached(symbol, country, market):
    is_kr = (country or "US").upper() in ("KR", "KOR", "KOREA")
    if is_kr:
        p = _pykrx_close(symbol)
        if p:
            return p
    h = get_history(to_yf_ticker(symbol, "KR" if is_kr else "US", market), period="5d")
    return float(h.iloc[-1]) if (not h.empty and pd.notna(h.iloc[-1])) else None



def normalize_to_100(price_series):
    """첫 유효값을 100으로 재설정(리베이스)하여 스케일·통화 차이를 통일합니다."""
    s = price_series.dropna()
    if s.empty:
        return s
    base = s.iloc[0]
    if base == 0:
        return s
    return s / base * 100.0


def build_growth_frame(ticker_map, start=None, period="1y"):
    """여러 종목 + 벤치마크(SPY)의 정규화 성장 시계열 DataFrame을 만듭니다.
    ticker_map: {표시이름: yf_ticker}
    반환: 열=종목명, 값=100 기준 정규화 지수, 공통 날짜 인덱스
    """
    series_list = []
    all_map = dict(ticker_map)
    all_map.setdefault("S&P500(SPY)", BENCHMARK_TICKER)

    for name, yft in all_map.items():
        raw = get_history(yft, start=start, period=period)
        if raw.empty:
            continue
        raw.name = name
        series_list.append(raw)

    if not series_list:
        return pd.DataFrame()

    df = pd.concat(series_list, axis=1).sort_index().ffill()
    # 공통 시작 이후 구간만 사용 후 정규화
    df = df.dropna(how="all")
    normalized = df.apply(normalize_to_100)
    return normalized


def quarterly_excess_returns(ticker_map, start=None, period="2y"):
    """분기별로 각 종목의 S&P500 대비 초과수익률(%p)을 계산합니다.
    ticker_map: {표시이름: yf_ticker}
    반환: DataFrame(index=분기, columns=종목명, 값=초과수익률%p)
    """
    # 벤치마크 포함 종가 수집
    all_map = dict(ticker_map)
    all_map["S&P500(SPY)"] = BENCHMARK_TICKER

    series_list = []
    for name, yft in all_map.items():
        raw = get_history(yft, start=start, period=period)
        if not raw.empty:
            raw.name = name
            series_list.append(raw)
    if not series_list:
        return pd.DataFrame()

    df = pd.concat(series_list, axis=1).sort_index().ffill()

    # 분기말 종가 → 분기 수익률(%)
    q_close = df.resample("QE").last()
    q_return = q_close.pct_change() * 100.0
    q_return = q_return.dropna(how="all")

    if "S&P500(SPY)" not in q_return.columns:
        return pd.DataFrame()

    bench = q_return["S&P500(SPY)"]
    excess = q_return.drop(columns=["S&P500(SPY)"]).subtract(bench, axis=0)
    excess["S&P500(SPY) 수익률"] = bench

    # 분기 인덱스를 2024Q1 형태 라벨로
    excess.index = [f"{d.year}Q{d.quarter}" for d in excess.index]
    return excess.round(2)
