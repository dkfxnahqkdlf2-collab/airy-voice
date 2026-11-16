@echo off
chcp 65001 > nul
title Shorts Voice Studio Pro 설치 마법사
cd /d "%~dp0"

echo ========================================================
echo   Shorts Voice Studio Pro 필수 라이브러리 자동 설치
echo ========================================================
echo.
echo  파이썬 필수 패키지를 자동으로 설치합니다...
echo.

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo  [성공] 필수 프로그램 설치가 완료되었습니다!
    echo.
    echo  1. [바탕화면_바로가기_만들기.bat]를 누르면 바탕화면에 바로가기가 생깁니다.
    echo  2. [run_voice_studio.bat]를 누르면 프로그램이 즉시 실행됩니다.
    echo ========================================================
) else (
    echo.
    echo  [오류] 설치 중 문제가 발생했습니다. Python 3.10 이상이 설치되어 있는지 확인해 주세요.
)
pause
