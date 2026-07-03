@echo off
title AI Screening Tool Web UI Launcher
echo ===================================================
echo   AI 사용 의심 선별 도구 로컬 웹 서버 구동 중...
echo ===================================================
echo.
echo * 브라우저 창이 자동으로 열리지 않으면 http://localhost:8000 에 직접 접속해 주세요.
echo * 이 창을 닫으면 웹 프로그램 구동이 종료됩니다.
echo.

:: 1. PATH에서 python 검사
where python >nul 2>nul
if %errorlevel% equ 0 (
    python app.py
    goto end
)

:: 2. 기본 AppData 설치 경로에서 python 검사
set LOCAL_PYTHON="%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
if exist %LOCAL_PYTHON% (
    %LOCAL_PYTHON% app.py
    goto end
)

:: 3. PATH에서 python3 검사
where python3 >nul 2>nul
if %errorlevel% equ 0 (
    python3 app.py
    goto end
)

echo.
echo [오류] Python을 찾을 수 없습니다. Python이 올바르게 설치되었는지 확인해 주세요.
pause

:end
