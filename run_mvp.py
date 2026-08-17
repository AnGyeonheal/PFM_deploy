import os
import json
from dotenv import load_dotenv

# 내부 모듈 불러오기
from pm import get_access_token, get_holdings, get_buying_power, get_exchange_rate
from analytics_engine import transform_to_mvp_json
from ai_copilot import generate_portfolio_report

def run_project_mvp():
    """
    구상안 6단계 로드맵 중 
    [1단계 PoC + 2단계 AI 연동 프로토타입]을 수행하는 메인 스크립트입니다.
    """
    load_dotenv()
    
    CLIENT_ID = os.getenv("TOSS_CLIENT_ID")
    CLIENT_SECRET = os.getenv("TOSS_CLIENT_SECRET")
    ACCOUNT_NO = os.getenv("TOSS_ACCOUNT_NO", "1")
    
    print("==================================================")
    print("📈 AI 기반 포트폴리오 성과 검진 MVP 시스템 구동")
    print("==================================================\n")
    
    # 1. Toss 증권 데이터 수집 (Data Collector)
    print("[1/3] Toss Open API 통신 및 계좌 잔고 수집...")
    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    if not token:
        print("토큰 발급 실패로 프로그램을 종료합니다.")
        return
        
    toss_data = get_holdings(token, ACCOUNT_NO)
    if not toss_data:
        print("보유 자산 조회 실패로 프로그램을 종료합니다.")
        return

    # 실제 예수금(KRW + USD 환산) 조회
    krw_cash = get_buying_power(token, ACCOUNT_NO, "KRW")
    usd_cash = get_buying_power(token, ACCOUNT_NO, "USD")
    fx_rate = get_exchange_rate(token)
    cash_krw = krw_cash + usd_cash * fx_rate
    print(f"    예수금: {krw_cash:,.0f}원 + ${usd_cash:,.2f}(환율 {fx_rate:,.1f}) = 총 {cash_krw:,.0f}원")
        
    # 2. 분석 엔진으로 JSON 규격화 (Calculation Engine)
    print("[2/3] 포트폴리오 정량 데이터 처리 (JSON 규격화)...")
    portfolio_json = transform_to_mvp_json("usr_102938", toss_data, cash_krw, fx_rate)
    
    print("\n--- 생성된 JSON 규격 구조 ---")
    print(json.dumps(portfolio_json, indent=2, ensure_ascii=False))
    print("------------------------------\n")
    
    # 3. AI 코파일럿 진단 리포트 발급 (AI Intelligence)
    print("[3/3] Gemini API 연동 및 맞춤형 리밸런싱 리포트 작성...")
    report = generate_portfolio_report(portfolio_json)
    
    print("\n================ [ AI 진단 리포트 ] ================\n")
    print(report)
    print("\n====================================================")


if __name__ == "__main__":
    run_project_mvp()
