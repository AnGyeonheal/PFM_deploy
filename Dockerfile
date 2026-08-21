# FastAPI 웹앱 배포용 이미지 (Oracle Cloud 등 고정 IP 서버)
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 빌드 도구(일부 휠 컴파일 대비)
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# 사용자 데이터는 볼륨으로 마운트 권장: -v pfm_data:/app/user_data
EXPOSE 8000
CMD ["uvicorn", "webapp:app", "--host", "0.0.0.0", "--port", "8000"]
