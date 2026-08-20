import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
import os
from datetime import datetime
from dotenv import load_dotenv

from pm import get_access_token, get_holdings, get_buying_power, get_exchange_rate, get_order_history, get_stock_info
from analytics_engine import transform_to_mvp_json, build_transaction_detail
from ai_copilot import chat_with_portfolio
from benchmark import to_yf_ticker, get_usdkrw_history
from manual_holdings import (
    load_manual_holdings, save_parsed_holdings, manual_to_orders,
    read_manual_csv, write_manual_csv,
    read_transactions_csv, write_transactions_csv, save_parsed_transactions,
    transactions_to_orders, derive_holdings_from_tx,
    read_dividends_csv, write_dividends_csv, save_parsed_dividends,
    set_data_dir, clear_all_imports,
)
from pme import (
    build_ticker_profit_growth, compute_usd_avg_cost, build_usdkrw_history_frame,
    compute_alpha_beta, build_total_profit_growth, build_ticker_price_trades, compute_rolling_beta,
    build_trade_bars,
)
from performance import compute_performance_summary, build_holdings_breakdown
from advanced_analytics import compute_dividends
from ai_copilot import parse_brokerage_transactions, parse_brokerage_full_transactions, parse_brokerage_dividends
from ai_copilot import generate_rebalancing_report
from auth import (
    register_user, verify_user, user_dir,
    load_credentials, save_credentials, has_toss_credentials, CRED_KEYS,
    create_session, resolve_session, destroy_session, get_user_info,
)
from report import build_portfolio_pdf

# 1. 페이지 설정 (반드시 최상단에 위치)
st.set_page_config(page_title="자산관리 대시보드", layout="wide", page_icon="📈")

# Streamlit Cloud 배포 시: st.secrets에 등록한 값을 os.getenv()로도 읽도록 환경변수에 반영
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

# ── 토스 스타일 테마 (Pretendard 폰트 · 카드형 UI · 토스 블루) ──────────────
# 주의: 마크다운이 코드블록으로 오인하지 않도록 각 줄을 들여쓰지 말 것
st.markdown(
"""
<link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css" />
<style>
:root {
--toss-blue: #3182F6;
--toss-blue-dark: #1B64DA;
--toss-bg: #F2F4F6;
--toss-card: #FFFFFF;
--toss-ink: #191F28;
--toss-sub: #6B7684;
--toss-border: #E5E8EB;
--toss-red: #F04452;
}
html, body, [class*="css"], .stApp, [data-testid="stAppViewContainer"] {
font-family: 'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, system-ui, 'Segoe UI', Roboto, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
}
.stApp { background: var(--toss-bg); }
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.0rem; padding-bottom: 4rem; max-width: 1400px; }
h1, h2, h3, h4 { color: var(--toss-ink); font-weight: 700; letter-spacing: -0.02em; }
h1 { font-size: 1.8rem !important; }
h2 { font-size: 1.3rem !important; margin-top: 0.3rem; }
h3 { font-size: 1.1rem !important; }
p, span, label, li { color: var(--toss-ink); }
[data-testid="stCaptionContainer"], .stCaption, small { color: var(--toss-sub) !important; }
[data-testid="stMetric"] { background: var(--toss-card); border: 1px solid var(--toss-border); border-radius: 20px; padding: 18px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); transition: transform .12s ease, box-shadow .12s ease; }
[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(49,130,246,0.10); }
[data-testid="stMetricLabel"] p { color: var(--toss-sub) !important; font-size: 0.86rem; font-weight: 600; }
[data-testid="stMetricValue"] { color: var(--toss-ink); font-weight: 700; font-size: 1.5rem; }
/* ── 버튼: 토스 스타일 (라운드 · 그라데이션 · 호버 리프트) ── */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button { border-radius: 14px; border: 1.5px solid var(--toss-border); background: #FFFFFF; color: var(--toss-ink); font-weight: 700; font-size: 0.92rem; padding: 0.58rem 1.15rem; transition: transform .12s ease, box-shadow .12s ease, border-color .12s ease, background .12s ease, color .12s ease; box-shadow: 0 1px 2px rgba(0,0,0,0.04); letter-spacing: -0.01em; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--toss-blue); color: var(--toss-blue); background: #F4F8FF; transform: translateY(-1px); box-shadow: 0 6px 16px rgba(49,130,246,0.14); }
.stButton > button:active, .stDownloadButton > button:active, [data-testid="stFormSubmitButton"] > button:active { transform: translateY(0); box-shadow: 0 1px 2px rgba(0,0,0,0.06); }
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible, [data-testid="stFormSubmitButton"] > button:focus-visible { outline: 3px solid rgba(49,130,246,0.35); outline-offset: 1px; }
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button { background: linear-gradient(180deg, #4A93F8 0%, var(--toss-blue) 100%); color: #fff; border: none; box-shadow: 0 4px 12px rgba(49,130,246,0.28); }
.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button:hover { background: linear-gradient(180deg, var(--toss-blue) 0%, var(--toss-blue-dark) 100%); color: #fff; transform: translateY(-1px); box-shadow: 0 8px 20px rgba(27,100,218,0.34); }
.stButton > button[kind="primary"]:active, [data-testid="stFormSubmitButton"] > button:active { background: var(--toss-blue-dark); box-shadow: 0 2px 8px rgba(27,100,218,0.30); }
.stDownloadButton > button { background: linear-gradient(180deg, #12B981 0%, var(--toss-green, #00A676) 100%); color: #fff; border: none; box-shadow: 0 4px 12px rgba(0,166,118,0.26); }
.stDownloadButton > button:hover { background: linear-gradient(180deg, #00A676 0%, #018A61 100%); color: #fff; transform: translateY(-1px); box-shadow: 0 8px 20px rgba(0,138,97,0.32); }
.stButton > button:disabled, .stDownloadButton > button:disabled, [data-testid="stFormSubmitButton"] > button:disabled { background: #EEF1F4; color: #B0B8C1; border: 1.5px solid var(--toss-border); box-shadow: none; transform: none; cursor: not-allowed; opacity: 1; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] { border-radius: 12px; padding: 6px 16px; background: #EEF1F4; color: var(--toss-sub); }
.stTabs [aria-selected="true"] { background: var(--toss-blue) !important; color: #fff !important; }
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"] { border: 1.6px solid var(--toss-border) !important; border-radius: 12px !important; background: #FFFFFF !important; transition: border-color .12s ease, box-shadow .12s ease; }
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within { border-color: var(--toss-blue) !important; box-shadow: 0 0 0 3px rgba(49,130,246,0.18) !important; }
.stTextInput input, .stNumberInput input, .stTextArea textarea, [data-baseweb="input"] input { border-radius: 12px !important; }
.stTextInput label, .stNumberInput label, .stTextArea label, .stSelectbox label, .stRadio label { font-weight: 600 !important; color: var(--toss-ink) !important; }
div[data-baseweb="select"] > div { border: 1.6px solid var(--toss-blue) !important; background: #F4F8FF !important; }
div[data-baseweb="select"] svg { color: var(--toss-blue) !important; fill: var(--toss-blue) !important; }
[data-testid="stDataFrame"], [data-testid="stTable"] { border-radius: 16px; overflow: hidden; border: 1px solid var(--toss-border); }
[data-testid="stExpander"] { border: 1px solid var(--toss-border); border-radius: 16px; background: var(--toss-card); }
.stPlotlyChart { background: var(--toss-card); border: 1px solid var(--toss-border); border-radius: 16px; padding: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.03); }
hr { border-color: var(--toss-border); margin: 1.4rem 0; }
[data-testid="stAlert"] { border-radius: 14px; }
[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid var(--toss-border); min-width: 330px !important; width: 330px !important; }
[data-testid="stChatMessage"] { background: var(--toss-bg); border-radius: 12px; padding: 4px 10px; }
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { font-size: 0.84rem; line-height: 1.45; }
</style>
""",
    unsafe_allow_html=True,
)

# Plotly 전역 스타일: 화이트 배경·Pretendard 폰트
_toss_tpl = pio.templates["plotly_white"]
_toss_tpl.layout.font.family = "Pretendard, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
_toss_tpl.layout.font.color = "#191F28"
_toss_tpl.layout.colorway = ["#3182F6", "#F04452", "#00A676", "#F9A825", "#8B5CF6", "#6B7684"]
_toss_tpl.layout.paper_bgcolor = "rgba(0,0,0,0)"
_toss_tpl.layout.plot_bgcolor = "rgba(0,0,0,0)"
pio.templates.default = "plotly_white"

# ── 로그인 게이트 ─────────────────────────────────────────────
if "username" not in st.session_state:
    st.session_state.username = None

# 세션 유지: 새로고침·재시작 시 URL의 세션 토큰으로 자동 로그인 복원
if not st.session_state.username:
    _sid = st.query_params.get("sid")
    _restored = resolve_session(_sid) if _sid else None
    if _restored:
        st.session_state.username = _restored

def _do_login_page():
    st.title("🔐 자산관리 대시보드 로그인")
    st.caption("로그인하면 임포트한 증권사 거래내역을 계정별로 저장하고 다시 불러올 수 있습니다.")
    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
    with tab_login:
        u = st.text_input("아이디", key="login_id")
        p = st.text_input("비밀번호", type="password", key="login_pw")
        keep = st.checkbox("로그인 상태 유지", value=True, key="login_keep")
        if st.button("로그인", type="primary", key="btn_login"):
            ok, msg = verify_user(u, p)
            if ok:
                st.session_state.username = u.strip()
                if keep:
                    st.query_params["sid"] = create_session(u.strip())
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(msg)
    with tab_signup:
        u2 = st.text_input("새 아이디", key="signup_id")
        p2 = st.text_input("새 비밀번호 (4자 이상)", type="password", key="signup_pw")
        if st.button("회원가입", key="btn_signup"):
            ok, msg = register_user(u2, p2)
            (st.success if ok else st.error)(msg)

if not st.session_state.username:
    _do_login_page()
    st.stop()

_USER = st.session_state.username
set_data_dir(user_dir(_USER))

def _migrate_legacy_imports():
    import shutil
    legacy_dir = os.path.dirname(os.path.abspath(__file__))
    udir = user_dir(_USER)
    for fname in ("manual_transactions.csv", "manual_holdings.csv"):
        src = os.path.join(legacy_dir, fname)
        dst = os.path.join(udir, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass
if not st.session_state.get("_migrated"):
    _migrate_legacy_imports()
    st.session_state["_migrated"] = True


# ── 사용자별 API 키 주입 & 최초 설정 게이트 ──────────────────────
def _secret(key):
    """Streamlit secrets에서 값을 안전하게 읽습니다(secrets 파일이 없어도 예외 없이 None)."""
    try:
        return st.secrets.get(key)
    except Exception:
        return None

def _apply_user_credentials():
    """저장된 사용자 API 키를 os.environ에 주입해 기존 os.getenv 기반 코드가 그대로 동작하게 함.
    사용자 저장값이 없으면 Streamlit secrets(앱 공용)로 폴백합니다."""
    creds = load_credentials(_USER)
    for k in CRED_KEYS:
        v = creds.get(k) or _secret(k)
        if v:
            os.environ[k] = str(v)

_apply_user_credentials()

def _credentials_form(context="setup"):
    """토스 API 키 입력 폼을 그리고 입력값 dict를 반환합니다. context는 위젯 key 접두사.
    (Gemini 키는 기본값이 내장되어 있어 입력받지 않습니다.)"""
    saved = load_credentials(_USER)
    cid = st.text_input("토스 CLIENT_ID", value=saved.get("TOSS_CLIENT_ID", ""),
                        key=f"{context}_cid", help="토스증권 Open API 앱의 Client ID")
    csec = st.text_input("토스 CLIENT_SECRET", value=saved.get("TOSS_CLIENT_SECRET", ""),
                         type="password", key=f"{context}_csec")
    acc = st.text_input("토스 ACCOUNT_NO (계좌 seq)", value=saved.get("TOSS_ACCOUNT_NO", "1") or "1",
                        key=f"{context}_acc")
    return {"TOSS_CLIENT_ID": cid, "TOSS_CLIENT_SECRET": csec, "TOSS_ACCOUNT_NO": acc}

# API 키 입력은 데이터 소스 선택(토스/둘다) 이후 단계에서 처리합니다.


# ── 데이터 로딩 (캐싱) ─────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_portfolio_data():
    load_dotenv()
    CLIENT_ID = os.getenv("TOSS_CLIENT_ID")
    CLIENT_SECRET = os.getenv("TOSS_CLIENT_SECRET")
    ACCOUNT_NO = os.getenv("TOSS_ACCOUNT_NO", "1")
    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    if not token:
        return None, "토스증권 API 토큰 발급에 실패했습니다. API 키(CLIENT_ID, SECRET)와 등록 IP를 확인하세요."
    toss_data = get_holdings(token, ACCOUNT_NO)
    if not toss_data:
        return None, "계좌·자산 데이터를 불러오지 못했습니다."
    krw_cash = get_buying_power(token, ACCOUNT_NO, "KRW")
    usd_cash = get_buying_power(token, ACCOUNT_NO, "USD")
    fx_rate = get_exchange_rate(token)
    cash_krw = krw_cash + usd_cash * fx_rate
    portfolio_json = transform_to_mvp_json("usr_102938", toss_data, cash_krw, fx_rate)
    portfolio_json.setdefault("asset_summary", {})
    portfolio_json["asset_summary"]["cash_krw_native"] = krw_cash
    portfolio_json["asset_summary"]["cash_usd_native"] = usd_cash
    portfolio_json["asset_summary"]["fx_rate"] = fx_rate
    return portfolio_json, None

@st.cache_data(ttl=300)
def fetch_trade_data():
    load_dotenv()
    CLIENT_ID = os.getenv("TOSS_CLIENT_ID")
    CLIENT_SECRET = os.getenv("TOSS_CLIENT_SECRET")
    ACCOUNT_NO = os.getenv("TOSS_ACCOUNT_NO", "1")
    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    if not token:
        return pd.DataFrame(), [], 0.0, {}
    fx_rate = get_exchange_rate(token)
    orders = get_order_history(token, ACCOUNT_NO)
    holdings_data = get_holdings(token, ACCOUNT_NO) or {}
    name_map = {i.get("symbol"): i.get("name") for i in holdings_data.get("result", {}).get("items", [])}
    detail_df = build_transaction_detail(orders, fx_rate, name_map)
    return detail_df, orders, fx_rate, name_map

@st.cache_data(ttl=1800)
def fetch_manual_holdings(fx_rate, user):
    return load_manual_holdings(fx_rate)

@st.cache_data(ttl=1800)
def fetch_manual_transactions(user):
    return read_transactions_csv()

@st.cache_data(ttl=1800)
def fetch_dividends(user):
    return read_dividends_csv()

@st.cache_data(ttl=1800)
def fetch_div_estimate(orders, fx):
    """보유수량 타임라인 × yfinance 주당배당으로 배당 추정 (검증값 없는 종목 보완용)."""
    return compute_dividends(orders, fx)

@st.cache_data(ttl=1800)
def fetch_tx_derived_holdings(fx_rate, user):
    return derive_holdings_from_tx(read_transactions_csv(), fx_rate)

@st.cache_data(ttl=1800)
def fetch_ticker_profit_growth(orders, fx, ticker, native=False):
    return build_ticker_profit_growth(orders, fx, ticker, native)

@st.cache_data(ttl=1800)
def fetch_rolling_beta(orders, fx, ticker):
    return compute_rolling_beta(orders, fx, ticker)

@st.cache_data(ttl=1800)
def fetch_usd_avg_cost(orders, fx):
    return compute_usd_avg_cost(orders, fx)

@st.cache_data(ttl=3600)
def fetch_fx_10y():
    return build_usdkrw_history_frame("10y")

@st.cache_data(ttl=1800)
def fetch_alpha_beta(orders, fx):
    return compute_alpha_beta(orders, fx)

@st.cache_data(ttl=1800)
def fetch_performance_summary(orders, fx, dkn, dun):
    return compute_performance_summary(orders, fx, dkn, dun)

@st.cache_data(ttl=1800)
def fetch_total_profit_growth(orders, fx):
    return build_total_profit_growth(orders, fx)

@st.cache_data(ttl=1800)
def fetch_holdings_breakdown(orders, fx, name_map, div_items):
    return build_holdings_breakdown(orders, fx, name_map, dict(div_items))

@st.cache_data(ttl=1800)
def fetch_ticker_price_trades(orders, ticker, start):
    return build_ticker_price_trades(orders, ticker, start)

@st.cache_data(ttl=3600)
def fetch_stock_names(tickers):
    if not tickers:
        return {}
    load_dotenv()
    token = get_access_token(os.getenv("TOSS_CLIENT_ID"), os.getenv("TOSS_CLIENT_SECRET"))
    if not token:
        return {}
    names = {}
    data = get_stock_info(token, ",".join(tickers)) or {}
    for item in data.get("result", []):
        if item.get("symbol") and item.get("name"):
            names[item["symbol"]] = item["name"]
    return names


def merge_manual_into_portfolio(portfolio_json, manual_df):
    """수동/타 증권사 보유를 포트폴리오에 병합. 같은 티커는 증권사 통합 합산."""
    if manual_df is None or manual_df.empty:
        return portfolio_json
    out = dict(portfolio_json)
    summary = dict(portfolio_json.get("asset_summary", {}))
    merged = {}
    for h in portfolio_json.get("holdings", []):
        tk = h.get("ticker")
        eval_krw = float(h.get("eval_krw", 0) or 0)
        ret = float(h.get("return_pct", 0) or 0)
        cost = eval_krw / (1 + ret / 100) if (1 + ret / 100) != 0 else eval_krw
        merged[tk] = {
            "ticker": tk, "name": h.get("name"), "currency": h.get("currency"),
            "quantity": float(h.get("quantity", 0) or 0), "eval_krw": eval_krw,
            "cost_krw": cost, "sector": h.get("sector", "Unknown"), "brokers": {"토스증권"},
        }
    add_eval = 0.0
    add_purchase = 0.0
    for _, r in manual_df.iterrows():
        tk = str(r.get("티커"))
        eval_krw = float(r.get("평가액(원)", 0) or 0)
        qty = float(r.get("수량", 0) or 0)
        avg = float(r.get("평균매수가", 0) or 0)
        cur = str(r.get("통화", "KRW")).upper()
        purchase_native = qty * avg
        if cur == "USD" and float(r.get("현재가", 0) or 0) > 0:
            fx_implied = eval_krw / (qty * float(r["현재가"])) if qty else 1
            purchase_krw = purchase_native * fx_implied
        else:
            purchase_krw = purchase_native
        add_eval += eval_krw
        add_purchase += purchase_krw
        broker = r.get("증권사", "타증권사")
        if tk in merged:
            m = merged[tk]
            m["quantity"] += qty
            m["eval_krw"] += eval_krw
            m["cost_krw"] += purchase_krw
            m["brokers"].add(broker)
        else:
            merged[tk] = {
                "ticker": tk, "name": r.get("종목명"), "currency": cur, "quantity": qty,
                "eval_krw": eval_krw, "cost_krw": purchase_krw, "sector": "Unknown",
                "brokers": {broker},
            }
    new_stock = sum(m["eval_krw"] for m in merged.values())
    holdings = []
    for m in merged.values():
        ret = (m["eval_krw"] / m["cost_krw"] - 1) * 100 if m["cost_krw"] else 0
        holdings.append({
            "ticker": m["ticker"], "name": m["name"], "currency": m["currency"],
            "quantity": round(m["quantity"], 4), "eval_krw": round(m["eval_krw"]),
            "weight_pct": round(m["eval_krw"] / new_stock * 100, 2) if new_stock else 0,
            "sector": m["sector"], "return_pct": round(ret, 2),
            "brokers": ", ".join(sorted(m["brokers"])),
        })
    holdings.sort(key=lambda x: x["weight_pct"], reverse=True)
    summary["stock_eval_krw"] = round(new_stock)
    base_total = float(portfolio_json.get("asset_summary", {}).get("total_asset_krw", 0) or 0)
    summary["total_asset_krw"] = round(base_total + add_eval)
    summary["purchase_krw"] = round(float(summary.get("purchase_krw", 0) or 0) + add_purchase)
    out["holdings"] = holdings
    out["asset_summary"] = summary
    return out


def _empty_portfolio(fx=1400.0):
    return {
        "user_profile": {"user_id": _USER, "target_benchmark": "S&P 500"},
        "asset_summary": {
            "total_asset_krw": 0, "stock_eval_krw": 0, "purchase_krw": 0, "cash_krw": 0,
            "cash_krw_native": 0, "cash_usd_native": 0, "fx_rate": fx,
        },
        "holdings": [],
    }


def _current_usdkrw():
    s = get_usdkrw_history("5d")
    return float(s.iloc[-1]) if (s is not None and not s.empty) else 1421.0


# ── 임포트 UI (거래내역/잔고 업로드·붙여넣기) ─────────────────────
def _extract_pdf_text(file_obj):
    """업로드된 PDF에서 텍스트를 추출합니다. 반환: (텍스트, 오류메시지 또는 None)."""
    try:
        from pypdf import PdfReader
    except Exception:
        return "", "PDF 처리를 위한 pypdf 라이브러리가 필요합니다. (conda install -c conda-forge pypdf)"
    try:
        try:
            file_obj.seek(0)
        except Exception:
            pass
        reader = PdfReader(file_obj)
        if reader.is_encrypted:
            try:
                reader.decrypt("")  # 빈 암호로 열리는 증권사 PDF 대응
            except Exception:
                return "", "암호가 걸린 PDF입니다. 암호를 해제한 뒤 다시 업로드하세요."
        parts = [p.extract_text() or "" for p in reader.pages]
        text = "\n".join(t for t in parts if t.strip())
        if not text.strip():
            return "", "PDF에서 텍스트를 추출하지 못했습니다(이미지 기반 스캔 PDF일 수 있음)."
        return text, None
    except Exception as e:
        return "", f"PDF 읽기 실패: {e}"


def render_import_ui(key_prefix="imp"):
    st.caption("증권사에서 내려받은 거래내역/잔고 파일을 올리면 AI가 표준 형식으로 변환·저장합니다.")
    broker_name = st.text_input("증권사 이름", value="한화투자증권", key=f"{key_prefix}_broker")
    import_mode = st.radio(
        "임포트 유형",
        ["전체 거래내역 (매수·매도 전체, 청산 종목 포함) · 권장", "현재 잔고만 (보유 종목 스냅샷)"],
        key=f"{key_prefix}_mode",
    )
    is_full_tx = import_mode.startswith("전체")
    ups = st.file_uploader(
        "파일 업로드 (CSV·TXT·엑셀·PDF, 복수 선택 가능)",
        type=["csv", "txt", "xlsx", "xls", "pdf"], accept_multiple_files=True, key=f"{key_prefix}_files",
    )
    pasted = st.text_area("또는 직접 붙여넣기", height=120, key=f"{key_prefix}_paste",
                          placeholder="매수/매도 일자·종목·수량·단가가 포함된 거래내역")
    raw_texts = []
    if ups:
        for up in ups:
            try:
                if up.name.lower().endswith(".pdf"):
                    ptext, perr = _extract_pdf_text(up)
                    if perr:
                        st.warning(f"'{up.name}': {perr}")
                    if ptext:
                        raw_texts.append(ptext)
                elif up.name.lower().endswith((".xlsx", ".xls")):
                    raw_texts.append(pd.read_excel(up).to_csv(index=False))
                else:
                    raw_texts.append(up.getvalue().decode("utf-8", errors="ignore"))
            except Exception as e:
                st.error(f"'{up.name}' 파일을 읽지 못했습니다: {e}")
    if pasted.strip():
        raw_texts.append(pasted)
    if st.button("AI로 변환 후 저장", type="primary", disabled=not raw_texts, key=f"{key_prefix}_go"):
        all_rows = []
        all_divs = []
        with st.spinner("AI가 파일을 분석하는 중입니다..."):
            for rt in raw_texts:
                if is_full_tx:
                    parsed, perr = parse_brokerage_full_transactions(rt, broker_name)
                else:
                    parsed, perr = parse_brokerage_transactions(rt, broker_name)
                if perr:
                    st.warning(perr)
                elif parsed:
                    all_rows.extend(parsed)
                if is_full_tx:  # 같은 파일에서 배당/분배금 기록도 함께 추출
                    dparsed, derr = parse_brokerage_dividends(rt, broker_name)
                    if dparsed:
                        all_divs.extend(dparsed)
        if all_rows or all_divs:
            if is_full_tx:
                saved = save_parsed_transactions(all_rows, replace_broker=broker_name) if all_rows else 0
                _hold = read_manual_csv()
                if not _hold.empty:
                    write_manual_csv(_hold[_hold["증권사"] != broker_name])
                dsaved = save_parsed_dividends(all_divs, replace_broker=broker_name) if all_divs else 0
                msg = f"{saved}건의 거래 · {dsaved}건의 배당을 '{broker_name}'로 저장했습니다."
            else:
                saved = save_parsed_holdings(all_rows, replace_broker=broker_name)
                msg = f"{saved}개 보유 종목을 '{broker_name}'로 저장했습니다."
            st.cache_data.clear()
            st.success(msg)
            st.rerun()
        else:
            st.warning("변환된 항목이 없습니다. 원본 형식을 확인해 주세요.")


# ════════════════════════════════════════════════════════════════
# 1) 데이터 소스 선택 게이트
# ════════════════════════════════════════════════════════════════
if "data_source" not in st.session_state:
    st.session_state.data_source = None
if "view" not in st.session_state:
    st.session_state.view = "개요"

SOURCE_LABELS = {
    "tx": "거래내역 임포트",
    "toss": "토스증권 API",
    "both": "거래내역 + 토스증권 API",
}

if st.session_state.data_source is None:
    # 단계식 설정 마법사: 1) 거래내역 임포트 여부 → 2) 토스증권 API 사용 여부
    st.session_state.setdefault("wiz_stage", "import")
    st.session_state.setdefault("wiz_use_tx", None)
    st.session_state.setdefault("wiz_use_toss", None)

    def _finalize_setup():
        ut, uo = st.session_state.wiz_use_tx, st.session_state.wiz_use_toss
        src = "both" if (ut and uo) else "tx" if ut else "toss" if uo else None
        if not src:  # 둘 다 건너뛴 경우 → 1단계부터 다시
            st.session_state.wiz_stage = "import"
            st.session_state.wiz_use_tx = None
            st.session_state.wiz_use_toss = None
            st.rerun()
        st.session_state.data_source = src
        for _k in ("wiz_stage", "wiz_use_tx", "wiz_use_toss"):
            st.session_state.pop(_k, None)
        st.cache_data.clear()
        st.rerun()

    _step = 1 if st.session_state.wiz_stage == "import" else 2
    st.title("📈 자산관리 대시보드 설정")
    st.caption(f"{_step}/2 단계 · 데이터 소스를 순서대로 설정합니다. 설정 후 왼쪽 사이드바에서 언제든 변경할 수 있습니다.")
    st.progress(_step / 2)

    # ── 1단계: 거래내역 임포트 여부 ──
    if st.session_state.wiz_stage == "import":
        st.markdown("### 1단계 · 거래내역 임포트")
        if st.session_state.wiz_use_tx is None:
            st.markdown("다른 증권사(한국투자·키움 등)의 **거래내역/잔고 파일을 임포트**해서 분석에 포함할까요?")
            _saved_tx = read_transactions_csv()
            _saved_hold = read_manual_csv()
            if len(_saved_tx) or len(_saved_hold):
                st.info(f"이미 저장된 임포트 데이터: 거래내역 {len(_saved_tx)}건 · 잔고 {len(_saved_hold)}종목")
            c1, c2 = st.columns(2)
            if c1.button("📥 네, 임포트할게요", type="primary", use_container_width=True, key="wiz_tx_yes"):
                st.session_state.wiz_use_tx = True
                st.rerun()
            if c2.button("건너뛰기 (임포트 안 함)", use_container_width=True, key="wiz_tx_no"):
                st.session_state.wiz_use_tx = False
                st.session_state.wiz_stage = "toss"
                st.rerun()
        else:
            st.success("거래내역 임포트를 사용합니다. 지금 파일을 올리거나, 나중에 사이드바에서 추가할 수 있습니다.")
            with st.container(border=True):
                render_import_ui("wiz")
            c1, c2 = st.columns(2)
            if c1.button("◀ 뒤로", use_container_width=True, key="wiz_tx_back"):
                st.session_state.wiz_use_tx = None
                st.rerun()
            if c2.button("다음 단계 (토스 API) →", type="primary", use_container_width=True, key="wiz_tx_next"):
                st.session_state.wiz_stage = "toss"
                st.rerun()
        st.stop()

    # ── 2단계: 토스증권 API 사용 여부 ──
    st.markdown("### 2단계 · 토스증권 API 연동")
    if st.session_state.wiz_use_toss is None:
        st.markdown("**토스증권 계좌를 실시간 연동**해서 보유·거래·예수금을 자동으로 불러올까요?")
        st.caption("토스 Open API 키가 필요하며, 호출 IP가 토스 개발자 콘솔에 등록되어 있어야 합니다.")
        c1, c2 = st.columns(2)
        if c1.button("🔗 네, 연동할게요", type="primary", use_container_width=True, key="wiz_toss_yes"):
            st.session_state.wiz_use_toss = True
            st.rerun()
        if c2.button("건너뛰기 (토스 미사용)", use_container_width=True, key="wiz_toss_no"):
            if st.session_state.wiz_use_tx:
                st.session_state.wiz_use_toss = False
                _finalize_setup()
            else:
                st.error("거래내역 임포트도 건너뛰어서 사용할 데이터가 없습니다. 토스 API를 연동하거나 '◀ 이전 단계'에서 임포트를 선택하세요.")
        if st.button("◀ 이전 단계", key="wiz_toss_prev"):
            st.session_state.wiz_stage = "import"
            st.session_state.wiz_use_tx = None
            st.rerun()
    else:
        _has_saved = has_toss_credentials(_USER)
        st.markdown("토스 Open API 키를 **직접 입력**하세요.")
        st.caption("키는 이 컴퓨터의 user_data 폴더에만 저장됩니다."
                   + (" · 저장된 키가 채워져 있으니 그대로 두거나 새 키로 바꿔 입력할 수 있어요." if _has_saved else ""))
        with st.container(border=True):
            _wiz_creds = _credentials_form("wiz")
            c1, c2 = st.columns(2)
            if c1.button("◀ 뒤로", use_container_width=True, key="wiz_toss_back2"):
                st.session_state.wiz_use_toss = None
                st.rerun()
            if c2.button("이 키로 저장하고 완료 →", type="primary", use_container_width=True, key="wiz_toss_save"):
                if _wiz_creds.get("TOSS_CLIENT_ID") and _wiz_creds.get("TOSS_CLIENT_SECRET"):
                    save_credentials(_USER, _wiz_creds)
                    _apply_user_credentials()
                    _finalize_setup()
                else:
                    st.error("CLIENT_ID와 CLIENT_SECRET을 모두 입력하세요.")
    st.stop()


# ════════════════════════════════════════════════════════════════
# 2) 데이터 로딩 (선택한 소스에 따라)
# ════════════════════════════════════════════════════════════════
# 선택한 소스가 토스 API를 사용하는데 저장된 키가 없으면 → 토스 API 키 입력 게이트
source = st.session_state.data_source
if source in ("toss", "both") and not has_toss_credentials(_USER):
    st.title("🔑 토스증권 API 키 입력")
    st.caption("선택하신 데이터 소스는 토스증권 실시간 연동이 필요합니다. 아래에 토스 Open API 키를 입력하세요. "
               "키는 이 컴퓨터의 사용자 폴더(user_data)에만 저장되며 외부로 공유되지 않습니다.")
    with st.container(border=True):
        _setup_creds = _credentials_form("setup")
        cA, cB = st.columns(2)
        if cA.button("저장하고 계속", type="primary", use_container_width=True):
            if _setup_creds.get("TOSS_CLIENT_ID") and _setup_creds.get("TOSS_CLIENT_SECRET"):
                save_credentials(_USER, _setup_creds)
                _apply_user_credentials()
                st.cache_data.clear()
                st.success("토스 API 키를 저장했습니다.")
                st.rerun()
            else:
                st.error("CLIENT_ID와 CLIENT_SECRET을 모두 입력하세요.")
        if cB.button("← 데이터 소스 다시 선택", use_container_width=True):
            st.session_state.data_source = None
            st.rerun()
    st.info("💡 토스 키 없이 이용하려면 '데이터 소스 다시 선택'에서 **거래내역 임포트**를 선택하세요.")
    st.stop()

use_toss = source in ("toss", "both")
use_tx = source in ("tx", "both")

portfolio_json = None
toss_orders = []
toss_name_map = {}
fx_rate = None

if use_toss:
    with st.spinner("토스증권 API와 연동 중입니다..."):
        portfolio_json, toss_err = fetch_portfolio_data()
    if toss_err or not portfolio_json:
        if source == "toss":
            st.error(toss_err or "토스증권 데이터를 불러오지 못했습니다.")
            st.stop()
        else:
            st.warning(f"토스증권 연동 실패 — 임포트한 거래내역만으로 분석합니다. ({toss_err})")
            use_toss = False
            portfolio_json = None
    else:
        _, toss_orders, fx_rate, toss_name_map = fetch_trade_data()

if not use_toss:
    fx_rate = _current_usdkrw()
    portfolio_json = _empty_portfolio(fx_rate)
if not fx_rate:
    fx_rate = _current_usdkrw()

# 타 증권사 거래내역·잔고 (tx/both)
tx_df = pd.DataFrame()
holdings_snapshot = pd.DataFrame()
has_tx = False
if use_tx:
    tx_df = fetch_manual_transactions(_USER)
    has_tx = tx_df is not None and not tx_df.empty
    tx_brokers = set(tx_df["증권사"].unique()) if has_tx else set()
    holdings_snapshot = fetch_manual_holdings(fx_rate, _USER)
    if holdings_snapshot is not None and not holdings_snapshot.empty:
        holdings_snapshot = holdings_snapshot[~holdings_snapshot["증권사"].isin(tx_brokers)]
    tx_holdings = fetch_tx_derived_holdings(fx_rate, _USER) if has_tx else pd.DataFrame()
    parts = [d for d in (tx_holdings, holdings_snapshot) if d is not None and not d.empty]
    manual_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
else:
    manual_df = pd.DataFrame()
has_manual = not manual_df.empty

if has_manual:
    portfolio_json = merge_manual_into_portfolio(portfolio_json, manual_df)

# 통합 주문(체결) 리스트
combined_orders = list(toss_orders)
if use_tx and has_tx:
    combined_orders += transactions_to_orders(tx_df)
if use_tx and holdings_snapshot is not None and not holdings_snapshot.empty:
    combined_orders += manual_to_orders(holdings_snapshot)

# 종목명 매핑
combined_name_map = dict(toss_name_map)
if has_manual:
    for _, r in manual_df.iterrows():
        combined_name_map.setdefault(str(r.get("티커")), r.get("종목명"))
traded_tickers = {o.get("symbol") for o in combined_orders if o.get("symbol")}
unknown = tuple(sorted(t for t in traded_tickers if t not in combined_name_map))
if unknown and use_toss:
    combined_name_map.update(fetch_stock_names(unknown))

detail_df = build_transaction_detail(combined_orders, fx_rate, combined_name_map)

# 종목별 청산 여부
net_qty = {}
for _o in combined_orders:
    _ex = _o.get("execution") or {}
    _q = float(_ex.get("filledQuantity") or 0)
    if _q == 0:
        continue
    _sym = _o.get("symbol")
    net_qty[_sym] = net_qty.get(_sym, 0) + (_q if _o.get("side") == "BUY" else -_q)
status_map = {s: ("청산" if abs(v) < 1e-6 else "보유중") for s, v in net_qty.items()}
if detail_df is not None and not detail_df.empty:
    detail_df["상태"] = detail_df["티커"].map(lambda t: status_map.get(t, "보유중"))

summary = portfolio_json.get("asset_summary", {})
holdings = portfolio_json.get("holdings", [])
has_data = bool(combined_orders) or bool(holdings)

# 배당: 검증(임포트/직접입력) 우선 + yfinance 추정(미입력 종목 보완, 토글)
# 신뢰성 낮은 배당(합성 고배당 ETF·데이터 오류)은 추정에서 제외하고 직접 입력을 유도
UNRELIABLE_DIV_YIELD = 0.6  # 연환산 추정 배당수익률 60% 초과 → 신뢰 불가
UNRELIABLE_DIV_TICKERS = {
    "MSTY", "TSLY", "NVDY", "CONY", "APLY", "AMZY", "MSFO", "GOOY", "FBY",
    "YMAX", "YMAG", "ULTY", "AMDY", "PLTY", "MRNY", "SNOY", "OARK", "JEPY",
}
st.session_state.setdefault("include_div_est", True)
include_div_est = st.session_state["include_div_est"]
div_records = fetch_dividends(_USER) if use_tx else pd.DataFrame()
div_krw_by_ticker = {}
div_krw_native = div_usd_native = 0.0
_div_view_rows = []
verified_tickers = set()
unreliable_div_tickers = []
if div_records is not None and not div_records.empty:
    for _, r in div_records.iterrows():
        amt = float(r.get("배당금", 0) or 0)
        if amt <= 0:
            continue
        tk = str(r.get("티커"))
        is_usd = str(r.get("통화", "KRW")).upper() == "USD"
        krw = amt * fx_rate if is_usd else amt
        verified_tickers.add(tk)
        div_krw_by_ticker[tk] = div_krw_by_ticker.get(tk, 0.0) + krw
        if is_usd:
            div_usd_native += amt
        else:
            div_krw_native += amt
        _div_view_rows.append({"일자": str(r.get("일자", "")), "종목": r.get("종목명") or tk, "티커": tk,
                               "통화": "USD" if is_usd else "KRW", "배당금": amt, "원화환산": krw, "구분": "검증"})
if include_div_est and has_data:
    _est = fetch_div_estimate(combined_orders, fx_rate)
    if _est is not None and not _est.empty:
        # 종목별 매수원금(native)·최초 매수일 → 추정 배당의 연환산 수익률로 신뢰성 판단
        _buy_native = {}
        _first_date = {}
        for _o in combined_orders:
            if _o.get("side") != "BUY":
                continue
            _ex = _o.get("execution") or {}
            _amt = float(_ex.get("filledAmount") or 0)
            if _amt <= 0:
                continue
            _tk = str(_o.get("symbol"))
            _buy_native[_tk] = _buy_native.get(_tk, 0.0) + _amt
            try:
                _d = pd.to_datetime(_ex.get("filledAt") or _o.get("orderedAt")).tz_localize(None)
                if _tk not in _first_date or _d < _first_date[_tk]:
                    _first_date[_tk] = _d
            except Exception:
                pass
        _now = pd.Timestamp.now().normalize()
        for _, r in _est.iterrows():
            tk = str(r.get("종목"))  # compute_dividends는 종목=티커(symbol)
            if tk in verified_tickers:  # 검증값이 있으면 추정 무시
                continue
            amt = float(r.get("배당수령(원본)", 0) or 0)
            if amt <= 0:
                continue
            # 신뢰성: 연환산 추정 배당수익률(추정배당÷매수원금÷보유연수)이 과도하면 제외
            _inv = _buy_native.get(tk, 0.0)
            _yrs = max((_now - _first_date.get(tk, _now)).days / 365.0, 0.1)
            _yld = (amt / _inv / _yrs) if _inv else 0.0
            if tk.upper() in UNRELIABLE_DIV_TICKERS or _yld > UNRELIABLE_DIV_YIELD:
                unreliable_div_tickers.append(tk)  # 추정 제외 → 직접 입력 안내
                continue
            is_usd = str(r.get("통화", "KRW")).upper() == "USD"
            krw = float(r.get("배당수령(원)", 0) or 0)
            div_krw_by_ticker[tk] = div_krw_by_ticker.get(tk, 0.0) + krw
            if is_usd:
                div_usd_native += amt
            else:
                div_krw_native += amt
            _div_view_rows.append({"일자": "", "종목": combined_name_map.get(tk, tk), "티커": tk,
                                   "통화": "USD" if is_usd else "KRW", "배당금": amt, "원화환산": krw,
                                   "구분": f"추정({int(r.get('배당횟수', 0))}회)"})
div_view_df = pd.DataFrame(_div_view_rows)
div_items = tuple(sorted(div_krw_by_ticker.items()))

# 공통 분석값(캐시) — 개요·성과·AI 컨텍스트 공유
perf = fetch_performance_summary(combined_orders, fx_rate, div_krw_native, div_usd_native) if has_data else None
ab = fetch_alpha_beta(combined_orders, fx_rate) if has_data else None


# ════════════════════════════════════════════════════════════════
# 3) 사이드바 (계정 · 데이터 소스 · 임포트 · 설정)
# ════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(f"### 👤 {_USER}")
    _uinfo = get_user_info(_USER)
    if _uinfo.get("created_at"):
        st.caption(f"가입일 · {_uinfo['created_at'][:10]}")
    st.caption(f"데이터 소스 · **{SOURCE_LABELS.get(source, source)}**")
    if st.button("🔄 데이터 소스 변경", use_container_width=True):
        st.session_state.data_source = None
        st.rerun()
    with st.expander("🔑 API 키 설정", expanded=False):
        _side_creds = _credentials_form("side")
        if st.button("💾 API 키 저장", type="primary", use_container_width=True, key="save_creds_side"):
            n = save_credentials(_USER, _side_creds)
            _apply_user_credentials()
            st.cache_data.clear()
            st.success(f"API 키 {n}개를 저장했습니다.")
            st.rerun()
        _c = load_credentials(_USER)
        _toss_ok = "✅ 설정됨" if (_c.get("TOSS_CLIENT_ID") and _c.get("TOSS_CLIENT_SECRET")) else "⚠️ 미설정"
        st.caption(f"토스 API {_toss_ok} · Gemini ✅ 기본 키 내장")
    st.divider()
    if use_tx:
        with st.expander("📥 거래내역 임포트/추가", expanded=not has_data):
            render_import_ui("side")
        _saved_tx = read_transactions_csv()
        _saved_hold = read_manual_csv()
        _saved_div = read_dividends_csv()
        st.caption(f"저장됨 · 거래내역 {len(_saved_tx)}건 · 잔고 {len(_saved_hold)}종목 · 배당 {len(_saved_div)}건")
        if st.button("🗑️ 저장된 임포트 삭제", use_container_width=True):
            clear_all_imports()
            st.cache_data.clear()
            st.rerun()
    st.divider()
    st.checkbox("yfinance 배당 추정 포함", key="include_div_est",
                help="직접 입력·임포트한 배당이 없는 종목만 '보유수량 타임라인 × yfinance 주당배당'으로 추정합니다. 검증값(임포트/직접입력)이 있으면 그 종목은 검증값이 우선입니다. (MSTY 등 부정확 종목은 직접 입력 권장)")
    st.divider()
    if st.button("로그아웃", use_container_width=True):
        destroy_session(st.query_params.get("sid"))
        st.query_params.clear()
        for k in ("username", "data_source", "chat_messages"):
            st.session_state.pop(k, None)
        st.cache_data.clear()
        st.rerun()


# ════════════════════════════════════════════════════════════════
# 4) 본문 + 우측 AI 패널 레이아웃
# ════════════════════════════════════════════════════════════════
main_col, ai_col = st.columns([2.75, 1.5], gap="large")

with main_col:
    st.markdown("## 📈 자산관리 대시보드")
    if not has_data:
        st.info("표시할 데이터가 없습니다. "
                + ("왼쪽 사이드바의 **거래내역 임포트**로 데이터를 추가하세요." if use_tx
                   else "토스증권 계좌에 거래·보유 내역이 없습니다."))
        st.stop()

    # ── 중앙 네비게이션 (버튼) ──
    NAV = ["개요", "보유 종목", "거래 내역", "성과 분석", "환율", "AI 진단"]
    ncols = st.columns(len(NAV))
    for i, name in enumerate(NAV):
        active = st.session_state.view == name
        if ncols[i].button(name, key=f"nav_{name}", use_container_width=True,
                           type="primary" if active else "secondary"):
            st.session_state.view = name
            st.rerun()
    view = st.session_state.view
    st.divider()

    # ─────────────────────────── 개요 ───────────────────────────
    if view == "개요":
        st.subheader("자산 및 성과 요약")
        _krw_cash = float(summary.get("cash_krw_native", 0) or 0)
        _usd_cash = float(summary.get("cash_usd_native", 0) or 0)
        _cash_fx = float(summary.get("fx_rate", fx_rate) or fx_rate or 0)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총자산", f"{summary.get('total_asset_krw', 0):,.0f} ₩")
        m2.metric("주식 평가액", f"{summary.get('stock_eval_krw', 0):,.0f} ₩")
        m3.metric("예수금 (원화)", f"{_krw_cash:,.0f} ₩")
        m4.metric("예수금 (달러)", f"$ {_usd_cash:,.2f}",
                  delta=f"≈ {_usd_cash * _cash_fx:,.0f} ₩" if _cash_fx else None, delta_color="off")

        p1, p2, p3 = st.columns(3)
        _port_xirr = ab.get("port_xirr_pct") if ab else None
        _alpha = ab.get("alpha_pct") if ab else None
        _beta = ab.get("beta") if ab else None
        p1.metric("연환산 수익률 (XIRR)", f"{_port_xirr:+.2f} %" if _port_xirr is not None else "N/A")
        p2.metric("S&P500 초과수익 (알파)", f"{_alpha:+.2f} %p" if _alpha is not None else "N/A",
                  delta="벤치마크 상회" if (_alpha or 0) >= 0 else "벤치마크 하회",
                  delta_color="normal" if (_alpha or 0) >= 0 else "inverse")
        p3.metric("시장 민감도 (베타)", f"{_beta}" if _beta is not None else "N/A")

        st.divider()
        st.markdown("#### 손익 구성")
        if perf:
            ccy = st.radio("표시 기준", ["원화 (환차 포함)", "달러 (환율 제외·순수 주가)"],
                           horizontal=True, key="ov_ccy")
            use_usd = ccy.startswith("달러")
            g1, g2, g3 = st.columns(3)
            g1.metric("누적 총손익", f"{perf['all_inclusive_krw']:,.0f} ₩",
                      delta=f"{perf['all_inclusive_pct']:+.2f}% (투입원금 대비)",
                      delta_color="normal" if perf["all_inclusive_krw"] >= 0 else "inverse")
            if use_usd:
                g2.metric("보유 평가손익 (달러)", f"$ {perf['unreal_native_usd']:,.2f}",
                          delta=f"{perf['unreal_native_usd_pct']:+.2f}%",
                          delta_color="normal" if perf["unreal_native_usd"] >= 0 else "inverse")
            else:
                g2.metric("보유 평가손익 (원화)", f"{perf['unreal_total_krw']:,.0f} ₩",
                          delta=f"{perf['unreal_total_pct']:+.2f}%",
                          delta_color="normal" if perf["unreal_total_krw"] >= 0 else "inverse")
            g3.metric("실현손익 (매도 확정)", f"{perf['realized_total_krw']:,.0f} ₩",
                      delta_color="normal" if perf["realized_total_krw"] >= 0 else "inverse")
            h1, h2, h3 = st.columns(3)
            h1.metric("순수 주가 손익", f"{perf['pure_price_krw']:,.0f} ₩")
            _dkn = float(perf.get("div_krw_native", 0) or 0)
            _dun = float(perf.get("div_usd_native", 0) or 0)
            h2.metric("배당 수익 (추정·합산)", f"{perf['div_krw']:,.0f} ₩",
                      delta=f"원화 {_dkn:,.0f}원 + 달러 ${_dun:,.2f}", delta_color="off")
            h3.metric("환차손익", f"{perf['fx_total_krw']:,.0f} ₩",
                      delta="환율 이익" if perf["fx_total_krw"] >= 0 else "환율 손실",
                      delta_color="normal" if perf["fx_total_krw"] >= 0 else "inverse")
            if _dun > 0 or _dkn > 0:
                st.caption(f"배당 내역: 원화 {_dkn:,.0f}원 + 달러 ${_dun:,.2f}"
                           f"(현재 환율 ≈ {_dun * _cash_fx:,.0f}원) → 현재 환율 기준 합산 {perf['div_krw']:,.0f}원.")
            st.caption("누적 총손익 = 순수 주가손익 + 환차손익 + 배당. 배당·환차손익은 시세 데이터 기반 추정치입니다.")
        else:
            st.info("손익을 계산할 거래 이력이 없습니다.")

        st.divider()
        st.markdown("#### 보유 비중")
        if holdings:
            df = pd.DataFrame(holdings)
            for c in ("quantity", "eval_krw", "weight_pct", "return_pct"):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            r1, r2 = st.columns([1, 1])
            with r1:
                fig = px.pie(df, values="weight_pct", names="name", hole=0.45)
                fig.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig, use_container_width=True)
            with r2:
                show = df.rename(columns={"name": "종목명", "weight_pct": "비중(%)",
                                          "eval_krw": "평가액(원)", "return_pct": "수익률(%)"})
                cols = [c for c in ["종목명", "비중(%)", "평가액(원)", "수익률(%)"] if c in show.columns]
                st.dataframe(show[cols].style.format({"비중(%)": "{:.2f}", "평가액(원)": "{:,.0f}",
                                                      "수익률(%)": "{:+.2f}"}),
                             use_container_width=True, hide_index=True, height=360)
        else:
            st.info("보유 종목이 없습니다.")

    # ─────────────────────────── 보유 종목 ───────────────────────────
    elif view == "보유 종목":
        st.subheader("종목별 실현·평가 성과")
        st.caption("분할매도를 반영한 평균단가 회계 기준입니다. 청산 종목은 매도 시점 실현가, 보유 종목은 잔여수량 평가 기준으로 계산합니다.")
        with st.spinner("종목별 성과를 계산하는 중입니다..."):
            brk_tbl = fetch_holdings_breakdown(combined_orders, fx_rate, combined_name_map, div_items)
        if brk_tbl is not None and not brk_tbl.empty:
            f1, f2 = st.columns(2)
            with f1:
                sel_st = st.multiselect("보유 상태", ["보유중", "청산"], key="hb_status")
            with f2:
                sel_tk = st.multiselect("종목", sorted(brk_tbl["티커"].unique()), key="hb_tk")
            tv = brk_tbl
            if sel_st:
                tv = tv[tv["상태"].isin(sel_st)]
            if sel_tk:
                tv = tv[tv["티커"].isin(sel_tk)]
            show = ["종목", "티커", "통화", "상태", "보유수량", "평단가(달러)", "평단가(원화)",
                    "투자원금(원)", "매도실현금액(원)", "실현손익(원)", "평가손익(원)", "누적배당금(원)", "수익률(%)"]
            show = [c for c in show if c in tv.columns]
            st.dataframe(
                tv[show].style.format({
                    "보유수량": "{:g}", "평단가(달러)": "{:,.2f}", "평단가(원화)": "{:,.2f}",
                    "투자원금(원)": "{:,.0f}", "매도실현금액(원)": "{:,.0f}",
                    "실현손익(원)": "{:,.0f}", "평가손익(원)": "{:,.0f}",
                    "누적배당금(원)": "{:,.0f}", "수익률(%)": "{:+.2f}",
                }, na_rep="-").background_gradient(cmap="RdYlGn", subset=["수익률(%)"]),
                use_container_width=True, hide_index=True, height=460,
            )
            _rp = float(brk_tbl["실현손익(원)"].sum())
            _up = float(brk_tbl["평가손익(원)"].sum())
            _inv = float(brk_tbl["투자원금(원)"].sum())
            t1, t2, t3 = st.columns(3)
            t1.metric("실현손익 합계", f"{_rp:,.0f} ₩", delta_color="normal" if _rp >= 0 else "inverse")
            t2.metric("평가손익 합계", f"{_up:,.0f} ₩", delta_color="normal" if _up >= 0 else "inverse")
            t3.metric("총손익 합계", f"{_rp + _up:,.0f} ₩",
                      delta=f"{(_rp + _up) / _inv * 100:+.2f}% (투자원금 대비)" if _inv else None,
                      delta_color="normal" if (_rp + _up) >= 0 else "inverse")
            st.caption("수익률(%) = (실현손익 + 평가손익) ÷ 투자원금. 평단가는 전체 매수의 수량가중 평균가입니다.")
        else:
            st.info("종목별 성과를 계산할 거래 이력이 없습니다.")

    # ─────────────────────────── 거래 내역 ───────────────────────────
    elif view == "거래 내역":
        st.subheader("체결 내역")
        st.caption("전체 체결 내역을 시간 오름차순으로 정리했습니다.")
        if detail_df is not None and not detail_df.empty:
            asc = detail_df.sort_values("체결일시", ascending=True).reset_index(drop=True)
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                bopt = sorted(asc["증권사"].unique()) if "증권사" in asc.columns else []
                sb = st.multiselect("증권사", bopt, key="tx_broker")
            with f2:
                ss = st.multiselect("구분", ["매수", "매도"], key="tx_side")
            with f3:
                stk = st.multiselect("종목", sorted(asc["티커"].unique()), key="tx_ticker")
            with f4:
                sopt = sorted(asc["상태"].unique()) if "상태" in asc.columns else []
                sstat = st.multiselect("상태", sopt, key="tx_status")
            v = asc.copy()
            if sb and "증권사" in v.columns:
                v = v[v["증권사"].isin(sb)]
            if ss:
                v = v[v["구분"].isin(ss)]
            if stk:
                v = v[v["티커"].isin(stk)]
            if sstat and "상태" in v.columns:
                v = v[v["상태"].isin(sstat)]
            cols = ["날짜", "증권사", "종목명", "티커", "상태", "구분", "수량",
                    "체결단가", "통화", "체결금액(원본)", "체결금액(원)", "수수료", "세금"]
            cols = [c for c in cols if c in v.columns]
            st.dataframe(
                v[cols].style.format({
                    "체결단가": "{:,.2f}", "체결금액(원본)": "{:,.2f}", "체결금액(원)": "{:,.0f}",
                    "수수료": "{:,.2f}", "세금": "{:,.2f}", "수량": "{:g}",
                }),
                use_container_width=True, hide_index=True, height=520,
            )
            st.caption(f"총 {len(v)}건 · {asc['날짜'].iloc[0]} ~ {asc['날짜'].iloc[-1]} · 적용 환율 1 USD = {fx_rate:,.1f} KRW")
        else:
            st.info("거래 내역이 없습니다.")

        # 배당 내역 (검증 우선 + yfinance 추정 보완)
        st.divider()
        st.subheader("배당 내역")
        st.caption("**검증** = 임포트/직접입력한 실수령액 · **추정** = 보유수량 타임라인 × yfinance 주당배당(부정확할 수 있음). "
                   "사이드바에서 추정 포함 여부를 켜고 끌 수 있으며, 검증값이 있는 종목은 추정보다 우선합니다.")
        if unreliable_div_tickers:
            _uniq = sorted(set(unreliable_div_tickers))
            _names = ", ".join(f"{combined_name_map.get(t, t)}({t})" for t in _uniq)
            st.warning(
                f"⚠️ 다음 종목은 배당 데이터 신뢰성이 낮아 **추정에서 제외**했습니다 — 아래 편집기에서 **직접 입력**하세요: {_names}\n\n"
                "(MSTY 등 합성 고배당 ETF는 yfinance 주당배당이 실제와 크게 달라 자동 추정을 신뢰할 수 없습니다.)"
            )
        if div_view_df is not None and not div_view_df.empty:
            dv = div_view_df.copy().sort_values(["구분", "일자"], ascending=[True, True])
            st.dataframe(
                dv[["일자", "구분", "종목", "티커", "통화", "배당금", "원화환산"]].style.format(
                    {"배당금": "{:,.2f}", "원화환산": "{:,.0f}"}),
                use_container_width=True, hide_index=True, height=300,
            )
            d1, d2, d3 = st.columns(3)
            d1.metric("원화 배당 합계", f"{div_krw_native:,.0f} ₩")
            d2.metric("달러 배당 합계", f"$ {div_usd_native:,.2f}")
            d3.metric("현재 환율 합산", f"{div_krw_native + div_usd_native * fx_rate:,.0f} ₩")
        else:
            st.info("배당 기록이 없습니다. 전체 거래내역을 임포트하면 배당이 자동 추출되고, 사이드바의 'yfinance 배당 추정 포함'을 켜면 추정치가 채워집니다. 아래 '배당 내역' 탭에서 직접 입력할 수도 있습니다.")

        if use_tx:
            with st.expander("✏️ 거래내역/잔고/배당 직접 수정"):
                tab_tx, tab_hold, tab_div = st.tabs(["거래내역", "잔고 스냅샷", "배당 내역"])
                with tab_tx:
                    raw_tx = read_transactions_csv()
                    edited_tx = st.data_editor(
                        raw_tx, num_rows="dynamic", use_container_width=True, hide_index=True,
                        column_config={
                            "시장": st.column_config.SelectboxColumn("시장", options=["KOSPI", "KOSDAQ", "US"]),
                            "구분": st.column_config.SelectboxColumn("구분", options=["매수", "매도"]),
                            "통화": st.column_config.SelectboxColumn("통화", options=["KRW", "USD"]),
                            "수량": st.column_config.NumberColumn("수량", format="%g"),
                            "단가": st.column_config.NumberColumn("단가", format="%.2f"),
                        },
                        key="tx_editor",
                    )
                    if st.button("💾 거래내역 저장", type="primary", key="save_tx"):
                        n = write_transactions_csv(edited_tx)
                        st.cache_data.clear()
                        st.success(f"{n}건 저장했습니다.")
                        st.rerun()
                with tab_hold:
                    raw_manual = read_manual_csv()
                    edited = st.data_editor(
                        raw_manual, num_rows="dynamic", use_container_width=True, hide_index=True,
                        column_config={
                            "시장": st.column_config.SelectboxColumn("시장", options=["KOSPI", "KOSDAQ", "US"]),
                            "통화": st.column_config.SelectboxColumn("통화", options=["KRW", "USD"]),
                            "수량": st.column_config.NumberColumn("수량", format="%g"),
                            "평균매수가": st.column_config.NumberColumn("평균매수가", format="%.2f"),
                        },
                        key="manual_editor",
                    )
                    if st.button("💾 잔고 저장", type="primary", key="save_hold"):
                        n = write_manual_csv(edited)
                        st.cache_data.clear()
                        st.success(f"{n}종목 저장했습니다.")
                        st.rerun()
                with tab_div:
                    st.caption("MSTY 등 배당이 이상하면 여기서 직접 실수령액을 입력·수정하세요. (통화 단위 그대로) "
                               "신뢰성 낮은 종목은 빈 행으로 미리 추가해 두었습니다.")
                    raw_div = read_dividends_csv()
                    # 신뢰성 낮아 추정 제외된 종목을 입력 편의를 위해 빈 행으로 시드
                    _present = set(raw_div["티커"].astype(str)) if not raw_div.empty else set()
                    _seed = [{"증권사": "직접입력", "일자": "", "티커": t, "종목명": combined_name_map.get(t, t),
                              "통화": "KRW" if str(t).isdigit() else "USD", "배당금": 0.0}
                             for t in sorted(set(unreliable_div_tickers)) if t not in _present]
                    if _seed:
                        raw_div = pd.concat([raw_div, pd.DataFrame(_seed)], ignore_index=True)
                    edited_div = st.data_editor(
                        raw_div, num_rows="dynamic", use_container_width=True, hide_index=True,
                        column_config={
                            "통화": st.column_config.SelectboxColumn("통화", options=["KRW", "USD"]),
                            "배당금": st.column_config.NumberColumn("배당금", format="%.2f"),
                        },
                        key="div_editor",
                    )
                    if st.button("💾 배당 저장", type="primary", key="save_div"):
                        n = write_dividends_csv(edited_div)
                        st.cache_data.clear()
                        st.success(f"{n}건 저장했습니다.")
                        st.rerun()

    # ─────────────────────────── 성과 분석 ───────────────────────────
    elif view == "성과 분석":
        st.subheader("수익금 성장 추이 및 벤치마크 비교")
        st.caption("투자원금을 제외한 순수 수익금의 성장을 S&P500(SPY)에 동일 현금흐름으로 투자했을 때와 비교합니다. "
                   "미국 주식은 환율 효과를 제거해 **달러 기준**으로 표시합니다. 그래프의 점을 클릭하면 해당일 알파(초과 %p)가 표시되고, "
                   "**하단 막대는 매수(초록)·매도(빨강) 수량**입니다.")
        ALL_LABEL = "전체 자산 (합산)"
        brk_tbl = fetch_holdings_breakdown(combined_orders, fx_rate, combined_name_map, div_items)
        tickers_opt = sorted(brk_tbl["티커"].unique()) if (brk_tbl is not None and not brk_tbl.empty) else []
        options = [ALL_LABEL] + tickers_opt
        sel_growth = st.selectbox("분석 대상", options, index=0,
                                  format_func=lambda t: t if t == ALL_LABEL else f"{combined_name_map.get(t, t)} ({t})",
                                  key="growth_target")
        is_all = sel_growth == ALL_LABEL
        # 개별 미국 종목이면 달러 기준(환율 제거)
        sel_ccy = None
        if not is_all and brk_tbl is not None and not brk_tbl.empty:
            _r = brk_tbl[brk_tbl["티커"] == sel_growth]
            if not _r.empty:
                sel_ccy = str(_r.iloc[0]["통화"]).upper()
        use_native = (not is_all) and sel_ccy == "USD"
        unit = "$" if use_native else "₩"
        mfmt = "%{y:,.2f}" if use_native else "%{y:,.0f}"
        pyfmt = (lambda x: f"${x:,.2f}") if use_native else (lambda x: f"{x:,.0f}원")

        with st.spinner("성장 추이를 계산하는 중입니다..."):
            gdf = (fetch_total_profit_growth(combined_orders, fx_rate) if is_all
                   else fetch_ticker_profit_growth(combined_orders, fx_rate, sel_growth, use_native))
        if gdf is not None and not gdf.empty:
            gidx = gdf.index
            growth_key = f"growth_chart_{'ALL' if is_all else sel_growth}"
            _prev = st.session_state.get(growth_key)
            _pts = []
            try:
                _pts = _prev.selection["points"]
            except Exception:
                try:
                    _pts = _prev["selection"]["points"]
                except Exception:
                    _pts = []
            click_info = None
            if _pts:
                try:
                    cdate = pd.to_datetime(_pts[-1]["x"]).normalize()
                    pos = gidx.get_indexer([cdate], method="nearest")[0]
                    row = gdf.iloc[pos]
                    inv = float(row.get("투자원금", 0) or 0)
                    myp = float(row["내 수익금"]); spyp = float(row["S&P500 수익금"])
                    if inv:
                        click_info = {"date": gidx[pos], "inv": inv, "myp": myp, "spyp": spyp,
                                      "my_r": myp / inv * 100, "spy_r": spyp / inv * 100,
                                      "alpha": (myp - spyp) / inv * 100}
                except Exception:
                    click_info = None

            # 개별 종목이면 주가·체결 데이터 확보 (마커 + 매수량 막대에 재사용)
            price_hist = buys_df = sells_df = None
            punit = "₩"
            if not is_all:
                price_hist, buys_df, sells_df, ccy = fetch_ticker_price_trades(combined_orders, sel_growth, gidx.min())
                punit = "$" if ccy == "USD" else "₩"

            fig_g = make_subplots(
                rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
                vertical_spacing=0.06, specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
            )
            fig_g.add_trace(go.Scatter(x=gidx, y=gdf["내 수익금"], name="내 수익금",
                                       mode="lines+markers", marker=dict(size=5, color="#EF553B"),
                                       line=dict(color="#EF553B", width=2.4),
                                       hovertemplate="%{x|%Y-%m-%d}<br>내 수익금 " + mfmt + unit + "<extra></extra>"),
                            row=1, col=1, secondary_y=False)
            fig_g.add_trace(go.Scatter(x=gidx, y=gdf["S&P500 수익금"], name="S&P500 수익금",
                                       mode="lines", line=dict(color="#636EFA", dash="dash", width=2),
                                       hovertemplate="%{x|%Y-%m-%d}<br>S&P500 " + mfmt + unit + "<extra></extra>"),
                            row=1, col=1, secondary_y=False)
            fig_g.add_hline(y=0, line_dash="dot", line_color="gray", row=1, col=1)

            # 최대 알파 지점 표시
            _invs = gdf["투자원금"].where(gdf["투자원금"] > 0)
            _alpha_s = (gdf["내 수익금"] - gdf["S&P500 수익금"]) / _invs * 100
            if _alpha_s.notna().any():
                _amax_date = _alpha_s.idxmax()
                _amax_val = float(_alpha_s.max())
                fig_g.add_trace(go.Scatter(
                    x=[_amax_date], y=[float(gdf.loc[_amax_date, "내 수익금"])], name="최대 알파",
                    mode="markers", marker=dict(symbol="star", size=16, color="#F59E0B", line=dict(width=1, color="#7C4A03")),
                    hovertemplate=f"최대 알파 {_amax_val:+.2f}%p<br>%{{x|%Y-%m-%d}}<extra></extra>"),
                    row=1, col=1, secondary_y=False)
                fig_g.add_annotation(x=_amax_date, y=float(gdf.loc[_amax_date, "내 수익금"]),
                                     text=f"⭐ 최대 알파 {_amax_val:+.1f}%p", showarrow=True, arrowhead=2,
                                     arrowcolor="#F59E0B", bgcolor="rgba(255,251,235,0.95)",
                                     bordercolor="#F59E0B", borderwidth=1, font=dict(size=11, color="#7C4A03"),
                                     yshift=18, row=1, col=1)

            # 개별 종목: 주가(얇은 선) + 매수/매도(마커)
            if not is_all:
                if price_hist is not None and not price_hist.empty:
                    fig_g.add_trace(go.Scatter(x=price_hist.index, y=price_hist.values, name=f"주가({punit})",
                                               mode="lines", line=dict(color="#94A3B8", width=1, dash="solid"),
                                               opacity=0.7,
                                               hovertemplate="%{x|%Y-%m-%d}<br>주가 %{y:,.2f}" + punit + "<extra></extra>"),
                                    row=1, col=1, secondary_y=True)
                if buys_df is not None and not buys_df.empty:
                    fig_g.add_trace(go.Scatter(x=buys_df["date"], y=buys_df["price"], name="🔺 매수", mode="markers",
                                               marker=dict(symbol="triangle-up", size=15, color="#16A34A",
                                                           line=dict(width=2, color="#052E16")),
                                               hovertemplate="매수 %{x|%Y-%m-%d}<br>단가 %{y:,.2f}" + punit + "<extra></extra>"),
                                    row=1, col=1, secondary_y=True)
                if sells_df is not None and not sells_df.empty:
                    fig_g.add_trace(go.Scatter(x=sells_df["date"], y=sells_df["price"], name="🔻 매도", mode="markers",
                                               marker=dict(symbol="triangle-down", size=15, color="#DC2626",
                                                           line=dict(width=2, color="#450A0A")),
                                               hovertemplate="매도 %{x|%Y-%m-%d}<br>단가 %{y:,.2f}" + punit + "<extra></extra>"),
                                    row=1, col=1, secondary_y=True)
                fig_g.update_yaxes(title_text=f"주가 ({punit})", secondary_y=True, showgrid=False, row=1, col=1)

            # ── 하단(row2): 매수/매도 수량 막대 (볼륨 스타일) ──
            if is_all:
                _bar_buys, _bar_sells = build_trade_bars(combined_orders, None)
                _bhover = "매수 %{x|%Y-%m-%d}<br>%{customdata} · 수량 %{y:g}<extra></extra>"
                _shover = "매도 %{x|%Y-%m-%d}<br>%{customdata} · 수량 %{y:g}<extra></extra>"
            else:
                _bar_buys, _bar_sells = buys_df, sells_df
                _bhover = "매수 %{x|%Y-%m-%d}<br>수량 %{y:g}<extra></extra>"
                _shover = "매도 %{x|%Y-%m-%d}<br>수량 %{y:g}<extra></extra>"
            _span_days = max((pd.Timestamp(gidx.max()) - pd.Timestamp(gidx.min())).days, 1)
            _bar_w = max(_span_days / 130.0, 1.0) * 86400000  # 막대 폭(ms): 기간의 약 1/130
            if _bar_buys is not None and not _bar_buys.empty and "qty" in _bar_buys.columns:
                fig_g.add_trace(go.Bar(x=_bar_buys["date"], y=_bar_buys["qty"], name="매수 수량",
                                       marker_color="#16A34A", opacity=0.85, width=_bar_w,
                                       customdata=(_bar_buys["symbol"] if "symbol" in _bar_buys.columns else None),
                                       hovertemplate=_bhover), row=2, col=1)
            if _bar_sells is not None and not _bar_sells.empty and "qty" in _bar_sells.columns:
                fig_g.add_trace(go.Bar(x=_bar_sells["date"], y=_bar_sells["qty"], name="매도 수량",
                                       marker_color="#DC2626", opacity=0.6, width=_bar_w,
                                       customdata=(_bar_sells["symbol"] if "symbol" in _bar_sells.columns else None),
                                       hovertemplate=_shover), row=2, col=1)
            fig_g.update_yaxes(title_text="수량(주)", showgrid=False, rangemode="tozero", row=2, col=1)

            fig_g.update_yaxes(title_text=f"누적 수익금 ({unit})", secondary_y=False, row=1, col=1)
            fig_g.update_xaxes(title_text="날짜", row=2, col=1)
            fig_g.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                                barmode="overlay")
            if click_info:
                d = click_info["date"]
                fig_g.add_vline(x=d, line_dash="dot", line_color="#888888", row=1, col=1)
                fig_g.add_annotation(x=d, y=click_info["myp"],
                                     text=(f"<b>{d.strftime('%Y-%m-%d')}</b><br>알파 {click_info['alpha']:+.2f}%p<br>"
                                           f"내 {click_info['my_r']:+.2f}% / S&P {click_info['spy_r']:+.2f}%"),
                                     showarrow=True, arrowhead=2, arrowcolor="#888888",
                                     bgcolor="rgba(255,255,255,0.9)", bordercolor="#888888", borderwidth=1,
                                     font=dict(size=12, color="#111111"), align="left", row=1, col=1)
            st.plotly_chart(fig_g, use_container_width=True, on_select="rerun", key=growth_key)
            if click_info:
                st.success(f"🗓️ {click_info['date'].strftime('%Y-%m-%d')} · 알파 {click_info['alpha']:+.2f}%p · "
                           f"내 {click_info['my_r']:+.2f}% / S&P500 {click_info['spy_r']:+.2f}%")
            my_p = gdf["내 수익금"].iloc[-1]
            spy_p = gdf["S&P500 수익금"].iloc[-1]
            label = "전체 자산" if is_all else combined_name_map.get(sel_growth, sel_growth)
            st.caption(f"{label} 현재 순수익금 {pyfmt(my_p)} vs 동일 현금흐름 S&P500 {pyfmt(spy_p)} → 차이 {pyfmt(my_p - spy_p)}"
                       + (" · 달러 기준(환율 제외)" if use_native else ""))

            # 베타의 변화 (롤링 베타)
            st.markdown("#### 베타의 변화 (60일 롤링 베타)")
            with st.spinner("롤링 베타를 계산하는 중입니다..."):
                rbeta = fetch_rolling_beta(combined_orders, fx_rate, None if is_all else sel_growth)
            if rbeta is not None and not rbeta.empty:
                fig_b = go.Figure()
                fig_b.add_trace(go.Scatter(x=rbeta.index, y=rbeta.values, name="롤링 베타",
                                           mode="lines", line=dict(color="#8B5CF6", width=2),
                                           hovertemplate="%{x|%Y-%m-%d}<br>베타 %{y:.2f}<extra></extra>"))
                fig_b.add_hline(y=1.0, line_dash="dot", line_color="gray", annotation_text="시장 = 1.0")
                fig_b.update_layout(height=240, yaxis_title="베타", xaxis_title="날짜", showlegend=False,
                                    margin=dict(t=10, b=10))
                st.plotly_chart(fig_b, use_container_width=True)
                st.caption(f"현재 베타 **{rbeta.iloc[-1]:.2f}** · 기간 범위 {rbeta.min():.2f} ~ {rbeta.max():.2f}. "
                           "1보다 크면 시장보다 민감(공격적), 작으면 방어적입니다. (60거래일 이동 회귀)")
            else:
                st.caption("롤링 베타를 계산하기엔 데이터가 부족합니다. (최소 60거래일 필요)")
        else:
            st.info("성장 추이 데이터를 계산하지 못했습니다.")

        st.divider()
        st.markdown("#### 벤치마크 대비 위험·수익 지표 (XIRR 기준)")
        if ab:
            a1, a2, a3 = st.columns(3)
            a1.metric("내 포트폴리오 XIRR", f"{ab['port_xirr_pct']} %" if ab["port_xirr_pct"] is not None else "N/A")
            a2.metric("S&P500 XIRR (동일 현금흐름)", f"{ab['spy_xirr_pct']} %" if ab["spy_xirr_pct"] is not None else "N/A")
            _alpha = ab["alpha_pct"]
            a3.metric("알파 (초과 XIRR)", f"{_alpha:+.2f} %p" if _alpha is not None else "N/A",
                      delta="벤치마크 상회" if (_alpha or 0) >= 0 else "벤치마크 하회",
                      delta_color="normal" if (_alpha or 0) >= 0 else "inverse")
            b1, b2 = st.columns(2)
            b1.metric("베타 (시장 민감도)", f"{ab['beta']}" if ab["beta"] is not None else "N/A")
            b2.metric("상관계수", f"{ab['corr']}" if ab["corr"] is not None else "N/A")
            if ab["beta"] is not None:
                bdesc = ("시장보다 변동이 큼(공격적)" if ab["beta"] > 1.1 else
                         "시장과 유사한 변동" if abs(ab["beta"] - 1) <= 0.1 else "시장보다 방어적")
                st.caption(f"알파는 동일 현금흐름을 S&P500에 투자했을 때 대비 연환산 초과수익입니다. 베타 {ab['beta']} — {bdesc}. "
                           f"측정 {ab['n_days']}거래일.")
        else:
            st.info("지표를 계산할 거래 이력이 없습니다.")

    # ─────────────────────────── 환율 ───────────────────────────
    elif view == "환율":
        st.subheader("달러 평단가 및 환율 분석")
        st.caption("미국 주식 매수 시점의 환율을 매수금액으로 가중평균한 '달러 평단가'를 최근 10년 환율과 비교합니다.")
        with st.spinner("환율 데이터를 계산하는 중입니다..."):
            usd_cost = fetch_usd_avg_cost(combined_orders, fx_rate)
            fx_10y = fetch_fx_10y()
        if usd_cost:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("달러 평단가", f"{usd_cost['avg_fx']:,.1f} 원/$")
            c2.metric("현재 환율", f"{usd_cost['current_fx']:,.1f} 원/$")
            gap = usd_cost["current_fx"] - usd_cost["avg_fx"]
            c3.metric("현재 − 평단 차이", f"{gap:+,.1f} 원", delta=f"{gap / usd_cost['avg_fx'] * 100:+.2f}%")
            c4.metric("누적 환차손익", f"{usd_cost['fx_pnl_krw']:,.0f} ₩",
                      delta="환율 이익" if usd_cost["fx_pnl_krw"] >= 0 else "환율 손실",
                      delta_color="normal" if usd_cost["fx_pnl_krw"] >= 0 else "inverse")
            if fx_10y is not None and not fx_10y.empty:
                fxp = fx_10y.reset_index()
                xcol = fxp.columns[0]
                fig_fx = px.line(fxp, x=xcol, y="원/달러", labels={xcol: "날짜", "원/달러": "USD/KRW 환율"},
                                 title="최근 10년 USD/KRW 환율과 달러 평단가")
                fig_fx.add_hline(y=usd_cost["avg_fx"], line_dash="dash", line_color="#EF553B",
                                 annotation_text=f"달러 평단가 {usd_cost['avg_fx']:,.1f}원", annotation_position="top left")
                st.plotly_chart(fig_fx, use_container_width=True)
                st.caption(f"현재 환율이 평단가보다 위면 환차익, 아래면 환차손입니다. (총 매수원금 ${usd_cost['total_usd']:,.0f})")
            else:
                st.info("환율 데이터를 불러오지 못했습니다.")
        else:
            st.info("미국 주식 매수 내역이 없어 달러 평단가를 계산할 수 없습니다.")

    # ─────────────────────────── AI 진단 ───────────────────────────
    elif view == "AI 진단":
        st.subheader("AI 포트폴리오 진단 · 리밸런싱 (알파·베타 관점)")
        st.caption("현재 포트폴리오의 알파(초과수익)와 베타(시장 민감도)를 근거로 AI가 리밸런싱 방향을 제안하고, "
                   "검진 결과를 PDF로 내려받을 수 있습니다.")

        if ab:
            q1, q2, q3, q4 = st.columns(4)
            _px = ab.get("port_xirr_pct")
            q1.metric("연환산 수익률 (XIRR)", f"{_px:+.2f} %" if _px is not None else "N/A")
            _al = ab.get("alpha_pct")
            q2.metric("알파 (초과수익)", f"{_al:+.2f} %p" if _al is not None else "N/A",
                      delta="벤치마크 상회" if (_al or 0) >= 0 else "벤치마크 하회",
                      delta_color="normal" if (_al or 0) >= 0 else "inverse")
            _bt = ab.get("beta")
            q3.metric("베타 (시장 민감도)", f"{_bt}" if _bt is not None else "N/A",
                      delta=("공격적" if (_bt or 0) > 1.1 else "방어적" if (_bt or 1) < 0.9 else "시장과 유사"),
                      delta_color="off")
            q4.metric("상관계수", f"{ab.get('corr')}" if ab.get("corr") is not None else "N/A")
        else:
            st.info("알파/베타를 계산할 거래 이력이 없습니다. 자산 요약과 보유 종목은 PDF로 저장할 수 있습니다.")

        st.divider()
        if st.button("🤖 AI 진단 리포트 생성", type="primary", key="gen_rebal",
                     disabled=not has_data, use_container_width=True):
            with st.spinner("AI가 알파·베타 관점에서 포트폴리오를 진단하는 중입니다..."):
                st.session_state["rebal_report"] = generate_rebalancing_report(portfolio_json, ab, perf)
                st.session_state["rebal_report_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        rebal = st.session_state.get("rebal_report")
        if rebal:
            st.caption(f"생성 시각 · {st.session_state.get('rebal_report_at', '')}")
            with st.container(border=True):
                st.markdown(rebal)
            if st.button("🗑️ 진단 리포트 지우기", key="clear_rebal"):
                st.session_state.pop("rebal_report", None)
                st.session_state.pop("rebal_report_at", None)
                st.rerun()
        else:
            st.info("아직 생성된 진단 리포트가 없습니다. 위 버튼을 눌러 AI 진단을 생성하세요.")

        st.divider()
        st.markdown("#### 📄 검진 결과 PDF 내보내기")
        st.caption("자산 요약 · 알파/베타 지표 · 보유 종목" + (" · AI 진단 리포트" if rebal else "") + "을 PDF로 저장합니다.")
        try:
            pdf_bytes = build_portfolio_pdf(
                _USER, SOURCE_LABELS.get(source, source),
                summary=summary, perf=perf, ab=ab, holdings=holdings,
                ai_report=rebal, fx_rate=fx_rate,
            )
            fname = f"portfolio_report_{_USER}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
            st.download_button("📥 PDF 다운로드", data=pdf_bytes, file_name=fname,
                               mime="application/pdf", use_container_width=True, key="dl_pdf")
        except Exception as e:
            st.error(f"PDF 생성 중 오류가 발생했습니다: {e}")


# ── 우측 AI 패널 ──────────────────────────────────────────────
def _ai_context():
    lines = [f"[현재 화면] {st.session_state.view}"]
    lines.append(f"총자산 {summary.get('total_asset_krw', 0):,.0f}원, 주식평가액 {summary.get('stock_eval_krw', 0):,.0f}원, "
                 f"예수금 {float(summary.get('cash_krw_native', 0) or 0):,.0f}원 + ${float(summary.get('cash_usd_native', 0) or 0):,.0f}")
    if ab:
        lines.append(f"포트폴리오 XIRR {ab.get('port_xirr_pct')}%, S&P500 XIRR {ab.get('spy_xirr_pct')}%, "
                     f"알파 {ab.get('alpha_pct')}%p, 베타 {ab.get('beta')}, 상관계수 {ab.get('corr')}")
    if perf:
        lines.append(f"누적총손익 {perf.get('all_inclusive_krw'):,.0f}원(순수주가 {perf.get('pure_price_krw'):,.0f}, "
                     f"실현 {perf.get('realized_total_krw'):,.0f}, 배당 {perf.get('div_krw'):,.0f}, 환차 {perf.get('fx_total_krw'):,.0f})")
    top = ", ".join(f"{h.get('name')}({h.get('weight_pct')}%, {h.get('return_pct')}%)" for h in holdings[:10])
    if top:
        lines.append(f"보유: {top}")
    return "\n".join(lines)

with ai_col:
    with st.container(border=True):
        st.markdown("#### 🤖 AI 코파일럿")
        st.caption("현재 화면의 데이터를 참고해 답변합니다.")
        if "chat_messages" not in st.session_state:
            st.session_state.chat_messages = []
        # 빠른 질문
        quick = {
            "개요": "지금 내 포트폴리오의 강점과 위험은?",
            "보유 종목": "성과가 부진한 종목과 개선 방향은?",
            "거래 내역": "최근 매매 패턴에서 보이는 특징은?",
            "성과 분석": "S&P500 대비 알파와 베타를 해석해줘",
            "환율": "지금 환율 수준에서 달러 매수는 유리해?",
        }.get(st.session_state.view)
        prefill = ""
        if quick and st.button(f"💡 {quick}", use_container_width=True, key="ai_quick"):
            prefill = quick
        with st.container(height=460):
            for msg in st.session_state.chat_messages[-12:]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
        with st.form("ai_form", clear_on_submit=True):
            q = st.text_area("질문 또는 조언 요청", value=prefill, height=80,
                             label_visibility="collapsed", placeholder="예: 비중이 쏠린 종목이 있어?")
            sent = st.form_submit_button("전송", type="primary", use_container_width=True)
        cc1, cc2 = st.columns(2)
        if cc2.button("대화 지우기", use_container_width=True, key="ai_clear"):
            st.session_state.chat_messages = []
            st.rerun()
        if sent and q and q.strip():
            st.session_state.chat_messages.append({"role": "user", "content": q.strip()})
            with st.spinner("AI가 답변을 작성 중입니다..."):
                answer = chat_with_portfolio(q.strip(), st.session_state.chat_messages[:-1],
                                             portfolio_json, _ai_context())
            st.session_state.chat_messages.append({"role": "assistant", "content": answer})
            st.rerun()
