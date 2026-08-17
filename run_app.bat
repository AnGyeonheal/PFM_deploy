@echo off
REM 포트포트 8501 고정 실행 스크립트 - 기존 서버를 종료한 뒤 새로 실행합니다.
echo [1/2] 기존 Streamlit 서버 종료 중...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

echo [2/2] 대시보드 실행 (http://localhost:8501)
"C:\Users\hilla\miniconda3\envs\envPM\python.exe" -m streamlit run app.py
