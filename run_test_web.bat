@echo off
setlocal
cd /d "%~dp0"
set "PM_PY=%USERPROFILE%\miniconda3\envs\envPM\python.exe"
if not exist "%PM_PY%" set "PM_PY=%USERPROFILE%\anaconda3\envs\envPM\python.exe"
if exist "%PM_PY%" (
  "%PM_PY%" share_web.py %*
) else (
  python share_web.py %*
)
endlocal