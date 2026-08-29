import os
import time
import requests
import json
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 토큰 발급 타임아웃: (연결 5s, 응답 15s). Akamai CDN 경유로 응답이 느릴 수 있어 read를 넉넉히 둠.
TOKEN_TIMEOUT = (5, 15)

def get_access_token(client_id, client_secret, retries=1):
    """1) 토큰 발급. 일시적 타임아웃/연결 오류는 retries 회 재시도."""
    url = 'https://openapi.tossinvest.com/oauth2/token'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret
    }

    for attempt in range(retries + 1):
        try:
            response = requests.post(url, headers=headers, data=data, timeout=TOKEN_TIMEOUT)
            response.raise_for_status()  # 200번대가 아니면 에러 발생
            return response.json().get('access_token')
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 401:
                print("[에러] 인증 실패 (401): Client ID 또는 Secret Key를 확인하세요.")
            elif status == 429:
                print("[에러] 요청 초과 (429): API 호출 한도를 초과했습니다.")
            else:
                print(f"[에러] HTTP 에러 발생: {status}")
            print(f"상세 메시지: {e.response.text}")
            return None  # 인증/요청 오류는 재시도해도 동일하므로 즉시 종료
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < retries:
                time.sleep(1.0)
                continue
            print("[에러] 토큰 서버 연결 실패(타임아웃): openapi.tossinvest.com 접속이 "
                  "사내 방화벽/네트워크에 의해 차단되었거나, 토스에 등록된 허용 IP가 아닐 수 있습니다.")
            print(f"상세: {type(e).__name__}")
        except requests.exceptions.RequestException as e:
            print(f"[에러] 네트워크 예외 발생: {e}")
            return None
    return None

def get_stock_info(access_token, symbol="005930"):
    """2) 시세·종목 정보 (토큰만 필요)"""
    url = f'https://openapi.tossinvest.com/api/v1/stocks?symbols={symbol}'
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"[에러] 종목 정보 조회 실패: {e.response.status_code}")
    except Exception as e:
        print(f"[에러] 조회 중 예외 발생: {e}")
    return None

def get_holdings(access_token, account="1"):
    """3) 계좌·자산 / 주문 (토큰 + 계좌 헤더)"""
    url = 'https://openapi.tossinvest.com/api/v1/holdings'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'X-Tossinvest-Account': account
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"[에러] 계좌/자산 조회 실패: {e.response.status_code}")
    except Exception as e:
        print(f"[에러] 계좌 조회 중 예외 발생: {e}")
    return None

def get_accounts(access_token):
    """4) 계좌 목록 조회 (실제 accountSeq 확인)"""
    url = 'https://openapi.tossinvest.com/api/v1/accounts'
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        return response.json().get("result", [])
    except requests.exceptions.HTTPError as e:
        print(f"[에러] 계좌 목록 조회 실패: {e.response.status_code}")
    except Exception as e:
        print(f"[에러] 계좌 목록 조회 중 예외 발생: {e}")
    return []

def get_buying_power(access_token, account="1", currency="KRW"):
    """5) 매수 가능 금액(예수금/현금) 조회"""
    url = 'https://openapi.tossinvest.com/api/v1/buying-power'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'X-Tossinvest-Account': account
    }
    try:
        response = requests.get(url, headers=headers, params={'currency': currency}, timeout=5)
        response.raise_for_status()
        result = response.json().get("result", {})
        return float(result.get("cashBuyingPower", 0))
    except requests.exceptions.HTTPError as e:
        print(f"[에러] 예수금({currency}) 조회 실패: {e.response.status_code}")
    except Exception as e:
        print(f"[에러] 예수금 조회 중 예외 발생: {e}")
    return 0.0

def get_exchange_rate(access_token):
    """6) 원/달러 환율 조회 (USD 자산 환산용)"""
    url = 'https://openapi.tossinvest.com/api/v1/exchange-rate'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'baseCurrency': 'USD', 'quoteCurrency': 'KRW'}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        response.raise_for_status()
        result = response.json().get("result", {})
        return float(result.get("rate", 1400.0))
    except Exception as e:
        print(f"[경고] 환율 조회 실패, 기본값 사용: {e}")
    return 1400.0

def get_candles(access_token, symbol, interval="1d", count=200):
    """8) 종목/ETF 캔들(일봉·분봉) 조회. interval은 '1d' 또는 '1m'. 최대 count=200.
    S&P500 벤치마크는 SPY(SPDR S&P 500 ETF) 심볼을 사용하면 됩니다.
    반환: [{timestamp, openPrice, highPrice, lowPrice, closePrice, volume, currency}, ...] (최신순)"""
    url = 'https://openapi.tossinvest.com/api/v1/candles'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'symbol': symbol, 'interval': interval, 'count': min(int(count), 200)}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=8)
        response.raise_for_status()
        return response.json().get("result", {}).get("candles", [])
    except Exception as e:
        print(f"[에러] 캔들({symbol}) 조회 실패: {e}")
    return []

def get_current_price(access_token, symbol):
    """9) 종목 현재가 조회. 반환: 현재가(float) 또는 None"""
    url = 'https://openapi.tossinvest.com/api/v1/prices'
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        response = requests.get(url, headers=headers, params={'symbols': symbol}, timeout=5)
        response.raise_for_status()
        result = response.json().get("result", [])
        if result:
            r0 = result[0]
            for key in ("price", "closePrice", "lastPrice", "currentPrice"):
                if r0.get(key) is not None:
                    return float(r0[key])
    except Exception as e:
        print(f"[에러] 현재가({symbol}) 조회 실패: {e}")
    return None

def get_current_prices(access_token, symbols, chunk=50):
    """9-2) 여러 종목 현재가를 한 번에 조회(배치). 반환: {symbol: 현재가(float)}.
    보유 종목 실시간 시세를 한 번의 호출로 받아 대시보드 싱크로율을 높입니다."""
    url = 'https://openapi.tossinvest.com/api/v1/prices'
    headers = {'Authorization': f'Bearer {access_token}'}
    syms = [str(s) for s in dict.fromkeys(symbols) if s]  # 중복 제거·순서 유지
    out = {}
    for i in range(0, len(syms), chunk):
        batch = syms[i:i + chunk]
        try:
            response = requests.get(url, headers=headers,
                                    params={'symbols': ",".join(batch)}, timeout=8)
            response.raise_for_status()
            for r0 in response.json().get("result", []):
                sym = r0.get("symbol")
                for key in ("price", "lastPrice", "closePrice", "currentPrice"):
                    if r0.get(key) is not None:
                        try:
                            out[sym] = float(r0[key])
                        except (TypeError, ValueError):
                            pass
                        break
        except Exception as e:
            print(f"[에러] 배치 현재가 조회 실패({batch[:3]}…): {e}")
    return out

def get_order_history(access_token, account="1", max_pages=50):
    """7) 체결 완료된 주문(매수/매도) 전체 이력 조회 (페이지네이션)"""
    url = 'https://openapi.tossinvest.com/api/v1/orders'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'X-Tossinvest-Account': account
    }
    all_orders = []
    cursor = None
    for _ in range(max_pages):
        params = {'status': 'CLOSED'}
        if cursor:
            params['cursor'] = cursor
        try:
            response = requests.get(url, headers=headers, params=params, timeout=5)
            if response.status_code == 429:
                time.sleep(1.2)  # 초당 1회 제한 대응
                continue
            response.raise_for_status()
            result = response.json().get("result", {})
            all_orders.extend(result.get("orders", []))
            if not result.get("hasNext"):
                break
            cursor = result.get("nextCursor")
            time.sleep(1.1)  # 계좌 API 초당 1회 제한 준수
        except Exception as e:
            print(f"[에러] 주문 이력 조회 중 예외 발생: {e}")
            break
    return all_orders

if __name__ == "__main__":
    # 환경변수(.env)에서 키 값을 안전하게 불러오기
    CLIENT_ID = os.getenv("TOSS_CLIENT_ID")
    CLIENT_SECRET = os.getenv("TOSS_CLIENT_SECRET")
    ACCOUNT_NO = os.getenv("TOSS_ACCOUNT_NO", "1")
    
    if not CLIENT_ID or not CLIENT_SECRET:
        print("[오류] .env 파일에서 TOSS_CLIENT_ID 또는 TOSS_CLIENT_SECRET을 찾을 수 없습니다.")
        exit(1)
        
    print("=== 1. 토큰 발급 ===")
    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    
    if token:
        print(f"발급된 토큰: {token[:10]}...\n")
        
        print("=== 2. 삼성전자(005930) 시세조회 ===")
        stock_info = get_stock_info(token, "005930")
        if stock_info:
            print(json.dumps(stock_info, indent=2, ensure_ascii=False), "\n")
        
        print("=== 3. 계좌/잔고 조회 ===")
        holdings_info = get_holdings(token, ACCOUNT_NO)
        if holdings_info:
            print(json.dumps(holdings_info, indent=2, ensure_ascii=False), "\n")
