@echo off
chcp 65001 >nul
title 자산관리 웹앱 (FastAPI)
cd /d "%~dp0"

echo ============================================
echo   자산관리 웹앱 실행  -  http://localhost:8000
echo   (이 창을 닫거나 Ctrl+C 로 종료합니다)
echo ============================================
echo.

REM envPM 파이썬 자동 탐색 (miniconda3 / anaconda3)
set "PM_PY=%USERPROFILE%\miniconda3\envs\envPM\python.exe"
if not exist "%PM_PY%" set "PM_PY=%USERPROFILE%\anaconda3\envs\envPM\python.exe"

REM 기존에 8000 포트를 쓰던 서버 종료
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

REM 3초 뒤 기본 브라우저로 자동 접속
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://localhost:8000'"

if exist "%PM_PY%" (
  "%PM_PY%" -m uvicorn webapp:app --host 127.0.0.1 --port 8000
) else (
  echo [알림] envPM 파이썬을 찾지 못해 conda 로 실행합니다.
  call conda run -n envPM python -m uvicorn webapp:app --host 127.0.0.1 --port 8000
)

echo.
echo 서버가 종료되었습니다.
pause
