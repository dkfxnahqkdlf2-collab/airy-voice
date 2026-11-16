@echo off
chcp 65001 > nul
title Shorts Voice Studio Pro
cd /d "%~dp0"

echo ========================================================
echo  Shorts Voice Studio Pro 실행 준비 중...
echo ========================================================

:: 기존 8502 포트 정리
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8502 "') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo  웹 브라우저를 자동으로 엽니다... (http://localhost:8502)
start "" "http://localhost:8502"

:: 파이썬 실행
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    py -m streamlit run voice_studio.py --server.port 8502
) else (
    python -m streamlit run voice_studio.py --server.port 8502
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [오류] Python 실행에 실패했습니다.
    echo Python 3.10 이상이 설치되어 있는지 확인해 주세요.
    pause
)
