@echo off
chcp 65001 >nul
title 포트폴리오 Discord 리포트 발송
cd /d "%~dp0"

REM envPM 파이썬 자동 탐색 (miniconda3 / anaconda3)
set "PM_PY=%USERPROFILE%\miniconda3\envs\envPM\python.exe"
if not exist "%PM_PY%" set "PM_PY=%USERPROFILE%\anaconda3\envs\envPM\python.exe"

"%PM_PY%" notify.py
