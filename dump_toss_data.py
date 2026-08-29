"""토스증권 Open API로 받아오는 모든 데이터를 한눈에 출력하는 점검 스크립트.
.env의 TOSS_CLIENT_ID / TOSS_CLIENT_SECRET / TOSS_ACCOUNT_NO 를 사용합니다.

실행: python dump_toss_data.py
개별 종목 시세를 보고 싶으면: python dump_toss_data.py 005930
"""
import json
import os
import sys

from dotenv import load_dotenv

from pm import (
    get_access_token, get_accounts, get_holdings, get_buying_power,
    get_exchange_rate, get_order_history, get_stock_info,
    get_current_price, get_candles,
)

load_dotenv()


def _dump(title, data):
    print("\n" + "=" * 60)
    print(f"■ {title}")
    print("=" * 60)
    if data is None:
        print("(데이터 없음 / 조회 실패)")
    elif isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(data)


def main():
    client_id = os.getenv("TOSS_CLIENT_ID")
    client_secret = os.getenv("TOSS_CLIENT_SECRET")
    account = os.getenv("TOSS_ACCOUNT_NO", "1")
    sample_symbol = sys.argv[1] if len(sys.argv) > 1 else "005930"  # 기본: 삼성전자

    if not client_id or not client_secret or client_id == "your_toss_client_id":
        print("[오류] .env 에 실제 TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 을 먼저 입력하세요.")
        sys.exit(1)

    print("토스증권 API 데이터 덤프를 시작합니다...")
    token = get_access_token(client_id, client_secret)
    if not token:
        print("[오류] 토큰 발급 실패 — API 키와 토스 콘솔의 허용 IP 등록을 확인하세요.")
        sys.exit(1)
    print(f"토큰 발급 성공: {token[:10]}...")

    # 1) 계좌 목록
    _dump("계좌 목록 (get_accounts)", get_accounts(token))

    # 2) 계좌·보유자산
    _dump(f"계좌/보유자산 (get_holdings, account={account})", get_holdings(token, account))

    # 3) 예수금(현금) — 원화/달러
    _dump("예수금 KRW (get_buying_power)", get_buying_power(token, account, "KRW"))
    _dump("예수금 USD (get_buying_power)", get_buying_power(token, account, "USD"))

    # 4) 환율
    _dump("원/달러 환율 (get_exchange_rate)", get_exchange_rate(token))

    # 5) 체결 주문 이력 (요약: 건수 + 첫 3건 원본)
    orders = get_order_history(token, account)
    _dump("체결 주문 이력 (get_order_history)", {
        "총_체결건수": len(orders),
        "샘플_최근3건": orders[:3],
    })

    # 6) 종목 시세/정보
    _dump(f"종목 정보 (get_stock_info, {sample_symbol})", get_stock_info(token, sample_symbol))
    _dump(f"현재가 (get_current_price, {sample_symbol})", get_current_price(token, sample_symbol))

    # 7) 일봉 캔들 (최근 5개만 미리보기)
    candles = get_candles(token, sample_symbol, interval="1d", count=200)
    _dump(f"일봉 캔들 (get_candles, {sample_symbol})", {
        "총_캔들수": len(candles),
        "샘플_최근5개": candles[:5],
    })

    print("\n완료: 위 항목이 토스증권 API로 받아오는 데이터 전체입니다.")


if __name__ == "__main__":
    main()
