@echo off
REM ASCII-only bootstrap. Keep every byte above the marker pure ASCII:
REM cmd.exe mis-parses UTF-8 lines under code page 936 (Chinese Windows).
REM Switch code page, then re-enter this file in a NEW cmd process.
if not "%~1"=="__utf8" (
    chcp 65001 >nul
    cmd /d /c call "%~f0" __utf8
    exit /b %errorlevel%
)
REM ==================== end of bootstrap =====================
title 浙考申论智阅
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 尚未安装，请先双击上层目录的 install.bat。
    pause & exit /b 1
)
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd backend
echo 停止服务按 Ctrl+C。服务就绪后会自动打开浏览器。
"..\.venv\Scripts\python.exe" main.py
pause
