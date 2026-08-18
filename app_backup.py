import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
import os
from dotenv import load_dotenv

from pm import get_access_token, get_holdings, get_buying_power, get_exchange_rate, get_order_history, get_stock_info
from analytics_engine import transform_to_mvp_json, build_transaction_detail, build_period_performance
from ai_copilot import generate_portfolio_report, chat_with_portfolio
from benchmark import to_yf_ticker, build_growth_frame, quarterly_excess_returns
from manual_holdings import (
    load_manual_holdings, save_parsed_holdings, manual_to_orders,
    read_manual_csv, write_manual_csv,
    read_transactions_csv, write_transactions_csv, save_parsed_transactions,
    transactions_to_orders, derive_holdings_from_tx,
    set_data_dir, clear_all_imports,
)
from advanced_analytics import compute_dividends, compute_fx_pnl
from pme import (
    build_pme_table, build_pme_growth, build_trade_spy_table, build_ticker_profit_growth,
    compute_usd_avg_cost, build_usdkrw_history_frame, compute_alpha_beta,
    build_total_profit_growth, build_ticker_price_trades,
)
from performance import compute_performance_summary, build_holdings_breakdown
from ai_copilot import parse_brokerage_transactions, parse_brokerage_full_transactions
from auth import register_user, verify_user, user_dir

# 1. 페이지 설정 (반드시 최상단에 위치)
st.set_page_config(page_title="AI 포트폴리오 코파일럿", layout="wide", page_icon="📈")

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
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1180px; }
h1, h2, h3, h4 { color: var(--toss-ink); font-weight: 700; letter-spacing: -0.02em; }
h1 { font-size: 1.9rem !important; }
h2 { font-size: 1.35rem !important; margin-top: 0.4rem; }
h3 { font-size: 1.12rem !important; }
p, span, label, li { color: var(--toss-ink); }
[data-testid="stCaptionContainer"], .stCaption, small { color: var(--toss-sub) !important; }
[data-testid="stMetric"] { background: var(--toss-card); border: 1px solid var(--toss-border); border-radius: 20px; padding: 18px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); transition: transform .12s ease, box-shadow .12s ease; }
[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(49,130,246,0.10); }
[data-testid="stMetricLabel"] p { color: var(--toss-sub) !important; font-size: 0.86rem; font-weight: 600; }
[data-testid="stMetricValue"] { color: var(--toss-ink); font-weight: 700; font-size: 1.5rem; }
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button { border-radius: 14px; border: 1px solid var(--toss-border); background: #FFFFFF; color: var(--toss-ink); font-weight: 600; padding: 0.5rem 1.1rem; transition: all .12s ease; }
.stButton > button:hover { border-color: var(--toss-blue); color: var(--toss-blue); }
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button { background: var(--toss-blue); color: #fff; border: none; }
.stButton > button[kind="primary"]:hover { background: var(--toss-blue-dark); }
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] { border-radius: 12px; padding: 6px 16px; background: #EEF1F4; color: var(--toss-sub); }
.stTabs [aria-selected="true"] { background: var(--toss-blue) !important; color: #fff !important; }
[data-baseweb="input"], [data-baseweb="select"] > div, .stTextInput input, .stNumberInput input { border-radius: 12px !important; }
[data-testid="stDataFrame"], [data-testid="stTable"] { border-radius: 16px; overflow: hidden; border: 1px solid var(--toss-border); }
[data-testid="stExpander"] { border: 1px solid var(--toss-border); border-radius: 16px; background: var(--toss-card); }
.stPlotlyChart { background: var(--toss-card); border: 1px solid var(--toss-border); border-radius: 16px; padding: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.03); }
hr { border-color: var(--toss-border); margin: 1.6rem 0; }
[data-testid="stAlert"] { border-radius: 14px; }
[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid var(--toss-border); }
</style>
""",
    unsafe_allow_html=True,
)

# Plotly 전역 스타일: 토스풍 화이트 배경·Pretendard 폰트
_toss_tpl = pio.templates["plotly_white"]
_toss_tpl.layout.font.family = "Pretendard, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"
_toss_tpl.layout.font.color = "#191F28"
_toss_tpl.layout.colorway = ["#3182F6", "#F04452", "#00A676", "#F9A825", "#8B5CF6", "#6B7684"]
_toss_tpl.layout.paper_bgcolor = "rgba(0,0,0,0)"
_toss_tpl.layout.plot_bgcolor = "rgba(0,0,0,0)"
pio.templates.default = "plotly_white"

# 분석 섹션(PME·배당·환차·AI) 임시 비활성화 플래그 (True로 바꾸면 다시 표시)
SHOW_ANALYSIS = False

# ── 로그인 게이트 ─────────────────────────────────────────────
if "username" not in st.session_state:
    st.session_state.username = None

def _do_login_page():
    st.title("🔐 AI 포트폴리오 코파일럿 로그인")
    st.caption("로그인하면 임포트한 타 증권사 거래내역을 계정별로 저장하고 다음에 다시 불러올 수 있습니다.")
    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
    with tab_login:
        u = st.text_input("아이디", key="login_id")
        p = st.text_input("비밀번호", type="password", key="login_pw")
        if st.button("로그인", type="primary", key="btn_login"):
            ok, msg = verify_user(u, p)
            if ok:
                st.session_state.username = u.strip()
                st.session_state.import_answered = False
                st.cache_data.clear()  # 이전 사용자 캐시 제거
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
    # ── 임시: 로그인 과정 비활성화(테스트용 admin 자동 로그인). 원복 시 아래 두 줄 삭제하고 주석 해제 ──
    st.session_state.username = "admin"
    # _do_login_page()
    # st.stop()

# 로그인된 사용자 데이터 폴더로 저장 경로 설정
_USER = st.session_state.username
set_data_dir(user_dir(_USER))

# 최초 로그인 시, 루트에 있던 기존 임포트 데이터를 이 계정 폴더로 1회 이관
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

# 사이드바: 사용자 정보 / 로그아웃 / 저장 데이터 삭제
with st.sidebar:
    st.markdown(f"### 👤 {_USER}")
    if st.button("로그아웃"):
        for k in ("username", "import_answered", "chat_messages"):
            st.session_state.pop(k, None)
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.markdown("#### 💾 저장된 임포트 데이터")
    _saved_tx = read_transactions_csv()
    _saved_hold = read_manual_csv()
    st.caption(f"거래내역 {len(_saved_tx)}건 · 잔고 {len(_saved_hold)}종목 저장됨")
    if st.button("🗑️ 저장된 임포트 전체 삭제"):
        clear_all_imports()
        st.cache_data.clear()
        st.success("저장된 임포트 데이터를 삭제했습니다.")
        st.rerun()

# 2. 메인 타이틀 및 헤더
st.title("📈 AI 기반 포트폴리오 성과 검진 대시보드")
st.markdown("토스증권 데이터를 실시간 연동하여 보유 자산 수익률(XIRR 등)을 점검하고, **Gemini AI**를 통한 리밸런싱 인사이트를 얻어보세요.")

# 3. 데이터 로딩 (캐싱 적용으로 API 호출 낭비 방지)
@st.cache_data(ttl=300) # 5분간 데이터 캐시 유지
def fetch_portfolio_data():
    load_dotenv()
    CLIENT_ID = os.getenv("TOSS_CLIENT_ID")
    CLIENT_SECRET = os.getenv("TOSS_CLIENT_SECRET")
    ACCOUNT_NO = os.getenv("TOSS_ACCOUNT_NO", "1")
    
    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    if not token:
        return None, "토스증권 API 토큰 발급에 실패했습니다. API 키(CLIENT_ID, SECRET)를 확인하세요."
        
    toss_data = get_holdings(token, ACCOUNT_NO)
    if not toss_data:
        return None, "계좌/자산 데이터를 불러오는 데 실패했습니다."

    # 실제 예수금(KRW + USD 환산) 조회
    krw_cash = get_buying_power(token, ACCOUNT_NO, "KRW")
    usd_cash = get_buying_power(token, ACCOUNT_NO, "USD")
    fx_rate = get_exchange_rate(token)
    cash_krw = krw_cash + usd_cash * fx_rate

    portfolio_json = transform_to_mvp_json("usr_102938", toss_data, cash_krw, fx_rate)
    # 예수금 원화/달러 원본 잔액을 요약에 함께 보관 (대시보드 표시용)
    portfolio_json.setdefault("asset_summary", {})
    portfolio_json["asset_summary"]["cash_krw_native"] = krw_cash
    portfolio_json["asset_summary"]["cash_usd_native"] = usd_cash
    portfolio_json["asset_summary"]["fx_rate"] = fx_rate
    return portfolio_json, None

@st.cache_data(ttl=300)
def fetch_trade_data():
    """체결 이력 + 종목명 매핑 후 상세 거래내역 DataFrame과 원본 주문 리스트 반환"""
    load_dotenv()
    CLIENT_ID = os.getenv("TOSS_CLIENT_ID")
    CLIENT_SECRET = os.getenv("TOSS_CLIENT_SECRET")
    ACCOUNT_NO = os.getenv("TOSS_ACCOUNT_NO", "1")

    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    if not token:
        return pd.DataFrame(), [], 0.0, {}
    fx_rate = get_exchange_rate(token)
    orders = get_order_history(token, ACCOUNT_NO)

    # 보유 종목에서 티커→종목명 매핑 확보
    holdings_data = get_holdings(token, ACCOUNT_NO) or {}
    name_map = {
        i.get("symbol"): i.get("name")
        for i in holdings_data.get("result", {}).get("items", [])
    }
    detail_df = build_transaction_detail(orders, fx_rate, name_map)
    return detail_df, orders, fx_rate, name_map

def _build_ticker_map(holdings, max_items=6):
    """보유 종목 리스트에서 {종목명: yfinance티커} 매핑 생성 (비중 상위 위주)."""
    tmap = {}
    for h in holdings[:max_items]:
        country = "KR" if h.get("currency") == "KRW" else "US"
        yft = to_yf_ticker(h.get("ticker"), country)
        if yft:
            tmap[h.get("name") or h.get("ticker")] = yft
    return tmap

@st.cache_data(ttl=1800)  # 벤치마크(yfinance)는 30분 캐시
def fetch_benchmark_analysis(ticker_map, period="2y"):
    """정규화 성장 시계열 + 분기별 S&P500 대비 초과수익률 표를 반환."""
    growth = build_growth_frame(ticker_map, period="1y")
    excess = quarterly_excess_returns(ticker_map, period=period)
    return growth, excess

@st.cache_data(ttl=1800)
def fetch_manual_holdings(fx_rate, user):
    """한화투자증권 등 수동 입력 보유 종목 로드 (user별 캐시)."""
    return load_manual_holdings(fx_rate)

@st.cache_data(ttl=1800)
def fetch_manual_transactions(user):
    """전체 거래내역(청산 포함) CSV 로드 (user별 캐시)."""
    return read_transactions_csv()

@st.cache_data(ttl=1800)
def fetch_tx_derived_holdings(fx_rate, user):
    """거래내역에서 현재 순보유(청산 제외) 산출 (user별 캐시)."""
    return derive_holdings_from_tx(read_transactions_csv(), fx_rate)

@st.cache_data(ttl=1800)
def fetch_income_analysis(orders, fx):
    """배당 수령 추정 + 환차손익 분석 (yfinance 배당·환율 활용). orders=토스+수동 합산."""
    div_df = compute_dividends(orders, fx)
    fx_summary, fx_df = compute_fx_pnl(orders, fx)
    return div_df, fx_summary, fx_df, fx

@st.cache_data(ttl=1800)
def fetch_pme_analysis(orders, fx, name_map):
    """매매 타이밍을 반영한 PME 종목별 초과수익표 + 포트폴리오 성장 추이. orders=토스+수동 합산."""
    pme_table = build_pme_table(orders, fx, name_map)
    pme_growth = build_pme_growth(orders, fx)
    return pme_table, pme_growth

@st.cache_data(ttl=1800)
def fetch_pme_table_only(orders, fx, name_map):
    """종목별 실현/평가 성과 표(청산 포함)만 계산 (성장추이 제외로 가볍게)."""
    return build_pme_table(orders, fx, name_map)

@st.cache_data(ttl=1800)
def fetch_trade_spy_table(orders, fx, name_map):
    """거래별 S&P500 대비 초과수익 투명 비교표."""
    return build_trade_spy_table(orders, fx, name_map)

@st.cache_data(ttl=1800)
def fetch_ticker_profit_growth(orders, fx, ticker):
    """종목별 수익금 성장 vs S&P500 수익금 시계열."""
    return build_ticker_profit_growth(orders, fx, ticker)

@st.cache_data(ttl=1800)
def fetch_usd_avg_cost(orders, fx):
    """USD 매수 시점 환율 가중평균(달러 평단가) 계산."""
    return compute_usd_avg_cost(orders, fx)

@st.cache_data(ttl=3600)
def fetch_fx_10y():
    """최근 10년 USD/KRW 환율 시계열."""
    return build_usdkrw_history_frame("10y")

@st.cache_data(ttl=1800)
def fetch_alpha_beta(orders, fx):
    """방법 A(현금흐름 XIRR) 기반 포트폴리오 알파·베타."""
    return compute_alpha_beta(orders, fx)

@st.cache_data(ttl=1800)
def fetch_performance_summary(orders, fx):
    """실현/미실현·주가/환차·배당을 분해한 직관적 성과 요약."""
    return compute_performance_summary(orders, fx)

@st.cache_data(ttl=1800)
def fetch_total_profit_growth(orders, fx):
    """전체 자산 수익금 성장 추이 vs S&P500."""
    return build_total_profit_growth(orders, fx)

@st.cache_data(ttl=1800)
def fetch_holdings_breakdown(orders, fx, name_map):
    """분할매도 반영 종목별 실현/평가 회계 표."""
    return build_holdings_breakdown(orders, fx, name_map)

@st.cache_data(ttl=1800)
def fetch_ticker_price_trades(orders, ticker, start):
    """개별 종목 주가 시계열 + 내 매수/매도 시점."""
    return build_ticker_price_trades(orders, ticker, start)

@st.cache_data(ttl=3600)
def fetch_stock_names(tickers):
    """청산 종목 등 미보유 티커의 종목명을 토스 stocks API로 일괄 조회."""
    if not tickers:
        return {}
    load_dotenv()
    token = get_access_token(os.getenv("TOSS_CLIENT_ID"), os.getenv("TOSS_CLIENT_SECRET"))
    if not token:
        return {}
    names = {}
    joined = ",".join(tickers)
    data = get_stock_info(token, joined) or {}
    for item in data.get("result", []):
        if item.get("symbol") and item.get("name"):
            names[item["symbol"]] = item["name"]
    return names


def merge_manual_into_portfolio(portfolio_json, manual_df):
    """수동(타 증권사) 보유를 토스 포트폴리오에 병합. 같은 티커는 증권사 통합 합산."""
    if manual_df is None or manual_df.empty:
        return portfolio_json
    out = dict(portfolio_json)
    summary = dict(portfolio_json.get("asset_summary", {}))

    # 티커 기준 통합 맵 구성 (토스 보유부터)
    merged = {}
    for h in portfolio_json.get("holdings", []):
        tk = h.get("ticker")
        eval_krw = float(h.get("eval_krw", 0) or 0)
        ret = float(h.get("return_pct", 0) or 0)
        cost = eval_krw / (1 + ret / 100) if (1 + ret / 100) != 0 else eval_krw
        merged[tk] = {
            "ticker": tk,
            "name": h.get("name"),
            "currency": h.get("currency"),
            "quantity": float(h.get("quantity", 0) or 0),
            "eval_krw": eval_krw,
            "cost_krw": cost,
            "sector": h.get("sector", "Unknown"),
            "brokers": {"토스증권"},
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

        if tk in merged:  # 같은 종목 → 합산
            m = merged[tk]
            m["quantity"] += qty
            m["eval_krw"] += eval_krw
            m["cost_krw"] += purchase_krw
            m["brokers"].add(broker)
        else:
            merged[tk] = {
                "ticker": tk,
                "name": r.get("종목명"),
                "currency": cur,
                "quantity": qty,
                "eval_krw": eval_krw,
                "cost_krw": purchase_krw,
                "sector": "Unknown",
                "brokers": {broker},
            }

    new_stock = sum(m["eval_krw"] for m in merged.values())
    holdings = []
    for m in merged.values():
        ret = (m["eval_krw"] / m["cost_krw"] - 1) * 100 if m["cost_krw"] else 0
        holdings.append({
            "ticker": m["ticker"],
            "name": m["name"],
            "currency": m["currency"],
            "quantity": round(m["quantity"], 4),
            "eval_krw": round(m["eval_krw"]),
            "weight_pct": round(m["eval_krw"] / new_stock * 100, 2) if new_stock else 0,
            "sector": m["sector"],
            "return_pct": round(ret, 2),
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


# 4. 임포트 여부 게이트(예/아니오) → 답변 후에만 토스 API 로드
if "import_answered" not in st.session_state:
    st.session_state.import_answered = False

if not st.session_state.import_answered:
    st.header("📥 다른 증권사 거래내역을 임포트하시겠어요?")
    _saved_tx0 = read_transactions_csv()
    _saved_h0 = read_manual_csv()
    if len(_saved_tx0) or len(_saved_h0):
        st.info(f"이 계정에 저장된 임포트: 거래내역 {len(_saved_tx0)}건 · 잔고 {len(_saved_h0)}종목 — 그대로 사용할 수 있어요.")
    st.markdown("토스증권은 API로 자동 연동됩니다. **한화투자증권 등 API가 없는 증권사** 종목도 함께 분석하려면 임포트하세요.")
    gc1, gc2 = st.columns(2)
    with gc1:
        if st.button("✅ 예, 임포트/관리하기", type="primary", key="gate_yes"):
            st.session_state.show_import_ui = True
    with gc2:
        if st.button("➡️ 아니오, 바로 분석 시작", key="gate_no"):
            st.session_state.import_answered = True
            st.session_state.show_import_ui = False
            st.rerun()

    if st.session_state.get("show_import_ui"):
        st.markdown("각 증권사에서 **거래내역/잔고를 다운로드**해 올리면 AI가 표준 형식으로 변환·저장합니다.")
        with st.container(border=True):
            broker_name = st.text_input("증권사 이름", value="한화투자증권", key="broker_name")
    import_mode = st.radio(
        "임포트 유형",
        ["전체 거래내역 (매수·매도 전부, 청산 종목 포함) ⭐권장", "현재 잔고만 (보유 종목 스냅샷)"],
        key="import_mode",
    )
    is_full_tx = import_mode.startswith("전체")
    st.caption(
        "⭐ **전체 거래내역**을 올리면 이미 매도한(청산) 종목까지 성과 분석에 포함됩니다. "
        "잔고만 있으면 현재 보유 종목만 반영됩니다."
    )
    ups = st.file_uploader(
        "거래내역/잔고 파일 (여러 개 선택 가능 · CSV·TXT·엑셀)",
        type=["csv", "txt", "xlsx", "xls"], accept_multiple_files=True, key="import_files"
    )
    pasted = st.text_area("또는 여기에 직접 붙여넣기", height=140, key="import_paste",
                          placeholder="매수/매도 일자·종목·수량·단가가 포함된 거래내역을 붙여넣으세요")

    raw_texts = []
    if ups:
        for up in ups:
            try:
                if up.name.lower().endswith((".xlsx", ".xls")):
                    raw_texts.append(pd.read_excel(up).to_csv(index=False))
                else:
                    raw_texts.append(up.getvalue().decode("utf-8", errors="ignore"))
            except Exception as e:
                st.error(f"'{up.name}' 파일을 읽지 못했습니다: {e}")
    if pasted.strip():
        raw_texts.append(pasted)

    if st.button("🤖 AI로 변환 후 합산 저장", type="primary", disabled=not raw_texts):
        all_rows = []
        with st.spinner("AI가 거래내역을 분석하는 중입니다..."):
            for rt in raw_texts:
                if is_full_tx:
                    parsed, perr = parse_brokerage_full_transactions(rt, broker_name)
                else:
                    parsed, perr = parse_brokerage_transactions(rt, broker_name)
                if perr:
                    st.warning(perr)
                elif parsed:
                    all_rows.extend(parsed)
        if all_rows:
            st.markdown("**변환 결과 미리보기**")
            preview_df = pd.DataFrame(all_rows)
            numcols = ("수량", "단가") if is_full_tx else ("수량", "평균매수가")
            for c in numcols:
                if c in preview_df.columns:
                    preview_df[c] = pd.to_numeric(preview_df[c], errors="coerce")
            st.dataframe(preview_df, use_container_width=True, hide_index=True)
            if is_full_tx:
                saved = save_parsed_transactions(all_rows, replace_broker=broker_name)
                # 같은 증권사의 잔고 스냅샷은 제거(중복 방지)
                _hold = read_manual_csv()
                if not _hold.empty:
                    write_manual_csv(_hold[_hold["증권사"] != broker_name])
                msg = f"{saved}건의 거래(매수·매도·청산 포함)를 '{broker_name}'로 저장했습니다."
            else:
                saved = save_parsed_holdings(all_rows, replace_broker=broker_name)
                msg = f"{saved}개 보유 종목을 '{broker_name}'로 저장했습니다."
            st.cache_data.clear()
            st.success(msg + " 아래 분석에 자동 합산됩니다.")
            st.rerun()
        else:
            st.warning("변환된 항목이 없습니다. 원본 형식을 확인해 주세요.")

        if st.button("분석 시작 →", type="primary", key="gate_done"):
            st.session_state.import_answered = True
            st.rerun()
    st.stop()

# ── 임포트 답변 완료 → 토스 API 로드 + 대시보드 ──────────────────
with st.spinner("증권사 API와 연동 중입니다..."):
    portfolio_json, error_msg = fetch_portfolio_data()

if error_msg:
    st.error(error_msg)
elif portfolio_json:
    # 거래 이력(토스) + 환율 확보
    detail_df, toss_orders, fx_rate, toss_name_map = fetch_trade_data()
    fx_for_manual = fx_rate if fx_rate else 1421.0

    # 타 증권사 데이터: (A) 전체 거래내역(청산 포함) + (B) 잔고 스냅샷
    tx_df = fetch_manual_transactions(_USER)
    has_tx = tx_df is not None and not tx_df.empty
    tx_brokers = set(tx_df["증권사"].unique()) if has_tx else set()

    holdings_snapshot = fetch_manual_holdings(fx_for_manual, _USER)
    # 거래내역이 있는 증권사는 잔고 스냅샷 대신 거래내역에서 파생 (중복 방지)
    if holdings_snapshot is not None and not holdings_snapshot.empty:
        holdings_snapshot = holdings_snapshot[~holdings_snapshot["증권사"].isin(tx_brokers)]

    tx_holdings = fetch_tx_derived_holdings(fx_for_manual, _USER) if has_tx else pd.DataFrame()

    # 화면/병합용 통합 보유 종목 (현재 순보유)
    manual_parts = [d for d in (tx_holdings, holdings_snapshot) if d is not None and not d.empty]
    manual_df = pd.concat(manual_parts, ignore_index=True) if manual_parts else pd.DataFrame()
    has_manual = not manual_df.empty

    if has_manual:
        portfolio_json = merge_manual_into_portfolio(portfolio_json, manual_df)
    if has_tx or has_manual:
        n_brokers = manual_df["증권사"].nunique() if has_manual else len(tx_brokers)
        extra = " (청산 종목 포함 거래내역 반영)" if has_tx else ""
        st.success(f"토스증권 + {n_brokers}개 타 증권사 데이터를 통합했습니다.{extra}")
    else:
        st.success("토스증권 계좌 데이터 연동 성공! (타 증권사 임포트 없음)")

    # 토스 주문 + 타증권사 주문 결합 → 모든 성과 분석에 반영
    #  - 거래내역(청산 포함): transactions_to_orders  /  잔고 스냅샷: manual_to_orders
    combined_orders = list(toss_orders)
    if has_tx:
        combined_orders += transactions_to_orders(tx_df)
    if holdings_snapshot is not None and not holdings_snapshot.empty:
        combined_orders += manual_to_orders(holdings_snapshot)

    # 통합 종목명 매핑 + 통합 상세 거래내역 (토스 + 타 증권사)
    combined_name_map = dict(toss_name_map)
    if has_manual:
        for _, r in manual_df.iterrows():
            combined_name_map.setdefault(str(r.get("티커")), r.get("종목명"))
    # 청산 종목 등 이름 미상 티커를 토스 stocks API로 보강
    traded_tickers = {o.get("symbol") for o in combined_orders if o.get("symbol")}
    unknown = tuple(sorted(t for t in traded_tickers if t not in combined_name_map))
    if unknown:
        combined_name_map.update(fetch_stock_names(unknown))
    detail_df = build_transaction_detail(combined_orders, fx_rate, combined_name_map)

    # 종목별 청산 여부(현재 순보유수량 0 → 청산) 계산 후 거래내역에 표시
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

    # 🔖 (임포트 직후) 타 증권사 보유 상세 + 직접 수정
    st.header("🏦 타 증권사 보유 상세 (임포트)")
    if has_manual:
        st.markdown("상단에서 임포트한 타 증권사 종목입니다. (자산 요약·성과 분석에 이미 합산되어 있습니다)")
        m_cols = ["증권사", "종목명", "티커", "시장", "통화", "수량",
                  "평균매수가", "현재가", "평가액(원)", "수익률(%)", "매수일"]
        m_cols = [c for c in m_cols if c in manual_df.columns]
        st.dataframe(
            manual_df[m_cols].style.format({
                "평균매수가": "{:,.2f}", "현재가": "{:,.2f}",
                "평가액(원)": "{:,.0f}", "수익률(%)": "{:+.2f}", "수량": "{:g}"
            }),
            use_container_width=True, hide_index=True
        )
        _by_broker = manual_df.groupby("증권사")["평가액(원)"].sum()
        _cols = st.columns(max(len(_by_broker), 1))
        for _c, (_bk, _v) in zip(_cols, _by_broker.items()):
            _c.metric(f"{_bk} 평가액", f"{_v:,.0f} ₩")
    else:
        st.info("임포트된 타 증권사 종목이 없습니다. 페이지 상단의 '📥 다른 증권사 거래내역 임포트'로 추가하세요.")

    with st.expander("✏️ 보유 내역 직접 수정하기 (AI 파싱 오류 보정 · 행 추가/삭제)", expanded=False):
        tab_tx, tab_hold = st.tabs(["📜 전체 거래내역 (청산 포함)", "📦 잔고 스냅샷"])

        with tab_tx:
            st.caption("매수/매도 개별 거래를 직접 고치거나 추가/삭제한 뒤 저장하세요. 청산 종목도 여기서 관리됩니다.")
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
                fetch_manual_transactions.clear()
                fetch_tx_derived_holdings.clear()
                st.success(f"{n}건의 거래를 저장했습니다.")
                st.rerun()

        with tab_hold:
            st.caption("잔고(현재 보유)만 입력한 증권사의 종목을 수정합니다.")
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
                fetch_manual_holdings.clear()
                st.success(f"{n}개 종목을 저장했습니다.")
                st.rerun()

    st.divider()

    # 🔖 (1) 주요 지표 섹션 (Metrics)
    st.header("1. 자산 요약")
    # 성과 비교는 XIRR로 일원화: 포트폴리오 XIRR vs S&P500 가상펀드 XIRR(초과 = 알파)
    _ab_top = fetch_alpha_beta(combined_orders, fx_rate)
    _port_xirr = _ab_top.get("port_xirr_pct") if _ab_top else None
    _xirr_alpha = _ab_top.get("alpha_pct") if _ab_top else None
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 자산 (원)", f"{summary.get('total_asset_krw', 0):,.0f} ₩")
    col2.metric("주식 평가액 (원)", f"{summary.get('stock_eval_krw', 0):,.0f} ₩")
    col3.metric("포트폴리오 수익률 (XIRR)",
                f"{_port_xirr:+.2f} %" if _port_xirr is not None else "N/A")
    col4.metric("S&P500 대비 알파 (초과 XIRR)",
                f"{_xirr_alpha:+.2f} %p" if _xirr_alpha is not None else "N/A",
                delta="S&P500 초과" if (_xirr_alpha or 0) >= 0 else "S&P500 미달",
                delta_color="normal" if (_xirr_alpha or 0) >= 0 else "inverse")

    # 예수금(원화/달러) — 토스 buying-power API 원본 잔액
    _krw_cash = float(summary.get("cash_krw_native", 0) or 0)
    _usd_cash = float(summary.get("cash_usd_native", 0) or 0)
    _cash_fx = float(summary.get("fx_rate", fx_rate) or fx_rate or 0)
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("💵 예수금 (원화)", f"{_krw_cash:,.0f} ₩")
    cc2.metric("💵 예수금 (달러)", f"$ {_usd_cash:,.2f}",
               delta=f"≈ {_usd_cash * _cash_fx:,.0f} ₩ (환율 {_cash_fx:,.0f})" if _cash_fx else None,
               delta_color="off")
    cc3.metric("💰 총 예수금 (원화 환산)", f"{_krw_cash + _usd_cash * _cash_fx:,.0f} ₩")

    st.divider()

    # 🔖 (1-2) 한눈에 보는 성과 요약 (직관적 지표 체계)
    st.header("📊 한눈에 보는 성과 요약")
    st.caption("실현/미실현·주가/환율·배당을 분해해 **무엇으로 얼마를 벌었는지** 직관적으로 보여줍니다. (토스 + 임포트 합산)")
    with st.spinner("실현·미실현·배당·환차 성과를 분해하는 중입니다... (yfinance 시세)"):
        perf = fetch_performance_summary(combined_orders, fx_rate)

    if perf:
        # 원화/외화 뷰 전환 토글 (미국 주식의 달러 기준 vs 원화 기준)
        view_ccy = st.radio(
            "보유 자산 손익 기준", ["원화(KRW) 기준", "달러(USD) 기준 · 순수 주가"],
            horizontal=True, key="perf_view_ccy",
            help="달러 기준은 환율 효과를 제거한 미국 주식의 순수 주가 손익입니다.",
        )
        use_usd = view_ccy.startswith("달러")

        st.markdown("##### 1️⃣ 전체 포트폴리오 누적 성과")
        g1c1, g1c2 = st.columns(2)
        g1c1.metric(
            "누적 총수익금 (매매+평가+배당+환차)", f"{perf['all_inclusive_krw']:,.0f} ₩",
            delta=f"{perf['all_inclusive_pct']:+.2f}% (투입원금 대비)",
            delta_color="normal" if perf["all_inclusive_krw"] >= 0 else "inverse",
        )
        g1c2.metric(
            "순수 주가 매매 손익 (배당·환율 제외)", f"{perf['pure_price_krw']:,.0f} ₩",
            delta=f"{perf['pure_price_pct']:+.2f}%",
            delta_color="normal" if perf["pure_price_krw"] >= 0 else "inverse",
        )

        st.markdown("##### 2️⃣ 보유 자산 성과 (미실현)")
        g2c1, g2c2 = st.columns(2)
        if use_usd:
            g2c1.metric(
                "현재 보유 평가 손익 (달러·순수 주가)", f"$ {perf['unreal_native_usd']:,.2f}",
                delta=f"{perf['unreal_native_usd_pct']:+.2f}% (달러 원금 대비)",
                delta_color="normal" if perf["unreal_native_usd"] >= 0 else "inverse",
            )
            g2c2.metric("미국 주식 달러 매수원금", f"$ {perf['cost_usd_remaining']:,.2f}")
        else:
            g2c1.metric(
                "현재 보유 평가 손익 (원화·환차 포함)", f"{perf['unreal_total_krw']:,.0f} ₩",
                delta=f"{perf['unreal_total_pct']:+.2f}% (보유원금 대비)",
                delta_color="normal" if perf["unreal_total_krw"] >= 0 else "inverse",
            )
            g2c2.metric("현재 보유 평가액", f"{perf['cur_value_krw']:,.0f} ₩")

        st.markdown("##### 3️⃣ 실현 및 부가 수익")
        g3c1, g3c2, g3c3 = st.columns(3)
        g3c1.metric(
            "누적 청산(매도) 실현 손익", f"{perf['realized_total_krw']:,.0f} ₩",
            delta_color="normal" if perf["realized_total_krw"] >= 0 else "inverse",
        )
        g3c2.metric("누적 배당 수익 (추정)", f"{perf['div_krw']:,.0f} ₩")
        g3c3.metric(
            "누적 환차손익 (보유+매도)", f"{perf['fx_total_krw']:,.0f} ₩",
            delta="환율 이득" if perf["fx_total_krw"] >= 0 else "환율 손실",
            delta_color="normal" if perf["fx_total_krw"] >= 0 else "inverse",
        )
        st.caption(
            "※ **누적 총수익금 = 순수 주가손익 + 환차손익 + 배당**으로 분해됩니다. "
            "달러 기준 뷰는 환율 효과를 제거한 미국 주식의 순수 주가 등락만 보여줍니다. "
            "배당·환차손익은 yfinance 배당/환율 기반 추정치입니다."
        )
    else:
        st.info("성과를 분해할 거래 이력이 없습니다.")

    st.divider()

    # 🔖 (2) 보유 종목 시각화 및 리스트
    st.header("2. 보유 종목 현황 및 비중")
    st.caption("여러 증권사에 같은 종목이 있으면 **통합 합산**해 총수량으로 표시합니다.")
    if holdings:
        df = pd.DataFrame(holdings)
        # 숫자 컬럼 타입 통일 (Arrow 직렬화 경고 방지)
        for c in ("quantity", "eval_krw", "weight_pct", "return_pct"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        # 컬럼 이름 예쁘게 변경
        df_display = df.rename(columns={
            "ticker": "티커", "name": "종목명", "quantity": "수량", "eval_krw": "평가액(원)",
            "weight_pct": "비중(%)", "return_pct": "수익률(%)", "currency": "통화",
            "sector": "섹터", "brokers": "보유 증권사"
        })
        display_cols = ["종목명", "통화", "수량", "평가액(원)", "비중(%)", "수익률(%)", "보유 증권사"]
        display_cols = [c for c in display_cols if c in df_display.columns]

        row1, row2 = st.columns([1.5, 1])

        with row1:
            st.markdown("#### 관심 종목 상세")
            # 데이터프레임 UI
            st.dataframe(df_display[display_cols], use_container_width=True, hide_index=True)

        with row2:
            st.markdown("#### 자산 분포 현황")
            # 비중 파이 차트
            fig = px.pie(df, values='weight_pct', names='name', hole=0.4)
            fig.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("보유 종목이 없습니다.")

    st.divider()

    # 🔖 (3) 통합 거래 내역 (토스 + 임포트, 시간 오름차순)
    st.header("3. 📜 통합 거래 내역 (토스증권 + 타 증권사)")
    st.markdown("토스증권 API 체결 내역과 임포트한 타 증권사 거래를 **시간 오름차순**으로 정리했습니다.")

    raw_orders = combined_orders
    trades_summary_text = None
    if detail_df is not None and not detail_df.empty:
        asc = detail_df.sort_values("체결일시", ascending=True).reset_index(drop=True)
        trades_summary_text = asc.drop(columns=["체결일시"], errors="ignore").to_string(index=False)

        f1, f2, f3, f4 = st.columns(4)
        with f1:
            brokers_opt = sorted(asc["증권사"].unique()) if "증권사" in asc.columns else []
            sel_broker = st.multiselect("증권사 필터", brokers_opt, key="tx_broker")
        with f2:
            sel_side = st.multiselect("구분 필터", ["매수", "매도"], key="tx_side")
        with f3:
            sel_ticker = st.multiselect("종목 필터", sorted(asc["티커"].unique()), key="tx_ticker")
        with f4:
            status_opt = sorted(asc["상태"].unique()) if "상태" in asc.columns else []
            sel_status = st.multiselect("청산여부 필터", status_opt, key="tx_status")

        view = asc.copy()
        if sel_broker and "증권사" in view.columns:
            view = view[view["증권사"].isin(sel_broker)]
        if sel_side:
            view = view[view["구분"].isin(sel_side)]
        if sel_ticker:
            view = view[view["티커"].isin(sel_ticker)]
        if sel_status and "상태" in view.columns:
            view = view[view["상태"].isin(sel_status)]

        cols = ["날짜", "증권사", "종목명", "티커", "상태", "구분", "수량",
                "체결단가", "통화", "체결금액(원본)", "체결금액(원)", "수수료", "세금"]
        cols = [c for c in cols if c in view.columns]
        st.dataframe(
            view[cols].style.format({
                "체결단가": "{:,.2f}", "체결금액(원본)": "{:,.2f}",
                "체결금액(원)": "{:,.0f}", "수수료": "{:,.2f}", "세금": "{:,.2f}", "수량": "{:g}"
            }),
            use_container_width=True, hide_index=True, height=560
        )
        if len(asc):
            st.caption(
                f"총 {len(view)}건 (오름차순) · 가장 오래된 거래 {asc['날짜'].iloc[0]} ~ 최근 {asc['날짜'].iloc[-1]} · "
                f"적용 환율 1 USD = {fx_rate:,.1f} KRW"
            )
        with st.expander("🔬 원본 주문(JSON) 보기 (토스 + 합성 임포트)"):
            st.json(raw_orders)
    else:
        st.info("거래 내역이 없거나 불러오지 못했습니다.")

    st.divider()

    # 🔖 (4) 종목별 실현·평가 성과 (청산 종목 포함) — 항상 표시
    st.header("4. 🎯 종목별 실현·평가 성과 (청산 종목 포함)")
    st.markdown("**전량 매도(청산)한 종목**은 매도 시점 기준 실현 수익률·손익을, **보유중 종목**은 현재 평가 수익률·손익을 보여줍니다. (토스 + 임포트 합산)")

    with st.spinner("종목별 실현·평가 성과를 계산하는 중입니다... (yfinance 시세)"):
        pme_name_map = dict(combined_name_map)
        perf_tbl = fetch_pme_table_only(combined_orders, fx_rate, pme_name_map)

    if perf_tbl is not None and not perf_tbl.empty:
        # 벤치마크(PME) 비교 컬럼 제거 → 내 수익률/손익만. 손익(원)=투자원금×수익률
        perf_tbl = perf_tbl.copy()
        perf_tbl["손익(원)"] = (perf_tbl["투자원금(원)"] * perf_tbl["내 수익률(%)"] / 100).round()
        show_cols = ["종목", "티커", "투자원금(원)", "내 수익률(%)", "손익(원)"]
        fmt = {"투자원금(원)": "{:,.0f}", "내 수익률(%)": "{:+.2f}", "손익(원)": "{:,.0f}"}
        closed = perf_tbl[perf_tbl["보유상태"] == "청산"]
        held = perf_tbl[perf_tbl["보유상태"] == "보유중"]

        st.markdown("#### 🏁 청산 종목 (매도 시점 기준 실현 성과)")
        if not closed.empty:
            st.dataframe(
                closed[show_cols].style.format(fmt)
                .background_gradient(cmap="RdYlGn", subset=["내 수익률(%)"]),
                use_container_width=True, hide_index=True
            )
            _c_pnl = float(closed["손익(원)"].sum())
            _c_inv = float(closed["투자원금(원)"].sum())
            st.caption(
                f"청산 종목 합계 · 투자원금 {_c_inv:,.0f}원 · **실현 손익 합계 {_c_pnl:+,.0f}원** "
                f"({_c_pnl / _c_inv * 100:+.2f}%)" if _c_inv else
                f"청산 종목 실현 손익 합계 {_c_pnl:+,.0f}원"
            )
        else:
            st.info("전량 매도(청산)한 종목이 없습니다.")

        st.markdown("#### 📦 보유중 종목 (현재 평가 성과)")
        if not held.empty:
            st.dataframe(
                held[show_cols].style.format(fmt)
                .background_gradient(cmap="RdYlGn", subset=["내 수익률(%)"]),
                use_container_width=True, hide_index=True
            )
            _h_pnl = float(held["손익(원)"].sum())
            _h_inv = float(held["투자원금(원)"].sum())
            st.caption(
                f"보유중 종목 합계 · 투자원금 {_h_inv:,.0f}원 · **현재 평가 손익 합계 {_h_pnl:+,.0f}원** "
                f"({_h_pnl / _h_inv * 100:+.2f}%)" if _h_inv else
                f"보유중 종목 평가 손익 합계 {_h_pnl:+,.0f}원"
            )
        else:
            st.info("보유중 종목이 없습니다.")

        # 손익 총합 요약 (청산 + 보유중 + 전체)
        st.markdown("#### 🧮 종목별 손익 총합")
        _closed_sum = float(closed["손익(원)"].sum()) if not closed.empty else 0.0
        _held_sum = float(held["손익(원)"].sum()) if not held.empty else 0.0
        _total_sum = float(perf_tbl["손익(원)"].sum())
        _total_inv = float(perf_tbl["투자원금(원)"].sum())
        e1, e2, e3 = st.columns(3)
        e1.metric("청산 종목 실현 손익 합", f"{_closed_sum:,.0f} ₩",
                  delta_color="normal" if _closed_sum >= 0 else "inverse")
        e2.metric("보유중 종목 평가 손익 합", f"{_held_sum:,.0f} ₩",
                  delta_color="normal" if _held_sum >= 0 else "inverse")
        e3.metric("전체 손익 합", f"{_total_sum:,.0f} ₩",
                  delta=f"{_total_sum / _total_inv * 100:+.2f}% (투자원금 대비)" if _total_inv else None,
                  delta_color="normal" if _total_sum >= 0 else "inverse")
        st.caption("**손익(원) = 투자원금 × 내 수익률**. 청산은 실현 손익, 보유중은 현재 평가 손익입니다. "
                   "S&P500 대비 초과수익(알파)은 섹션 6에서 XIRR 기준으로 확인하세요.")
    else:
        st.info("성과를 계산할 거래 이력이 없습니다.")

    st.divider()

    # 🔖 (5) 종목별 실현·평가 상세 & 수익금 성장 추이 — 항상 표시
    st.header("5. 🔍 종목별 실현·평가 상세 & 수익금 성장 추이")
    st.markdown(
        "종목별로 **분할매도를 반영한 평균단가 회계**로 실현/평가 성과를 보여줍니다. "
        "청산 종목은 **매도 시점 실현가 기준**(현재가 아님), 보유 종목은 잔여수량 평가 기준입니다. "
        "(S&P500 대비 초과수익·알파는 섹션 6에서 XIRR 기준으로 통합 제공)"
    )

    with st.spinner("종목별 실현·평가 회계를 계산하는 중입니다..."):
        brk_tbl = fetch_holdings_breakdown(combined_orders, fx_rate, combined_name_map)

    if brk_tbl is not None and not brk_tbl.empty:
        tf1, tf2 = st.columns(2)
        with tf1:
            sel_st = st.multiselect("상태 필터", ["보유중", "청산"], key="brk_status")
        with tf2:
            sel_tk = st.multiselect("종목 필터", sorted(brk_tbl["티커"].unique()), key="brk_tk")
        tv = brk_tbl
        if sel_st:
            tv = tv[tv["상태"].isin(sel_st)]
        if sel_tk:
            tv = tv[tv["티커"].isin(sel_tk)]

        show = ["종목", "티커", "통화", "상태", "보유수량", "평단가(달러)", "평단가(원화)",
                "투자원금(원)", "매도실현금액(원)", "실현손익(원)", "평가손익(원)", "수익률(%)"]
        show = [c for c in show if c in tv.columns]
        st.dataframe(
            tv[show].style.format({
                "보유수량": "{:g}", "평단가(달러)": "{:,.2f}", "평단가(원화)": "{:,.2f}",
                "투자원금(원)": "{:,.0f}", "매도실현금액(원)": "{:,.0f}",
                "실현손익(원)": "{:,.0f}", "평가손익(원)": "{:,.0f}", "수익률(%)": "{:+.2f}",
            }, na_rep="-").background_gradient(cmap="RdYlGn", subset=["수익률(%)"]),
            use_container_width=True, hide_index=True, height=420
        )
        st.caption(
            "**수익률(%) = (실현손익 + 평가손익) ÷ 투자원금**. 청산 종목은 매도 시점 실현손익만, "
            "보유 종목은 잔여수량 평가손익까지 반영합니다. **평단가**는 전체 매수의 수량가중 평균가입니다."
        )

        # 📈 수익금 성장 추이 (전체 자산 + 종목별) vs S&P500 (투자원금 제외 순수익)
        st.markdown("#### 📈 수익금 성장 추이 (투자원금 제외) vs S&P500")
        st.caption("투자한 원금을 뺀 **순수 수익금**이 시간에 따라 어떻게 커졌는지, 같은 돈을 S&P500(SPY)에 넣었을 때와 비교합니다. "
                   "**그래프의 점을 클릭**하면 그 날짜 기준 손익률(%)이 표시됩니다.")

        ALL_LABEL = "📊 전체 자산 (합산)"
        tickers_opt = sorted(brk_tbl["티커"].unique())
        options = [ALL_LABEL] + tickers_opt
        sel_growth = st.selectbox(
            "대상 선택", options, index=0,
            format_func=lambda t: t if t == ALL_LABEL else f"{combined_name_map.get(t, t)} ({t})",
            key="growth_target",
        )
        is_all = sel_growth == ALL_LABEL

        with st.spinner("수익금 성장 추이를 계산하는 중입니다..."):
            gdf = (fetch_total_profit_growth(combined_orders, fx_rate) if is_all
                   else fetch_ticker_profit_growth(combined_orders, fx_rate, sel_growth))

        if gdf is not None and not gdf.empty:
            gidx = gdf.index
            growth_key = f"growth_chart_{'ALL' if is_all else sel_growth}"

            # 이전 클릭(선택) 상태를 세션에서 읽어 그래프에 알파 주석을 미리 반영
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
                        click_info = {
                            "date": gidx[pos], "inv": inv, "myp": myp, "spyp": spyp,
                            "my_r": myp / inv * 100, "spy_r": spyp / inv * 100,
                            "alpha": (myp - spyp) / inv * 100,
                        }
                except Exception:
                    click_info = None

            # 이중 y축: 좌(수익금 원) / 우(주가, 개별 종목만)
            fig_g = make_subplots(specs=[[{"secondary_y": True}]])
            fig_g.add_trace(go.Scatter(
                x=gidx, y=gdf["내 수익금"], name="내 수익금",
                mode="lines+markers", marker=dict(size=4), line=dict(color="#EF553B"),
            ), secondary_y=False)
            fig_g.add_trace(go.Scatter(
                x=gidx, y=gdf["S&P500 수익금"], name="S&P500 수익금",
                mode="lines", line=dict(color="#636EFA", dash="dash"),
            ), secondary_y=False)
            fig_g.add_hline(y=0, line_dash="dot", line_color="gray")

            # 개별 종목: 현재 주가 곡선 + 매수/매도 시점 마커
            if not is_all:
                price_hist, buys_df, sells_df, ccy = fetch_ticker_price_trades(
                    combined_orders, sel_growth, gidx.min())
                unit = "$" if ccy == "USD" else "₩"
                if price_hist is not None and not price_hist.empty:
                    fig_g.add_trace(go.Scatter(
                        x=price_hist.index, y=price_hist.values, name=f"주가({unit})",
                        mode="lines", line=dict(color="#00A676", width=1.2),
                        hovertemplate="%{x|%Y-%m-%d}<br>주가 %{y:,.2f}" + unit + "<extra></extra>",
                    ), secondary_y=True)
                if buys_df is not None and not buys_df.empty:
                    fig_g.add_trace(go.Scatter(
                        x=buys_df["date"], y=buys_df["price"], name="매수",
                        mode="markers",
                        marker=dict(symbol="triangle-up", size=12, color="#2ca02c",
                                    line=dict(width=1, color="white")),
                        hovertemplate="매수 %{x|%Y-%m-%d}<br>단가 %{y:,.2f}" + unit + "<extra></extra>",
                    ), secondary_y=True)
                if sells_df is not None and not sells_df.empty:
                    fig_g.add_trace(go.Scatter(
                        x=sells_df["date"], y=sells_df["price"], name="매도",
                        mode="markers",
                        marker=dict(symbol="triangle-down", size=12, color="#d62728",
                                    line=dict(width=1, color="white")),
                        hovertemplate="매도 %{x|%Y-%m-%d}<br>단가 %{y:,.2f}" + unit + "<extra></extra>",
                    ), secondary_y=True)
                fig_g.update_yaxes(title_text=f"주가 ({unit})", secondary_y=True, showgrid=False)

            fig_g.update_yaxes(title_text="누적 수익금(원)", secondary_y=False)
            fig_g.update_xaxes(title_text="날짜")
            fig_g.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))

            # 클릭 지점: 세로선 + 알파 주석을 그래프 위에 표시
            if click_info:
                d = click_info["date"]
                fig_g.add_vline(x=d, line_dash="dot", line_color="#888888")
                fig_g.add_annotation(
                    x=d, y=click_info["myp"], yref="y",
                    text=(f"<b>{d.strftime('%Y-%m-%d')}</b><br>"
                          f"알파 {click_info['alpha']:+.2f}%p<br>"
                          f"내 {click_info['my_r']:+.2f}% / S&P {click_info['spy_r']:+.2f}%"),
                    showarrow=True, arrowhead=2, arrowcolor="#888888",
                    bgcolor="rgba(255,255,255,0.9)", bordercolor="#888888", borderwidth=1,
                    font=dict(size=12, color="#111111"), align="left",
                )

            st.plotly_chart(fig_g, use_container_width=True, on_select="rerun", key=growth_key)

            if click_info:
                st.success(
                    f"🗓️ **{click_info['date'].strftime('%Y-%m-%d')}** 기준 · "
                    f"**알파 {click_info['alpha']:+.2f}%p** · "
                    f"내 손익률 {click_info['my_r']:+.2f}% ({click_info['myp']:,.0f}원) · "
                    f"S&P500 {click_info['spy_r']:+.2f}% ({click_info['spyp']:,.0f}원) · "
                    f"당시 투자원금 {click_info['inv']:,.0f}원"
                )
            else:
                st.caption("💡 그래프의 **점을 클릭**하면 그 날짜의 알파(초과 %p)가 그래프 위에 표시됩니다."
                           + ("" if is_all else " · 초록 곡선=주가, ▲매수 / ▼매도 시점"))

            my_p = gdf["내 수익금"].iloc[-1]
            spy_p = gdf["S&P500 수익금"].iloc[-1]
            target_label = "전체 자산" if is_all else combined_name_map.get(sel_growth, sel_growth)
            st.caption(
                f"**{target_label}** 현재 순수익금 {my_p:,.0f}원 vs "
                f"같은 돈을 S&P500에 넣었다면 {spy_p:,.0f}원 → **차이 {my_p - spy_p:+,.0f}원**"
            )
        else:
            st.info("수익금 성장 데이터를 계산하지 못했습니다.")
    else:
        st.info("종목별 실현·평가 성과를 계산할 거래 이력이 없습니다.")

    st.divider()

    # 🔖 (6) 달러 평단가 · 10년 환율 · S&P500 알파/베타
    st.header("6. 💵 달러 평단가 & S&P500 알파·베타")

    # 6-1. 달러 평단가 + 최근 10년 환율 그래프 (y=a 평단가 수평선)
    st.markdown("#### 💱 나의 달러 평단가 (매수 시점 환율 가중평균) vs 최근 10년 환율")
    st.caption("토스증권 + 임포트한 거래내역의 **USD 매수 체결**을 그날 환율로 가중평균해 달러 평단가를 구하고, 최근 10년 환율 위에 y=a 수평선으로 표시합니다.")
    with st.spinner("달러 평단가와 10년 환율을 계산하는 중입니다..."):
        usd_cost = fetch_usd_avg_cost(combined_orders, fx_rate)
        fx_10y = fetch_fx_10y()

    if usd_cost:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("달러 평단가", f"{usd_cost['avg_fx']:,.1f} 원/$")
        c2.metric("현재 환율", f"{usd_cost['current_fx']:,.1f} 원/$")
        gap = usd_cost["current_fx"] - usd_cost["avg_fx"]
        c3.metric("현재 − 평단 차이", f"{gap:+,.1f} 원",
                  delta=f"{gap / usd_cost['avg_fx'] * 100:+.2f}%")
        c4.metric("누적 환차손익", f"{usd_cost['fx_pnl_krw']:,.0f} ₩",
                  delta="환율 이득" if usd_cost["fx_pnl_krw"] >= 0 else "환율 손실",
                  delta_color="normal" if usd_cost["fx_pnl_krw"] >= 0 else "inverse")

        if fx_10y is not None and not fx_10y.empty:
            fxp = fx_10y.reset_index()
            xcol = fxp.columns[0]
            fig_fx = px.line(fxp, x=xcol, y="원/달러",
                             labels={xcol: "날짜", "원/달러": "USD/KRW 환율"},
                             title="최근 10년 USD/KRW 환율과 내 달러 평단가 (y=a)")
            fig_fx.add_hline(
                y=usd_cost["avg_fx"], line_dash="dash", line_color="#EF553B",
                annotation_text=f"내 달러 평단가 {usd_cost['avg_fx']:,.1f}원",
                annotation_position="top left",
            )
            st.plotly_chart(fig_fx, use_container_width=True)
            st.caption(
                f"빨간 점선(y=a = {usd_cost['avg_fx']:,.1f}원)이 내 달러 평단가입니다. "
                f"현재 환율({usd_cost['current_fx']:,.1f}원)이 평단가보다 **위면 환차익, 아래면 환차손**입니다. "
                f"(총 매수원금 ${usd_cost['total_usd']:,.0f})"
            )
        else:
            st.info("10년 환율 데이터를 불러오지 못했습니다.")
    else:
        st.info("USD(미국 주식) 매수 내역이 없어 달러 평단가를 계산할 수 없습니다.")

    st.divider()

    # 6-2. S&P500 대비 알파(초과 XIRR) & 베타
    st.markdown("#### 📊 포트폴리오 전체 S&P500 대비 알파(초과 XIRR) & 베타")
    st.caption(
        "**XIRR 기준 단일 성과 비교**: 같은 날짜·같은 금액을 S&P500(SPY)에 투자했다고 가정한 XIRR과 "
        "내 실제 XIRR의 차이가 알파입니다. **청산·보유 종목이 모두 기간·금액 비중대로 자동 합산**됩니다."
    )
    with st.spinner("XIRR 기반 알파·베타를 계산하는 중입니다... (yfinance 10년 시세)"):
        ab = fetch_alpha_beta(combined_orders, fx_rate)

    if ab:
        a1, a2, a3 = st.columns(3)
        a1.metric("내 포트폴리오 XIRR",
                  f"{ab['port_xirr_pct']} %" if ab["port_xirr_pct"] is not None else "N/A")
        a2.metric("S&P500 XIRR (동일 현금흐름)",
                  f"{ab['spy_xirr_pct']} %" if ab["spy_xirr_pct"] is not None else "N/A")
        _alpha = ab["alpha_pct"]
        a3.metric("알파 (초과 XIRR)",
                  f"{_alpha:+.2f} %p" if _alpha is not None else "N/A",
                  delta="S&P500 초과" if (_alpha or 0) >= 0 else "S&P500 미달",
                  delta_color="normal" if (_alpha or 0) >= 0 else "inverse")

        b1, b2 = st.columns(2)
        b1.metric("베타 (시장 민감도)", f"{ab['beta']}" if ab["beta"] is not None else "N/A")
        b2.metric("상관계수 (vs S&P500)", f"{ab['corr']}" if ab["corr"] is not None else "N/A")

        if ab["beta"] is not None:
            beta_desc = ("시장보다 변동이 큼(공격적)" if ab["beta"] > 1.1 else
                         "시장과 유사한 변동" if abs(ab["beta"] - 1) <= 0.1 else
                         "시장보다 방어적")
            _alpha_txt = f"{_alpha:+.2f}%p" if _alpha is not None else "N/A"
            st.caption(
                f"**알파 {_alpha_txt}**: 같은 현금흐름을 S&P500에 넣었을 때보다 연환산 수익률(XIRR)이 이만큼 높/낮습니다. · "
                f"**베타 {ab['beta']}**: {beta_desc} (1이면 시장과 동일 변동). · "
                f"측정 {ab['n_days']}거래일 · 내 평가액 {ab['my_final_krw']:,.0f}원 vs 동일 현금흐름 S&P500 {ab['spy_final_krw']:,.0f}원."
            )
        st.caption(
            "※ 성과 비교는 금액·기간 비중을 반영하는 **XIRR 차이(알파)** 로 일원화되어 있습니다. "
            "베타는 매수·매도 기여금을 제거한 일간 수익률을 S&P500(원화 환산) 수익률에 회귀해 산출합니다."
        )
    else:
        st.info("알파·베타를 계산할 거래 이력이 없습니다.")

    st.divider()

    # ⏸️ 아래 분석 섹션들은 임시 비활성화되어 있습니다. (SHOW_ANALYSIS=True 로 다시 활성화)
    if not SHOW_ANALYSIS:
        st.info("📊 분기별 성과·포트폴리오 PME 성장추이·배당/환차손익·AI 진단 등 **일부 분석 기능은 현재 비활성화** 상태입니다. "
                "거래내역 통합이 완료되면 다시 켤 예정입니다.")

    # 🔖 (5) S&P500 대비 성과 분석 (PME · 매매 타이밍 반영)
    if SHOW_ANALYSIS:
        st.header("4. 📊 S&P500 대비 성과 (매매 타이밍 반영)")
        st.markdown(
            "단순 주가 비교가 아니라, **내가 실제로 매수/매도한 시점·금액을 그대로 S&P500(SPY)에 투자했다면**과 비교하는 "
            "**PME(Public Market Equivalent)** 방식입니다. 매매 타이밍이 반영되어 진짜 초과수익(알파)을 보여줍니다."
        )

        with st.spinner("매매 이력 기반 PME 성과를 계산하는 중입니다... (yfinance 장기 시세)"):
            pme_name_map = {h.get("ticker"): h.get("name") for h in holdings}
            pme_table, pme_growth = fetch_pme_analysis(combined_orders, fx_rate, pme_name_map)

        # 포트폴리오 vs S&P500 PME 성장 추이
        st.markdown("#### 📈 내 포트폴리오 vs S&P500 PME (누적 수익률 %)")
        if pme_growth is not None and not pme_growth.empty:
            ret_cols = ["내 수익률(%)", "S&P500 PME 수익률(%)"]
            rdf = pme_growth.reset_index().rename(columns={"index": "날짜"})
            xcol = rdf.columns[0]
            long_r = rdf.melt(id_vars=xcol, value_vars=ret_cols, var_name="구분", value_name="수익률")
            fig_r = px.line(
                long_r, x=xcol, y="수익률", color="구분",
                labels={xcol: "날짜", "수익률": "누적 수익률(%)"},
                color_discrete_map={"내 수익률(%)": "#EF553B", "S&P500 PME 수익률(%)": "#636EFA"},
            )
            for tr in fig_r.data:
                if "PME" in tr.name:
                    tr.line.dash = "dash"
            st.plotly_chart(fig_r, use_container_width=True)

            my_ret = pme_growth["내 수익률(%)"].iloc[-1]
            spy_ret = pme_growth["S&P500 PME 수익률(%)"].iloc[-1]
            my_final = pme_growth["내 포트폴리오"].iloc[-1]
            spy_final = pme_growth["S&P500 PME"].iloc[-1]
            st.caption(
                f"현재 내 누적 수익률 **{my_ret:.1f}%** vs S&P500 PME **{spy_ret:.1f}%** → "
                f"**타이밍 반영 초과수익 {my_ret - spy_ret:+.1f}%p**. "
                "두 선은 같은 현금흐름을 받으므로 원금 계단은 공유하지만, 벌어지는 간격이 곧 알파입니다."
            )

            with st.expander("💵 절대 평가액(원) 그래프로 보기"):
                adf = pme_growth.reset_index().rename(columns={"index": "날짜"})
                axcol = adf.columns[0]
                long_a = adf.melt(id_vars=axcol, value_vars=["내 포트폴리오", "S&P500 PME", "누적 투자원금"],
                                  var_name="구분", value_name="평가액")
                fig_a = px.line(
                    long_a, x=axcol, y="평가액", color="구분",
                    labels={axcol: "날짜", "평가액": "평가액(원)"},
                    color_discrete_map={"내 포트폴리오": "#EF553B", "S&P500 PME": "#636EFA", "누적 투자원금": "#AAAAAA"},
                )
                for tr in fig_a.data:
                    if tr.name == "S&P500 PME":
                        tr.line.dash = "dash"
                    if tr.name == "누적 투자원금":
                        tr.line.dash = "dot"
                st.plotly_chart(fig_a, use_container_width=True)
                st.caption(f"내 포트폴리오 {my_final:,.0f}원 vs S&P500 PME {spy_final:,.0f}원 (격차 {my_final - spy_final:+,.0f}원)")
        else:
            st.info("성장 추이를 계산하지 못했습니다.")

        # 종목별 PME 초과수익 표
        st.markdown("#### 📋 종목별 S&P500 대비 초과수익 (매매 타이밍 반영)")
        if pme_table is not None and not pme_table.empty:
            st.dataframe(
                pme_table.style.format({
                    "투자원금(원)": "{:,.0f}", "내 수익률(%)": "{:+.2f}",
                    "S&P500 PME(%)": "{:+.2f}", "초과수익(%p)": "{:+.2f}", "초과손익(원)": "{:,.0f}"
                }).background_gradient(cmap="RdYlGn", subset=["초과수익(%p)"]),
                use_container_width=True, hide_index=True, height=430
            )
            st.caption(
                "**내 수익률**: 실제 매수 시점 기준 수익률. **S&P500 PME(%)**: 같은 시점·금액을 SPY에 넣었을 때 수익률. "
                "**초과수익(%p)** 양수(초록)면 S&P500보다 잘한 것입니다. (청산 종목은 매매 시점 기준 잔여 효과로 계산)"
            )
        else:
            st.info("PME 초과수익을 계산하지 못했습니다.")

        st.divider()

    # ⏸️ 아래 분석 섹션(배당·환차·AI)들은 임시 비활성화 — SHOW_ANALYSIS=True 로 다시 켤 수 있음
    if not SHOW_ANALYSIS:
        st.stop()

    # 🔖 (6) 배당 수익 및 환차손익
    st.header("6. 💰 배당 수익 & 환차손익")
    st.markdown("토스 API에는 배당 내역이 없어 **yfinance 배당·환율 데이터**로 추정합니다. (토스+타 증권사 보유 합산)")

    with st.spinner("배당·환율 데이터를 분석하는 중입니다..."):
        div_df, fx_summary, fx_df, inc_fx = fetch_income_analysis(combined_orders, fx_rate)

    total_div = int(div_df["배당수령(원)"].sum()) if div_df is not None and not div_df.empty else 0
    total_fx_pnl = int(fx_summary.get("총_환차손익_원", 0)) if fx_summary else 0

    # 배당 포함 수익률 계산
    purchase_krw = float(summary.get("purchase_krw", 0) or 0)
    eval_krw = float(summary.get("stock_eval_krw", 0) or 0)
    price_pnl = eval_krw - purchase_krw
    base_return = (price_pnl / purchase_krw * 100) if purchase_krw else 0
    total_return_with_div = ((price_pnl + total_div) / purchase_krw * 100) if purchase_krw else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("누적 배당 수령(추정)", f"{total_div:,.0f} ₩")
    m2.metric("가격 수익률", f"{base_return:.2f} %")
    m3.metric("배당 포함 총수익률", f"{total_return_with_div:.2f} %",
              delta=f"{total_return_with_div - base_return:+.2f}%p (배당 기여)")
    m4.metric("누적 환차손익", f"{total_fx_pnl:,.0f} ₩",
              delta="환율 이득" if total_fx_pnl >= 0 else "환율 손실",
              delta_color="normal" if total_fx_pnl >= 0 else "inverse")

    col_d, col_f = st.columns(2)

    with col_d:
        st.markdown("#### 📗 종목별 배당 수령 (추정)")
        if div_df is not None and not div_df.empty:
            st.dataframe(
                div_df.style.format({
                    "배당수령(원본)": "{:,.2f}", "배당수령(원)": "{:,.0f}"
                }),
                use_container_width=True, hide_index=True, height=320
            )
        else:
            st.info("배당 이력이 있는 보유 종목이 없습니다.")

    with col_f:
        st.markdown("#### 💱 종목별 환차손익 (USD 매수분)")
        if fx_df is not None and not fx_df.empty:
            st.dataframe(
                fx_df.style.format({
                    "매수원금(USD)": "{:,.2f}", "평균매수환율": "{:,.1f}",
                    "현재환율": "{:,.1f}", "환차손익(원)": "{:,.0f}"
                }).background_gradient(cmap="RdYlGn", subset=["환차손익(원)"]),
                use_container_width=True, hide_index=True, height=320
            )
            st.caption(
                f"평균 매수환율 {fx_summary.get('평균_매수환율')}원 → 현재 {fx_summary.get('현재환율')}원. "
                "매수 당시보다 원화가 강세면 환차손, 약세면 환차익이 발생합니다."
            )
        else:
            st.info("USD 매수 내역이 없습니다.")

    st.caption("⚠️ 배당은 yfinance 주당 배당 × 배당락일 보유수량 추정치이며, 실제 세후 수령액과 다를 수 있습니다. 환율은 USD/KRW(yfinance) 기준.")

    st.divider()

    # 🔖 (7) AI 코파일럿 진단 리포트 구역
    st.header("7. Gemini AI 퀀트 검진")
    st.markdown("포트폴리오의 비중 쏠림, 시황 반응성 등을 AI 기반으로 분석합니다.")
    
    if st.button("🚀 AI 분석 리포트 받아보기", type="primary"):
        with st.spinner("AI가 데이터를 분석하고 처방전을 쓰고 있습니다... (약 5~10초 소요)"):
            report_text = generate_portfolio_report(portfolio_json)
            
        st.subheader("💡 진단 결과")
        with st.expander("AI 리포트 전체 보기", expanded=True):
            st.markdown(report_text)

    st.divider()

    # 🔖 (8) AI 코파일럿과 대화하기 (챗봇)
    st.header("8. 💬 AI 코파일럿과 대화하기")
    st.markdown("내 포트폴리오와 거래 내역을 바탕으로 자유롭게 질문해 보세요. AI가 필요하면 **토스증권 API로 실시간 시세·S&P500(SPY) 벤치마크를 스스로 조회**해 답합니다.")
    st.caption("예: *내 애플이 S&P500 대비 초과수익 내고 있어?*, *SPY 최근 수익률은?*, *올해 순투자금이 얼마야?*")

    # 대화 이력 초기화
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    # 이전 대화 렌더링
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 대화 초기화 버튼
    if st.session_state.chat_messages:
        if st.button("🗑️ 대화 내용 지우기"):
            st.session_state.chat_messages = []
            st.rerun()

    # 사용자 입력 처리
    if user_input := st.chat_input("포트폴리오에 대해 무엇이든 물어보세요..."):
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("AI가 답변을 작성하고 있습니다..."):
                answer = chat_with_portfolio(
                    user_input,
                    st.session_state.chat_messages[:-1],  # 직전까지의 이력
                    portfolio_json,
                    trades_summary_text
                )
            st.markdown(answer)
        st.session_state.chat_messages.append({"role": "assistant", "content": answer})
