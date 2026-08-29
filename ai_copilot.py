import os
import json
import time
import google.generativeai as genai
from dotenv import load_dotenv

from pm import (
    get_access_token, get_holdings, get_order_history,
    get_candles, get_current_price, get_exchange_rate,
)

# Gemini API 키는 코드에 하드코딩하지 않습니다(공개 저장소 노출 방지).
# 로컬은 .env, Streamlit Cloud는 Secrets(app.py에서 os.environ으로 브리지)에서 읽습니다.
load_dotenv()

# 무료 한도(429/RPM) 대비: 여러 모델을 순서대로 폴백 (각 모델은 별도 한도 버킷).
# '-latest' 별칭은 최신 안정 모델을 자동 추종하며, lite 계열이 무료 한도가 넉넉합니다.
MODEL_CHAIN = [
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]


def _is_quota_error(err):
    s = str(err).lower()
    return "429" in s or "quota" in s or "rate" in s or "exhaust" in s


def _generate_with_fallback(prompt, system_instruction=None, tools=None, max_retry=2):
    """모델 폴백 + 429 재시도로 generate_content를 호출합니다.
    반환: (response 또는 None, 에러메시지 또는 None)"""
    last_err = None
    for model_name in MODEL_CHAIN:
        for attempt in range(max_retry):
            try:
                model = genai.GenerativeModel(
                    model_name, system_instruction=system_instruction, tools=tools
                )
                return model.generate_content(prompt), None
            except Exception as e:
                last_err = e
                if _is_quota_error(e):
                    time.sleep(2 * (attempt + 1))  # 백오프 후 재시도
                    continue
                break  # 한도 외 에러는 다음 모델로
    return None, last_err

def generate_portfolio_report(portfolio_json):
    """
    Gemini API를 호출하여 입력된 JSON 포트폴리오 데이터를 바탕으로 
    AI 진단 리포트를 생성합니다.
    """
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "여기에_발급받으신_Gemini_API_Key를_입력하세요":
        return "[오류] .env 파일에 유효한 GEMINI_API_KEY가 없습니다. 설정 후 다시 시도해주세요."
        
    genai.configure(api_key=gemini_key, transport="rest")

    prompt = f"""
    당신은 퀀트 분석가이자 인공지능 자산 관리(Copilot) 시스템입니다. 
    다음 제공되는 JSON 형태의 포트폴리오 정량 데이터를 분석하여 아래 내용이 포함된 리포트를 마크다운 형식으로 작성해주세요.
    
    [요청 사항]
    1. 자산 배분 균형도 평가 (위험 집중도, 섹터 편향 등)
    2. 벤치마크(S&P 500) 성과 대비 초과 수익 분석 (PME 알파 등)
    3. 리스트 진단 및 시장 상황에 따른 리밸런싱 방향 제안
    4. 친절하고 전문가적인 톤 앤 매너 유지
    
    [포트폴리오 정량 데이터]
    {json.dumps(portfolio_json, ensure_ascii=False, indent=2)}
    """
    
    print("🤖 Gemini AI가 포트폴리오를 분석 중입니다...")
    response, err = _generate_with_fallback(prompt)
    if response is not None:
        return response.text
    if _is_quota_error(err):
        return "⚠️ Gemini 무료 사용량(하루 한도)을 초과했습니다. 잠시 후 다시 시도하거나 API 한도를 확인해 주세요."
    return f"AI 분석 중 에러가 발생했습니다: {err}"


def generate_rebalancing_report(portfolio_json, metrics=None, perf=None, extra_context=None):
    """알파(초과수익)와 베타(시장 민감도) 관점에서 포트폴리오를 진단하고
    구체적인 리밸런싱 방향을 제안하는 마크다운 리포트를 생성합니다.

    portfolio_json: 보유/요약 데이터
    metrics: compute_alpha_beta 결과 dict (port_xirr_pct, spy_xirr_pct, alpha_pct, beta, corr, n_days)
    perf: compute_performance_summary 결과 dict (선택)
    extra_context: 추가 컨텍스트 문자열(선택)
    """
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "여기에_발급받으신_Gemini_API_Key를_입력하세요":
        return "[오류] .env 파일 또는 API 키 설정에 유효한 GEMINI_API_KEY가 없습니다. 설정 후 다시 시도해주세요."

    genai.configure(api_key=gemini_key, transport="rest")

    metrics = metrics or {}
    metrics_txt = json.dumps(metrics, ensure_ascii=False, indent=2)
    perf_txt = json.dumps(perf, ensure_ascii=False, indent=2) if perf else "제공되지 않음"

    prompt = f"""
당신은 퀀트 포트폴리오 매니저이자 리스크 분석가입니다.
아래 사용자의 포트폴리오 데이터와 정량 지표를 바탕으로, **알파(초과수익)와 베타(시장 민감도) 관점**에서
포트폴리오를 진단하고 리밸런싱 방향을 제안하는 리포트를 한국어 마크다운으로 작성하세요.

반드시 아래 구조(제목 그대로)로 작성하세요:

## 1. 종합 진단
- 현재 알파(S&P500 대비 초과 XIRR)와 베타를 해석하세요. 알파가 양수/음수인지, 베타가 1보다 큰지 작은지에 따라
  이 포트폴리오가 "시장을 이기고 있는지", "시장보다 공격적/방어적인지"를 명확히 판정하세요.
- 상관계수(corr)로 시장 동조화 수준도 함께 언급하세요.

## 2. 알파 관점 (초과수익 개선)
- 어떤 종목/섹터가 알파에 기여하거나 갉아먹는지 추론하고, 알파를 높이기 위한 조정(비중 확대/축소, 교체)을 제안하세요.
- 비중이 과도하게 쏠린 종목의 리스크와, 벤치마크 대비 부진 종목의 처리 방향을 제시하세요.

## 3. 베타 관점 (리스크·시장 민감도 조절)
- 목표 베타를 어느 수준으로 가져갈지(예: 공격적 1.1~1.3, 중립 0.9~1.1, 방어적 0.7~0.9) 시나리오로 제안하세요.
- 베타를 낮추려면/높이려면 어떤 유형의 자산(저베타 배당주·현금·채권형 vs 고베타 성장주)을 늘리고 줄여야 하는지 구체적으로 쓰세요.

## 4. 실행 제안 (리밸런싱 액션)
- "종목 A 비중 X% → Y%" 형태의 **구체적이고 실행 가능한** 조정안을 3~6개 제시하세요(대략치라도 방향과 크기를 명시).
- 각 액션이 알파와 베타에 미치는 예상 효과를 한 줄로 덧붙이세요.

## 5. 유의사항
- 데이터 추정의 한계와, 투자 자문이 아닌 참고용임을 간단히 명시하세요.

작성 규칙:
- 전문적이되 이해하기 쉽게. 숫자는 데이터에 근거해 인용하세요(임의 창작 금지).
- 표는 사용하지 말고, 제목과 불릿(-)만 사용하세요.

[정량 지표 (알파/베타/XIRR/상관계수)]
{metrics_txt}

[손익 요약]
{perf_txt}

[포트폴리오 보유/요약 데이터]
{json.dumps(portfolio_json, ensure_ascii=False, indent=2)}
"""
    if extra_context:
        prompt += f"\n[추가 컨텍스트]\n{extra_context}\n"

    print("🤖 Gemini AI가 알파/베타 리밸런싱 리포트를 작성 중입니다...")
    response, err = _generate_with_fallback(prompt)
    if response is not None:
        return response.text
    if _is_quota_error(err):
        return "⚠️ Gemini 무료 사용량(하루 한도)을 초과했습니다. 잠시 후 다시 시도해 주세요."
    return f"AI 리밸런싱 분석 중 에러가 발생했습니다: {err}"


def parse_brokerage_transactions(raw_text, broker_name="증권사"):
    """증권사에서 다운로드한 거래내역(원본 텍스트/CSV)을 Gemini로 파싱해
    표준 보유 종목 스키마(JSON 리스트)로 변환합니다.
    반환 스키마: [{"증권사","티커","종목명","시장","수량","평균매수가","통화","매수일"}, ...]
    """
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "여기에_발급받으신_Gemini_API_Key를_입력하세요":
        return None, "[오류] .env 파일에 유효한 GEMINI_API_KEY가 없습니다."

    genai.configure(api_key=gemini_key, transport="rest")

    prompt = f"""
당신은 증권사 거래내역/잔고 파일을 표준 포맷으로 변환하는 데이터 파서입니다.
아래 '{broker_name}'에서 받은 원본 데이터를 분석해서, **현재 실제 보유 중인** 종목 목록을 JSON 배열로만 출력하세요.

각 원소는 아래 필드를 가져야 합니다:
- "증권사": "{broker_name}"
- "티커": 종목코드 (국내는 6자리 숫자 예 "005930", 미국은 심볼 예 "AAPL")
- "종목명": 한글 또는 영문 종목명
- "시장": "KOSPI" | "KOSDAQ" | "US" 중 하나
- "수량": 현재 순보유 수량 (숫자)
- "평균매수가": 평균 매입 단가 (숫자, 통화 단위 그대로)
- "통화": "KRW" | "USD"
- "매수일": "YYYY-MM-DD" 형식 (알 수 없으면 빈 문자열 "")

⚠️ 수량 계산 규칙 (매우 중요):
1. 데이터에 **잔고(보유수량)** 컬럼이 있으면 그 값을 그대로 '수량'으로 사용하세요. 거래내역을 합산하지 마세요.
2. 거래내역만 있으면 **(매수 수량 합계 − 매도 수량 합계) = 순보유 수량**으로 계산하세요. 절대 매수만 더하지 마세요.
3. '체결금액'이나 '거래대금'을 평균단가로 나눠서 수량을 만들지 마세요. 반드시 '수량/체결수량' 컬럼의 값을 쓰세요.
4. 계산 결과 순보유 수량이 0 이하이면 그 종목은 제외하세요.
5. 국내 주식 수량은 보통 정수입니다. 소수점 수량이 나오면 계산이 잘못된 것이니 다시 확인하세요.

기타:
- 반드시 JSON 배열만 출력하세요. 설명, 마크다운 코드펜스(```) 없이 순수 JSON만.

[원본 데이터]
{raw_text[:12000]}
"""
    response, err = _generate_with_fallback(prompt)
    if response is None:
        if _is_quota_error(err):
            return None, "⚠️ Gemini 무료 사용량(하루 한도)을 초과했습니다. 잠시 후 다시 시도해 주세요."
        return None, f"거래내역 파싱 중 에러: {err}"
    try:
        text = (response.text or "").strip()
        # 코드펜스 제거
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("result") or data.get("holdings") or []
        return data, None
    except json.JSONDecodeError:
        return None, f"AI 응답을 JSON으로 변환하지 못했습니다. 원본 형식을 확인하세요.\n응답: {text[:300]}"
    except Exception as e:
        return None, f"거래내역 파싱 중 에러: {e}"


def parse_brokerage_full_transactions(raw_text, broker_name="증권사"):
    """증권사 거래내역 파일을 개별 매매(매수/매도) 트랜잭션 목록으로 파싱합니다.
    청산된 종목도 포함하여 모든 체결 내역을 반환합니다.
    반환 스키마: [{"증권사","일자","티커","종목명","시장","구분(매수/매도)","수량","단가","통화"}, ...]
    """
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "여기에_발급받으신_Gemini_API_Key를_입력하세요":
        return None, "[오류] .env 파일에 유효한 GEMINI_API_KEY가 없습니다."

    genai.configure(api_key=gemini_key, transport="rest")

    prompt = f"""
당신은 증권사 '거래내역(체결내역)' 파일을 개별 매매 트랜잭션으로 변환하는 데이터 파서입니다.
아래 '{broker_name}'의 원본 거래내역을 분석해서, **모든 개별 체결(매수/매도)** 을 JSON 배열로만 출력하세요.

각 원소(트랜잭션 1건)는 아래 필드를 가집니다:
- "증권사": "{broker_name}"
- "일자": 체결일 "YYYY-MM-DD"
- "티커": 종목코드 (국내 6자리 숫자 "005930", 미국 심볼 "AAPL")
- "종목명": 종목명
- "시장": "KOSPI" | "KOSDAQ" | "US"
- "구분": "매수" | "매도"
- "수량": 체결 수량 (숫자)
- "단가": 체결 단가 (숫자, 통화 단위 그대로)
- "통화": "KRW" | "USD"

⚠️ 매우 중요:
1. **매수·매도 모든 체결을 각각 1건씩** 출력하세요. 종목별로 합치지 말고 개별 거래를 그대로 나열하세요.
2. **이미 전량 매도(청산)한 종목의 거래도 반드시 포함**하세요. 절대 제외하지 마세요.
3. 입출금·배당·수수료만 있는 행은 제외하고, 실제 주식 매수/매도 체결만 포함하세요.
4. 반드시 JSON 배열만 출력하세요. 설명, 코드펜스(```) 없이 순수 JSON만.

[원본 거래내역]
{raw_text[:14000]}
"""
    response, err = _generate_with_fallback(prompt)
    if response is None:
        if _is_quota_error(err):
            return None, "⚠️ Gemini 무료 사용량(하루 한도)을 초과했습니다. 잠시 후 다시 시도해 주세요."
        return None, f"거래내역 파싱 중 에러: {err}"
    try:
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("result") or data.get("transactions") or []
        return data, None
    except json.JSONDecodeError:
        return None, f"AI 응답을 JSON으로 변환하지 못했습니다. 원본 형식을 확인하세요.\n응답: {text[:300]}"
    except Exception as e:
        return None, f"거래내역 파싱 중 에러: {e}"


def parse_brokerage_dividends(raw_text, broker_name="증권사"):
    """증권사 거래내역/입출금 내역에서 '배당금/분배금' 수령 기록만 추출합니다.
    반환 스키마: [{"증권사","일자","티커","종목명","통화","배당금"}, ...]
    """
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "여기에_발급받으신_Gemini_API_Key를_입력하세요":
        return None, "[오류] .env 파일에 유효한 GEMINI_API_KEY가 없습니다."

    genai.configure(api_key=gemini_key, transport="rest")

    prompt = f"""
당신은 증권사 거래내역/입출금 파일에서 '배당금·분배금 수령' 기록만 뽑아내는 데이터 파서입니다.
아래 '{broker_name}'의 원본에서 **실제로 입금된 배당금/분배금(distribution)** 항목만 JSON 배열로 출력하세요.

각 원소(배당 1건)의 필드:
- "증권사": "{broker_name}"
- "일자": 배당 입금일 "YYYY-MM-DD"
- "티커": 종목코드 (국내 6자리 "005930", 미국 심볼 "AAPL", ETF는 그 심볼 예 "MSTY")
- "종목명": 종목/ETF 이름
- "통화": "KRW" | "USD"
- "배당금": 실제 수령 금액 (숫자, 통화 단위 그대로. 세금 공제 후 실수령액이 있으면 그 값)

⚠️ 매우 중요:
1. **배당금·분배금 입금 행만** 포함하세요. 주식 매수/매도, 예수금 입출금, 수수료 행은 제외합니다.
2. 같은 종목이라도 **입금일이 다르면 각각 별도 건**으로 나열하세요(합치지 마세요).
3. 금액은 부호 없는 양수로, 통화 단위(원/달러) 그대로 적으세요.
4. 배당 기록이 전혀 없으면 빈 배열 []을 출력하세요.
5. 반드시 JSON 배열만 출력하세요. 설명·코드펜스(```) 없이 순수 JSON만.

[원본 데이터]
{raw_text[:14000]}
"""
    response, err = _generate_with_fallback(prompt)
    if response is None:
        if _is_quota_error(err):
            return None, "⚠️ Gemini 무료 사용량(하루 한도)을 초과했습니다. 잠시 후 다시 시도해 주세요."
        return None, f"배당 파싱 중 에러: {err}"
    try:
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("result") or data.get("dividends") or []
        return data, None
    except json.JSONDecodeError:
        return None, f"AI 응답을 JSON으로 변환하지 못했습니다. 원본 형식을 확인하세요.\n응답: {text[:300]}"
    except Exception as e:
        return None, f"배당 파싱 중 에러: {e}"


def review_toss_transactions(orders, name_map=None):
    """토스 API로 가져온 거래 체결내역을 Gemini로 교차 점검해 이상 징후를 찾습니다.
    데이터 무결성(체결금액 불일치·선행 매수 없는 매도·중복·비정상 단가·통화 불일치 등)을 검토합니다.
    반환: (dict{"summary": str, "issues": [ {...} ]} 또는 None, 에러메시지 또는 None)
    """
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "여기에_발급받으신_Gemini_API_Key를_입력하세요":
        return None, "[오류] .env 파일 또는 API 키 설정에 유효한 GEMINI_API_KEY가 없습니다."

    genai.configure(api_key=gemini_key, transport="rest")

    name_map = name_map or {}
    lines = []
    for o in orders or []:
        ex = o.get("execution") or {}
        sym = o.get("symbol")
        lines.append("|".join(str(x) for x in [
            sym, name_map.get(sym, sym), o.get("side"), o.get("currency", "KRW"),
            ex.get("filledQuantity"), ex.get("averageFilledPrice"),
            ex.get("filledAmount"), ex.get("commission"), ex.get("tax"),
            ex.get("filledAt") or o.get("orderedAt"),
        ]))
    if not lines:
        return None, "점검할 토스 거래내역이 없습니다."
    data_text = ("심볼|종목명|구분|통화|체결수량|체결단가|체결금액|수수료|세금|체결시각\n"
                 + "\n".join(lines[:400]))

    prompt = f"""
당신은 증권 거래내역의 데이터 무결성을 점검하는 감사(audit) 전문가입니다.
아래는 토스증권 API에서 가져온 체결 거래내역입니다. 각 행은 개별 체결 1건이며 '|'로 구분됩니다.
데이터를 분석해 **이상 징후·오류 가능성**을 찾아내세요.

점검 항목:
1. 체결금액 불일치: 체결금액 ≈ 체결수량 × 체결단가 인지. 크게 어긋나면 이상.
2. 선행 매수 없는 매도: 특정 종목의 누적 매수 수량보다 매도 수량이 많은지(공매도/데이터 누락 의심).
3. 중복 의심: 동일 종목·구분·수량·금액·시각이 반복되는 체결.
4. 비정상 단가/수량: 0 이하, 비현실적으로 크거나 작은 값, 자릿수 이상.
5. 통화 불일치: 국내(6자리 숫자 코드) 종목인데 USD, 미국 종목인데 KRW 등.
6. 시각 이상: 미래 날짜, 파싱 불가.

반드시 아래 JSON만 출력하세요(설명·코드펜스 없이):
{{
  "summary": "전체 점검 요약 1~3문장",
  "issues": [
    {{"심각도": "높음|중간|낮음", "티커": "종목코드", "종목명": "이름", "유형": "점검항목", "설명": "무엇이 왜 이상한지", "근거": "관련 수치/시각"}}
  ]
}}
이상이 없으면 issues는 빈 배열로 두고 summary에 정상임을 적으세요.

[거래내역]
{data_text}
"""
    response, err = _generate_with_fallback(prompt)
    if response is None:
        if _is_quota_error(err):
            return None, "⚠️ Gemini 무료 사용량(하루 한도)을 초과했습니다. 잠시 후 다시 시도해 주세요."
        return None, f"거래내역 점검 중 에러: {err}"
    try:
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            data = {"summary": "", "issues": data if isinstance(data, list) else []}
        data.setdefault("summary", "")
        data.setdefault("issues", [])
        return data, None
    except json.JSONDecodeError:
        return None, f"AI 응답을 JSON으로 변환하지 못했습니다.\n응답: {text[:300]}"
    except Exception as e:
        return None, f"거래내역 점검 중 에러: {e}"


def _build_toss_tools(token, account="1"):
    """Gemini가 자율적으로 호출할 수 있는 토스증권 API 도구 함수들을 생성합니다."""

    def get_current_stock_price(symbol: str) -> str:
        """특정 종목/ETF의 현재가를 토스증권 API로 조회합니다.
        symbol: 종목 티커 (예: 'AAPL', '005930', S&P500 벤치마크는 'SPY').
        반환: 현재가와 통화 정보 문자열."""
        price = get_current_price(token, symbol)
        if price is None:
            return f"{symbol}의 현재가를 조회하지 못했습니다."
        return f"{symbol} 현재가: {price}"

    def get_daily_price_history(symbol: str, count: int = 60) -> str:
        """종목/ETF의 일봉(종가) 과거 데이터를 토스증권 API로 조회합니다.
        S&P500 벤치마크가 필요하면 symbol='SPY'(SPDR S&P 500 ETF)를 사용하세요.
        symbol: 종목 티커. count: 가져올 일수(최대 200, 최신순).
        반환: '날짜=종가' 목록 문자열."""
        candles = get_candles(token, symbol, "1d", min(int(count), 200))
        if not candles:
            return f"{symbol}의 일봉 데이터를 조회하지 못했습니다."
        lines = [f"{c['timestamp'][:10]}={c['closePrice']}" for c in candles]
        return f"{symbol} 일봉 종가(최신순, {len(lines)}개):\n" + ", ".join(lines)

    def get_benchmark_return(symbol: str, count: int = 60) -> str:
        """지정 기간 동안 종목 또는 벤치마크(SPY)의 수익률(%)을 계산합니다.
        symbol: 종목 티커 (S&P500은 'SPY'). count: 기간(일, 최대 200).
        반환: 기간 시작/종료 종가와 수익률(%)."""
        candles = get_candles(token, symbol, "1d", min(int(count), 200))
        if len(candles) < 2:
            return f"{symbol}의 수익률 계산에 필요한 데이터가 부족합니다."
        newest = float(candles[0]["closePrice"])
        oldest = float(candles[-1]["closePrice"])
        ret = (newest / oldest - 1) * 100 if oldest else 0
        return (f"{symbol}: {candles[-1]['timestamp'][:10]} 종가 {oldest} → "
                f"{candles[0]['timestamp'][:10]} 종가 {newest}, 수익률 {ret:.2f}%")

    def get_my_holdings_detail() -> str:
        """사용자의 현재 보유 주식 상세(종목별 수량·평가금액·손익)를 토스증권 API로 조회합니다."""
        data = get_holdings(token, account)
        if not data:
            return "보유 주식 데이터를 조회하지 못했습니다."
        items = data.get("result", {}).get("items", [])
        lines = []
        for it in items:
            pl = it.get("profitLoss", {})
            lines.append(
                f"{it.get('name')}({it.get('symbol')}): 수량 {it.get('quantity')}, "
                f"평가액 {it.get('marketValue', {}).get('amount')} {it.get('currency')}, "
                f"수익률 {float(pl.get('rate', 0)) * 100:.2f}%"
            )
        return "보유 종목 상세:\n" + "\n".join(lines)

    def get_my_trade_history(limit: int = 30) -> str:
        """사용자의 최근 체결(매수/매도) 거래 이력을 토스증권 API로 조회합니다.
        limit: 반환할 최근 거래 건수."""
        orders = get_order_history(token, account)
        filled = [o for o in orders if float((o.get("execution") or {}).get("filledAmount") or 0) > 0]
        filled.sort(key=lambda o: (o.get("execution") or {}).get("filledAt") or "", reverse=True)
        lines = []
        for o in filled[:int(limit)]:
            ex = o.get("execution", {})
            side = "매수" if o.get("side") == "BUY" else "매도"
            lines.append(
                f"{(ex.get('filledAt') or '')[:10]} {o.get('symbol')} {side} "
                f"{ex.get('filledQuantity')}주 @ {ex.get('averageFilledPrice')} {o.get('currency')}"
            )
        return f"최근 거래 {len(lines)}건:\n" + "\n".join(lines)

    return [
        get_current_stock_price,
        get_daily_price_history,
        get_benchmark_return,
        get_my_holdings_detail,
        get_my_trade_history,
    ]


def chat_with_portfolio(user_message, chat_history, portfolio_json, trades_summary=None):
    """
    포트폴리오/거래 데이터를 컨텍스트로 삼아 Gemini와 대화합니다.
    Gemini가 필요 시 토스증권 API 도구를 스스로 호출해 실시간 데이터를 찾습니다.
    - user_message: 사용자의 이번 질문
    - chat_history: [{"role": "user"/"assistant", "content": str}, ...] 이전 대화
    - portfolio_json: 보유 자산 요약 JSON
    - trades_summary: 분기별 거래 요약 등 추가 컨텍스트(선택)
    반환: AI 응답 문자열
    """
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "여기에_발급받으신_Gemini_API_Key를_입력하세요":
        return "[오류] .env 파일에 유효한 GEMINI_API_KEY가 없습니다. 설정 후 다시 시도해주세요."

    genai.configure(api_key=gemini_key, transport="rest")

    # 토스 API 도구 준비 (토큰 발급)
    tools = None
    client_id = os.getenv("TOSS_CLIENT_ID")
    client_secret = os.getenv("TOSS_CLIENT_SECRET")
    account = os.getenv("TOSS_ACCOUNT_NO", "1")
    token = get_access_token(client_id, client_secret) if client_id and client_secret else None
    if token:
        tools = _build_toss_tools(token, account)

    system_context = f"""당신은 사용자의 개인 자산 관리 AI 코파일럿입니다.
아래는 사용자의 실제 토스증권 포트폴리오 데이터입니다. 이 데이터에 근거하여 한국어로 친절하고 전문적으로 답변하세요.

중요: 아래 요약 데이터에 없는 정보(개별 종목의 과거 주가, S&P500(SPY) 벤치마크 수익률, 실시간 현재가, 상세 거래 이력 등)가 필요하면
반드시 제공된 도구(함수)를 호출해서 토스증권 API로 실제 데이터를 조회한 뒤 그 값을 근거로 답변하세요.
예: 어떤 종목이 S&P500 대비 초과수익을 냈는지 물으면, get_benchmark_return('SPY', ...)로 벤치마크 수익률을 구하고
각 종목의 수익률과 비교해 초과수익(알파)을 계산하세요. 임의로 추측하지 마세요.

[보유 자산/요약 데이터]
{json.dumps(portfolio_json, ensure_ascii=False, indent=2)}
"""
    if trades_summary:
        system_context += f"\n[분기별 거래 요약]\n{trades_summary}\n"

    # 이전 대화 이력을 Gemini 형식으로 변환
    history = []
    for msg in chat_history:
        role = "user" if msg["role"] == "user" else "model"
        history.append({"role": role, "parts": [msg["content"]]})

    # 모델 폴백 + 429 재시도
    last_err = None
    for model_name in MODEL_CHAIN:
        for attempt in range(2):
            try:
                model = genai.GenerativeModel(
                    model_name, system_instruction=system_context, tools=tools
                )
                chat = model.start_chat(
                    history=history,
                    enable_automatic_function_calling=bool(tools),
                )
                response = chat.send_message(user_message)
                return response.text
            except Exception as e:
                last_err = e
                if _is_quota_error(e):
                    time.sleep(2 * (attempt + 1))
                    continue
                break  # 한도 외 에러는 다음 모델로
    if _is_quota_error(last_err):
        return ("⚠️ Gemini 무료 사용량(하루 한도)을 초과했습니다. 잠시 후 다시 시도해 주세요.\n"
                "참고: AI가 실시간 데이터를 조회하며 여러 번 호출하기 때문에 한도가 빨리 소진될 수 있습니다.")
    return f"AI 대화 중 에러가 발생했습니다: {last_err}"

