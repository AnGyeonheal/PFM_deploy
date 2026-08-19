@echo off
REM 포트 8501 고정 실행 스크립트 - 기존 서버를 종료한 뒤 새로 실행합니다.
echo [1/2] 기존 Streamlit 서버 종료 중...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

echo [2/2] 대시보드 실행 (http://localhost:8501)
REM envPM 가상환경의 python 을 자동 탐색 (miniconda3 / anaconda3), 없으면 conda run 으로 폴백
set "PM_PY=%USERPROFILE%\miniconda3\envs\envPM\python.exe"
if not exist "%PM_PY%" set "PM_PY=%USERPROFILE%\anaconda3\envs\envPM\python.exe"
if exist "%PM_PY%" (
  "%PM_PY%" -m streamlit run app.py
) else (
  echo [알림] envPM python 을 찾지 못해 conda run 으로 실행합니다.
  call conda run -n envPM python -m streamlit run app.py
)
